"""La imagen del boletín (PNG de 1200 × 630) para compartir: la vista previa de WhatsApp, Slack, Teams, Telegram o
Facebook cuando alguien pega el enlace, y el archivo que «Compartir» manda desde el teléfono.

Muestra lo que se entiende de un vistazo: el mosaico del Perú con el color de cada departamento, los contadores por
nivel, el estado del ENFEN y la edición. Se dibuja sin dependencias (``zlib`` y una letra de mapa de bits de 5 × 7),
así la actualización diaria no necesita Pillow ni un navegador. Las letras van en mayúsculas sin tildes: una letra de
mapa de bits con tildes sería ilegible a ese tamaño, y las siglas del mosaico ya son así.
"""

from __future__ import annotations

import struct
import unicodedata
import zlib

W, H = 1200, 630

# 5 × 7: cada letra son 7 filas de 5 bits (el bit más alto, a la izquierda).
_G = {
    "A": "0E 11 11 1F 11 11 11", "B": "1E 11 11 1E 11 11 1E", "C": "0E 11 10 10 10 11 0E", "D": "1E 11 11 11 11 11 1E",
    "E": "1F 10 10 1E 10 10 1F", "F": "1F 10 10 1E 10 10 10", "G": "0E 11 10 17 11 11 0F", "H": "11 11 11 1F 11 11 11",
    "I": "0E 04 04 04 04 04 0E", "J": "07 02 02 02 02 12 0C", "K": "11 12 14 18 14 12 11", "L": "10 10 10 10 10 10 1F",
    "M": "11 1B 15 15 11 11 11", "N": "11 11 19 15 13 11 11", "O": "0E 11 11 11 11 11 0E", "P": "1E 11 11 1E 10 10 10",
    "Q": "0E 11 11 11 15 12 0D", "R": "1E 11 11 1E 14 12 11", "S": "0F 10 10 0E 01 01 1E", "T": "1F 04 04 04 04 04 04",
    "U": "11 11 11 11 11 11 0E", "V": "11 11 11 11 11 0A 04", "W": "11 11 11 15 15 15 0A", "X": "11 11 0A 04 0A 11 11",
    "Y": "11 11 0A 04 04 04 04", "Z": "1F 01 02 04 08 10 1F",
    "0": "0E 11 13 15 19 11 0E", "1": "04 0C 04 04 04 04 0E", "2": "0E 11 01 02 04 08 1F", "3": "1F 02 04 02 01 11 0E",
    "4": "02 06 0A 12 1F 02 02", "5": "1F 10 1E 01 01 11 0E", "6": "06 08 10 1E 11 11 0E", "7": "1F 01 02 04 08 08 08",
    "8": "0E 11 11 0E 11 11 0E", "9": "0E 11 11 0F 01 02 0C",
    " ": "00 00 00 00 00 00 00", ".": "00 00 00 00 00 0C 0C", ",": "00 00 00 00 0C 04 08", ":": "00 0C 0C 00 0C 0C 00",
    "-": "00 00 00 1F 00 00 00", "/": "01 01 02 04 08 10 10", "(": "02 04 08 08 08 04 02", ")": "08 04 02 02 02 04 08",
    "%": "18 19 02 04 08 13 03", "+": "00 04 04 1F 04 04 00", "·": "00 00 00 0C 0C 00 00", "°": "0C 12 12 0C 00 00 00",
    "'": "04 04 08 00 00 00 00", "?": "0E 11 01 02 04 00 04", "!": "04 04 04 04 04 00 04",
}
GLYPHS = {k: [int(x, 16) for x in v.split()] for k, v in _G.items()}


def _plain(text: str) -> str:
    """Mayúsculas sin tildes («Ñ» → «N»), solo con las letras que hay."""
    keep = {"·", "°"}
    t = "".join(c if c in keep else unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode()
                for c in str(text or "").replace("«", "").replace("»", "")).upper()
    return "".join(c if c in GLYPHS else " " for c in t)


def _rgb(hexcolor: str) -> tuple[int, int, int]:
    h = hexcolor.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class Canvas:
    def __init__(self, w: int, h: int, bg: str):
        self.w, self.h = w, h
        r, g, b = _rgb(bg)
        self.px = bytearray(bytes((r, g, b)) * (w * h))

    def rect(self, x: int, y: int, w: int, h: int, color: str) -> None:
        r, g, b = _rgb(color)
        x0, y0, x1, y1 = max(0, x), max(0, y), min(self.w, x + w), min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes((r, g, b)) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def frame(self, x: int, y: int, w: int, h: int, t: int, color: str, dashed: bool = False) -> None:
        if not dashed:
            for (a, b, c, d) in ((x, y, w, t), (x, y + h - t, w, t), (x, y, t, h), (x + w - t, y, t, h)):
                self.rect(a, b, c, d, color)
            return
        step = 3 * t
        for xx in range(x, x + w, 2 * step):
            self.rect(xx, y, min(step, x + w - xx), t, color)
            self.rect(xx, y + h - t, min(step, x + w - xx), t, color)
        for yy in range(y, y + h, 2 * step):
            self.rect(x, yy, t, min(step, y + h - yy), color)
            self.rect(x + w - t, yy, t, min(step, y + h - yy), color)

    @staticmethod
    def text_width(text: str, scale: int) -> int:
        return max(0, len(_plain(text)) * 6 * scale - scale)

    def text(self, x: int, y: int, text: str, scale: int, color: str, max_w: int = 0) -> int:
        """Escribe ``text``; con ``max_w`` corta con «...» lo que no cabe. Devuelve el ancho escrito."""
        t = _plain(text)
        if max_w and self.text_width(t, scale) > max_w:
            n = max(0, (max_w + scale) // (6 * scale) - 3)
            t = t[:n].rstrip() + "..."
        for i, ch in enumerate(t):
            rows = GLYPHS[ch]
            for ry, bits in enumerate(rows):
                for rx in range(5):
                    if bits & (1 << (4 - rx)):
                        self.rect(x + (i * 6 + rx) * scale, y + ry * scale, scale, scale, color)
        return self.text_width(t, scale)

    def png(self) -> bytes:
        raw = b"".join(b"\x00" + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3]) for y in range(self.h))

        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def wrap(text: str, scale: int, max_w: int, lines: int) -> list[str]:
    words, out, cur = _plain(text).split(), [], ""
    for w in words:
        nxt = f"{cur} {w}".strip()
        if Canvas.text_width(nxt, scale) <= max_w:
            cur = nxt
            continue
        out.append(cur)
        cur = w
        if len(out) == lines:
            break
    if len(out) < lines and cur:
        out.append(cur)
    if len(out) == lines and " ".join(out) != " ".join(words):
        out[-1] = out[-1] + "..."
    return [x for x in out if x]


def share_png(doc: dict) -> bytes:
    """La imagen de la edición: mosaico a la izquierda; contadores, ENFEN y la frase de resumen a la derecha."""
    from . import boletin as B

    c = Canvas(W, H, "#f2f4f6")
    brand, ink, muted = B.BRAND, "#1f1f1f", "#4a5560"
    # Encabezado.
    c.rect(0, 0, W, 96, brand)
    c.text(40, 24, "BOLETIN DE EVENTOS EL NINO · PERU", 4, "#ffffff")
    cut = B.when(doc.get("cutoff")) if doc.get("cutoff") else ""
    c.text(40, 64, f"EDICION N° {doc.get('edition', '')} · {cut} (HORA DE LIMA)", 2, "#ffffff")
    # Mosaico: 6 columnas × 8 filas de 52 px.
    by = {s["code"]: s for s in doc.get("segments") or []}
    size, gap, mx, my = 54, 6, 44, 126
    c.rect(mx - 16, my - 14, 6 * (size + gap) + 26, 8 * (size + gap) + 22, "#ffffff")
    for code, (r, col) in B.TILES.items():
        s = by.get(code)
        if not s:
            continue
        x, y = mx + col * (size + gap), my + r * (size + gap)
        bg, fg = B.LEVELS[s["rank"]][2], B.INK[s["rank"]]
        c.rect(x, y, size, size, bg)
        if s["rank"] >= 0 and not s.get("now", True):
            c.frame(x + 3, y + 3, size - 6, size - 6, 2, fg, dashed=True)
        ab = B.ABBR[code]
        c.text(x + (size - c.text_width(ab, 2)) // 2, y + (size - 14) // 2, ab, 2, fg)
    c.text(mx, my + 7 * (size + gap) + 6, "NORTE", 2, muted)
    c.text(mx, my + 7 * (size + gap) + 26, "ARRIBA", 2, muted)
    # Contadores.
    cx, cy, bw, bh = 432, 126, 140, 100
    counts = doc.get("counts") or {}
    for i, (r, k, lbl) in enumerate(((3, "rojo", "EN ROJO"), (2, "naranja", "EN NARANJA"), (1, "amarillo", "EN AMARILLO"),
                                     (0, "sinNivel", "SIN NIVEL"), (-1, "verde", "SIN AVISOS"))):
        x = cx + i * (bw + 10)
        bg, fg = B.LEVELS[r][2], B.INK[r]
        c.rect(x, cy, bw, bh, bg)
        n = str(counts.get(k, 0))
        c.text(x + (bw - c.text_width(n, 6)) // 2, cy + 14, n, 6, fg)
        c.text(x + (bw - c.text_width(lbl, 2)) // 2, cy + 74, lbl, 2, fg)
    c.text(cx, cy + bh + 12, "DEPARTAMENTOS SEGUN EL NIVEL MAS ALTO DE SUS AVISOS OFICIALES", 2, muted)
    # ENFEN.
    y = cy + bh + 52
    e = ((doc.get("enso") or {}).get("enfen")) or {}
    if e.get("status"):
        c.rect(cx, y, 740, 92, "#e3ebf0")
        c.rect(cx, y, 8, 92, brand)
        c.text(cx + 24, y + 14, "ESTADO OFICIAL DEL ENFEN", 2, muted)
        c.text(cx + 24, y + 40, e["status"], 4, ink, max_w=700)
        y += 112
    # Lo que no dicen ya los contadores: qué cambió en esta edición o, en la primera, dónde está lo más alto.
    top = [s["name"] for s in doc.get("segments") or [] if s["rank"] >= 2]
    if top:
        c.text(cx, y, "LOS MAS CRITICOS", 2, muted)
        y += 22
        for line in wrap(B.join_es(top, 6), 3, 740, 2):
            c.text(cx, y, line, 3, ink)
            y += 30
        y += 8
    changes = [x for x in doc.get("changes") or [] if x.get("rule") != "inicial"]
    if changes:
        c.text(cx, y, "QUE CAMBIO EN ESTA EDICION", 2, muted)
        y += 22
        for x in changes[:3]:
            for line in wrap("- " + x["text"], 2, 740, 3):
                if y > H - 34:
                    break
                c.text(cx, y, line, 2, ink)
                y += 22
    else:
        brief = next((h.get("brief") for h in doc.get("headline") or [] if h["id"] == "avisos" and h.get("brief")), "")
        for line in wrap(brief, 2, 740, 3):
            c.text(cx, y, line, 2, ink)
            y += 22
    return c.png()


def share_page(doc: dict, site: str) -> str:
    """Una página mínima con las etiquetas Open Graph: el enlace que se pega en WhatsApp o Slack muestra la imagen,
    el título y la frase; quien la abre va al boletín. El número de edición en la dirección de la imagen evita que
    WhatsApp muestre la vista previa de una edición vieja."""
    import html as H_

    from . import boletin as B

    site = site.rstrip("/") + "/"
    e = H_.escape
    title = f"Boletín El Niño · Perú, N° {doc.get('edition', '')}"
    desc = doc.get("summary") or "Avisos oficiales de El Niño por departamento."
    img = f"{site}data/boletin.png?n={doc.get('edition', '')}"
    url = f"{site}#/boletin"
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>{e(title)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{e(desc)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Observatorio ENSO Perú">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{e(img)}">
<meta property="og:image:width" content="{W}"><meta property="og:image:height" content="{H}">
<meta property="og:image:alt" content="Mapa de cuadros del Perú por nivel de aviso, contadores por nivel y estado del ENFEN">
<meta property="og:url" content="{e(B.share_url(doc, site))}">
<meta name="twitter:card" content="summary_large_image">
<meta http-equiv="refresh" content="0;url={e(url)}">
<link rel="canonical" href="{e(url)}">
</head><body><p><a href="{e(url)}">{e(title)}</a></p><p>{e(desc)}</p>
<p><img src="{e(img)}" alt="Mapa del boletín" width="600" height="315"></p>
<p>{e(B.when(doc.get('cutoff')) if doc.get('cutoff') else '')} (hora de Lima). No es una alerta oficial.</p></body></html>
"""
