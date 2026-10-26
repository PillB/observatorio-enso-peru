// Pruebas del vigilante (.github/scripts/watchdog.cjs) con un `github` y un `fetch` de mentira.
// Se corren con `node --test` (las lanza tests/test_watchdog.py).
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { describe, it } from 'node:test';

const require = createRequire(import.meta.url);
const { run, HEARTBEAT_MAX_HOURS, PROBE_MAX_DAYS } = require('../../../.github/scripts/watchdog.cjs');

const NOW = Date.parse('2026-10-22T12:00:00Z');
const ago = (h) => new Date(NOW - h * 36e5).toISOString().replace('.000Z', '+00:00');
const context = { repo: { owner: 'o', repo: 'r' }, payload: { repository: { default_branch: 'main' } } };
const notFound = () => Object.assign(new Error('Not Found'), { status: 404 });

function beat(hours, extra = {}) {
  return {
    schema: 'enso-relay-heartbeat/1', at: ago(hours), result: 'ok', reachable: '9/11',
    collector: { host: 'mac-lima', kit: '2026.10.3', runner: 'collector_service/1' }, ...extra,
  };
}

// Corrida de la sonda semanal en main.
const probeRun = (hours, extra = {}) => ({
  head_branch: 'main', event: 'schedule', status: 'completed', conclusion: 'success', created_at: ago(hours), ...extra,
});

// GitHub de mentira: `branches` da el latido de cada rama (un objeto, un Error o nada → 404); `runs`, las corridas
// de cada flujo (por omisión, una sonda semanal buena de hace 2 días).
function fake({ branches = {}, issues = [], runs = {} } = {}) {
  const byWorkflow = { 'probe-sources.yml': [probeRun(48)], ...runs };
  const calls = [];
  const all = issues.map((i) => ({ state: 'open', updated_at: ago(1), ...i }));
  const github = {
    rest: {
      actions: {
        enableWorkflow: async () => {},
        listWorkflowRuns: async (p) => ({ data: { workflow_runs: byWorkflow[p.workflow_id] || [] } }),
        createWorkflowDispatch: async (p) => { calls.push(['dispatch', p.ref, p.workflow_id]); },
      },
      issues: {
        listForRepo: async (p) => {
          assert.equal(p.labels, 'incidente-datos');
          return { data: all.filter((i) => i.state === 'open') };
        },
        create: async (p) => {
          const i = { number: 100 + all.length, state: 'open', updated_at: ago(0), ...p };
          all.push(i);
          calls.push(['create', i.number, p.title, p.body, p.labels]);
          return { data: i };
        },
        createComment: async (p) => { calls.push(['comment', p.issue_number, p.body]); },
        update: async (p) => {
          Object.assign(all.find((i) => i.number === p.issue_number), p);
          calls.push(['update', p.issue_number, p.state]);
        },
      },
      repos: {
        getContent: async (p) => {
          assert.equal(p.path, 'heartbeat.json');
          const hb = branches[p.ref];
          if (hb === undefined) throw notFound();
          if (hb instanceof Error) throw hb;
          const text = typeof hb === 'string' ? hb : JSON.stringify(hb);
          return { data: { content: Buffer.from(text).toString('base64').replace(/(.{60})/g, '$1\n'), encoding: 'base64' } };
        },
      },
    },
  };
  return { github, calls, issues: all };
}

function core() {
  const c = { warnings: [], failed: [] };
  return Object.assign(c, { info() {}, warning: (m) => c.warnings.push(m), setFailed: (m) => c.failed.push(m) });
}

const site = (hours) => async () => ({ ok: true, json: async () => ({ generatedAt: ago(hours), publicationId: 'pub-1', health: { worst: 'warning' } }) });
const env = { SITE_URL: 'https://sitio.example/', MAX_AGE_HOURS: '30' };
const go = (f, c = core(), extra = {}) => run({ github: f.github, context, core: c, fetch: site(2), env, now: NOW, ...extra });

describe('vigilante: latidos de los recolectores', () => {
  it('un latido de 50 h en data-peru abre un issue con el equipo, el recolector y el resultado', async () => {
    const f = fake({ branches: { 'data-peru': beat(50, { result: 'sin-fuentes', reachable: '0/11' }) } });
    await go(f);
    const created = f.calls.filter((c) => c[0] === 'create');
    assert.equal(created.length, 1);
    const [, , title, body, labels] = created[0];
    assert.match(title, /recolector del Perú/);
    assert.deepEqual(labels, ['incidente-datos']);
    assert.ok(body.includes('<!-- enso-fp:collector-silent-data-peru -->'));
    for (const s of ['mac-lima', '2026.10.3', 'sin-fuentes', '0/11', 'hace 50 horas']) assert.ok(body.includes(s), s);
    assert.ok(!f.calls.some((c) => c[0] === 'dispatch'), 'el sitio está al día: no se relanza');
  });

  it('un latido reciente cierra el issue abierto, con un comentario', async () => {
    const f = fake({
      branches: { 'data-peru': beat(3) },
      issues: [{ number: 7, body: 'callado\n\n<!-- enso-fp:collector-silent-data-peru -->' }],
    });
    await go(f);
    assert.deepEqual(f.calls.map((c) => c.slice(0, 2)), [['comment', 7], ['update', 7]]);
    assert.match(f.calls[0][2], /volvió a latir/);
    assert.equal(f.issues[0].state, 'closed');
  });

  it('una rama que no existe (404) no se revisa', async () => {
    const f = fake({ issues: [{ number: 7, body: '<!-- enso-fp:collector-silent-data-n8n -->' }] });
    await go(f);
    assert.deepEqual(f.calls, []);
  });

  it('mientras sigue callado recuerda una vez al día, sin abrir otro issue', async () => {
    const issue = { number: 8, body: '<!-- enso-fp:collector-silent-data-n8n -->' };
    const hb = beat(60, { collector: { kind: 'n8n', host: 'n8n-aws', workflow: 'enso-n8n-recolector' } });
    let f = fake({ branches: { 'data-n8n': hb }, issues: [{ ...issue, updated_at: ago(5) }] });
    await go(f);
    assert.deepEqual(f.calls, []);
    f = fake({ branches: { 'data-n8n': hb }, issues: [{ ...issue, updated_at: ago(25) }] });
    await go(f);
    assert.deepEqual(f.calls.map((c) => c.slice(0, 2)), [['comment', 8]]);
    assert.ok(f.calls[0][2].includes('n8n-aws') && f.calls[0][2].includes('enso-n8n-recolector'));
  });

  it('un latido ilegible cuenta como callado; un error de la API no abre ni cierra nada', async () => {
    const f = fake({ branches: { 'data-peru': 'no es json', 'data-n8n': Object.assign(new Error('boom'), { status: 500 }) } });
    const c = core();
    await go(f, c);
    assert.deepEqual(f.calls.map((x) => x[0]), ['create']);
    assert.ok(f.calls[0][3].includes('no tiene fecha legible'));
    assert.ok(c.warnings.some((w) => w.includes('data-n8n')));
  });

  it(`el límite es de ${HEARTBEAT_MAX_HOURS} horas, como RELAY_STALE_HOURS en el pipeline`, async () => {
    const f = fake({ branches: { 'data-peru': beat(HEARTBEAT_MAX_HOURS - 1), 'data-n8n': beat(HEARTBEAT_MAX_HOURS + 1) } });
    await go(f);
    const created = f.calls.filter((c) => c[0] === 'create');
    assert.equal(created.length, 1);
    assert.ok(created[0][3].includes('collector-silent-data-n8n'));
  });
});

describe('vigilante: antigüedad del sitio (como antes)', () => {
  it('un sitio de 40 h relanza el flujo diario y abre su issue; los latidos se revisan igual', async () => {
    const f = fake({ branches: { 'data-peru': beat(50) } });
    await go(f, core(), { fetch: site(40) });
    assert.deepEqual(f.calls.filter((c) => c[0] === 'dispatch'), [['dispatch', 'main', 'observatory.yml']]);
    const bodies = f.calls.filter((c) => c[0] === 'create').map((c) => c[3]);
    assert.equal(bodies.length, 2);
    assert.ok(bodies[0].includes('enso-fp:site-stale') && bodies[0].includes('se relanzó la actualización'));
    assert.ok(bodies[1].includes('enso-fp:collector-silent-data-peru'));
  });

  it('una corrida de prueba en otra rama (no despliega) no impide relanzar main', async () => {
    const branchRun = { head_branch: 'claude/x', event: 'workflow_dispatch', status: 'in_progress', created_at: ago(1) };
    const f = fake({ runs: { 'observatory.yml': [branchRun] } });
    await go(f, core(), { fetch: site(40) });
    assert.deepEqual(f.calls.filter((c) => c[0] === 'dispatch'), [['dispatch', 'main', 'observatory.yml']]);
    const g = fake({ runs: { 'observatory.yml': [{ ...branchRun, head_branch: 'main' }] } });
    await go(g, core(), { fetch: site(40) });
    assert.deepEqual(g.calls.filter((c) => c[0] === 'dispatch'), []);
  });

  it('un sitio al día cierra el issue del sitio atrasado', async () => {
    const f = fake({ issues: [{ number: 3, body: '<!-- enso-fp:site-stale -->' }] });
    await go(f);
    assert.deepEqual(f.calls.map((c) => c.slice(0, 2)), [['comment', 3], ['update', 3]]);
  });

  it('sin SITE_URL falla el paso, pero revisa los latidos', async () => {
    const f = fake({ branches: { 'data-peru': beat(50) } });
    const c = core();
    await go(f, c, { env: { MAX_AGE_HOURS: '30' } });
    assert.equal(c.failed.length, 1);
    assert.equal(f.calls.filter((x) => x[0] === 'create').length, 1);
  });

  it('si una revisión lanza un error, la otra corre y el paso falla', async () => {
    const f = fake({ branches: { 'data-peru': beat(50) } });
    f.github.rest.actions.listWorkflowRuns = async () => { throw new Error('API caída'); };
    await assert.rejects(go(f, core(), { fetch: site(40) }), /API caída/);
    assert.equal(f.calls.filter((x) => x[0] === 'create' && x[3].includes('collector-silent')).length, 1);
  });
});

describe('vigilante: sonda semanal del registro', () => {
  const dispatched = (f) => f.calls.filter((c) => c[0] === 'dispatch');

  it(`sin sonda buena en main en ${PROBE_MAX_DAYS} días la relanza en main`, async () => {
    const c = core();
    const f = fake({ runs: { 'probe-sources.yml': [probeRun(24 * (PROBE_MAX_DAYS + 1))] } });
    await go(f, c);
    assert.deepEqual(dispatched(f), [['dispatch', 'main', 'probe-sources.yml']]);
    assert.ok(c.warnings.some((w) => w.includes('se relanzó')));
    assert.ok(!f.calls.some((x) => x[0] === 'create'), 'no abre issue');
  });

  it('una sonda que nunca corrió en main también se relanza; las de otras ramas no cuentan', async () => {
    const f = fake({ runs: { 'probe-sources.yml': [probeRun(2, { head_branch: 'claude/x', event: 'push' })] } });
    await go(f);
    assert.deepEqual(dispatched(f), [['dispatch', 'main', 'probe-sources.yml']]);
  });

  it('una sonda buena reciente, una en curso o una relanzada hoy no se relanzan', async () => {
    for (const runs of [[probeRun(24 * (PROBE_MAX_DAYS - 1))],
      [probeRun(1, { status: 'in_progress', conclusion: null }), probeRun(24 * 30)],
      [probeRun(3, { event: 'workflow_dispatch', conclusion: 'failure' }), probeRun(24 * 30)]]) {
      const c = core();
      const f = fake({ runs: { 'probe-sources.yml': runs } });
      await go(f, c);
      assert.deepEqual(dispatched(f), [], JSON.stringify(runs));
      if (runs[0].conclusion === 'failure') assert.ok(c.warnings.some((w) => w.includes('failure')));
    }
  });
});
