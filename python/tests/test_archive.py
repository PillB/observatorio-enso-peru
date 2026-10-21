"""Copias archivadas servidas por el sitio: extensiones seguras y páginas escapadas."""

from datetime import date
from types import SimpleNamespace

from enso import archive


def test_third_party_markup_is_stored_as_text():
    assert archive.kind(b"%PDF-1.7 ...") == "pdf"
    assert archive.kind(b"<html><script>alert(1)</script></html>") == "txt"
    assert archive.kind(b'<?xml version="1.0"?><rss/>') == "txt"
    assert archive.kind(b'{"a": 1}', "application/json") == "json"
    assert archive.kind(b"{not json", "application/json") == "txt"
    assert archive.kind(b"a,b\n1,2\n", url="https://x/y.csv") == "csv"
    assert archive.kind(b"<html>", "text/csv") == "txt"
    assert archive.source_path("cpc-oni", b"1950 1 -1.5").endswith(".txt")


def test_carry_accepts_only_archive_paths(tmp_path):
    w = archive.Writer(tmp_path)
    got = {}
    fetch = lambda rel: got.setdefault(rel, b"%PDF-1.4 old")
    assert archive.carry(w, "../../etc/passwd", fetch) is None
    assert archive.carry(w, "archive/sources/x/../../../a.pdf", fetch) is None
    assert archive.carry(w, "https://evil.example/a.pdf", fetch) is None
    assert not got
    rel = "archive/sources/enfen-comunicados/0123456789ab.pdf"
    assert archive.carry(w, rel, fetch) == rel
    assert (tmp_path / rel).read_bytes() == b"%PDF-1.4 old"
    assert w.files[rel]["carried"] is True


def test_news_day_page_escapes_feed_text(tmp_path):
    w = archive.Writer(tmp_path)
    feeds = {"f1": SimpleNamespace(url="https://medio.pe/feed", name="Medio <b>")}
    items = [{"id": "abc123", "first_seen": "2026-10-20T10:00:00+00:00", "published": "2026-10-20T09:00:00+00:00",
              "feed": "f1", "outlet": "Medio", "title": "Lluvias <script>alert(1)</script>",
              "summary": "Huaico & \"desborde\"", "link": "https://medio.pe/nota?x=1&y=2"},
             {"id": "old", "first_seen": "2025-01-01T00:00:00+00:00", "feed": "f1", "title": "Vieja",
              "link": "https://medio.pe/vieja"}]
    pages = archive.write_news_days(w, items, feeds, {"f1": "archive/feeds/f1.txt"}, {"abc123"}, date(2026, 10, 21))
    assert pages == ["archive/news/2026-10-20.html"]
    text = (tmp_path / pages[0]).read_text(encoding="utf-8")
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert 'id="abc123"' in text
    assert 'href="https://medio.pe/nota?x=1&amp;y=2"' in text
    assert 'href="../feeds/f1.txt"' in text
    assert "Content-Security-Policy" in text
    assert archive.news_page(items[0]) == "archive/news/2026-10-20.html#abc123"
