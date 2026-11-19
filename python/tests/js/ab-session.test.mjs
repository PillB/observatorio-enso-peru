// La máquina de estados de una versión en el navegador (public/assets/js/ab.js, clase Session): asignada → vista
// previa (un enlace o el tutorial) → elegida. Ver docs/maquinas-de-estado.md, «Versiones (experimentos)».
// Se corre con `node --test` (la lanza tests/test_alert_map.py). Sin navegador: location, document y localStorage
// son de mentira, y cada prueba importa el módulo de nuevo (las sesiones se guardan por módulo).
import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';

const MOD = new URL('../../../public/assets/js/ab.js', import.meta.url).href;
let n = 0;
let sent;
let store;

function env({ hash = '', search = '', tour = false } = {}) {
  store = new Map();
  sent = [];
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  // ENSO_BACKEND: como el sitio de Cloudflare, para ver lo que se manda (sendBeacon de mentira).
  globalThis.ENSO_BACKEND = true;
  globalThis.location = { hash, search, protocol: 'https:', hostname: 'enso-peru.pages.dev' };
  globalThis.addEventListener = () => {};
  globalThis.window = globalThis;
  globalThis.document = {
    documentElement: { dataset: tour ? { tourDemo: '1' } : {} },
    visibilityState: 'visible',
    addEventListener: () => {},
    dispatchEvent: () => true,
  };
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { sendBeacon: (_u, blob) => { blob.text().then((t) => sent.push(JSON.parse(t))); return true; } },
  });
}

const fresh = () => import(`${MOD}?n=${++n}`);
const saved = (key) => JSON.parse(store.get(key));
const today = () => new Date().toISOString().slice(0, 10);

describe('versiones en el navegador (ab.js Session)', () => {
  beforeEach(() => env());

  it('un enlace muestra otra versión sin cambiar la de la persona', async () => {
    env({ search: '?sitio=B' });
    store.set('enso-version-sitio', JSON.stringify({ v: 'A', chosen: true, at: today() }));
    const { ab } = await fresh();
    const s = ab('sitio');
    assert.equal(s.variant, 'B');
    assert.equal(s.own, 'A');
    assert.equal(s.preview, 'B');
    assert.equal(saved('enso-version-sitio').v, 'A');
  });

  it('elegir la versión que muestra el enlace la adopta (antes no hacía nada: ya era la que se veía)', async () => {
    env({ hash: '#/noticias?version=C' });
    store.set('enso-mapa-version', JSON.stringify({ v: 'A', chosen: false, at: today() }));
    const { ab } = await fresh();
    const s = ab('mapa');
    assert.equal(s.variant, 'C');
    s.choose('C');
    assert.equal(s.preview, null);
    assert.equal(s.own, 'C');
    const st = saved('enso-mapa-version');
    assert.equal(st.v, 'C');
    assert.equal(st.chosen, true);
  });

  it('elegir la propia mientras se ve un enlace vuelve a ella', async () => {
    env({ search: '?sitio=B' });
    store.set('enso-version-sitio', JSON.stringify({ v: 'A', chosen: true, at: today() }));
    const { ab } = await fresh();
    const s = ab('sitio');
    s.choose('A');
    assert.equal(s.preview, null);
    assert.equal(s.variant, 'A');
  });

  it('elegir la que ya es suya y se ve no cambia nada ni manda nada', async () => {
    store.set('enso-mapa-version', JSON.stringify({ v: 'B', chosen: true, at: '2000-01-01' }));
    const { ab } = await fresh();
    const s = ab('mapa');
    s.choose('B');
    assert.equal(saved('enso-mapa-version').at, '2000-01-01', 'no se reescribe como una elección nueva');
    assert.ok(!s.flags.has('choose'));
  });

  it('lo que pulsa el tutorial se ve como vista previa y no se cuenta; la persona puede adoptarla después', async () => {
    store.set('enso-vista-memoria', JSON.stringify({ v: 'resumen', chosen: true, at: today() }));
    const { ab } = await fresh();
    const s = ab('memoria');
    document.documentElement.dataset.tourDemo = '1';
    s.choose('cuencas');
    delete document.documentElement.dataset.tourDemo;
    assert.equal(s.variant, 'cuencas');
    assert.equal(s.own, 'resumen');
    assert.equal(saved('enso-vista-memoria').v, 'resumen');
    // Mientras se ve la del tutorial, lo que haga la persona no se cuenta como uso de la suya.
    s.mark('select');
    assert.equal(s.flags.size, 0);
    // La persona elige la que dejó el tutorial: ahora es la suya.
    s.choose('cuencas');
    assert.equal(s.preview, null);
    assert.equal(saved('enso-vista-memoria').v, 'cuencas');
    assert.ok(s.flags.has('choose') && s.flags.has('view'));
  });

  it('una versión que no existe en el enlace no se muestra', async () => {
    env({ hash: '#/noticias?version=Z' });
    const { ab } = await fresh();
    const s = ab('mapa');
    assert.equal(s.preview, null);
    assert.ok(['A', 'B', 'C', 'D'].includes(s.variant));
  });
});
