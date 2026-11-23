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

const settle = () => new Promise((r) => setTimeout(r, 5));
/** Los eventos mandados, por versión: {v: [eventos…]} (cada aviso por separado). */
const beacons = () => sent.map((b) => `${b.v}:${[...b.e].sort().join(',')}`);
const count = (e) => sent.reduce((a, b) => a + b.e.filter((x) => x === e).length, 0);

describe('ab.js: qué visita entra en la decisión y cuántas veces cuenta cada evento', () => {
  beforeEach(() => env());

  it('un evento cuenta una vez por visita aunque la página se oculte y vuelva (antes «use» se mandaba otra vez)', async () => {
    store.set('enso-vista-memoria', JSON.stringify({ v: 'cuencas', chosen: false, at: today() }));
    const { ab } = await fresh();
    const s = ab('memoria');
    s.mark('view');
    s.mark('select');
    s.flush();                    // visibilitychange → hidden
    s.mark('select');             // vuelve a la pestaña y filtra otra vez
    s.mark('detail');
    s.flush();
    await settle();
    assert.equal(count('use'), 1);
    assert.equal(count('select'), 1);
    assert.equal(count('view'), 1);
    assert.equal(count('detail'), 1, 'lo nuevo de la visita sí se manda');
  });

  it('la primera visita sorteada manda rview y ruse a su versión; la vuelta del mismo navegador ya no', async () => {
    let mod = await fresh();
    let s = mod.ab('mapa');
    const v = s.own;
    s.mark('hover');              // pasar el cursor no es uso
    s.flush();
    s.mark('view');
    s.mark('hover');
    s.flush();
    s.mark('select');
    s.flush();
    await settle();
    assert.deepEqual(beacons(), [`${v}:hover`, `${v}:rview,view`, `${v}:ruse,select,use`]);
    // Otro día, la misma persona: su versión sigue, pero esa visita no es una muestra nueva.
    sent = [];
    mod = await fresh();
    s = mod.ab('mapa');
    s.mark('view');
    s.mark('select');
    s.flush();
    await settle();
    assert.equal(count('rview') + count('ruse'), 0);
    assert.equal(count('view'), 1);
  });

  for (const [what, loc] of [['?version=… con la misma letra o no', { hash: '#/noticias?version=A' }],
    ['?nivel=… de la memoria', { hash: '#/memoria?nivel=distrito&area=200401' }], ['?sitio=B', { search: '?sitio=B' }]]) {
    it(`una primera visita que llega con un enlace (${what}) no entra en la decisión`, async () => {
      env(loc);
      const { ab } = await fresh();
      for (const x of ['mapa', 'memoria', 'sitio']) { const s = ab(x); s.mark('view'); s.mark('select'); s.flush(); }
      await settle();
      assert.equal(count('rview'), 0, beacons().join(' '));
    });
  }

  it('un uso antes de que la versión se vea no cuenta como uso de la visita sorteada', async () => {
    const { ab } = await fresh();
    const s = ab('sitio');
    s.mark('use');
    s.flush();
    s.mark('view');
    s.flush();
    await settle();
    assert.equal(count('ruse'), 0);
    assert.equal(count('rview'), 1);
  });

  it('intención de tratar: si elige otra en su primera visita, lo de esa visita sigue siendo de la sorteada', async () => {
    const { ab } = await fresh();
    const s = ab('memoria');
    const a = s.own;
    const b = ['resumen', 'cuencas'].find((x) => x !== a);
    s.mark('view');
    s.choose(b);
    s.mark('detail');
    s.flush();
    await settle();
    const r = sent.filter((x) => x.e.includes('rview') || x.e.includes('ruse'));
    assert.deepEqual(r.map((x) => [x.v, x.e.filter((e) => e[0] === 'r').sort()]), [[a, ['rview']], [a, ['ruse']]]);
    assert.ok(sent.some((x) => x.v === b && x.e.includes('use')), 'el uso de la elegida se cuenta en sus totales');
    assert.ok(sent.some((x) => x.v === b && x.e.includes('view') && x.e.includes('choose')), 'la elegida cuenta su propia vista');
  });

  it('uso en la primera visita con una vista previa (un fallo de carga, el tutorial) cuenta para la sorteada', async () => {
    const { ab } = await fresh();
    const s = ab('memoria');
    const a = s.own;
    s.mark('view');
    s.show(a === 'resumen' ? 'cuencas' : 'resumen');
    s.mark('select');
    document.documentElement.dataset.tourDemo = '1';
    s.mark('detail');             // lo pulsa el tutorial: no es de la persona
    delete document.documentElement.dataset.tourDemo;
    s.flush();
    await settle();
    assert.deepEqual(beacons(), [`${a}:ruse,rview,view`]);
  });

  it('la ganadora puesta a propósito (4 de cada 5) no entra en la decisión; el resto, sorteado, sí', async () => {
    const real = Math.random;
    try {
      for (const [rnd, n] of [[0.1, 0], [0.95, 1]]) {
        env();
        store.set('enso-ab-ganadoras', JSON.stringify({ at: today(), d: { boletin: 'ficha' } }));
        Math.random = () => rnd;
        const { ab } = await fresh();
        const s = ab('boletin');
        s.mark('view');
        s.flush();
        await settle();
        assert.equal(count('rview'), n, `azar ${rnd}: ${beacons()}`);
        if (!n) assert.equal(s.own, 'ficha');
      }
    } finally { Math.random = real; }
  });

  it('sitio: «use» (abrió una segunda pestaña) es uso de la visita sorteada', async () => {
    const { ab } = await fresh();
    const s = ab('sitio');
    s.mark('view');
    s.mark('use');
    s.flush();
    await settle();
    assert.deepEqual(beacons(), [`${s.own}:ruse,rview,use,view`]);
  });

  it('un clic del tutorial no es uso de la visita sorteada, aunque sea el único', async () => {
    const { ab } = await fresh();
    const s = ab('memoria');
    s.mark('view');
    document.documentElement.dataset.tourDemo = '1';
    s.mark('detail');
    s.mark('view');
    delete document.documentElement.dataset.tourDemo;
    s.flush();
    await settle();
    assert.deepEqual(beacons(), [`${s.own}:rview,view`]);
  });

  it('sin almacenamiento cada carga sortea de nuevo: esas visitas no entran en la decisión', async () => {
    globalThis.localStorage = { getItem: () => null, setItem: () => { throw new Error('bloqueado'); }, removeItem: () => {} };
    for (let i = 0; i < 2; i++) {
      const { ab } = await fresh();
      const s = ab('memoria');
      s.mark('view');
      s.mark('select');
      s.flush();
    }
    await settle();
    assert.equal(count('view'), 2);
    assert.equal(count('rview') + count('ruse'), 0, beacons().join(' '));
  });
});
