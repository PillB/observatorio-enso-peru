"""Degradación persistente: desde cuándo y en cuántas corridas está degradada cada fuente o feed (``degraded-persistent``).

Lo que en noviembre de 2026 duró semanas sin que nadie lo viera quedaba como «info» en cada corrida (``relay-channel``,
``carried-forward``, ``feed-down``, ``feed-inactive``, un feed que solo llega por n8n) o lo vigilaba una guardia que
solo comparaba con ayer. Aquí cada corrida lee el estado que dejó la anterior (``degraded.json`` de la publicación,
con los intentos de lo que se arrastra), suma una corrida a lo que sigue degradado y, cuando lleva más días que su
umbral (``enso/data/degradacion.json``, según la cadencia de la fuente o del feed) y al menos ``minRuns`` corridas,
anota una incidencia ``warning`` (y así un issue, ``tools/sync_issues.py``) que se repite en cada corrida mientras siga
degradado y se cierra sola cuando lleva ``recoverHours`` y ``recoverRuns`` bien (una sola corrida buena no basta: los
servidores de gob.pe, GEOSINPAD y CENVUL respondían una corrida sí y otra no el 20 y 21 de noviembre de 2026).

Estados (uno por fuente o feed, el primero que aplique):

* fuentes oficiales (``sources.json``): ``failed`` (sin dato), ``carried`` (se publica el anterior), ``archive`` (solo
  el Internet Archive), ``relay`` (solo la copia de n8n o del Perú, aunque el registro la asigna a Actions; una URL
  que el registro deja al Perú, como el portal del ENFEN, no cuenta);
* feeds (``news/feeds.json``): ``down``, ``unreadable`` (otra forma, entradas sin fecha o respuesta cortada), ``empty`` (un feed válido
  sin entradas; una capa de avisos o FIRMS vacía, o un simulacro del PTWC, no cuenta: es que no hay avisos), ``carried`` (la lectura de
  un feed «lector» lleva más de ``readerCarryHours`` sin renovarse), ``relay`` (como arriba) e ``inactive`` (sin
  entradas nuevas: cuenta desde que pasó su ``stale_days``).

Solo escalan los estados que ningún otro código ya lleva a un issue (``escalate``): una fuente que falla ya anota
``unreachable`` o ``format-changed``; un feed oficial de avisos caído, ``hazard-feed-down``. Los feeds oficiales de
avisos tienen una incidencia cada uno (``news-<feed>``, como ``hazard-feed-down``); los demás feeds, una por estado
(``feeds-<estado>``), con la lista: 30 feeds de gob.pe que solo llegan por n8n son una causa, no 30 issues.

Lo que una corrida no revisa (``--only``, un feed omitido por tiempo, una corrida sin noticias) conserva su cuenta sin
sumar, y si ya había escalado la incidencia se repite: que no se haya mirado no es que esté bien."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

CODE = "degraded-persistent"
FILE = "degraded.json"
RULES_PATH = Path(__file__).parent / "data" / "degradacion.json"
_RULES: Optional[dict] = None


def rules(path: Optional[Path] = None) -> dict:
    global _RULES
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if _RULES is None:
        _RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return _RULES


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(s: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _unplanned_relay(channel: str, url: Optional[str], plan: dict) -> bool:
    """Llegó por la copia de un recolector aunque el registro la asigna a Actions (o no la tiene: entonces se pidió
    directo primero). La copia subida a mano (``relay-manual``) no cuenta: la pide ``manual-download-needed``."""
    if channel not in ("relay-n8n", "relay-peru"):
        return False
    planned = plan.get(url) if url else None
    return planned is None or "actions" in planned


def source_state(acq, plan: dict) -> Optional[str]:
    """Estado de degradación de una fuente oficial (``observatory.Acquired``); None si está bien."""
    if not acq.ok:
        return "carried" if acq.carried else "failed"
    if acq.channel.startswith("archive"):
        return "archive"
    if _unplanned_relay(acq.channel, acq.url, plan):
        return "relay"
    return None


UNOBSERVED = "unobserved"


def _unobserved(st: dict) -> Any:
    """Esta corrida no pidió el feed (``--only``, omitido por tiempo)."""
    return st.get("skipped") or st.get("omitted") or str(st.get("error") or "").startswith("omitido:")


def _carried_feed(st: dict, now: datetime, cfg: dict) -> tuple[Optional[str], Optional[datetime]]:
    """(estado, desde) de un feed «lector» que se publica con su lectura anterior."""
    at = _parse(st.get("checkedAt"))
    if at is None or now - at <= timedelta(hours=cfg.get("readerCarryHours", 44)):
        return UNOBSERVED, None  # el lector lo lee cada 20 h: entre lecturas se ve la anterior
    return "carried", at


def _malformed_feed(st: dict) -> Optional[str]:
    """``unreadable`` (entradas sin fecha o respuesta cortada) o ``empty`` (feed válido sin entradas); None si no."""
    if ((st.get("items") or 0) > 0 and not st.get("latest")) or st.get("truncated"):
        return "unreadable"
    if not st.get("items") and st.get("error"):
        # Respondió un feed válido sin ninguna entrada («feed sin entradas»; las capas de avisos y FIRMS vacías no
        # traen error: es que no hay avisos). Antes no tenía estado: un feed vaciado quedaba como «info» para siempre
        # (``tools/drift_sim.py``, mutación ``items-none``).
        return "empty"
    return None


def _failed_feed(st: dict) -> Optional[str]:
    """Estado de un feed que no se pudo leer bien (``down``, ``unreadable``, ``empty``); None si se leyó."""
    if not st.get("ok") or st.get("upstreamDown"):
        return "unreadable" if st.get("formatError") else "down"
    return _malformed_feed(st)


def _inactive_feed(st: dict, feed) -> tuple[Optional[str], Optional[datetime]]:
    """(``inactive``, desde): cuenta desde que la entrada más reciente pasó su ``stale_days``."""
    latest = _parse(st.get("latest"))
    return "inactive", (latest + timedelta(days=getattr(feed, "stale_days", 7)) if latest else None)


def feed_state(st: dict, feed, plan: dict, now: datetime, cfg: dict) -> tuple[Optional[str], Optional[datetime]]:
    """(estado, desde) de un feed según su entrada de ``news/feeds.json``. ``UNOBSERVED`` si esta corrida no lo pidió;
    ``desde`` solo cuando el propio estado lo dice (la última lectura de un feed arrastrado, la entrada más reciente
    de uno inactivo)."""
    if _unobserved(st):
        return UNOBSERVED, None
    if st.get("carried"):
        return _carried_feed(st, now, cfg)
    failed = _failed_feed(st)
    if failed:
        return failed, None
    if _unplanned_relay(str(st.get("channel") or ""), getattr(feed, "url", None) or st.get("url"), plan):
        return "relay", None
    if not st.get("active") and st.get("latest"):
        return _inactive_feed(st, feed)
    return None, None


def threshold(state: str, cadence_days: float, cfg: dict, key: str) -> Optional[dict]:
    """Regla del estado (días y corridas) para una fuente o feed; None si un override la apaga."""
    base = (cfg.get("states") or {}).get(state)
    over = (cfg.get("overrides") or {}).get(key) or {}
    if state in over:
        if over[state] is None:
            return None
        base = {**(base or {}), **over[state]}
    if not base:
        return None
    days = min(base.get("maxDays", 30), max(base.get("minDays", 3), base.get("factor", 1.0) * (cadence_days or 1)))
    return {"days": round(days, 1), "runs": int(base.get("minRuns", 3)), "what": base.get("what", state)}


def _incident(kind: str, ident: str) -> str:
    """Clave de la incidencia de una fuente (su id) o de un feed oficial de avisos (``news-<feed>``)."""
    return ident if kind == "source" else f"news-{ident}"


def _since(old: dict, since_hint: Optional[datetime], now: datetime) -> datetime:
    """Desde cuándo está degradado: lo más antiguo entre lo anotado, lo que dice el estado y ahora."""
    since = _parse(old.get("since")) if old else None
    return min(d for d in (since, since_hint, now) if d is not None)


def _record(old: dict, kind: str, ident: str, state: str, since: datetime, now: datetime, counts: bool) -> dict:
    """Entrada degradada de esta corrida (sin ``okSince``/``okRuns``: ya no responde bien)."""
    rec = {"kind": kind, "id": ident, "state": state, "since": _iso(since),  # okSince/okRuns: ya no
           "stateSince": old.get("stateSince") if old.get("state") == state and old.get("stateSince") else _iso(now),
           "runs": int(old.get("runs") or 0) + 1, "lastAt": _iso(now)}
    # Corridas en estados que escalan para este tipo: un feed oficial caído tres días (eso ya lo lleva
    # hazard-feed-down) que en la cuarta llega solo por n8n no tiene «relay» persistente; tiene una corrida.
    # Si alterna caído y relay, las corridas de relay se suman y escala igual.
    rec["escRuns"] = int(old.get("escRuns") or 0) + (1 if counts else 0)
    return rec


class _Run:
    """Lo que acumula una corrida de ``update``: entradas nuevas, claves vistas, grupos de feeds y escalados que
    respondieron bien hace poco."""

    def __init__(self, prev: dict, now: datetime, log, cfg: dict) -> None:
        self.prev, self.now, self.log, self.cfg = prev, now, log, cfg
        self.out: dict[str, dict] = {}
        self.seen: set[str] = set()
        self.escalate = cfg.get("escalate") or {}
        self.groups: dict[str, list[str]] = {}  # feeds-<estado>: líneas de los feeds que no son oficiales
        self.pending: list[tuple[str, str, str]] = []  # escalados que respondieron bien hace poco: su issue sigue abierto

    def observe(self, key: str, kind: str, ident: str, label: str, state: Optional[str], cadence: float,
                since_hint: Optional[datetime] = None, detail: str = "") -> None:
        """Suma esta corrida a la fuente o feed ``key`` (``state`` None: respondió bien)."""
        self.seen.add(key)
        old = self.prev.get(key) if isinstance(self.prev.get(key), dict) else {}
        if state is None:
            if old:
                self._healthy(key, kind, ident, label, old)
            return
        self._degraded(key, kind, ident, label, state, cadence, since_hint, detail, old)

    def _healthy(self, key: str, kind: str, ident: str, label: str, old: dict) -> None:
        """Bien en esta corrida. Sale del estado (y su incidencia se cierra) cuando lleva recoverHours y
        recoverRuns bien: los servidores de gob.pe, GEOSINPAD o CENVUL responden en una corrida y en la
        siguiente no (20 y 21-11-2026); sin esto, la cuenta volvería a cero con cada corrida buena y lo que
        falla una de cada dos nunca escalaría, o su issue se abriría y cerraría a diario."""
        now, cfg = self.now, self.cfg
        ok_since = _parse(old.get("okSince")) or now
        ok_runs = int(old.get("okRuns") or 0) + 1
        if (now - ok_since >= timedelta(hours=cfg.get("recoverHours", 24))
                and ok_runs >= int(cfg.get("recoverRuns", 2))):
            return
        self.out[key] = {**old, "okSince": _iso(ok_since), "okRuns": ok_runs, "lastAt": _iso(now)}
        if old.get("escalated"):
            self.pending.append((kind, ident, f"{label}: {old.get('state')} desde el {str(old.get('since'))[:10]}; "
                                              f"respondió bien desde el {_iso(ok_since)[:16]} ({ok_runs} corridas): "
                                              "se cierra si sigue bien"))

    def _degraded(self, key: str, kind: str, ident: str, label: str, state: str, cadence: float,
                  since_hint: Optional[datetime], detail: str, old: dict) -> None:
        """Degradado en esta corrida: suma la corrida y escala si pasó el umbral."""
        now = self.now
        since = _since(old, since_hint, now)
        counts = state in (self.escalate.get(kind) or [])
        rec = _record(old, kind, ident, state, since, now, counts)
        rule = threshold(state, cadence, self.cfg, key)
        days = (now - since).total_seconds() / 86400
        if rule is not None:
            rec["thresholdDays"] = rule["days"]
        rec["escalated"] = bool(rule and counts and days >= rule["days"] and rec["escRuns"] >= rule["runs"])
        self.out[key] = rec
        if rec["escalated"]:
            self._escalated(kind, ident, label, state, rec, rule, days, detail)

    def _escalated(self, kind: str, ident: str, label: str, state: str, rec: dict, rule: dict, days: float,
                   detail: str) -> None:
        """Anota la incidencia (o la línea del grupo de feeds) de lo que pasó su umbral."""
        core = (f"desde el {rec['since'][:10]} ({days:.0f} días, {rec['runs']} corridas degradadas; umbral "
                f"{rule['days']:g} días)" + (f". {detail}" if detail else ""))
        if kind == "feed":
            self.groups.setdefault(state, []).append(f"{label} {core}")
        else:
            self.log.add("warning", _incident(kind, ident), "validate", "degraded-persistent",
                         f"{label}: {rule['what']} {core}.")

    def flush_pending(self) -> None:
        """Repite la incidencia de los escalados que respondieron bien hace poco (su issue sigue abierto)."""
        for kind, ident, msg in self.pending:
            if kind == "feed":
                self.groups.setdefault(str((self.prev.get(f"feed:{ident}") or {}).get("state")), []).append(msg)
            else:
                self.log.add("warning", _incident(kind, ident), "validate", "degraded-persistent", msg + ".")


def _prev_entities(previous: Optional[dict]) -> dict:
    """Entidades de ``degraded.json`` de la publicación anterior ({} si no hay o está mal formado)."""
    prev = (previous or {}).get("entities") if isinstance(previous, dict) else None
    return prev if isinstance(prev, dict) else {}


def _observe_sources(run: _Run, sources: Optional[list], plan: dict) -> None:
    """Suma la corrida de cada fuente oficial revisada."""
    for src, acq in sources or []:
        run.observe(f"source:{src.id}", "source", src.id, f"{src.institution} · {src.product}",
                    source_state(acq, plan), src.cadence_days,
                    detail=f"Canal: {acq.channel}" if acq.ok else (acq.error or "")[:200])


def _feed_detail(st: dict) -> Any:
    """Detalle de un feed degradado: el error, el corte o el canal por el que llegó."""
    return st.get("error") or st.get("truncated") or (
        f"Canal: {st.get('channel')}" + (f" (copia del {st['copyAt']})" if st.get("copyAt") else "")
        if st.get("channel") else "")


def _observe_feeds(run: _Run, feeds: list, plan: dict, now: datetime, cfg: dict, official) -> None:
    """Suma la corrida de cada feed que esta corrida pidió."""
    for feed, st in feeds:
        state, hint = feed_state(st, feed, plan, now, cfg)
        if state == UNOBSERVED:
            continue
        kind = "official-feed" if official is not None and official(feed) else "feed"
        detail = _feed_detail(st)
        run.observe(f"feed:{st['id']}", kind, st["id"], st.get("name") or st["id"], state,
                    getattr(feed, "stale_days", 7) if state in ("inactive", "carried", "empty") else 1, hint,
                    str(detail)[:200])


def _log_groups(log, groups: dict[str, list[str]], cfg: dict) -> None:
    """Una incidencia ``feeds-<estado>`` por estado, con la lista de feeds."""
    for state, lines in sorted(groups.items()):
        rule = (cfg.get("states") or {}).get(state) or {}
        log.add("warning", f"feeds-{state}", "validate", "degraded-persistent",
                f"Feeds degradados por más tiempo que su umbral ({len(lines)}; {state}: {rule.get('what', state)}): "
                + "; ".join(lines[:25]) + ("; …" if len(lines) > 25 else "") + ".")


def _repeat_unseen(log, old: dict, regroup: dict[str, list[str]]) -> None:
    """Repite la incidencia de lo que ya escalaba y esta corrida no revisó."""
    msg = (f"{old.get('id')}: degradado ({old.get('state')}) desde el {str(old.get('since'))[:10]}, "
           f"{old.get('runs')} corridas; no se revisó en esta corrida")
    if old.get("kind") == "feed":
        regroup.setdefault(str(old.get("state")), []).append(msg)
    else:
        log.add("warning", old["id"] if old.get("kind") == "source" else f"news-{old.get('id')}", "validate",
                "degraded-persistent", msg + ".")


def _carry_unseen(run: _Run, catalog: Optional[set]) -> dict[str, list[str]]:
    """Lo que esta corrida no revisó: conserva su cuenta (sin sumar) y, si ya escalaba, la incidencia sigue abierta.
    Devuelve las líneas de los feeds no revisados por estado."""
    forget = timedelta(days=run.cfg.get("forgetDays", 30))
    regroup: dict[str, list[str]] = {}
    for key, old in run.prev.items():
        if key in run.seen or not isinstance(old, dict) or (catalog is not None and key not in catalog):
            continue
        last = _parse(old.get("lastAt"))
        if last is None or run.now - last > forget:
            continue
        run.out[key] = old
        if old.get("escalated"):
            _repeat_unseen(run.log, old, regroup)
    return regroup


def _log_regroup(log, regroup: dict[str, list[str]], groups: dict[str, list[str]]) -> None:
    """Incidencia de los grupos de feeds que solo tienen feeds no revisados."""
    for state, lines in sorted(regroup.items()):
        if state in groups:
            continue  # la incidencia del grupo ya salió con los que sí se revisaron
        log.add("warning", f"feeds-{state}", "validate", "degraded-persistent", "; ".join(lines[:25]) + ".")


def update(previous: Optional[dict], now: datetime, log, *, sources: Optional[list] = None,
           feeds: Optional[list] = None, plan: Optional[dict] = None, cfg: Optional[dict] = None,
           official=None, catalog: Optional[set] = None, prev_state: str = "ok") -> dict:
    """Estado nuevo (lo que se publica en ``degraded.json``) a partir del anterior y de esta corrida.

    ``sources``: pares (``Source``, ``Acquired``) revisados en la corrida; ``feeds``: pares (``Feed``, estado de
    ``news/feeds.json``), None si la corrida no leyó noticias. ``official(feed)`` dice si es un feed oficial de avisos.
    ``catalog``: claves que siguen en el catálogo (lo demás se olvida). ``prev_state``: lo que dijo
    ``PreviousPublication.state`` del archivo (``ok``, ``missing``, ``unreachable``)."""
    cfg = cfg or rules()
    plan = plan or {}
    prev = _prev_entities(previous)
    if prev_state == "unreachable":
        log.add("info", "degraded", "validate", "degraded-unchecked",
                f"No se pudo leer {FILE} de la publicación anterior: la cuenta de corridas degradadas vuelve a empezar.")
    run = _Run(prev, now, log, cfg)
    _observe_sources(run, sources, plan)
    if feeds is not None:
        _observe_feeds(run, feeds, plan, now, cfg, official)
    run.flush_pending()
    _log_groups(log, run.groups, cfg)
    _log_regroup(log, _carry_unseen(run, catalog), run.groups)
    out = run.out
    return {"version": 1, "entities": dict(sorted(out.items())),
            "escalated": sorted(k for k, v in out.items() if v.get("escalated"))}
