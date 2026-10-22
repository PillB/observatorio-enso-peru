"""Dibuja los diagramas de arquitectura a partir de ``docs/arquitectura.json``.

Uso:
    python -m tools.architecture [--check] [--explorer ruta.html]
    # --check: falla si los SVG, el texto o el explorador no están al día
    # --explorer: además escribe el explorador en un solo archivo, que se abre sin servidor

Escribe ``docs/arquitectura.svg`` (completo), ``docs/arquitectura-simple.svg``
(simplificado), sus versiones en inglés (``-en.svg``) y sus copias en
``public/assets/``; los anexos A1 a A10 de ``docs/arquitectura-anexos.json``
en ``docs/anexos/`` y ``public/assets/anexos/``; el explorador
``public/arquitectura.html`` y el texto de ``docs/arquitectura.md``. Las cajas
y las conexiones salen del modelo; las líneas se trazan solas (rutas
ortogonales que esquivan las cajas), así que agregar una conexión es editar el
JSON y volver a correr.

Los anchos de texto se miden con las métricas de DejaVu Sans, la más ancha de
las fuentes del sistema que usan los navegadores: si cabe con ella, cabe en
iPhone, Android, Windows y macOS.
"""

from __future__ import annotations

import argparse
import heapq
import json
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "docs" / "arquitectura.json"
OUT = {
    "full": [ROOT / "docs" / "arquitectura.svg", ROOT / "public" / "assets" / "arquitectura.svg"],
    "simple": [ROOT / "docs" / "arquitectura-simple.svg", ROOT / "public" / "assets" / "arquitectura-simple.svg"],
}

# Anchos de DejaVu Sans y DejaVu Sans Bold (milésimas de em).
_CHARS = " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~áéíóúÁÉÍÓÚñÑüÜ¿¡°·→←↔–…«»×≥≤"
_REG = (
    "318,401,460,838,636,950,780,275,390,390,500,838,318,361,318,337,636,636,636,636,636,636,636,636,636,636,337,337,838,"
    "838,838,531,1000,684,686,698,770,632,575,775,752,295,295,656,557,863,748,787,603,787,695,635,611,732,684,989,685,611,"
    "685,390,337,390,838,500,500,613,635,550,635,615,352,635,634,278,278,579,278,974,634,612,635,635,411,521,392,634,592,"
    "818,592,592,525,636,337,636,838,613,615,278,612,634,684,632,295,787,732,634,748,634,732,531,401,500,318,838,838,838,"
    "500,1000,612,612,838,838,838"
)
_BOLD = (
    "348,456,521,838,696,1002,872,306,457,457,523,838,380,415,380,365,696,696,696,696,696,696,696,696,696,696,400,400,838,"
    "838,838,580,1000,774,762,734,830,683,683,821,837,372,372,775,637,995,837,850,733,850,770,720,682,812,774,1103,771,724,"
    "725,457,365,457,838,500,500,675,716,593,716,678,435,716,712,343,343,665,343,1042,712,687,716,716,493,595,478,712,652,"
    "924,645,652,582,712,365,712,838,675,678,343,687,712,774,683,372,850,812,712,837,712,812,580,456,500,380,838,838,838,"
    "500,1000,646,646,838,838,838"
)
_W = {False: dict(zip(_CHARS, map(int, _REG.split(",")))), True: dict(zip(_CHARS, map(int, _BOLD.split(","))))}


def text_width(s: str, size: float, bold: bool = False) -> float:
    t = _W[bold]
    return sum(t.get(c, 1000 if bold else 950) for c in s) * size / 1000


def _split_long(word: str, width: float, size: float, bold: bool) -> list[str]:
    """Parte una palabra más ancha que la línea (una URL) después de «/», «.» o «-», o donde haga falta."""
    if text_width(word, size, bold) <= width:
        return [word]
    parts, cur = [], ""
    for ch in word:
        if cur and text_width(cur + ch, size, bold) > width:
            cut = max(cur.rfind("/"), cur.rfind("."), cur.rfind("-"))
            if cut > len(cur) // 3:
                parts.append(cur[:cut + 1])
                cur = cur[cut + 1:]
            else:
                parts.append(cur)
                cur = ""
        cur += ch
    parts.append(cur)
    return parts


def wrap(s: str, width: float, size: float, bold: bool = False) -> list[str]:
    """Corte por palabras; una palabra más ancha que la línea (una URL) se parte."""
    lines: list[str] = []
    for para in s.split("\n"):
        cur = ""
        words = [w for word in para.split() for w in _split_long(word, width, size, bold)]
        for word in words:
            cand = f"{cur} {word}" if cur else word
            if cur and text_width(cand, size, bold) > width:
                lines.append(cur)
                cur = word
            else:
                cur = cand
        lines.append(cur)
    return lines


def _n(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Rutas ortogonales sobre una grilla (A* con castigo por quiebres y cruces)
# ---------------------------------------------------------------------------
DIRS = {"E": (1, 0), "W": (-1, 0), "S": (0, 1), "N": (0, -1)}
OUTWARD = {"right": "E", "left": "W", "bottom": "S", "top": "N"}
OPPOSITE = {"E": "W", "W": "E", "S": "N", "N": "S"}


class Router:
    def __init__(self, width: float, height: float, boxes: list[tuple[float, float, float, float]], g: int = 6):
        self.g = g
        self.cols, self.rows = int(width // g) + 1, int(height // g) + 1
        self.blocked = bytearray(self.cols * self.rows)
        self.near = bytearray(self.cols * self.rows)
        self.used_h = bytearray(self.cols * self.rows)
        self.used_v = bytearray(self.cols * self.rows)
        self.failed: list = []
        for x, y, w, h in boxes:
            self._mark(x, y, w, h, 1, self.blocked, 1)
            self._mark(x, y, w, h, 3, self.near, 1)
        for r in range(self.rows):  # el borde del dibujo no se usa
            for c in (0, 1, self.cols - 2, self.cols - 1):
                self.blocked[r * self.cols + c] = 1

    def _mark(self, x, y, w, h, pad, arr, val):
        g = self.g
        c0, c1 = max(0, int(x // g) - pad + 1), min(self.cols - 1, int((x + w) // g) + pad)
        r0, r1 = max(0, int(y // g) - pad + 1), min(self.rows - 1, int((y + h) // g) + pad)
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                arr[r * self.cols + c] = val

    def route(self, a: tuple[float, float], a_dir: str, b: tuple[float, float], b_dir: str, stub: int = 3) -> list[tuple[float, float]]:
        """De ``a`` (que sale hacia ``a_dir``) a ``b`` (al que se entra desde ``b_dir``, su lado hacia afuera)."""
        g, C = self.g, self.cols
        # Cajas enfrentadas y muy juntas (una debajo de la otra): un tramo corto, sin rodeos.
        if (a_dir, b_dir) in (("S", "N"), ("N", "S"), ("E", "W"), ("W", "E")):
            vertical = a_dir in "SN"
            gap = (b[1] - a[1]) if a_dir == "S" else (a[1] - b[1]) if a_dir == "N" else (b[0] - a[0]) if a_dir == "E" else (a[0] - b[0])
            if 0 < gap <= 2 * stub * g:
                if vertical:
                    mid = (a[1] + b[1]) / 2
                    return simplify([a, (a[0], mid), (b[0], mid), b])
                mid = (a[0] + b[0]) / 2
                return simplify([a, (mid, a[1]), (mid, b[1]), b])
        dx, dy = DIRS[a_dir]
        sc, sr = round(a[0] / g) + dx * stub, round(a[1] / g) + dy * stub
        ex, ey = DIRS[b_dir]
        gc, gr = round(b[0] / g) + ex * stub, round(b[1] / g) + ey * stub
        final = OPPOSITE[b_dir]
        start = (sc, sr, a_dir)
        best = {start: 0}
        prev: dict = {}
        heap = [(abs(gc - sc) + abs(gr - sr), 0, start)]
        goal = None
        while heap:
            _, cost, st = heapq.heappop(heap)
            if cost > best.get(st, 1 << 30):
                continue
            c, r, d = st
            if c == gc and r == gr and d == final:
                goal = st
                break
            for nd, (mx, my) in DIRS.items():
                if nd == OPPOSITE[d]:
                    continue
                nc, nr = c + mx, r + my
                if not (0 <= nc < self.cols and 0 <= nr < self.rows):
                    continue
                i = nr * C + nc
                if self.blocked[i] and not (abs(nc - gc) + abs(nr - gr) == 0):
                    continue
                step = 1 + (12 if nd != d else 0) + self.near[i] * 2
                if nd in "EW":
                    step += self.used_h[i] * 14 + self.used_v[i] * 3
                else:
                    step += self.used_v[i] * 14 + self.used_h[i] * 3
                nst = (nc, nr, nd)
                ncost = cost + step
                if ncost < best.get(nst, 1 << 30):
                    best[nst] = ncost
                    prev[nst] = st
                    heapq.heappush(heap, (ncost + abs(gc - nc) + abs(gr - nr), ncost, nst))
        if goal is None:  # sin ruta: se anota y queda una línea directa, que el generador rechaza
            self.failed.append((a, b))
            return [a, b]
        cells = []
        st = goal
        while st in prev:
            cells.append(st)
            st = prev[st]
        cells.append(start)
        cells.reverse()
        for c, r, d in cells:
            i = r * C + c
            if d in "EW":
                self.used_h[i] = min(3, self.used_h[i] + 1)
            else:
                self.used_v[i] = min(3, self.used_v[i] + 1)
        pts = [a] + [(c * g, r * g) for c, r, _ in cells] + [b]
        return simplify(pts)


def simplify(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in pts:
        if out and abs(out[-1][0] - p[0]) < 0.01 and abs(out[-1][1] - p[1]) < 0.01:
            continue
        while len(out) >= 2:
            (x0, y0), (x1, y1) = out[-2], out[-1]
            if (abs(x0 - x1) < 0.01 and abs(x1 - p[0]) < 0.01) or (abs(y0 - y1) < 0.01 and abs(y1 - p[1]) < 0.01):
                out.pop()
            else:
                break
        out.append(p)
    return out


def path_d(pts: list[tuple[float, float]], r: float = 6) -> str:
    """Polilínea con esquinas redondeadas."""
    if len(pts) < 3:
        return "M" + " L".join(f"{_n(x)} {_n(y)}" for x, y in pts)
    d = [f"M{_n(pts[0][0])} {_n(pts[0][1])}"]
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        l1, l2 = abs(x1 - x0) + abs(y1 - y0), abs(x2 - x1) + abs(y2 - y1)
        rr = min(r, l1 / 2, l2 / 2)
        ax = x1 - (rr if x1 > x0 else -rr if x1 < x0 else 0)
        ay = y1 - (rr if y1 > y0 else -rr if y1 < y0 else 0)
        bx = x1 + (rr if x2 > x1 else -rr if x2 < x1 else 0)
        by = y1 + (rr if y2 > y1 else -rr if y2 < y1 else 0)
        d.append(f"L{_n(ax)} {_n(ay)} Q{_n(x1)} {_n(y1)} {_n(bx)} {_n(by)}")
    d.append(f"L{_n(pts[-1][0])} {_n(pts[-1][1])}")
    return " ".join(d)


def segments(pts):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        yield (x0, y0, x1, y1, abs(x1 - x0) + abs(y1 - y0))


def overlaps(a, b, pad=0.0):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax - pad < bx + bw and bx - pad < ax + aw and ay - pad < by + bh and by - pad < ay + ah


# ---------------------------------------------------------------------------
# Estilos: los colores son las variables del sitio, con valores de respaldo
# para cuando el SVG se abre solo (claro y oscuro).
# ---------------------------------------------------------------------------
LIGHT = {"bg-elev": "#ffffff", "bg-sunk": "#eaeef3", "fg": "#0d1b2a", "fg-2": "#3c4d61", "fg-3": "#5d6e82",
         "line": "#d5dde7", "brand": "#0b4f71", "brand-2": "#0e7490", "cool": "#2166ac", "warm": "#b2182b",
         "ok": "#1b7a43", "watch": "#8a5a00", "s1": "#c2410c", "s2": "#0f766e", "na": "#55657a"}
DARK = {"bg-elev": "#0f1c2b", "bg-sunk": "#0b1622", "fg": "#e3ebf3", "fg-2": "#b4c2d1", "fg-3": "#8d9db0",
        "line": "#22344a", "brand": "#5cc3e6", "brand-2": "#38bdf8", "cool": "#6cb2e6", "warm": "#f4795f",
        "ok": "#5fd08f", "watch": "#f3c15b", "s1": "#fb923c", "s2": "#5eead4", "na": "#9aabbf"}
# Grupo -> variable de color de su borde.
GROUP_VAR = {"sources": "cool", "channels": "s2", "stores": "watch", "pipeline": "brand", "publication": "ok",
             "site": "s1", "operations": "na", "people": "warm"}
# Tipo de conexión -> (variable de color, guiones).
EDGE_STYLE = {"data": ("fg-3", ""), "fallback": ("watch", "6 4"), "trigger": ("brand-2", "2 3"),
              "control": ("brand-2", "2 3"), "human": ("warm", "8 3 2 3")}


def _rules(pal: dict) -> list[tuple[str, str]]:
    v = lambda k: f"var(--{k}, {pal[k]})"  # noqa: E731
    r = [
        (".ar-bg", f"fill: {v('bg-elev')};"),
        (".ar-col", f"fill: {v('bg-sunk')};"),
        (".ar-node", f"fill: {v('bg-elev')};"),
        (".ar-h, .ar-big, .ar-t", f"fill: {v('fg')};"),
        (".ar-s", f"fill: {v('fg-2')};"),
        (".ar-m", f"fill: {v('fg-3')};"),
        (".ar-halo", f"stroke: {v('bg-elev')};"),
        (".ar-badge", f"fill: {v('bg-elev')};"),
        (".ar-step", f"fill: {v('brand')};"),
        (".ar-step-n", f"fill: {v('bg-elev')};"),
        (".ar-rule", f"stroke: {v('line')};"),
        (".ar-chip", f"fill: {v('bg-sunk')}; stroke: {v('line')};"),
        (".ar-chip-t", f"fill: {v('fg-2')};"),
        (".ar-tag", f"fill: {v('bg-elev')}; stroke: {v('brand-2')};"),
        (".ar-tag-t, .ar-link", f"fill: {v('brand-2')};"),
        (".ar-warn", f"stroke: {v('watch')};"),
    ]
    for g, var in GROUP_VAR.items():
        r.append((f".ar-g-{g}", f"stroke: {v(var)};"))
        r.append((f".ar-f-{g}", f"fill: {v(var)};"))
    for k, (var, _) in EDGE_STYLE.items():
        r.append((f".ar-e-{k}", f"stroke: {v(var)};"))
        r.append((f".ar-k-{k}", f"fill: {v(var)};"))
    return r


def style_block() -> str:
    fixed = [
        ".ar-node { stroke-width: 1.5; }",
        ".ar-h { font-weight: 700; }",
        ".ar-big, .ar-t, .ar-step-n { font-weight: 700; }",
        ".ar-halo { stroke-width: 5px; stroke-linejoin: round; paint-order: stroke; }",
        ".ar-badge { stroke-width: 1.5; }",
        ".ar-rule { stroke-width: 1; }",
        ".ar-e { fill: none; stroke-width: 1.5; }",
        ".ar-edge:hover .ar-e, .ar-edge:focus .ar-e { stroke-width: 3; }",
        ".ar-node-g:hover .ar-node { stroke-width: 3; }",
        ".ar-tile { fill-opacity: 0.13; }",
        ".ar-icon, .ar-warn { fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }",
        ".ar-chip { stroke-width: 1; }",
        ".ar-tag { stroke-width: 1.2; }",
        ".ar-tag-t, .ar-link { font-weight: 700; }",
        ".ar-annex { cursor: pointer; }",
        ".ar-annex:hover .ar-tag, .ar-annex:focus .ar-tag { stroke-width: 2.4; }",
    ]
    out = ["  <style>"]
    out += [f"    {x}" for x in fixed]
    out += [f"    {sel} {{ {decl} }}" for sel, decl in _rules(LIGHT)]
    out.append("    /* abierto solo, sigue el tema del sistema; dentro del sitio mandan las variables del tema */")
    out.append("    @media (prefers-color-scheme: dark) {")
    for sel, decl in _rules(DARK):
        sels = ", ".join(f":root:not([data-theme='light']) {x.strip()}" for x in sel.split(","))
        out.append(f"      {sels} {{ {decl} }}")
    out.append("    }")
    out.append("  </style>")
    return "\n".join(out)


def markers(prefix: str) -> str:
    out = ["  <defs>"]
    for k in EDGE_STYLE:
        out.append(f'    <marker id="{prefix}-m-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
                   f'markerHeight="7" orient="auto-start-reverse"><path class="ar-k-{k}" d="M0 0L10 5L0 10z"/></marker>')
    out.append("  </defs>")
    return "\n".join(out)


def t(x, y, s, cls, size, anchor=None, extra=""):
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text class="{cls}" x="{_n(x)}" y="{_n(y)}" font-size="{_n(size)}"{a}{extra}>{escape(s)}</text>'


# ---------------------------------------------------------------------------
# Cajas
# ---------------------------------------------------------------------------
TAG_SIZE, CHIP_SIZE, CHIP_H, TILE = 10.5, 10, 17, 30

# Íconos de los anexos: trazos propios en una grilla de 24×24 (como public/assets/js/icons.js), sin logotipos.
ICONS = {
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "server": '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01M11 7.5h6M11 16.5h6"/>',
    "laptop": '<rect x="5" y="5" width="14" height="10" rx="1.5"/><path d="M2.5 19h19l-2-4h-15z"/>',
    "cloud": '<path d="M7 19a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 9.5a4.75 4.75 0 0 1-.5 9.5z"/>',
    "flow": '<circle cx="5" cy="6" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="12" r="2.5"/><path d="M7.5 6h3a3 3 0 0 1 3 3v0a3 3 0 0 0 3 3M7.5 18h3a3 3 0 0 0 3-3v0a3 3 0 0 1 3-3"/>',
    "branch": '<circle cx="6" cy="5" r="2.2"/><circle cx="6" cy="19" r="2.2"/><circle cx="18" cy="7" r="2.2"/><path d="M6 7.2v9.6M18 9.2c0 5-6 3.5-11 7.8"/>',
    "commit": '<circle cx="12" cy="12" r="3.5"/><path d="M2 12h6.5M15.5 12H22"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>',
    "pdf": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
    "rss": '<path d="M5 11a8 8 0 0 1 8 8M5 5a14 14 0 0 1 14 14"/><circle cx="6" cy="18" r="1.4"/>',
    "database": '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "alert": '<path d="M12 3l9.5 17H2.5z"/><path d="M12 10v4M12 17v.01"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3.5 6.5l8.5 6 8.5-6"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14a6.5 6.5 0 0 1 3.5 6"/>',
    "pin": '<path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0 1 13 0c0 4.8-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    "chart": '<path d="M4 4v16h16"/><path d="M7 15l4-5 3 3 5-6"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
    "key": '<circle cx="8" cy="15" r="4.5"/><path d="M11.2 11.8L20 3M16 7l3 3M14 9l2 2"/>',
    "lock": '<rect x="4.5" y="10.5" width="15" height="10.5" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5M12 14.5v2.5"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5M5 20h14"/>',
    "download": '<path d="M12 4v12M7 11l5 5 5-5M5 20h14"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.3-4.5L4 8.5M4 4v4.5h4.5M4 13a8 8 0 0 0 14.3 4.5l1.7-2M20 20v-4.5h-4.5"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12.5 15H17"/>',
    "rocket": '<path d="M5 15c-1.5 1.5-2 4.5-2 6 1.5 0 4.5-.5 6-2M14.5 4.5c3-1.5 5-1.5 5.5-1 .5.5.5 2.5-1 5.5L13 15l-4-4z"/><path d="M9 11l-3.5-.5L8 7.5l4 .5M13 15l.5 3.5L16.5 16l-.5-4"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8.5 20h7M12 16v4"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/>',
    "history": '<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6L3.5 8.5"/><path d="M3.5 4v4.5H8M12 8v4.5l3 2"/>',
    "filter": '<path d="M3 5h18l-7 8.5V20l-4-2v-4.5z"/>',
    "merge": '<circle cx="6" cy="5" r="2.2"/><circle cx="6" cy="19" r="2.2"/><circle cx="18" cy="12" r="2.2"/><path d="M6 7.2v9.6M7.5 6.6C9 10 12 12 15.8 12"/>',
    "robot": '<rect x="5" y="8" width="14" height="11" rx="2"/><path d="M12 8V4.5M9.5 12.5h.01M14.5 12.5h.01M9.5 16h5M3 12.5v3M21 12.5v3"/><circle cx="12" cy="4" r="1"/>',
    "sparkle": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    "map": '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>',
    "box": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
    "wave": '<path d="M2 12c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/><path d="M2 17c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/><path d="M12 3v4"/>',
    "code": '<path d="M8.5 7L3.5 12l5 5M15.5 7l5 5-5 5M13.5 4.5l-3 15"/>',
    "chat": '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12h5"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
}


def tag_width(label: str) -> float:
    return text_width(label, TAG_SIZE, True) + 12


class Box:
    """Caja con título, texto y detalle. Opcionales: ``step`` (número del recorrido), ``tags`` (anexos a los que
    remite: (id, etiqueta, href, explicación)), y en los anexos el ícono (``node["icon"]``) y las tecnologías
    (``node["tech"]``)."""

    def __init__(self, node: dict, x: float, y: float, w: float, lang: str, sizes: tuple, step: str = "",
                 tags: list | None = None):
        self.node, self.id, self.x, self.y, self.w = node, node["id"], x, y, w
        self.group = node.get("group", "pipeline")
        ts, ss, ms = sizes
        self.sizes = sizes
        self.step = step
        self.tags = tags or []
        self.icon = node.get("icon") or ""
        pad = 12
        self.tags_w = sum(tag_width(tg[1]) for tg in self.tags) + 4 * max(0, len(self.tags) - 1) + (8 if self.tags else 0)
        inner = w - 2 * pad - (26 if step else 0) - (TILE + 8 if self.icon else 0) - self.tags_w
        self.title = wrap(node[f"name_{lang}"], inner, ts, True)
        self.body = wrap(node[f"what_{lang}"], w - 2 * pad, ss)
        meta = node.get(f"meta_{lang}") or ""
        self.meta = wrap(meta, w - 2 * pad, ms) if meta else []
        self.lh_t, self.lh_s, self.lh_m = ts * 1.3, ss * 1.38, ms * 1.38
        # Tecnologías: fichas en filas, al pie de la caja.
        self.chips: list[tuple[float, float, str]] = []
        cx, row = 0.0, 0
        for name in node.get("tech") or []:
            cw = text_width(name, CHIP_SIZE) + 12
            if cx and cx + cw > w - 2 * pad:
                cx, row = 0.0, row + 1
            self.chips.append((cx, row * (CHIP_H + 5), name))
            cx += cw + 5
        chips_h = self.chips_h = (row + 1) * (CHIP_H + 5) + 2 if self.chips else 0
        head = max(len(self.title) * self.lh_t, TILE + 4 if self.icon else 0, 20 if self.tags else 0)
        self.head = head
        self.h = pad + head + 4 + len(self.body) * self.lh_s + (len(self.meta) * self.lh_m + 4 if self.meta else 0) + chips_h + pad - 2

    @property
    def rect(self):
        return (self.x, self.y, self.w, self.h)

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def svg(self, prefix: str, tip: str) -> list[str]:
        ts, ss, ms = self.sizes
        pad = 12
        o = [f'  <g class="ar-node-g" id="{prefix}-n-{self.id}" data-node="{self.id}">',
             f"    <title>{escape(tip)}</title>",
             f'    <rect class="ar-node ar-g-{self.group}" x="{_n(self.x)}" y="{_n(self.y)}" width="{_n(self.w)}" height="{_n(self.h)}" rx="8"/>',
             f'    <rect class="ar-f-{self.group}" x="{_n(self.x)}" y="{_n(self.y + 8)}" width="4" height="{_n(self.h - 16)}" rx="2"/>']
        y = self.y + pad + ts
        tx = self.x + pad
        if self.step:
            o.append(f'    <circle class="ar-step" cx="{_n(tx + 9)}" cy="{_n(y - ts * 0.36)}" r="10"/>')
            o.append("    " + t(tx + 9, y - ts * 0.36 + 4.2, self.step, "ar-step-n", 12, "middle"))
            tx += 26
        if self.icon:
            ty = self.y + pad - 2
            o.append(f'    <rect class="ar-tile ar-f-{self.group}" x="{_n(tx)}" y="{_n(ty)}" width="{TILE}" height="{TILE}" rx="7"/>')
            o.append(f'    <g class="ar-icon ar-g-{self.group}" transform="translate({_n(tx + 3)} {_n(ty + 3)})">{ICONS[self.icon]}</g>')
            if len(self.title) == 1:
                y = ty + TILE / 2 + ts * 0.36
            tx += TILE + 8
        for line in self.title:
            o.append("    " + t(tx, y, line, "ar-t", ts))
            y += self.lh_t
        y = self.y + pad + self.head + 4 + (ts - self.lh_t) + self.lh_s
        for line in self.body:
            o.append("    " + t(self.x + pad, y, line, "ar-s", ss))
            y += self.lh_s
        if self.meta:
            y += 4
            for line in self.meta:
                o.append("    " + t(self.x + pad, y, line, "ar-m", ms))
                y += self.lh_m
        if self.chips:
            cy0 = self.y + self.h - 4 - self.chips_h
            for cx, dy, name in self.chips:
                cw = text_width(name, CHIP_SIZE) + 12
                o.append(f'    <rect class="ar-chip" x="{_n(self.x + pad + cx)}" y="{_n(cy0 + dy)}" width="{_n(cw)}" height="{CHIP_H}" rx="8.5"/>')
                o.append("    " + t(self.x + pad + cx + 6, cy0 + dy + 12, name, "ar-chip-t", CHIP_SIZE))
        # Las etiquetas de anexo van al final: así el primer texto de la caja sigue siendo su título.
        tx = self.x + self.w - pad + 4
        for aid, label, href, tip in reversed(self.tags):
            tw = tag_width(label)
            tx -= tw
            o.append(f'    <a class="ar-annex" href="{escape(href)}" data-annex="{aid}"><title>{escape(tip)}</title>'
                     f'<rect class="ar-tag" x="{_n(tx)}" y="{_n(self.y + 7)}" width="{_n(tw)}" height="17" rx="8.5"/>'
                     + t(tx + tw / 2, self.y + 19.5, label, "ar-tag-t", TAG_SIZE, "middle") + "</a>")
            tx -= 4
        o.append("  </g>")
        return o


# ---------------------------------------------------------------------------
# Conexiones
# ---------------------------------------------------------------------------
def choose_sides(a: Box, b: Box, col_of: dict, override: list | None = None, info: dict | None = None) -> tuple[str, str]:
    """Lados por los que sale y entra una conexión. ``info`` dice la columna de cada caja, cuál le sigue en su
    columna y cuáles van en la banda de abajo."""
    if override:
        return override[0], override[1]
    info = info or {}
    band = info.get("band", set())
    nxt = info.get("next", {})
    last = info.get("last", set())
    ca, cb = col_of.get(a.id), col_of.get(b.id)
    if a.id not in band and b.id not in band and ca is not None and cb is not None:
        if ca != cb:
            return ("right", "left") if cb > ca else ("left", "right")
        if nxt.get(a.id) == b.id:
            return "bottom", "top"
        if nxt.get(b.id) == a.id:
            return "top", "bottom"
        return "right", "right"
    if (a.id in band) != (b.id in band):  # columna <-> banda
        col, bnd = (a, b) if b.id in band else (b, a)
        if col.id in last and abs(col.cx - bnd.cx) < col.w:
            side = "bottom"
        else:
            side = "right" if bnd.cx >= col.cx else "left"
        return (side, "top") if col is a else ("top", side)
    # dentro de la banda
    if abs(a.y - b.y) < 1:
        return ("right", "left") if b.cx > a.cx else ("left", "right")
    if abs(a.cx - b.cx) < max(a.w, b.w) / 2:
        return ("bottom", "top") if b.y > a.y else ("top", "bottom")
    if b.y > a.y:
        return ("right", "top") if b.cx > a.cx else ("left", "top")
    return ("right", "bottom") if b.cx > a.cx else ("left", "bottom")


def assign_ports(boxes: dict, edges: list, sides: dict, g: int) -> dict:
    """Reparte las conexiones de cada lado de cada caja a lo largo del lado, ordenadas por el otro extremo."""
    per: dict = {}
    for i, e in enumerate(edges):
        sa, sb = sides[i]
        per.setdefault((e["from"], sa), []).append((i, 0, e["to"]))
        per.setdefault((e["to"], sb), []).append((i, 1, e["from"]))
    ports: dict = {}
    for (nid, side), lst in per.items():
        b = boxes[nid]
        horiz = side in ("top", "bottom")
        lst.sort(key=lambda it: (boxes[it[2]].cx if horiz else boxes[it[2]].cy, it[0]))
        lo, hi = (b.x + 14, b.x + b.w - 14) if horiz else (b.y + 10, b.y + b.h - 10)
        n = len(lst)
        for k, (i, end, _) in enumerate(lst):
            pos = (lo + hi) / 2 if n == 1 else lo + (hi - lo) * (k + 0.5) / n
            pos = round(pos / g) * g
            pos = min(max(pos, lo), hi)
            if side == "left":
                pt = (b.x, pos)
            elif side == "right":
                pt = (b.x + b.w, pos)
            elif side == "top":
                pt = (pos, b.y)
            else:
                pt = (pos, b.y + b.h)
            ports[(i, end)] = pt
    return ports


def place_on_path(pts, w, h, taken, boxes, prefer_horizontal=False):
    """Busca un lugar para una insignia de ``w``×``h`` centrada sobre un tramo de la línea."""
    segs = sorted(segments(pts), key=lambda s: -s[4])
    if prefer_horizontal:
        segs.sort(key=lambda s: (abs(s[1] - s[3]) > 0.01, -s[4]))
    for frac in (0.5, 0.32, 0.68, 0.2, 0.8):
        for x0, y0, x1, y1, ln in segs:
            if ln < max(w, h) + 10:
                continue
            cx, cy = x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac
            r = (cx - w / 2, cy - h / 2, w, h)
            if any(overlaps(r, q, 2) for q in taken) or any(overlaps(r, bx, 1) for bx in boxes):
                continue
            return cx, cy, abs(y0 - y1) < 0.01
    x0, y0, x1, y1, _ = segs[0]
    return (x0 + x1) / 2, (y0 + y1) / 2, abs(y0 - y1) < 0.01


def seg_rects(pts, pad: float = 3.0) -> list:
    return [(min(x0, x1) - pad, min(y0, y1) - pad, abs(x1 - x0) + 2 * pad, abs(y1 - y0) + 2 * pad)
            for x0, y0, x1, y1, _ in segments(pts)]


def place_label(pts, label: str, size: float, taken, boxes, max_w: float = 170, lines_of_others=()):
    """Insignia sobre la línea y la etiqueta al lado: encima de un tramo horizontal (cortada al ancho del tramo)
    o a la derecha de uno vertical. Devuelve (insignia, líneas de la etiqueta, caja de la etiqueta) o None."""
    lh = size * 1.3
    longest = max(text_width(w, size) for w in label.split())
    cands = []
    for x0, y0, x1, y1, ln in segments(pts):
        horiz = abs(y0 - y1) < 0.01
        for frac in (0.5, 0.35, 0.65, 0.22, 0.78):
            cx, cy = x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac
            badge = (cx - 10, cy - 10, 20, 20)
            if horiz:
                room = min(max_w, ln - 16)
                if room < max(50, longest):  # sin partir palabras
                    continue
                lines = wrap(label, room, size)
                tw = max(text_width(x, size) for x in lines)
                if tw > ln - 8:
                    continue
                th = len(lines) * lh
                places = [(cx - tw / 2 - 3, cy - 13 - th, tw + 6, th + 4)]
            else:
                if ln < 40:
                    continue
                lines = wrap(label, max_w, size)
                tw = max(text_width(x, size) for x in lines)
                th = len(lines) * lh
                # a la derecha de la línea o, si no cabe, a la izquierda
                places = [(cx + 13, cy - th / 2 - 2, tw + 6, th + 4), (cx - 13 - tw - 6, cy - th / 2 - 2, tw + 6, th + 4)]
            for k, lab in enumerate(places):
                # Menos renglones, mejor; luego los tramos horizontales, el lado derecho y el medio del tramo.
                score = (len(lines), 0 if horiz else 1, k, abs(frac - 0.5))
                cands.append((score, (cx, cy, horiz), lines, lab, badge))
    cands.sort(key=lambda c: c[0])
    for _, bpos, lines, lab, badge in cands:
        if any(overlaps(lab, q, 3) or overlaps(badge, q, 2) for q in taken):
            continue
        if any(overlaps(lab, bx, 2) or overlaps(badge, bx, 2) for bx in boxes):
            continue
        if any(overlaps(lab, q) or overlaps(badge, q) for q in lines_of_others):
            continue
        return bpos, lines, lab, badge
    return None


def route_edges(boxes: dict, edges: list, col_of: dict, width: float, height: float, g: int = 6, obstacles=(), info=None):
    sides = {i: choose_sides(boxes[e["from"]], boxes[e["to"]], col_of, e.get("sides"), info) for i, e in enumerate(edges)}
    ports = assign_ports(boxes, edges, sides, g)
    router = Router(width, height, [b.rect for b in boxes.values()] + list(obstacles), g)
    order = sorted(range(len(edges)), key=lambda i: (abs(boxes[edges[i]["from"]].cx - boxes[edges[i]["to"]].cx)
                                                     + abs(boxes[edges[i]["from"]].cy - boxes[edges[i]["to"]].cy), i))
    routes, bad = {}, []
    for i in order:
        sa, sb = sides[i]
        n = len(router.failed)
        routes[i] = router.route(ports[(i, 0)], OUTWARD[sa], ports[(i, 1)], OUTWARD[sb])
        if len(router.failed) > n:
            bad.append(f'{edges[i]["from"]} -> {edges[i]["to"]} ({sa}, {sb})')
    if bad:
        raise ValueError("conexiones sin ruta (mover cajas o fijar «sides»): " + ", ".join(bad))
    return routes


def edge_svg(prefix: str, i: int, e: dict, pts, badge: str, bpos, label: str | None, lpos, lang: str,
             tip: str, label_size: float = 11.5) -> list[str]:
    kind = e.get("kind", "data") if e.get("kind") in EDGE_STYLE else "data"
    dash = EDGE_STYLE[kind][1]
    da = f' stroke-dasharray="{dash}"' if dash else ""
    both = ' marker-start="url(#%s-m-%s)"' % (prefix, kind) if e.get("both") else ""
    o = [f'  <g class="ar-edge" id="{prefix}-e-{badge}" data-edge="{badge}" data-from="{e["from"]}" data-to="{e["to"]}" tabindex="0">',
         f"    <title>{escape(tip)}</title>",
         f'    <path class="ar-e ar-e-{kind}" d="{path_d(pts)}"{da} marker-end="url(#{prefix}-m-{kind})"{both}/>']
    if label and lpos:
        lines, (lx, ly, lw, lh) = lpos
        step = label_size * 1.3
        for k, line in enumerate(lines):
            o.append("    " + t(lx + 3, ly + 2 + label_size + k * step - 1, line, "ar-s ar-halo", label_size))
    bx, by, _ = bpos
    r = 9 if len(badge) < 3 else 11
    o.append(f'    <circle class="ar-badge ar-e-{kind}" cx="{_n(bx)}" cy="{_n(by)}" r="{r}"/>')
    o.append("    " + t(bx, by + 3.8, badge, "ar-t", 10.5, "middle"))
    o.append("  </g>")
    return o


# ---------------------------------------------------------------------------
# Diagramas
# ---------------------------------------------------------------------------
UI = {
    "es": {"how": "Cómo leerlo", "edges": "Conexiones", "steps": "Recorrido", "key": "Líneas:",
           "kinds": {"data": "datos", "fallback": "respaldo", "trigger": "disparo o control", "human": "paso manual"},
           "annex": "Anexo", "annex_steps": "Pasos y conexiones", "annex_edges": "qué viaja por cada línea, cuándo y por qué",
           "fails": "Si algo falla", "fails_sub": "qué pasa y qué respaldo entra",
           "details": "Detalla estas cajas del diagrama completo:", "back": "← Volver al diagrama completo",
           "tags": "Las etiquetas A1 a A{n} abren el anexo de cada parte: sus pasos, tecnologías y respaldos.",
           "tech": "Tecnología"},
    "en": {"how": "How to read it", "edges": "Connections", "steps": "Walkthrough", "key": "Lines:",
           "kinds": {"data": "data", "fallback": "fallback", "trigger": "trigger or control", "human": "manual step"},
           "annex": "Annex", "annex_steps": "Steps and connections", "annex_edges": "what travels along each line, when and why",
           "fails": "If something fails", "fails_sub": "what happens and which fallback takes over",
           "details": "Details these boxes of the full diagram:", "back": "← Back to the full diagram",
           "tags": "Tags A1 to A{n} open each part's annex: its steps, technologies and fallbacks.",
           "tech": "Technology"},
}


def _key_row(x: float, y: float, lang: str, prefix: str) -> tuple[list[str], float]:
    o = [t(x, y + 4, UI[lang]["key"], "ar-t", 11.5)]
    x += text_width(UI[lang]["key"], 11.5, True) + 12
    for k, name in UI[lang]["kinds"].items():
        dash = EDGE_STYLE[k][1]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        o.append(f'<path class="ar-e ar-e-{k}" d="M{_n(x)} {_n(y)} L{_n(x + 34)} {_n(y)}"{da} marker-end="url(#{prefix}-m-{k})"/>')
        o.append(t(x + 42, y + 4, name, "ar-s", 11.5))
        x += 42 + text_width(name, 11.5) + 22
    return o, x


def _tip(n: dict, lang: str) -> str:
    parts = [n[f"name_{lang}"] + ".", n[f"what_{lang}"]]
    if n.get(f"meta_{lang}"):
        parts.append(n[f"meta_{lang}"].rstrip(".") + ".")
    if n.get("tech"):
        parts.append(f'{UI[lang]["tech"]}: {", ".join(n["tech"])}.')
    return " ".join(parts)


def _etip(e: dict, nodes: dict, lang: str, badge: str) -> str:
    a, b = nodes[e["from"]][f"name_{lang}"], nodes[e["to"]][f"name_{lang}"]
    expl = e.get(f"explain_{lang}", "")
    return f"{badge}. {a} → {b}: {e[f'label_{lang}']}." + (f" {expl}" if expl else "")


def _legend(entries: list[tuple[str, str, str, str, str]], x: float, y: float, width: float, ncols: int,
            gap: float = 28) -> tuple[list[str], float]:
    """Entradas (insignia, tipo, título, subtítulo, texto) en ``ncols`` columnas equilibradas por altura."""
    colw = (width - gap * (ncols - 1)) / ncols
    text_x = 30
    blocks = []
    for badge, kind, title, sub, body in entries:
        tl = wrap(title, colw - text_x, 11.5, True)
        sl = wrap(sub, colw - text_x, 10.5) if sub else []
        bl = wrap(body, colw - text_x, 11) if body else []
        h = len(tl) * 15 + len(sl) * 14 + len(bl) * 15 + 12
        blocks.append((badge, kind, tl, sl, bl, h))
    total = sum(b[-1] for b in blocks)
    target = total / ncols
    cols, cur, acc = [], [], 0.0
    for b in blocks:
        if cur and acc + b[-1] / 2 > target and len(cols) < ncols - 1:
            cols.append(cur)
            cur, acc = [], 0.0
        cur.append(b)
        acc += b[-1]
    cols.append(cur)
    o: list[str] = []
    bottom = y
    for ci, col in enumerate(cols):
        cx, cy = x + ci * (colw + gap), y
        for badge, kind, tl, sl, bl, h in col:
            k = kind if kind in EDGE_STYLE else "data"
            if kind == "warn":
                o.append(f'<g class="ar-warn" transform="translate({_n(cx)} {_n(cy - 5)}) scale(0.85)">{ICONS["alert"]}</g>')
            elif kind == "step":
                o.append(f'<circle class="ar-step" cx="{_n(cx + 10)}" cy="{_n(cy + 6)}" r="10"/>')
                o.append(t(cx + 10, cy + 10.2, badge, "ar-step-n", 11.5, "middle"))
            else:
                r = 9 if len(badge) < 3 else 11
                o.append(f'<circle class="ar-badge ar-e-{k}" cx="{_n(cx + 10)}" cy="{_n(cy + 6)}" r="{r}"/>')
                o.append(t(cx + 10, cy + 9.8, badge, "ar-t", 10.5, "middle"))
            ly = cy + 10
            for line in tl:
                o.append(t(cx + text_x, ly, line, "ar-t", 11.5))
                ly += 15
            for line in sl:
                o.append(t(cx + text_x, ly - 1, line, "ar-m", 10.5))
                ly += 14
            for line in bl:
                o.append(t(cx + text_x, ly, line, "ar-s", 11))
                ly += 15
            cy += h
        bottom = max(bottom, cy)
    return o, bottom


def _svg(prefix: str, width: float, height: float, title: str, desc: str, body: list[str]) -> str:
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(width)} {_n(height)}" role="img" '
            f'aria-labelledby="{prefix}-t {prefix}-d" font-family="system-ui, -apple-system, \'Segoe UI\', Roboto, Arial, sans-serif">')
    return "\n".join([
        head,
        f'  <title id="{prefix}-t">{escape(title)}</title>',
        f'  <desc id="{prefix}-d">{escape(desc)}</desc>',
        style_block(),
        markers(prefix),
        f'  <rect class="ar-bg" x="0" y="0" width="{_n(width)}" height="{_n(height)}" rx="14"/>',
        *[("  " + line if not line.startswith("  ") else line) for line in body],
        "</svg>",
        "",
    ])


def annex_file(aid: str, lang: str) -> str:
    return f"{aid}{'-en' if lang == 'en' else ''}.svg"


def annex_tag(a: dict, lang: str, base: str = "anexos/") -> tuple[str, str, str, str]:
    return (a["id"], a["id"].upper(), base + annex_file(a["id"], lang), f'{UI[lang]["annex"]} {a["id"].upper()}: {a[f"title_{lang}"]}')


def _subtitle(text: str, lang: str, annexes: list | None) -> str:
    return f'{text} {UI[lang]["tags"].format(n=len(annexes))}' if annexes else text


def render_full(model: dict, lang: str = "es", annexes: list | None = None) -> str:
    m = model["full"]
    P = "af"
    W, M = m["width"], 20
    MC = m.get("margin", 44)  # las columnas dejan a cada lado un pasillo para las líneas
    nodes = {n["id"]: n for n in m["nodes"]}
    # Cada caja remite al anexo que la detalla.
    tag_of = {c: [annex_tag(a, lang)] for a in annexes or [] for c in a["covers"]}
    body: list[str] = []
    body.append(t(M, 38, m[f"title_{lang}"], "ar-big", 20))
    sub = wrap(_subtitle(m[f"subtitle_{lang}"], lang, annexes), W - 2 * M, 12)
    y = 60
    for line in sub:
        body.append(t(M, y, line, "ar-s", 12))
        y += 17
    k, _ = _key_row(M, y + 6, lang, P)
    body += k
    top = y + 30
    cols = m["columns"]
    gutter = (W - 2 * MC - sum(c["w"] for c in cols)) / (len(cols) - 1)
    boxes: dict[str, Box] = {}
    col_of: dict[str, int] = {}
    xs, x = [], MC
    for c in cols:
        xs.append(x)
        x += c["w"] + gutter
    bottoms = []
    for ci, c in enumerate(cols):
        cy = top + 40
        for n in (n for n in m["nodes"] if n.get("col") == c["id"]):
            cy += n.get("gap_before", 0)
            b = Box(n, xs[ci] + 10, cy, c["w"] - 20, lang, (12.5, 11, 10.5), tags=tag_of.get(n["id"]))
            boxes[n["id"]] = b
            col_of[n["id"]] = ci
            cy += b.h + m.get("gap", 26)
        bottoms.append(cy)
    col_bottom = max(bottoms) - m.get("gap", 26) + 14
    panels = []
    for ci, c in enumerate(cols):
        panels.append(f'<rect class="ar-col" x="{_n(xs[ci])}" y="{_n(top)}" width="{_n(c["w"])}" height="{_n(col_bottom - top)}" rx="10"/>')
        panels.append(t(xs[ci] + 12, top + 25, c[f"title_{lang}"], "ar-h", 15))
    # Banda de operación y personas, debajo de las columnas: cada caja va bajo una columna, en filas.
    band = m["band"]
    band_nodes = [n for n in m["nodes"] if n.get("col") == "band"]
    by = col_bottom + m.get("corridor", 70)
    bx0, bw = MC, W - 2 * MC
    col_idx = {c["id"]: i for i, c in enumerate(cols)}
    rows: dict[int, list] = {}
    for n in band_nodes:
        rows.setdefault(n.get("row", 0), []).append(n)
    ry = by + 72
    for r in sorted(rows):
        rh = 0.0
        for n in rows[r]:
            ci = col_idx[n["slot"]]
            b = Box(n, xs[ci] + 10, ry, cols[ci]["w"] - 20, lang, (12.5, 11, 10.5), tags=tag_of.get(n["id"]))
            boxes[n["id"]] = b
            rh = max(rh, b.h)
        ry += rh + m.get("band_gap", 40)
    band_bottom = ry - m.get("band_gap", 40) + 14
    panels.append(f'<rect class="ar-col" x="{_n(bx0)}" y="{_n(by)}" width="{_n(bw)}" height="{_n(band_bottom - by)}" rx="10"/>')
    panels.append(t(bx0 + 12, by + 25, band[f"title_{lang}"], "ar-h", 15))
    region_h = band_bottom + 24
    obstacles = [(0, 0, W, top - 8)]
    obstacles += [(xs[ci], top + 6, text_width(c[f"title_{lang}"], 15, True) + 24, 26) for ci, c in enumerate(cols)]
    obstacles.append((bx0, by + 8, text_width(band[f"title_{lang}"], 15, True) + 24, 22))
    info = {"band": {n["id"] for n in band_nodes}, "next": {}, "last": set()}
    for c in cols:
        ids = [n["id"] for n in m["nodes"] if n.get("col") == c["id"]]
        info["next"].update(zip(ids, ids[1:]))
        if ids:
            info["last"].add(ids[-1])
    routes = route_edges(boxes, m["edges"], col_of, W, region_h, 6, obstacles, info)
    taken: list = []
    rects = [b.rect for b in boxes.values()]
    edge_parts: list[str] = []
    for i, e in enumerate(m["edges"]):
        badge = str(i + 1)
        r = 9 if len(badge) < 3 else 11
        pos = place_on_path(routes[i], 2 * r + 2, 2 * r + 2, taken, rects)
        taken.append((pos[0] - r - 1, pos[1] - r - 1, 2 * r + 2, 2 * r + 2))
        edge_parts += edge_svg(P, i, e, routes[i], badge, pos, None, None, lang, _etip(e, nodes, lang, badge))
    body += panels
    body += ["", "  <!-- conexiones -->", *edge_parts, "", "  <!-- cajas -->"]
    for b in boxes.values():
        body += b.svg(P, _tip(b.node, lang))
    # Leyenda de conexiones
    ly = region_h + 16
    body.append(f'<line class="ar-rule" x1="{M}" y1="{_n(ly)}" x2="{_n(W - M)}" y2="{_n(ly)}"/>')
    body.append(t(M, ly + 30, f'{UI[lang]["edges"]}: {m[f"legend_{lang}"]}', "ar-h", 15))
    entries = []
    for i, e in enumerate(m["edges"]):
        a, b = nodes[e["from"]][f"name_{lang}"], nodes[e["to"]][f"name_{lang}"]
        when = f' · {e[f"when_{lang}"]}' if e.get(f"when_{lang}") else ""
        entries.append((str(i + 1), e.get("kind", "data"), e[f"label_{lang}"], f"{a} → {b}{when}", e[f"explain_{lang}"]))
    leg, bottom = _legend(entries, M, ly + 52, W - 2 * M, 3)
    body += leg
    H = bottom + 20
    return _svg(P, W, H, m[f"title_{lang}"], m[f"desc_{lang}"], body)


def render_simple(model: dict, lang: str = "es", annexes: list | None = None) -> str:
    m = model["simple"]
    tag_of: dict[str, list] = {}
    for a in annexes or []:
        for sid in a.get("simple", []):
            tag_of.setdefault(sid, []).append(annex_tag(a, lang))
    P = "as"
    W, M = m["width"], 20
    nodes = {n["id"]: n for n in m["nodes"]}
    steps = model["walkthrough"]
    # El número de cada caja es el paso del recorrido que la presenta (el primero que la nombra primero).
    step_of: dict[str, str] = {}
    for si, s in enumerate(steps):
        step_of.setdefault(s["nodes"][0], str(si + 1))
    for si, s in enumerate(steps):
        for nid in s["nodes"]:
            step_of.setdefault(nid, str(si + 1))
    body: list[str] = []
    body.append(t(M, 38, m[f"title_{lang}"], "ar-big", 20))
    y = 60
    for line in wrap(_subtitle(m[f"subtitle_{lang}"], lang, annexes), W - 2 * M, 12):
        body.append(t(M, y, line, "ar-s", 12))
        y += 17
    k, _ = _key_row(M, y + 6, lang, P)
    body += k
    top = y + 34
    boxes: dict[str, Box] = {}
    for n in m["nodes"]:
        boxes[n["id"]] = Box(n, n["x"], top + n["y"], n["w"], lang, (14, 12, 11), step_of.get(n["id"], ""),
                             tags=tag_of.get(n["id"]))
    region_h = max(b.y + b.h for b in boxes.values()) + 30
    routes = route_edges(boxes, m["edges"], {}, W, region_h, 6, [(0, 0, W, top - 12)])
    taken: list = []
    rects = [b.rect for b in boxes.values()]
    parts: list[str] = []
    for i, e in enumerate(m["edges"]):
        badge = chr(ord("A") + i)
        others = [r for j in routes if j != i for r in seg_rects(routes[j])]
        got = place_label(routes[i], e[f"label_{lang}"], 11.5, taken, rects, lines_of_others=others)
        if got:
            bpos, lines, lab, bbox = got
            taken += [lab, bbox]
            lpos = (lines, lab)
        else:  # sin lugar para el texto: solo la insignia (la explicación está en la leyenda)
            bpos = place_on_path(routes[i], 22, 22, taken, rects)
            taken.append((bpos[0] - 11, bpos[1] - 11, 22, 22))
            lpos = None
        parts += edge_svg(P, i, e, routes[i], badge, bpos, e[f"label_{lang}"], lpos, lang, _etip(e, nodes, lang, badge))
    body += ["", "  <!-- conexiones -->", *parts, "", "  <!-- cajas -->"]
    for b in boxes.values():
        body += b.svg(P, _tip(b.node, lang))
    ly = region_h + 6
    body.append(f'<line class="ar-rule" x1="{M}" y1="{_n(ly)}" x2="{_n(W - M)}" y2="{_n(ly)}"/>')
    half = (W - 2 * M - 32) / 2
    body.append(t(M, ly + 30, UI[lang]["steps"], "ar-h", 15))
    body.append(t(M + half + 32, ly + 30, UI[lang]["edges"], "ar-h", 15))
    s_entries = [(str(i + 1), "step", s[f"title_{lang}"], "", s[f"text_{lang}"]) for i, s in enumerate(steps)]
    e_entries = [(chr(ord("A") + i), e.get("kind", "data"), e[f"label_{lang}"],
                  f'{nodes[e["from"]][f"name_{lang}"]} → {nodes[e["to"]][f"name_{lang}"]}', e[f"explain_{lang}"])
                 for i, e in enumerate(m["edges"])]
    a, b1 = _legend(s_entries, M, ly + 50, half, 1)
    c, b2 = _legend(e_entries, M + half + 32, ly + 50, half, 1)
    body += a + c
    H = max(b1, b2) + 20
    return _svg(P, W, H, m[f"title_{lang}"], m[f"desc_{lang}"], body)


def render_annex(model: dict, annexes: list, a: dict, lang: str = "es") -> str:
    """Un anexo: el detalle de una parte del sistema en columnas (dónde corre cada paso), con sus pasos, la
    tecnología de cada uno, las conexiones numeradas y, abajo, qué pasa si algo falla."""
    P = a["id"]
    AID = a["id"].upper()
    W, M = a.get("width", 1440), 20
    MC = a.get("margin", 36)
    by_id = {x["id"]: x for x in annexes}
    full_nodes = {n["id"]: n for n in model["full"]["nodes"]}
    nodes = {n["id"]: n for n in a["nodes"]}
    body: list[str] = []
    back = UI[lang]["back"]
    back_w = text_width(back, 12, True)
    title = f'{UI[lang]["annex"]} {AID} · {a[f"title_{lang}"]}'
    y = 38
    for line in wrap(title, W - 2 * M - back_w - 24, 20, True):
        body.append(t(M, y, line, "ar-big", 20))
        y += 26
    body.append(f'<a class="ar-annex" href="../arquitectura{"-en" if lang == "en" else ""}.svg" data-annex="full">'
                + t(W - M, 36, back, "ar-link", 12, "end") + "</a>")
    y += 22 - 26
    for line in wrap(a[f"subtitle_{lang}"], W - 2 * M, 12):
        body.append(t(M, y, line, "ar-s", 12))
        y += 17
    covers = ", ".join(full_nodes[c][f"name_{lang}"] for c in a["covers"])
    for line in wrap(f'{UI[lang]["details"]} {covers}.', W - 2 * M, 11):
        body.append(t(M, y + 2, line, "ar-m", 11))
        y += 15
    k, _ = _key_row(M, y + 8, lang, P)
    body += k
    top = y + 32
    cols = a["columns"]
    gutter = (W - 2 * MC - sum(c["w"] for c in cols)) / max(1, len(cols) - 1)
    if len(cols) > 1 and gutter < 48:
        raise ValueError(f"{a['id']}: columnas demasiado anchas (pasillo de {gutter:.0f} px)")
    xs, x = [], MC
    for c in cols:
        xs.append(x)
        x += c["w"] + gutter
    heads = []
    for c in cols:
        sub = wrap(c.get(f"sub_{lang}", ""), c["w"] - 24, 10.5) if c.get(f"sub_{lang}") else []
        heads.append(sub)
    head_h = 34 + max(len(h) for h in heads) * 14
    boxes: dict[str, Box] = {}
    col_of: dict[str, int] = {}
    bottoms = []
    for ci, c in enumerate(cols):
        cy = top + head_h + 6
        for n in (n for n in a["nodes"] if n["col"] == c["id"]):
            cy += n.get("gap_before", 0)
            tags = [annex_tag(by_id[s], lang, "") for s in n.get("see", [])]
            b = Box({"group": a.get("group", "pipeline"), **n}, xs[ci] + 10, cy, c["w"] - 20, lang, (12.5, 11, 10.5), tags=tags)
            boxes[n["id"]] = b
            col_of[n["id"]] = ci
            cy += b.h + a.get("gap", 30)
        bottoms.append(cy)
    col_bottom = max(bottoms) - a.get("gap", 30) + 14
    panels = []
    obstacles = [(0, 0, W, top - 8)]
    for ci, c in enumerate(cols):
        panels.append(f'<rect class="ar-col" x="{_n(xs[ci])}" y="{_n(top)}" width="{_n(c["w"])}" height="{_n(col_bottom - top)}" rx="10"/>')
        panels.append(t(xs[ci] + 12, top + 25, c[f"title_{lang}"], "ar-h", 15))
        for li, line in enumerate(heads[ci]):
            panels.append(t(xs[ci] + 12, top + 42 + li * 14, line, "ar-m", 10.5))
        obstacles.append((xs[ci], top + 6, c["w"], head_h - 4))
    region_h = col_bottom + 24
    info = {"band": set(), "next": {}, "last": set()}
    for c in cols:
        ids = [n["id"] for n in a["nodes"] if n["col"] == c["id"]]
        info["next"].update(zip(ids, ids[1:]))
        if ids:
            info["last"].add(ids[-1])
    try:
        routes = route_edges(boxes, a["edges"], col_of, W, region_h, 6, obstacles, info)
    except ValueError as exc:
        raise ValueError(f"{a['id']}: {exc}") from None
    taken: list = []
    rects = [b.rect for b in boxes.values()]
    edge_parts: list[str] = []
    for i, e in enumerate(a["edges"]):
        badge = str(i + 1)
        r = 9 if len(badge) < 3 else 11
        pos = place_on_path(routes[i], 2 * r + 2, 2 * r + 2, taken, rects)
        taken.append((pos[0] - r - 1, pos[1] - r - 1, 2 * r + 2, 2 * r + 2))
        edge_parts += edge_svg(P, i, e, routes[i], badge, pos, None, None, lang, _etip(e, nodes, lang, badge))
    body += panels
    body += ["", "  <!-- conexiones -->", *edge_parts, "", "  <!-- cajas -->"]
    for b in boxes.values():
        body += b.svg(P, _tip(b.node, lang))
    ly = region_h + 16
    body.append(f'<line class="ar-rule" x1="{M}" y1="{_n(ly)}" x2="{_n(W - M)}" y2="{_n(ly)}"/>')
    body.append(t(M, ly + 30, f'{UI[lang]["annex_steps"]}: {UI[lang]["annex_edges"]}', "ar-h", 15))
    entries = []
    for i, e in enumerate(a["edges"]):
        fa, fb = nodes[e["from"]][f"name_{lang}"], nodes[e["to"]][f"name_{lang}"]
        when = f' · {e[f"when_{lang}"]}' if e.get(f"when_{lang}") else ""
        entries.append((str(i + 1), e.get("kind", "data"), e[f"label_{lang}"], f"{fa} → {fb}{when}", e.get(f"explain_{lang}", "")))
    leg, bottom = _legend(entries, M, ly + 52, W - 2 * M, 3)
    body += leg
    if a.get("fails"):
        fy = bottom + 18
        body.append(f'<line class="ar-rule" x1="{M}" y1="{_n(fy)}" x2="{_n(W - M)}" y2="{_n(fy)}"/>')
        body.append(t(M, fy + 30, f'{UI[lang]["fails"]}: {UI[lang]["fails_sub"]}', "ar-h", 15))
        fails = [("", "warn", f[f"if_{lang}"], "", f[f"then_{lang}"]) for f in a["fails"]]
        leg, bottom = _legend(fails, M, fy + 52, W - 2 * M, 3)
        body += leg
    H = bottom + 20
    return _svg(P, W, H, title, a[f"desc_{lang}"], body)


ANNEXES = ROOT / "docs" / "arquitectura-anexos.json"
ANNEX_DIRS = [ROOT / "docs" / "anexos", ROOT / "public" / "assets" / "anexos"]


def load_annexes(path: Path = ANNEXES) -> list:
    return json.loads(path.read_text(encoding="utf-8"))["annexes"] if path.exists() else []


def outputs(model: dict, annexes: list) -> dict[str, tuple[str, list[Path]]]:
    """Cada dibujo con los archivos donde va: los principales en docs/ y public/assets/, los anexos en anexos/."""
    out: dict[str, tuple[str, list[Path]]] = {}
    for lang, sfx in (("es", ""), ("en", "-en")):
        out[f"full{sfx}"] = (render_full(model, lang, annexes), [p.with_name(p.stem + sfx + ".svg") for p in OUT["full"]])
        out[f"simple{sfx}"] = (render_simple(model, lang, annexes), [p.with_name(p.stem + sfx + ".svg") for p in OUT["simple"]])
        for a in annexes:
            out[a["id"] + sfx] = (render_annex(model, annexes, a, lang), [d / annex_file(a["id"], lang) for d in ANNEX_DIRS])
    return out


def render_all(model: dict, annexes: list | None = None) -> dict[str, str]:
    if annexes is None:
        annexes = load_annexes()
    return {k: svg for k, (svg, _) in outputs(model, annexes).items()}


DOC = ROOT / "docs" / "arquitectura.md"
DOC_START, DOC_END = "<!-- recorrido:inicio (generado por python -m tools.architecture) -->", "<!-- recorrido:fin -->"


def _cell(s: str) -> str:
    # «sources/<id>.json» se vería como una etiqueta HTML y desaparecería al mostrar el Markdown.
    return s.replace("|", "\\|").replace("\n", " ").replace("<", "&lt;")


def render_doc_section(model: dict) -> str:
    """El recorrido y las conexiones en texto, para docs/arquitectura.md (se leen sin abrir el SVG)."""
    simple, full = model["simple"], model["full"]
    sn = {n["id"]: n for n in simple["nodes"]}
    fn = {n["id"]: n for n in full["nodes"]}
    step_of: dict[str, int] = {}
    for i, st in enumerate(model["walkthrough"]):
        step_of.setdefault(st["nodes"][0], i + 1)
    for i, st in enumerate(model["walkthrough"]):
        for nid in st["nodes"]:
            step_of.setdefault(nid, i + 1)
    out = [DOC_START, "", "**Recorrido del diagrama simplificado** (el número de cada caja es el paso que la presenta):", ""]
    for i, st in enumerate(model["walkthrough"]):
        boxes = ", ".join(f"{sn[n]['name_es']} ({step_of[n]})" for n in st["nodes"])
        out.append(f"{i + 1}. **{st['title_es']}.** {st['text_es']} _Cajas: {boxes}._")
    out += ["", "**Conexiones del diagrama simplificado:**", "", "| | De → a | Qué viaja, cuándo y por qué |", "|---|---|---|"]
    for i, e in enumerate(simple["edges"]):
        out.append(f"| {chr(65 + i)} | {_cell(sn[e['from']]['name_es'])} → {_cell(sn[e['to']]['name_es'])} | "
                   f"**{_cell(e['label_es'])}.** {_cell(e['explain_es'])} |")
    out += ["", "**Qué cubre cada caja del simplificado en el completo:**", ""]
    for n in simple["nodes"]:
        out.append(f"- **{n['name_es']}:** " + ", ".join(fn[c]["name_es"] for c in n["covers"]) + ".")
    out += ["", "<details><summary>Las 70 conexiones del diagrama completo, en texto</summary>".replace("70", str(len(full["edges"]))), "",
            "| N.º | De → a | Cuándo | Qué viaja y por qué |", "|---|---|---|---|"]
    for i, e in enumerate(full["edges"]):
        out.append(f"| {i + 1} | {_cell(fn[e['from']]['name_es'])} → {_cell(fn[e['to']]['name_es'])} | {_cell(e.get('when_es', ''))} | "
                   f"**{_cell(e['label_es'])}.** {_cell(e['explain_es'])} |")
    out += ["", "</details>", ""]
    out += [f"<details><summary>Las {len(full['nodes'])} cajas del diagrama completo, en texto</summary>", ""]
    groups = [(c["id"], c["title_es"]) for c in full["columns"]] + [("band", full["band"]["title_es"])]
    for col, title in groups:
        out += [f"**{title}**", "", "| Caja | Qué es y qué hace | Detalle |", "|---|---|---|"]
        for n in full["nodes"]:
            if n["col"] != col:
                continue
            when = f" _{_cell(n['meta_es'])}._" if n.get("meta_es") else ""
            out.append(f"| **{_cell(n['name_es'])}** | {_cell(n['what_es'])}{when} | {_cell(n.get('details_es', ''))} |")
        out.append("")
    out += ["</details>", "", DOC_END]
    return "\n".join(out)


ANNEX_START, ANNEX_END = "<!-- anexos:inicio (generado por python -m tools.architecture) -->", "<!-- anexos:fin -->"


def render_doc_annexes(model: dict, annexes: list) -> str:
    """Los anexos en docs/arquitectura.md: un índice, el dibujo de cada uno y su texto (pasos, cajas y fallas)."""
    fn = {n["id"]: n for n in model["full"]["nodes"]}
    sn = {n["id"]: n for n in model["simple"]["nodes"]}
    out = [ANNEX_START, "", "| Anexo | Qué detalla | Cajas del completo | Cajas del simplificado |", "|---|---|---|---|"]
    for a in annexes:
        out.append(f"| [{a['id'].upper()} · {_cell(a['title_es'])}](#{a['id']}) | {_cell(a['desc_es'])} | "
                   + ", ".join(_cell(fn[c]["name_es"]) for c in a["covers"]) + " | "
                   + ", ".join(_cell(sn[c]["name_es"]) for c in a["simple"]) + " |")
    out.append("")
    for a in annexes:
        aid, nodes = a["id"], {n["id"]: n for n in a["nodes"]}
        out += [f'<a id="{aid}"></a>', "", f"#### Anexo {aid.upper()} · {a['title_es']}", "", a["subtitle_es"], "",
                f"![Anexo {aid.upper()}: {a['title_es']}](anexos/{annex_file(aid, 'es')})", "",
                f"_In English: [anexos/{annex_file(aid, 'en')}](anexos/{annex_file(aid, 'en')})._", "",
                f"<details><summary>{aid.upper()} en texto: {len(a['nodes'])} pasos, {len(a['edges'])} conexiones "
                f"y {len(a.get('fails', []))} casos de falla</summary>", "",
                "| Paso | Dónde | Qué hace | Tecnología |", "|---|---|---|---|"]
        cols = {c["id"]: c["title_es"] for c in a["columns"]}
        for n in a["nodes"]:
            meta = f" _{_cell(n['meta_es'])}._" if n.get("meta_es") else ""
            see = " Ver " + ", ".join(f"[{x.upper()}](#{x})" for x in n["see"]) + "." if n.get("see") else ""
            out.append(f"| **{_cell(n['name_es'])}** | {_cell(cols[n['col']])} | {_cell(n['what_es'])}{meta}{see} | "
                       f"{_cell(', '.join(n.get('tech', [])))} |")
        out += ["", "| N.º | De → a | Qué viaja, cuándo y por qué |", "|---|---|---|"]
        for i, e in enumerate(a["edges"]):
            when = f" _{_cell(e['when_es'])}._" if e.get("when_es") else ""
            expl = f" {_cell(e['explain_es'])}" if e.get("explain_es") else ""
            out.append(f"| {i + 1} | {_cell(nodes[e['from']]['name_es'])} → {_cell(nodes[e['to']]['name_es'])} | "
                       f"**{_cell(e['label_es'])}.**{expl}{when} |")
        if a.get("fails"):
            out += ["", "**Si algo falla:**", ""]
            out += [f"- **{f['if_es']}.** {f['then_es']}" for f in a["fails"]]
        out += ["", "</details>", ""]
    out.append(ANNEX_END)
    return "\n".join(out)


def render_doc(model: dict, doc: str, annexes: list | None = None) -> str:
    a, b = doc.index(DOC_START), doc.index(DOC_END) + len(DOC_END)
    doc = doc[:a] + render_doc_section(model) + doc[b:]
    if annexes and ANNEX_START in doc:
        a, b = doc.index(ANNEX_START), doc.index(ANNEX_END) + len(ANNEX_END)
        doc = doc[:a] + render_doc_annexes(model, annexes) + doc[b:]
    return doc


EXPLORER = ROOT / "public" / "arquitectura.html"
EXPLORER_UI = {
    "es": {"page": "Arquitectura del Observatorio ENSO Perú", "simple": "Diagrama simplificado", "full": "Diagrama completo",
           "simple_lead": "El sistema en {ns} cajas, de las fuentes al sitio. Toca una caja para abrir el anexo que la detalla.",
           "full_lead": "Las {nf} partes del sistema y sus conexiones numeradas. Toca una caja o su etiqueta A1 a A10 "
                        "para abrir su anexo: los pasos, la tecnología de cada uno y qué pasa si algo falla.",
           "hint": "Toca una caja o una conexión para leer qué es; las etiquetas A1 a A10 abren el anexo de cada parte.",
           "diagrams": "Diagramas", "annexes": "Anexos", "open": "Abrir", "zoom": "Tamaño real", "lang": "Idioma",
           "svg": "Abrir este SVG", "site": "Volver al sitio", "nav": "Diagramas y anexos",
           "error": "No se pudo cargar este diagrama. Intente de nuevo en unos minutos.",
           "foot": "Se dibujan con python -m tools.architecture desde docs/arquitectura.json y docs/arquitectura-anexos.json."},
    "en": {"page": "ENSO Peru Observatory architecture", "simple": "Simplified diagram", "full": "Full diagram",
           "simple_lead": "The system in {ns} boxes, from the sources to the site. Tap a box to open the annex that details it.",
           "full_lead": "The system's {nf} parts and their numbered connections. Tap a box or its A1 to A10 tag to open "
                        "its annex: the steps, each one's technology and what happens if something fails.",
           "hint": "Tap a box or a connection to read what it is; the A1 to A10 tags open each part's annex.",
           "diagrams": "Diagrams", "annexes": "Annexes", "open": "Open", "zoom": "Actual size", "lang": "Language",
           "svg": "Open this SVG", "site": "Back to the site", "nav": "Diagrams and annexes",
           "error": "This diagram could not be loaded. Please try again in a few minutes.",
           "foot": "Drawn with python -m tools.architecture from docs/arquitectura.json and docs/arquitectura-anexos.json."},
}


def render_explorer(model: dict, annexes: list, inline: dict | None = None) -> str:
    """La página que recorre los diagramas y sus anexos (public/arquitectura.html).

    Con ``inline`` ({"css": ..., "js": ..., "svgs": {archivo: svg}}) sale una sola página que se abre sin servidor:
    estilos, código y dibujos van dentro."""
    counts = {"ns": len(model["simple"]["nodes"]), "nf": len(model["full"]["nodes"])}
    ui = {lang: {k: v.format(**counts) if "{" in v else v for k, v in d.items()} for lang, d in EXPLORER_UI.items()}
    U = ui["es"]
    meta = {"base": "assets/", "ui": ui,
            "annexes": [{k: a[k] for k in ("id", "title_es", "title_en", "desc_es", "desc_en")} for a in annexes]}
    meta_json = json.dumps(meta, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    nav = [f'      <li class="ax-main-view"><a href="#{v}" data-view="{v}"><span class="ax-nav-t">{escape(U[v])}</span></a></li>'
           for v in ("simple", "full")]
    items = [f'      <li><a href="#{a["id"]}" data-view="{a["id"]}" title="{escape(a["title_es"])}"><b>{a["id"].upper()}</b>'
             f'<span class="ax-nav-t">{escape(a["title_es"])}</span></a></li>' for a in annexes]
    if inline:
        head = [f"  <style>\n{inline['css']}  </style>"]
        site = ""
        open_svg = ""
        tail = [f'  <template data-file="{escape(name)}">{svg}</template>' for name, svg in inline["svgs"].items()]
        tail.append(f"  <script>\n{inline['js']}  </script>")
    else:
        head = ['  <meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\'; '
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                "base-uri 'self'; form-action 'self'\">",
                '  <link rel="icon" href="favicon.svg" type="image/svg+xml">',
                '  <link rel="stylesheet" href="assets/css/arquitectura.css">']
        site = f'      <a class="ax-btn" href="./#/metodologia" data-ui="site">{U["site"]}</a>\n'
        open_svg = f'    <p class="ax-foot"><a id="ax-open" href="assets/arquitectura-simple.svg" target="_blank" rel="noopener" data-ui="svg">{U["svg"]}</a></p>\n'
        tail = ['  <script src="assets/js/arquitectura.js"></script>']
    return "\n".join([
        "<!doctype html>",
        '<html lang="es-PE">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        f"  <title>{escape(U['page'])}</title>",
        '  <meta name="description" content="Diagramas de arquitectura del Observatorio ENSO Perú y sus anexos A1 a A10: de dónde sale cada dato, qué tecnología lo procesa y qué respaldo entra si algo falla.">',
        *head,
        "</head>",
        "<body>",
        '  <header class="ax-header">',
        f'    <span class="ax-brand"><span>{escape(U["page"])}<small>{len(annexes)} anexos · ES / EN</small></span></span>',
        '    <div class="ax-tools">',
        f'      <div class="ax-seg" role="group" aria-label="Idioma / Language"><button type="button" data-lang="es" aria-pressed="true">Español</button><button type="button" data-lang="en" aria-pressed="false">English</button></div>',
        f'      <button type="button" class="ax-btn" id="ax-zoom" aria-pressed="false" data-ui="zoom">{U["zoom"]}</button>',
        site + "    </div>",
        "  </header>",
        '  <div class="ax-layout">',
        f'    <nav class="ax-nav" aria-label="{escape(U["nav"])}">',
        f'      <h2 data-ui="diagrams">{U["diagrams"]}</h2>',
        "      <ol>",
        *nav,
        "      </ol>",
        f'      <h2 data-ui="annexes">{U["annexes"]}</h2>',
        "      <ol>",
        *items,
        "      </ol>",
        "    </nav>",
        '    <main class="ax-main">',
        f'      <h1 id="ax-title" tabindex="-1">{escape(U["simple"])}</h1>',
        f'      <p class="ax-lead" id="ax-lead">{escape(U["simple_lead"])}</p>',
        f'      <p class="ax-hint" data-ui="hint">{escape(U["hint"])}</p>',
        '      <figure class="ax-fig" id="ax-fig" aria-busy="true"></figure>',
        '      <div class="ax-note" id="ax-note" aria-live="polite" hidden></div>',
        '      <div class="ax-pager"><button type="button" class="ax-btn" id="ax-prev" hidden></button>'
        '<button type="button" class="ax-btn" id="ax-next" hidden></button></div>',
        open_svg + f'      <p class="ax-foot" data-ui="foot">{escape(U["foot"])}</p>',
        "    </main>",
        "  </div>",
        f'  <script type="application/json" id="arch-meta">{meta_json}</script>',
        *tail,
        "</body>",
        "</html>",
        "",
    ])


def render_standalone(model: dict, annexes: list) -> str:
    """El explorador en un solo archivo, para compartir sin el sitio."""
    svgs = {}
    for key, (svg, paths) in outputs(model, annexes).items():
        p = paths[-1]
        svgs[f"anexos/{p.name}" if p.parent.name == "anexos" else p.name] = svg
    css = (ROOT / "public" / "assets" / "css" / "arquitectura.css").read_text(encoding="utf-8")
    js = (ROOT / "public" / "assets" / "js" / "arquitectura.js").read_text(encoding="utf-8")
    return render_explorer(model, annexes, {"css": css, "js": js, "svgs": svgs})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--model", type=Path, default=MODEL)
    ap.add_argument("--annexes", type=Path, default=ANNEXES)
    ap.add_argument("--explorer", type=Path, help="además, escribir el explorador en un solo archivo HTML en esta ruta")
    a = ap.parse_args(argv)
    model = json.loads(a.model.read_text(encoding="utf-8"))
    annexes = load_annexes(a.annexes)
    stale = []
    files = [(p, svg) for svg, paths in outputs(model, annexes).values() for p in paths]
    files.append((DOC, render_doc(model, DOC.read_text(encoding="utf-8"), annexes)))
    files.append((EXPLORER, render_explorer(model, annexes)))
    expected = {p for p, _ in files}
    for d in ANNEX_DIRS:
        # Un anexo que ya no está en el modelo no debe quedar publicado.
        stale += [p for p in sorted(d.glob("*.svg")) if p not in expected] if d.exists() else []
    for p, text in files:
        if a.check:
            if not p.exists() or p.read_text(encoding="utf-8") != text:
                stale.append(p)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
    if not a.check:
        for p in stale:
            p.unlink()
        stale = []
        if a.explorer:
            a.explorer.write_text(render_standalone(model, annexes), encoding="utf-8")
    if stale:
        print("No están al día (corre python -m tools.architecture): " + ", ".join(str(p.relative_to(ROOT)) for p in stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
