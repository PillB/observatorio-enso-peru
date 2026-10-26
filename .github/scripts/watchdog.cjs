// Vigilante independiente (.github/workflows/watchdog.yml, con actions/github-script cada 6 horas).
//
// * Sitio: si la publicación en vivo tiene más de MAX_AGE_HOURS horas, reactiva y relanza el flujo diario una
//   vez y abre (o comenta) el issue enso-fp:site-stale; lo cierra cuando el sitio vuelve a estar al día.
// * Recolectores: lee heartbeat.json de las ramas data-peru y data-n8n. Si el último latido tiene más de
//   HEARTBEAT_MAX_HOURS (las RELAY_STALE_HOURS del pipeline), abre el issue enso-fp:collector-silent-<rama>, con el
//   equipo, el recolector y su último resultado, y lo recuerda una vez al día; lo cierra cuando vuelve a latir. Una
//   rama que no existe o no tiene latido (404) no se revisa: ese recolector puede no estar instalado todavía.
//   Así un recolector callado se ve aunque el flujo diario esté fallando y no llegue a sincronizar sus incidencias.
// * Registro: si la sonda semanal (probe-sources.yml) no terminó bien en la rama principal en PROBE_MAX_DAYS días
//   (GitHub puede saltarse una corrida programada, como el lunes 26 de octubre de 2026), la relanza, como mucho una
//   vez al día. Sin ella, las URL nuevas del registro quedan sin medir (robots «unknown») y los canales no siguen
//   a los servidores que dejan de responder.
//
// Las pruebas (python/tests/js/watchdog.test.mjs) le pasan un `github` de mentira.
'use strict';

const LABEL = 'incidente-datos';
const WORKFLOW = 'observatory.yml';
const HEARTBEAT_MAX_HOURS = 36;
const REMIND_HOURS = 24;
const PROBE = 'probe-sources.yml';
const PROBE_MAX_DAYS = 8;
const BUSY = ['queued', 'in_progress', 'waiting', 'pending', 'requested'];
const COLLECTORS = {
  'data-peru': { title: 'El recolector del Perú', name: 'el recolector del Perú', doc: 'docs/servidor-peru.md' },
  'data-n8n': { title: 'El flujo de n8n', name: 'el flujo de n8n', doc: 'docs/n8n.md' },
};

const hours = (now, iso) => (now - Date.parse(iso)) / 36e5;

async function openIssues(github, context) {
  const { data } = await github.rest.issues.listForRepo({ ...context.repo, state: 'open', labels: LABEL, per_page: 100 });
  return data;
}

async function closeIssue(github, context, issue, body) {
  await github.rest.issues.createComment({ ...context.repo, issue_number: issue.number, body });
  await github.rest.issues.update({ ...context.repo, issue_number: issue.number, state: 'closed', state_reason: 'completed' });
}

async function checkSite({ github, context, core, fetch, env, now }) {
  if (!env.SITE_URL) {
    core.setFailed('Con DEPLOY_TARGET=cloudflare hay que guardar la dirección del sitio en la variable SITE_URL (ver docs/despliegue-cloudflare.md).');
    return;
  }
  // Reactivar por API reinicia el plazo de 60 días sin actividad; el vigilante
  // también se reactiva a sí mismo y el flujo diario lo reactiva a él (keepalive).
  for (const id of [WORKFLOW, 'watchdog.yml', 'probe-sources.yml']) {
    try { await github.rest.actions.enableWorkflow({ ...context.repo, workflow_id: id }); } catch (e) { core.warning(`${id}: ${e.message}`); }
  }
  let gen = null, pub = null, worst = null, err = null;
  try {
    const r = await fetch(`${env.SITE_URL.replace(/\/?$/, '/')}data/dashboard.json?t=${now}`, { headers: { 'Cache-Control': 'no-cache' } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    gen = d.generatedAt; pub = d.publicationId; worst = d.health?.worst;
  } catch (e) { err = e.message; }
  const age = gen ? hours(now, gen) : Infinity;
  core.info(`publication ${pub} generated ${gen} (${age.toFixed(1)} h), worst=${worst}, error=${err}`);
  const stale = !(age <= Number(env.MAX_AGE_HOURS || 30));
  const prev = (await openIssues(github, context)).find((i) => (i.body || '').includes('enso-fp:site-stale'));
  if (!stale) {
    if (prev) await closeIssue(github, context, prev, `El sitio vuelve a estar al día (publicación \`${pub}\`). Se cierra automáticamente.`);
    return;
  }
  const { data: runs } = await github.rest.actions.listWorkflowRuns({ ...context.repo, workflow_id: WORKFLOW, per_page: 5 });
  const busy = runs.workflow_runs.some((r) => BUSY.includes(r.status));
  const recent = runs.workflow_runs.find((r) => r.event === 'workflow_dispatch' && now - Date.parse(r.created_at) < 6 * 36e5);
  let action = 'ya hay una corrida en curso';
  if (!busy && !recent) {
    await github.rest.actions.createWorkflowDispatch({ ...context.repo, workflow_id: WORKFLOW, ref: context.payload.repository?.default_branch || 'main' });
    action = 'se relanzó la actualización';
  } else if (recent && !busy) action = 'ya se relanzó en las últimas 6 horas; se requiere revisión';
  const body = `El sitio en vivo no está al día: ${err ? `no se pudo leer (${err})` : `la publicación \`${pub}\` tiene ${age.toFixed(0)} horas`}. Acción: ${action}.\n\n<!-- enso-fp:site-stale -->`;
  if (prev) await github.rest.issues.createComment({ ...context.repo, issue_number: prev.number, body });
  else await github.rest.issues.create({ ...context.repo, title: '[datos] El sitio publicado está desactualizado', body, labels: [LABEL] });
}

// Latido de la rama, `null` si no existe (404) y `{}` si no se puede leer.
async function heartbeat(github, context, ref) {
  let data;
  try {
    ({ data } = await github.rest.repos.getContent({ ...context.repo, ref, path: 'heartbeat.json' }));
  } catch (e) {
    if (e.status === 404) return null;
    throw e;
  }
  try {
    const hb = JSON.parse(Buffer.from(data.content || '', data.encoding || 'base64').toString('utf8'));
    return hb && typeof hb === 'object' ? hb : {};
  } catch { return {}; }
}

function silentBody(ref, hb, age) {
  const c = COLLECTORS[ref];
  const who = hb.collector || {};
  const kit = who.kit || who.runner || who.workflow || who.kind || 'sin dato';
  const last = hb.at
    ? `El último latido de ${c.name} (rama \`${ref}\`) es del ${hb.at}: hace ${age.toFixed(0)} horas (el límite es ${HEARTBEAT_MAX_HOURS}).`
    : `El latido de ${c.name} (rama \`${ref}\`) no tiene fecha legible.`;
  return `${last}\n\n- Equipo: \`${who.host || 'sin dato'}\`\n- Recolector: \`${kit}\`\n`
    + `- Último resultado: \`${hb.result || 'sin dato'}\`${hb.reachable ? ` (${hb.reachable} fuentes)` : ''}\n\n`
    + `Sin latidos, el sitio no recibe copias nuevas de ese canal. Revisar el equipo o el flujo (${c.doc}).\n\n`
    + `<!-- enso-fp:collector-silent-${ref} -->`;
}

async function checkCollectors({ github, context, core, now }) {
  let open = null;
  for (const ref of Object.keys(COLLECTORS)) {
    let hb;
    try { hb = await heartbeat(github, context, ref); } catch (e) {
      core.warning(`${ref}: no se pudo leer heartbeat.json (${e.status || ''} ${e.message})`);
      continue;
    }
    if (hb === null) { core.info(`${ref}: sin rama o sin latido; no se revisa`); continue; }
    const age = hb.at ? hours(now, hb.at) : NaN;
    core.info(`${ref}: latido ${hb.at} (${age.toFixed(1)} h), resultado ${hb.result}`);
    open = open || await openIssues(github, context);
    const fp = `<!-- enso-fp:collector-silent-${ref} -->`;
    const prev = open.find((i) => (i.body || '').includes(fp));
    if (age <= HEARTBEAT_MAX_HOURS) {
      if (prev) await closeIssue(github, context, prev, `${COLLECTORS[ref].title} volvió a latir (${hb.at}, resultado \`${hb.result}\`). Se cierra automáticamente.`);
      continue;
    }
    const body = silentBody(ref, hb, age);
    if (!prev) {
      await github.rest.issues.create({ ...context.repo, title: `[datos] ${COLLECTORS[ref].title} no da señales (${ref})`, body, labels: [LABEL] });
    } else if (!(hours(now, prev.updated_at) < REMIND_HOURS)) {
      await github.rest.issues.createComment({ ...context.repo, issue_number: prev.number, body }); // un recordatorio al día
    }
  }
}

// La sonda semanal en la rama principal: si no terminó bien en PROBE_MAX_DAYS días, se relanza (una vez al día).
async function checkProbe({ github, context, core, now }) {
  const branch = context.payload.repository?.default_branch || 'main';
  const { data } = await github.rest.actions.listWorkflowRuns({ ...context.repo, workflow_id: PROBE, branch, per_page: 20 });
  const runs = data.workflow_runs.filter((r) => r.head_branch === branch);
  const ok = runs.find((r) => r.conclusion === 'success');
  core.info(`${PROBE}: última sonda buena en ${branch}: ${ok ? ok.created_at : 'ninguna'}`);
  if (ok && hours(now, ok.created_at) <= PROBE_MAX_DAYS * 24) return;
  if (runs.some((r) => BUSY.includes(r.status))) return;
  const recent = runs.find((r) => r.event === 'workflow_dispatch' && hours(now, r.created_at) < 24);
  if (recent) {
    core.warning(`${PROBE}: sin sonda buena en ${PROBE_MAX_DAYS} días; la relanzada el ${recent.created_at} terminó «${recent.conclusion}»: revisar ${recent.html_url || 'su corrida'}`);
    return;
  }
  await github.rest.actions.createWorkflowDispatch({ ...context.repo, workflow_id: PROBE, ref: branch });
  core.warning(`${PROBE}: sin sonda buena en ${branch} en ${PROBE_MAX_DAYS} días; se relanzó`);
}

// Revisa el sitio, los recolectores y la sonda; un error en uno no impide revisar los demás.
async function run({ github, context, core, fetch = globalThis.fetch, env = process.env, now = Date.now() }) {
  let error = null;
  for (const check of [checkSite, checkCollectors, checkProbe]) {
    try { await check({ github, context, core, fetch, env, now }); } catch (e) { error = error || e; }
  }
  if (error) throw error;
}

module.exports = { run, checkSite, checkCollectors, checkProbe, HEARTBEAT_MAX_HOURS, PROBE_MAX_DAYS };
