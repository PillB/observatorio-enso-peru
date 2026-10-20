// Tutorial guiado con 13 modos. Estado versionado en localStorage:
// se puede pausar, reanudar (también tras recargar), reiniciar y borrar.
// Los pasos apuntan a elementos con data-tour-id; si un elemento no
// existe, el paso se muestra centrado en lugar de fallar.

import { esc, $, storage } from './lib/dom.js';
import { TOUR_MODES } from './content.js';
import { ICON } from './icons.js';

const KEY = 'enso-tour';
const VERSION = 2;

function readState() {
  try {
    const s = JSON.parse(storage(KEY) || 'null');
    return s && s.version === VERSION ? s : { version: VERSION, completed: [], active: null };
  } catch {
    return { version: VERSION, completed: [], active: null };
  }
}

export class Tour {
  constructor({ getData, navigate }) {
    this.getData = getData;
    this.navigate = navigate;
    this.state = readState();
    this.pop = null;
    this.target = null;
    this.returnFocus = null;
    this.onKey = (e) => {
      if (!this.pop) return;
      if (e.key === 'Escape') { e.preventDefault(); this.pause(); }
      else if (e.key === 'ArrowRight' && !e.target.closest('input,select,textarea')) this.next();
      else if (e.key === 'ArrowLeft' && !e.target.closest('input,select,textarea')) this.prev();
    };
  }

  save() { storage(KEY, JSON.stringify(this.state)); }

  /** Diálogo con la lista de modos y los controles de progreso. */
  openMenu() {
    const dlg = document.getElementById('tour-dialog');
    const a = this.state.active;
    const paused = a && a.status === 'paused' ? TOUR_MODES.find((m) => m.id === a.mode) : null;
    dlg.querySelector('.dlg-body').innerHTML = `
      ${paused ? `<div class="notice notice-info"><p>Tiene en pausa «${esc(paused.title)}» (paso ${a.step + 1} de ${paused.steps.length}).</p><button type="button" class="btn" data-act="resume">Reanudar</button></div>` : ''}
      <p class="muted">Elija un tema. Puede pausar con Esc y reanudar después; el progreso se guarda en este navegador.</p>
      <ul class="tour-menu">${TOUR_MODES.map((m) => `<li><button type="button" data-mode="${esc(m.id)}"><strong>${esc(m.title)}</strong><br><span class="muted small">${esc(m.desc)} · ${m.steps.length} pasos</span>${this.state.completed.includes(m.id) ? ' <span class="done">✓ completado</span>' : ''}</button></li>`).join('')}</ul>
      <div class="row tour-reset"><button type="button" class="btn ghost" data-act="clear">Borrar progreso del tutorial</button></div>`;
    dlg.querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => { dlg.close(); this.start(b.dataset.mode); }));
    dlg.querySelector('[data-act="resume"]')?.addEventListener('click', () => { dlg.close(); this.resume(); });
    dlg.querySelector('[data-act="clear"]').addEventListener('click', () => {
      this.state = { version: VERSION, completed: [], active: null };
      this.save();
      this.announce('Se borró el progreso del tutorial.');
      this.openMenu();
    });
    this.returnFocus = document.activeElement;
    if (!dlg.open) dlg.showModal();
  }

  start(modeId, step = 0) {
    this.state.active = { mode: modeId, step, status: 'running', startedAt: new Date().toISOString() };
    this.save();
    this.show();
  }

  resume() {
    if (!this.state.active) return;
    this.state.active.status = 'running';
    this.save();
    this.show();
  }

  /** Tras recargar, ofrece continuar un recorrido que estaba en curso. */
  maybeResume() {
    const a = this.state.active;
    if (a && a.status === 'running') { a.status = 'paused'; this.save(); }
  }

  mode() { return TOUR_MODES.find((m) => m.id === this.state.active?.mode); }

  async show() {
    const m = this.mode();
    if (!m) return;
    const i = this.state.active.step;
    const st = m.steps[i];
    if (st.route && location.hash !== st.route && !(st.route === '#/' && (location.hash === '' || location.hash === '#'))) {
      await new Promise((res) => {
        const done = () => { document.removeEventListener('view:ready', done); res(); };
        document.addEventListener('view:ready', done);
        this.navigate(st.route);
        setTimeout(done, 2500);
      });
    }
    this.clearHighlight();
    const el = document.querySelector(`[data-tour-id="${st.target}"]`);
    if (el) {
      el.classList.add('tour-highlight');
      el.scrollIntoView({ block: 'center', behavior: 'auto' });
      this.target = el;
    }
    const text = typeof st.text === 'function' ? st.text(this.getData()) : st.text;
    if (!this.pop) {
      this.pop = document.createElement('div');
      this.pop.className = 'tour-pop';
      this.pop.setAttribute('role', 'dialog');
      this.pop.setAttribute('aria-modal', 'false');
      this.pop.setAttribute('aria-labelledby', 'tour-title');
      document.body.append(this.pop);
      document.addEventListener('keydown', this.onKey);
      window.addEventListener('resize', this.place);
    }
    const last = i === m.steps.length - 1;
    this.pop.innerHTML = `
      <div class="tour-head"><span class="muted small">${esc(m.title)} · paso ${i + 1} de ${m.steps.length}</span>
        <button type="button" class="icon-btn" data-act="close" aria-label="Salir del tutorial">${ICON.close}</button></div>
      <h2 id="tour-title">${esc(st.title)}</h2><p>${esc(text)}</p>
      ${el ? '' : '<p class="muted small">Este elemento no está visible ahora mismo.</p>'}
      <div class="tour-progress" aria-hidden="true"><span></span></div>
      <div class="row"><button type="button" class="btn ghost" data-act="pause">Pausar</button>
        <button type="button" class="btn ghost" data-act="restart">Reiniciar</button>
        <button type="button" class="btn ghost" data-act="prev" ${i === 0 ? 'disabled' : ''}>Anterior</button>
        <button type="button" class="btn" data-act="next">${last ? 'Terminar' : 'Siguiente'}</button></div>`;
    this.pop.querySelector('.tour-progress span').style.width = `${((i + 1) / m.steps.length) * 100}%`;
    this.pop.querySelector('[data-act="close"]').onclick = () => this.exit();
    this.pop.querySelector('[data-act="pause"]').onclick = () => this.pause();
    this.pop.querySelector('[data-act="restart"]').onclick = () => this.start(m.id, 0);
    this.pop.querySelector('[data-act="prev"]').onclick = () => this.prev();
    this.pop.querySelector('[data-act="next"]').onclick = () => this.next();
    this.place();
    this.pop.querySelector('[data-act="next"]').focus({ preventScroll: true });
  }

  place = () => {
    if (!this.pop) return;
    const p = this.pop;
    const narrow = innerWidth < 640;
    if (!this.target || narrow) {
      p.style.left = '50%'; p.style.transform = 'translateX(-50%)'; p.style.top = ''; p.style.bottom = '12px';
      return;
    }
    const r = this.target.getBoundingClientRect();
    const h = p.offsetHeight;
    const below = r.bottom + 12 + h < innerHeight;
    p.style.transform = '';
    p.style.bottom = '';
    const top = below ? r.bottom + 12 : r.top - h - 12;
    // Si el elemento es más alto que la pantalla, la ventana va abajo.
    if (top < 12 || top + h > innerHeight - 12) { p.style.top = ''; p.style.bottom = '12px'; }
    else p.style.top = `${top}px`;
    p.style.left = `${Math.min(innerWidth - p.offsetWidth - 12, Math.max(12, r.left))}px`;
  };

  next() {
    const m = this.mode();
    if (!m) return;
    if (this.state.active.step >= m.steps.length - 1) {
      if (!this.state.completed.includes(m.id)) this.state.completed.push(m.id);
      this.state.active = null;
      this.save();
      this.close();
      this.announce(`Completó «${m.title}».`);
      return;
    }
    this.state.active.step += 1;
    this.save();
    this.show();
  }

  prev() {
    if (!this.state.active || this.state.active.step === 0) return;
    this.state.active.step -= 1;
    this.save();
    this.show();
  }

  pause() {
    if (!this.state.active) return;
    this.state.active.status = 'paused';
    this.save();
    this.close();
    this.announce('Tutorial en pausa. Puede reanudarlo desde «Ayuda y tutorial».');
  }

  exit() {
    this.state.active = null;
    this.save();
    this.close();
    this.announce('Salió del tutorial.');
  }

  clearHighlight() {
    document.querySelectorAll('.tour-highlight').forEach((x) => x.classList.remove('tour-highlight'));
    this.target = null;
  }

  close() {
    this.clearHighlight();
    this.pop?.remove();
    this.pop = null;
    document.removeEventListener('keydown', this.onKey);
    window.removeEventListener('resize', this.place);
    ($('#help-btn') || this.returnFocus)?.focus();
  }

  announce(msg) {
    const live = document.getElementById('live');
    if (live) { live.textContent = ''; setTimeout(() => { live.textContent = msg; }, 50); }
  }
}
