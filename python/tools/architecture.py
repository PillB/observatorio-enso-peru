"""Dibuja los diagramas de arquitectura a partir de ``docs/arquitectura.json``.

Uso:
    python -m tools.architecture [--check]   # --check: falla si los SVG no están al día

Escribe ``docs/arquitectura.svg`` (completo), ``docs/arquitectura-simple.svg``
(simplificado) y sus copias en ``public/assets/``. Las cajas y las conexiones
salen del modelo; las líneas se trazan solas (rutas ortogonales que esquivan
las cajas), así que agregar una conexión es editar el JSON y volver a correr.

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
class Box:
    def __init__(self, node: dict, x: float, y: float, w: float, lang: str, sizes: tuple, step: str = ""):
        self.node, self.id, self.x, self.y, self.w = node, node["id"], x, y, w
        self.group = node.get("group", "pipeline")
        ts, ss, ms = sizes
        self.sizes = sizes
        self.step = step
        pad = 12
        inner = w - 2 * pad - (26 if step else 0)
        self.title = wrap(node[f"name_{lang}"], inner, ts, True)
        self.body = wrap(node[f"what_{lang}"], w - 2 * pad, ss)
        meta = node.get(f"meta_{lang}") or ""
        self.meta = wrap(meta, w - 2 * pad, ms) if meta else []
        self.lh_t, self.lh_s, self.lh_m = ts * 1.3, ss * 1.38, ms * 1.38
        self.h = pad + len(self.title) * self.lh_t + 4 + len(self.body) * self.lh_s + (len(self.meta) * self.lh_m + 4 if self.meta else 0) + pad - 2

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
        for line in self.title:
            o.append("    " + t(tx, y, line, "ar-t", ts))
            y += self.lh_t
        y += 4 - self.lh_t + self.lh_s
        for line in self.body:
            o.append("    " + t(self.x + pad, y, line, "ar-s", ss))
            y += self.lh_s
        if self.meta:
            y += 4
            for line in self.meta:
                o.append("    " + t(self.x + pad, y, line, "ar-m", ms))
                y += self.lh_m
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
           "kinds": {"data": "datos", "fallback": "respaldo", "trigger": "disparo o control", "human": "paso manual"}},
    "en": {"how": "How to read it", "edges": "Connections", "steps": "Walkthrough", "key": "Lines:",
           "kinds": {"data": "data", "fallback": "fallback", "trigger": "trigger or control", "human": "manual step"}},
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
        parts.append(n[f"meta_{lang}"])
    return " ".join(parts)


def _etip(e: dict, nodes: dict, lang: str, badge: str) -> str:
    a, b = nodes[e["from"]][f"name_{lang}"], nodes[e["to"]][f"name_{lang}"]
    return f"{badge}. {a} → {b}: {e[f'label_{lang}']}. {e[f'explain_{lang}']}"


def _legend(entries: list[tuple[str, str, str, str, str]], x: float, y: float, width: float, ncols: int,
            gap: float = 28) -> tuple[list[str], float]:
    """Entradas (insignia, tipo, título, subtítulo, texto) en ``ncols`` columnas equilibradas por altura."""
    colw = (width - gap * (ncols - 1)) / ncols
    text_x = 30
    blocks = []
    for badge, kind, title, sub, body in entries:
        tl = wrap(title, colw - text_x, 11.5, True)
        sl = wrap(sub, colw - text_x, 10.5) if sub else []
        bl = wrap(body, colw - text_x, 11)
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
            if kind == "step":
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


def render_full(model: dict, lang: str = "es") -> str:
    m = model["full"]
    P = "af"
    W, M = m["width"], 20
    MC = m.get("margin", 44)  # las columnas dejan a cada lado un pasillo para las líneas
    nodes = {n["id"]: n for n in m["nodes"]}
    body: list[str] = []
    body.append(t(M, 38, m[f"title_{lang}"], "ar-big", 20))
    sub = wrap(m[f"subtitle_{lang}"], W - 2 * M, 12)
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
            b = Box(n, xs[ci] + 10, cy, c["w"] - 20, lang, (12.5, 11, 10.5))
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
            b = Box(n, xs[ci] + 10, ry, cols[ci]["w"] - 20, lang, (12.5, 11, 10.5))
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


def render_simple(model: dict, lang: str = "es") -> str:
    m = model["simple"]
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
    for line in wrap(m[f"subtitle_{lang}"], W - 2 * M, 12):
        body.append(t(M, y, line, "ar-s", 12))
        y += 17
    k, _ = _key_row(M, y + 6, lang, P)
    body += k
    top = y + 34
    boxes: dict[str, Box] = {}
    for n in m["nodes"]:
        boxes[n["id"]] = Box(n, n["x"], top + n["y"], n["w"], lang, (14, 12, 11), step_of.get(n["id"], ""))
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


def render_all(model: dict) -> dict[str, str]:
    return {"full": render_full(model), "simple": render_simple(model)}


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


def render_doc(model: dict, doc: str) -> str:
    a, b = doc.index(DOC_START), doc.index(DOC_END) + len(DOC_END)
    return doc[:a] + render_doc_section(model) + doc[b:]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--model", type=Path, default=MODEL)
    a = ap.parse_args(argv)
    model = json.loads(a.model.read_text(encoding="utf-8"))
    out = render_all(model)
    stale = []
    files = [(p, svg) for key, svg in out.items() for p in OUT[key]]
    files.append((DOC, render_doc(model, DOC.read_text(encoding="utf-8"))))
    for p, text in files:
        if a.check:
            if not p.exists() or p.read_text(encoding="utf-8") != text:
                stale.append(p)
        else:
            p.write_text(text, encoding="utf-8")
    if stale:
        print("No están al día (corre python -m tools.architecture): " + ", ".join(str(p.relative_to(ROOT)) for p in stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
