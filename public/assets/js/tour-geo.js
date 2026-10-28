// Geometría del tutorial: dónde va la ventana del paso y cuánto desplazar la página para que la ventana no tape
// nunca lo que se resalta ni lo que el tutorial toca. Funciones puras (rectángulos en píxeles de la ventana del
// navegador), sin DOM: las prueba test_browser.py importando este módulo.
//
// La regla: la ventana se coloca solo en posiciones que no se cruzan con ningún rectángulo a evitar (el elemento
// resaltado con su margen, el control que se pulsa, el tooltip que abre, el control con el foco). Si no queda
// ninguna, se reduce a una píldora sobre la cabecera fija: lo que tapa allí ya estaba tapado por la cabecera.

/** Separación entre la ventana y lo resaltado, y margen con los bordes de la pantalla. */
export const GAP = 12;
export const EDGE = 8;
/** Lo mínimo que debe verse de un elemento más alto que la pantalla, debajo de la ventana. */
export const MIN_VISIBLE = 140;
/** Lo mínimo que debe verse del elemento en cualquier plan (o el elemento entero, si es más bajo). */
export const MIN_SEEN = 48;

export const rect = (top, left, width, height) => ({ top, left, right: left + width, bottom: top + height, width, height });
export const intersects = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
export const pad = (r, p) => rect(r.top - p, r.left - p, r.width + 2 * p, r.height + 2 * p);

export function union(list) {
  const rs = list.filter(Boolean);
  if (!rs.length) return null;
  const top = Math.min(...rs.map((r) => r.top)), left = Math.min(...rs.map((r) => r.left));
  return rect(top, left, Math.max(...rs.map((r) => r.right)) - left, Math.max(...rs.map((r) => r.bottom)) - top);
}

/** La parte de r que cae dentro de [top, bottom] (lo que tapa la cabecera fija no se ve: no cuenta). */
export function clipY(r, top, bottom) {
  const t = Math.max(r.top, top), b = Math.min(r.bottom, bottom);
  return b > t ? rect(t, r.left, r.width, b - t) : null;
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/**
 * Posición de la ventana del paso.
 *
 * vp: {width, height, top} (top: borde inferior de la cabecera fija); size: {width, height} de la ventana;
 * focus: rectángulo junto al que debe ir (el elemento resaltado, con su margen) o null; avoid: rectángulos que no
 * puede tocar; prefer: el lado de la vez anterior (para no saltar de un lado a otro mientras nada cambia).
 *
 * Devuelve {side, left, top} o {side: 'pill'} si no cabe en ningún lado.
 */
export function placePopover(vp, size, focus, avoid, prefer = null) {
  const { width: W, height: H } = size;
  const minY = vp.top + EDGE, maxY = vp.height - EDGE - H, maxX = vp.width - EDGE - W;
  if (maxX < EDGE - 0.5 || maxY < minY - 0.5) return { side: 'pill' };
  // Solo cuenta lo visible bajo la cabecera.
  const blockers = avoid.map((r) => clipY(r, vp.top, vp.height)).filter(Boolean);
  const free = (left, top) => {
    const box = rect(top, left, W, H);
    return !blockers.some((r) => intersects(box, r));
  };
  const cands = [];
  const f = focus ? clipY(focus, vp.top, vp.height) : null;
  if (f) {
    const xs = [clamp(f.left + f.width / 2 - W / 2, EDGE, maxX), clamp(f.left, EDGE, maxX), clamp(f.right - W, EDGE, maxX)];
    const ys = [clamp(f.top + f.height / 2 - H / 2, minY, maxY), clamp(f.top, minY, maxY), clamp(f.bottom - H, minY, maxY)];
    const sides = {
      bottom: xs.map((x) => [x, focus.bottom + GAP]),
      top: xs.map((x) => [x, focus.top - GAP - H]),
      right: ys.map((y) => [focus.right + GAP, y]),
      left: ys.map((y) => [focus.left - GAP - W, y]),
    };
    const order = ['bottom', 'top', 'right', 'left'];
    if (prefer && sides[prefer]) order.unshift(prefer);
    for (const side of order) for (const [x, y] of sides[side]) cands.push([side, x, y]);
  }
  // Sin lugar al lado: en un espacio libre de la pantalla (abajo o arriba, al centro o a un lado).
  for (const y of [maxY, minY]) for (const x of [clamp(vp.width / 2 - W / 2, EDGE, maxX), EDGE, maxX]) cands.push(['dock', x, y]);
  // Se redondea antes de comprobar: la posición que se devuelve es la que se comprobó.
  for (const [side, x0, y0] of cands) {
    const x = Math.round(x0), y = Math.round(y0);
    if (x < EDGE - 0.5 || x > maxX + 0.5 || y < minY - 0.5 || y > maxY + 0.5) continue;
    if (free(x, y)) return { side, left: x, top: y };
  }
  return { side: 'pill' };
}

/**
 * Cuánto desplazar la página para mostrar `target` (en coordenadas del documento) con la ventana al lado.
 *
 * vp: {width, height, top}; size: tamaño de la ventana ({width, height, min}: min, lo más que se puede acortar); scrollY: desplazamiento actual; avoid: otros rectángulos (en
 * coordenadas del documento) que la ventana tampoco puede tocar, como el control que se acaba de usar.
 * Devuelve {y, side, maxHeight} — y puede quedar fuera de [0, maxScroll]: quien llama agrega el espacio que falte.
 * maxHeight (o null) limita el alto de la ventana cuando el elemento es más alto que la pantalla.
 *
 * Se prueban, en orden, varias disposiciones (sin mover nada; elemento y ventana centrados juntos; la ventana al
 * lado; el elemento arriba o abajo con la ventana en el espacio que queda; si es más alto que la pantalla, su
 * comienzo bajo la ventana) y se devuelve la primera en que la ventana cabe sin tocar nada.
 */
export function planScroll(vp, size, target, scrollY, avoid = []) {
  const avail = vp.height - vp.top - 2 * EDGE;
  const W = size.width, H0 = size.height;
  // El alto más bajo al que se puede acortar la ventana (su texto se desplaza por dentro; los botones, no).
  const MIN_H = Math.min(H0, size.min || 120);
  const T = target;
  const top0 = vp.top + EDGE;  // primera fila útil bajo la cabecera
  const center = (blockTop, blockH) => blockTop - (top0 + (avail - blockH) / 2);
  const cands = [];
  const stack = T.height + GAP + H0 <= avail;
  if (stack) {
    cands.push({ y: scrollY, side: 'bottom' }, { y: scrollY, side: 'top' });
    const below = { y: center(T.top, T.height + GAP + H0), side: 'bottom' };
    const above = { y: center(T.top - GAP - H0, T.height + GAP + H0), side: 'top' };
    cands.push(...(Math.abs(below.y - scrollY) <= Math.abs(above.y - scrollY) ? [below, above] : [above, below]));
    // El elemento pegado arriba (la ventana debajo) o abajo (la ventana encima).
    cands.push({ y: T.top - top0, side: 'bottom' }, { y: T.bottom - (vp.height - EDGE), side: 'top' });
  }
  if (T.height <= avail && vp.width - 2 * EDGE >= T.width + GAP + W) {
    cands.push({ y: center(T.top, T.height), side: vp.width - T.right - EDGE >= GAP + W ? 'right' : 'left' });
  }
  // No caben juntos, pero el elemento sí cabe: la ventana se acorta (su texto se desplaza por dentro) antes que
  // dejar parte del elemento fuera de la pantalla.
  if (!stack && T.height + GAP + MIN_H <= avail) {
    const Hs = avail - T.height - GAP;
    const blk = T.height + GAP + Hs;
    cands.push({ y: center(T.top, blk), side: 'bottom', maxHeight: Hs, H: Hs }, { y: center(T.top - GAP - Hs, blk), side: 'top', maxHeight: Hs, H: Hs });
  }
  // Más alto que lo que queda: la ventana arriba y el comienzo del elemento justo debajo; o la ventana abajo y el
  // final del elemento justo encima. Si la ventana no deja ver al menos MIN_VISIBLE, se acorta (desplaza por dentro).
  let H = H0, maxHeight = null;
  const room = avail - GAP - Math.min(T.height, MIN_VISIBLE);
  if (H > room) { H = Math.max(MIN_H, room); maxHeight = H; }
  cands.push({ y: T.top - (top0 + H + GAP), side: 'top', maxHeight, H, tall: 'top' });
  cands.push({ y: T.bottom - (vp.height - EDGE - H - GAP), side: 'bottom', maxHeight, H, tall: 'bottom' });
  for (const c of cands) {
    const h = c.H || H0;
    const sh = (r) => rect(r.top - c.y, r.left, r.width, r.height);
    const T2 = sh(T);
    // El elemento debe verse entero (o, si es más alto que la pantalla, su comienzo o su final).
    const okTop = T2.top >= vp.top + EDGE - 1, okBottom = T2.bottom <= vp.height - EDGE + 1;
    if (c.tall === 'top' ? !okTop : c.tall === 'bottom' ? !okBottom : !(okTop && okBottom)) continue;
    // Y que de verdad se vea algo: no vale un plan que deja el elemento debajo de la ventana o tras la cabecera.
    const seen = Math.min(T2.bottom, vp.height) - Math.max(T2.top, vp.top);
    if (seen < Math.min(T.height, MIN_SEEN) - 1) continue;
    const p = placePopover(vp, { width: W, height: h }, T2, [T2, ...avoid.map(sh)], c.side);
    if (p.side !== 'pill') return { y: c.y, side: p.side, maxHeight: c.maxHeight || null };
  }
  // Nada sirve (una pantalla muy baja): el elemento se muestra desde su comienzo y la ventana queda como píldora.
  return { y: T.top - top0, side: 'bottom', maxHeight: null };
}
