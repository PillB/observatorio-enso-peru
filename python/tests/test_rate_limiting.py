"""Contratos de rate limiting (HTTP 429) y backoff exponencial + jitter.

Usa ``httpx.MockTransport`` para simular 429s y verifica que el fetcher
espera (backoff) y eventualmente recupera o agota reintentos.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from enso.fetchers import FetchError, FetchResult, PslNino12Fetcher


def _valid_csv() -> bytes:
    return (
        b"year,1,2,3,4,5,6,7,8,9,10,11,12\n"
        b"1990,0.10,0.20,0.30,0.10,-0.10,-0.20,-0.30,-0.20,0.00,0.10,0.20,0.10\n"
        b"2026,1.10,1.30,1.40,1.30,1.10,0.90,0.80,-99,-99,-99,-99,-99\n"
    )


def _make_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_backoff_seconds_is_monotonic_and_capped(tmp_path):
    fetcher = PslNino12Fetcher(cache_dir=tmp_path)
    waits = [fetcher._backoff_seconds(i) for i in range(10)]
    base_values = [min(fetcher.backoff_cap, fetcher.backoff_base * (2 ** i)) for i in range(10)]
    for w, b in zip(waits, base_values):
        assert b <= w <= b + b / 2
        assert w <= fetcher.backoff_cap + fetcher.backoff_cap / 2


def test_429_triggers_backoff_and_retry(tmp_path):
    """429 con Retry-After → espera y reintenta. Tras éxito, devuelve el contenido."""
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=_valid_csv(), headers={"ETag": '"abc"'})

    transport = _make_transport(handler)
    sleeps: list[float] = []
    fetcher = PslNino12Fetcher(
        cache_dir=tmp_path,
        transport=transport,
        sleep=lambda s: sleeps.append(s),
        min_interval=0.0,
    )
    fetcher.max_retries = 3
    result = fetcher.fetch(allow_network=True)
    assert result.status_code == 200
    assert len(sleeps) >= 1
    assert sleeps[0] > 0
    assert result.content == _valid_csv()
    assert len(calls) == 2


def test_429_persistent_returns_cache_or_raises(tmp_path):
    """429 persistente: si no hay caché, lanza tras agotar reintentos."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    transport = _make_transport(handler)
    fetcher = PslNino12Fetcher(
        cache_dir=tmp_path, transport=transport,
        sleep=lambda s: None, min_interval=0.0,
    )
    fetcher.max_retries = 2
    with pytest.raises(FetchError):
        fetcher.fetch(allow_network=True)


def test_429_persistent_returns_cache_when_available(tmp_path):
    """429 persistente con caché previo: devuelve el caché marcado from_cache."""
    cache = tmp_path
    fetcher_seed = PslNino12Fetcher(cache_dir=cache, min_interval=0.0,
                                    sleep=lambda s: None)
    seed = FetchResult(
        source_id=fetcher_seed.source_id,
        url=fetcher_seed.url,
        content=_valid_csv(),
        status_code=200,
        fetched_at="2026-01-01T00:00:00+00:00",
        etag='"seed"',
        last_modified=None,
    )
    fetcher_seed._write_cache(seed)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    transport = _make_transport(handler)
    fetcher = PslNino12Fetcher(cache_dir=cache, transport=transport,
                               min_interval=0.0, sleep=lambda s: None)
    fetcher.max_retries = 1
    result = fetcher.fetch(allow_network=True)
    assert result.from_cache is True
    assert result.content == _valid_csv()


def test_5xx_is_retryable(tmp_path):
    """HTTP 500 se reintenta y eventualmente usa caché o falla."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"server error")

    transport = _make_transport(handler)
    fetcher = PslNino12Fetcher(cache_dir=tmp_path, transport=transport,
                               min_interval=0.0, sleep=lambda s: None)
    fetcher.max_retries = 1
    with pytest.raises(FetchError):
        fetcher.fetch(allow_network=True)


def test_4xx_client_error_not_retried(tmp_path):
    """HTTP 404 no se reintenta: falla inmediatamente."""
    call_count = [0]

    def handler(req: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(404, content=b"not found")

    transport = _make_transport(handler)
    fetcher = PslNino12Fetcher(cache_dir=tmp_path, transport=transport,
                               min_interval=0.0, sleep=lambda s: None)
    fetcher.max_retries = 3
    with pytest.raises(FetchError):
        fetcher.fetch(allow_network=True)
    # 404 no se reintenta → sólo 1 llamada.
    assert call_count[0] == 1


def test_304_uses_cache(tmp_path):
    """HTTP 304 devuelve el caché si existe."""
    cache = tmp_path
    fetcher_seed = PslNino12Fetcher(cache_dir=cache, min_interval=0.0,
                                    sleep=lambda s: None)
    seed = FetchResult(
        source_id=fetcher_seed.source_id,
        url=fetcher_seed.url,
        content=_valid_csv(),
        status_code=200,
        fetched_at="2026-01-01T00:00:00+00:00",
        etag='"seed"',
    )
    fetcher_seed._write_cache(seed)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    transport = _make_transport(handler)
    fetcher = PslNino12Fetcher(cache_dir=cache, transport=transport,
                               min_interval=0.0, sleep=lambda s: None)
    result = fetcher.fetch(allow_network=True)
    assert result.from_cache is True
    assert result.content == _valid_csv()
