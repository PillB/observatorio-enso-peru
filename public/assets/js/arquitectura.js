// Explorador de la arquitectura (arquitectura.html): los dos diagramas principales y sus anexos A1 a A10.
//
// La dirección dice qué se ve: #simple, #full o #a1 … #a10, con «-en» para la versión en inglés (#a4-en).
// Al tocar una caja de un diagrama principal se abre su anexo (o se elige entre sus anexos); las etiquetas
// A1 a A10, los enlaces «ver A5» de los anexos y «Volver al diagrama completo» navegan dentro de esta página.
// Los SVG se piden a assets/ o, en la copia que se abre sin servidor, se leen de las <template> de la página.
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const META = JSON.parse($('#arch-meta').textContent);
  const UI = META.ui;
  const VIEWS = ['simple', 'full', ...META.annexes.map((a) => a.id)];
  const fig = $('#ax-fig');
  const note = $('#ax-note');
  let current = null;
  let token = 0;

  const file = (view, lang) => {
    const s = lang === 'en' ? '-en' : '';
    if (view === 'full') return `arquitectura${s}.svg`;
    if (view === 'simple') return `arquitectura-simple${s}.svg`;
    return `anexos/${view}${s}.svg`;
  };
  const parse = () => {
    const m = /^#?(simple|full|a\d+)(-en)?$/.exec(location.hash);
    const lang = m ? (m[2] ? 'en' : 'es') : (current?.lang || 'es');
    return { view: m && VIEWS.includes(m[1]) ? m[1] : 'simple', lang };
  };
  const hashOf = (view, lang) => `#${view}${lang === 'en' ? '-en' : ''}`;
  const go = (view, lang = current.lang) => {
    if (location.hash === hashOf(view, lang)) render();
    else location.hash = hashOf(view, lang);
  };
  const annex = (id) => META.annexes.find((a) => a.id === id);
  const label = (view, lang) => {
    if (view === 'simple' || view === 'full') return UI[lang][view];
    const a = annex(view);
    return `${a.id.toUpperCase()} · ${a[`title_${lang}`]}`;
  };

  async function svgText(view, lang) {
    const name = file(view, lang);
    const tpl = $$('template[data-file]').find((t) => t.dataset.file === name);
    if (tpl) return tpl.innerHTML;
    const r = await fetch(META.base + name, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    return r.text();
  }

  function setNote(content) {
    note.replaceChildren(...content);
    note.hidden = !content.length;
  }

  function annexButtons(ids, lang) {
    return ids.filter(annex).map((id) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'ax-go';
      b.textContent = `${UI[lang].open} ${label(id, lang)}`;
      b.addEventListener('click', () => go(id));
      return b;
    });
  }

  function chrome(view, lang) {
    document.documentElement.lang = lang === 'en' ? 'en' : 'es-PE';
    document.title = `${label(view, lang)} · ${UI[lang].page}`;
    $('#ax-title').textContent = label(view, lang);
    $('#ax-lead').textContent = view === 'simple' || view === 'full' ? UI[lang][`${view}_lead`] : annex(view)[`desc_${lang}`];
    $$('[data-view]').forEach((b) => {
      const on = b.dataset.view === view;
      b.setAttribute('aria-current', on ? 'page' : 'false');
      const t = b.querySelector('.ax-nav-t');
      if (t) t.textContent = b.dataset.view.startsWith('a') ? annex(b.dataset.view)[`title_${lang}`] : UI[lang][b.dataset.view];
    });
    $$('[data-lang]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lang === lang)));
    $$('[data-ui]').forEach((el) => { el.textContent = UI[lang][el.dataset.ui]; });
    const i = VIEWS.indexOf(view);
    const prev = $('#ax-prev');
    const next = $('#ax-next');
    prev.hidden = i <= 0;
    next.hidden = i >= VIEWS.length - 1;
    if (i > 0) prev.textContent = `← ${label(VIEWS[i - 1], lang)}`;
    if (i < VIEWS.length - 1) next.textContent = `${label(VIEWS[i + 1], lang)} →`;
    const open = $('#ax-open');
    if (open) open.href = META.base + file(view, lang);
  }

  async function render() {
    const { view, lang } = parse();
    const changed = !current || current.view !== view || current.lang !== lang;
    current = { view, lang };
    chrome(view, lang);
    setNote([]);
    const my = ++token;
    try {
      const svg = await svgText(view, lang);
      if (my !== token) return;
      if (!svg.trimStart().startsWith('<svg')) throw new Error('no es un SVG');
      fig.innerHTML = svg;
      fig.setAttribute('aria-busy', 'false');
      applyZoom();
    } catch (e) {
      if (my !== token) return;
      console.warn(e);
      fig.textContent = UI[lang].error;
    }
    if (changed) {
      fig.scrollTo?.(0, 0);
      $('#ax-title').focus({ preventScroll: true });
      window.scrollTo({ top: 0 });
    }
  }

  function applyZoom() {
    const svg = $('svg', fig);
    if (!svg) return;
    const real = $('#ax-zoom').getAttribute('aria-pressed') === 'true';
    const w = svg.viewBox.baseVal?.width;
    svg.style.width = real && w ? `${w}px` : '100%';
    svg.style.maxWidth = real ? 'none' : '100%';
    svg.style.height = 'auto';
  }

  // Toque o clic dentro del dibujo.
  fig.addEventListener('click', (ev) => {
    const link = ev.target.closest('a[data-annex]');
    if (link) {
      ev.preventDefault();
      go(link.dataset.annex === 'full' ? 'full' : link.dataset.annex);
      return;
    }
    const el = ev.target.closest('[data-node], [data-edge]');
    if (!el) return;
    const tip = el.querySelector(':scope > title')?.textContent || '';
    const ids = $$('a[data-annex]', el).map((a) => a.dataset.annex).filter((id) => id !== 'full');
    const main = current.view === 'simple' || current.view === 'full';
    if (main && el.dataset.node && ids.length === 1) {
      go(ids[0]);
      return;
    }
    const p = document.createElement('p');
    p.textContent = tip;
    setNote([p, ...annexButtons(ids, current.lang)]);
  });
  fig.addEventListener('keydown', (ev) => {
    if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.matches?.('[data-edge], [data-node]')) {
      ev.preventDefault();
      ev.target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    }
  });

  $$('[data-view]').forEach((b) => b.addEventListener('click', (ev) => { ev.preventDefault(); go(b.dataset.view); }));
  $$('[data-lang]').forEach((b) => b.addEventListener('click', () => go(current.view, b.dataset.lang)));
  $('#ax-prev').addEventListener('click', () => go(VIEWS[VIEWS.indexOf(current.view) - 1]));
  $('#ax-next').addEventListener('click', () => go(VIEWS[VIEWS.indexOf(current.view) + 1]));
  $('#ax-zoom').addEventListener('click', (ev) => {
    const b = ev.currentTarget;
    b.setAttribute('aria-pressed', String(b.getAttribute('aria-pressed') !== 'true'));
    applyZoom();
  });
  window.addEventListener('hashchange', render);
  render();
})();
