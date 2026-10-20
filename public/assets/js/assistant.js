// Asistente de datos determinista. No es un modelo de lenguaje: reconoce
// la intención de la pregunta con reglas y responde solo con valores de la
// publicación vigente, citando cada evidencia (serie, periodo, fuente e
// identificador de publicación). No emite alertas ni pronósticos propios.

import { html, raw, esc, $ } from './lib/dom.js';
import * as F from './lib/format.js';
import { GLOSSARY, OFFICIAL_LINKS } from './content.js';
import { ICON } from './icons.js';

const norm = (s) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[¿?¡!.,;:()"]/g, ' ').replace(/\s+/g, ' ').trim();

const SUGGEST = [
  '¿Qué indica el valor más reciente de Niño 1+2 y cuál es su periodo de validez?',
  '¿Cuál es el estado oficial de ENFEN?',
  '¿Estamos en El Niño?',
  '¿Cómo están los vientos alisios?',
  '¿Qué dice la señal del equipo GRD?',
  '¿Cómo se compara con 1997?',
  '¿Qué es el RONI?',
  '¿Cuándo se actualizaron los datos?',
];

// Series que el asistente sabe nombrar (clave → patrones).
const SERIES = [
  ['icen', /\bicen\b/],
  ['nino12_oisst', /nino ?1 ?\+? ?2|nino 12|niño costero|costa/], ['nino34_oisst', /nino ?3[ .]?4|nino 34/],
  ['nino3_oisst', /nino ?3\b(?![ .]?4)/], ['nino4_oisst', /nino ?4\b/], ['roni', /\broni\b/], ['oni', /\boni\b/],
  ['soi_troup', /\bsoi\b|oscilacion del sur|presion/], ['cpac850_anom', /viento|alisio/],
  ['heat_180w100w', /calor|termoclina|subsuperfic/],
];

export const assistantView = {
  render() {
    return html`
      <div class="page-head"><div class="eyebrow">Asistente</div><h1>Pregunte sobre los datos</h1>
        <p>Asistente automático basado en reglas (no usa inteligencia artificial generativa). Responde solo con los datos de la publicación vigente y muestra la evidencia de cada cifra.</p></div>
      <section class="card" data-tour-id="assistant" aria-labelledby="qa-h">
        <h2 id="qa-h" class="visually-hidden">Conversación</h2>
        <form id="qa-form" class="row" autocomplete="off">
          <label for="qa-in" class="visually-hidden">Su pregunta</label>
          <input id="qa-in" class="input grow" maxlength="300" placeholder="Por ejemplo: ¿cuál es el último ICEN?" required>
          <button class="btn" type="submit">${raw(ICON.send)}<span>Preguntar</span></button>
        </form>
        <div class="suggest" data-tour-id="assistant-suggest" aria-label="Preguntas sugeridas">${SUGGEST.map((q) => html`<button type="button" class="pill-btn" data-q="${q}">${q}</button>`)}</div>
        <div id="qa-log" class="qa-log" aria-live="polite"></div>
        <p class="muted small">El asistente no emite alertas ni recomendaciones de emergencia. Para decisiones, consulte a ENFEN, SENAMHI e INDECI.</p>
      </section>`;
  },

  after(S) {
    const log = $('#qa-log');
    const ask = (q) => {
      const a = answer(q, S);
      log.insertAdjacentHTML('beforeend', String(html`<div class="qa-q">${q}</div><div class="qa-a">${raw(a.html)}${a.evidence.length ? html`<div class="evid">Evidencia: ${a.evidence.join(' · ')} · publicación ${S.pub}</div>` : ''}</div>`));
      log.lastElementChild.scrollIntoView({ block: 'nearest' });
    };
    $('#qa-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const q = $('#qa-in').value.trim();
      if (q) ask(q);
      $('#qa-in').value = '';
    });
    document.querySelectorAll('[data-q]').forEach((b) => b.addEventListener('click', () => ask(b.dataset.q)));
  },
};

function seriesAnswer(S, k) {
  const s = S.dash.series[k];
  if (!s) return { html: 'Esa serie no está disponible en esta publicación.', evidence: [] };
  const l = s.latest;
  const per = s.periodKind === 'season' ? F.fmtSeason(l.period) : F.fmtMonth(l.period);
  const ev = [`serie:${k}@${l.period}`, `fuente:${s.source}`];
  if (l.stale) {
    return { html: String(html`<p><strong>Dato actual no disponible</strong> para ${s.label}. El último valor válido es ${F.fmtValue(l.value, s.units)} y corresponde a ${per}; supera la vigencia de esta serie, por lo que no representa la condición actual.</p>`), evidence: ev };
  }
  const cat = l.category?.label ? ` Clasificación: ${l.category.label.toLowerCase()}.` : '';
  const chg = l.previous ? ` Cambio frente a ${s.periodKind === 'season' ? F.fmtSeason(l.previous.period) : F.fmtMonth(l.previous.period)}: ${F.fmtValue(l.previous.change, s.units)}.` : '';
  let extra = '';
  if (k === 'nino12_oisst' && S.dash.weekly?.nino12) {
    const w = S.dash.weekly.nino12.latest;
    extra = ` El dato semanal más reciente es ${F.fmtValue(w.anom, 'degC')} (semana centrada en el ${F.fmtDate(w.date)}). Ninguno de los dos es el ICEN: el índice oficial es la media de tres meses que publica ENFEN.`;
    ev.push(`semanal:nino12@${w.date}`);
  }
  return {
    html: String(html`<p><strong>${s.label}:</strong> ${F.fmtValue(l.value, s.units)}, válido para <strong>${per}</strong> (${s.frequency}).${cat}${chg}${extra}</p><p class="muted small">${s.description}</p>`),
    evidence: ev,
  };
}

function officialAnswer(S, who) {
  const o = S.dash.official?.[who];
  const name = who === 'enfen' ? 'ENFEN' : 'NOAA';
  if (!o?.status) return { html: `No se pudo leer el último estado de ${name} en esta publicación. Consulte la fuente oficial.`, evidence: [] };
  const st = who === 'enfen' ? o.status : `${o.statusEs} (${o.status})`;
  const stale = o.stale ? ' Este estado ya no es vigente: debió publicarse un comunicado más reciente que aún no se pudo leer.' : '';
  return {
    html: String(html`<p>Estado de ${name}: <strong>${st}</strong>${who === 'enfen' ? `, comunicado N° ${o.number}` : ''}, emitido el ${F.fmtDate(o.issued)}.${o.nextIssue ? ` Próximo: ${F.fmtDate(o.nextIssue)}.` : ''}${stale}</p>`),
    evidence: [`oficial:${who}@${o.issued}`],
  };
}

export function answer(q, S) {
  const t = norm(q);
  const out = (h, ev = []) => ({ html: h, evidence: ev });

  if (/soi costero|soi de la costa|soi local/.test(t)) {
    return out('<p>No existe un «SOI costero». El SOI es un índice de escala cuenca: compara la presión en Tahití y en Darwin (Australia). Para la costa peruana se usan la temperatura del mar en Niño 1+2 y el ICEN.</p>');
  }
  if (/evacu|emergencia|peligro|que hago|debo (salir|preocup)|alerta roja|huaico|inundaci/.test(t)) {
    const links = OFFICIAL_LINKS.filter((l) => /INDECI|SENAMHI|CENEPRED/.test(l.name));
    return out(String(html`<p>Este observatorio no emite alertas ni instrucciones de emergencia. Siga a las autoridades:</p><ul>${links.map((l) => html`<li><a href="${l.url}" rel="noopener" target="_blank">${l.name}</a></li>`)}</ul>`));
  }
  if (/pronostic|predic|va a llover|proximo (ano|verano)|futuro|como estara|cuanto durara/.test(t)) {
    const n = S.dash.official?.noaa;
    const e = S.dash.official?.enfen;
    return out(String(html`<p>El observatorio no hace pronósticos propios. Las perspectivas oficiales son:</p><ul>
      ${e?.summary ? html`<li><strong>ENFEN</strong> (comunicado N° ${e.number}, ${F.fmtDate(e.issued)}): ${e.summary}</li>` : ''}
      ${n?.synopsis ? html`<li><strong>NOAA</strong> (${F.fmtDate(n.issued)}, en inglés): <span lang="en">${n.synopsis}</span></li>` : ''}</ul>`),
    [e ? `oficial:enfen@${e.issued}` : '', n ? `oficial:noaa@${n.issued}` : ''].filter(Boolean));
  }
  if (/actualiz|vigencia|fecha de los datos|cuando se/.test(t)) {
    return out(String(html`<p>Esta publicación se generó el ${F.fmtDateTime(S.dash.generatedAt)}. Cada dato tiene su propio periodo de validez, que se indica junto al valor. ${S.dash.health ? `${S.dash.health.sourcesOk} de ${S.dash.health.sourcesTotal} fuentes respondieron con normalidad.` : ''}</p>`), ['publicacion']);
  }
  if (/\bd20\b|isoterma/.test(t)) {
    return out('<p>El observatorio no publica la profundidad de la isoterma de 20 °C (D20): no hay una fuente pública verificada de ese valor. Como referencia del calor bajo la superficie se muestra el contenido de calor de 0–300 m de NOAA, sin aplicarle los umbrales de D20.</p>');
  }
  if (/grd|semaforo|senal operativa/.test(t)) {
    const g = S.dash.grd;
    return out(String(html`<p>${g.disclaimer}</p><ul>${g.signals.map((x) => html`<li><strong>${x.name} (${x.region})</strong>: ${x.label}${x.value !== null && !x.stale ? ` — ${x.direction || F.fmtValue(x.value, x.units)} (${F.fmtMonth(x.period)})` : ''}</li>`)}</ul>`), g.signals.filter((x) => x.period).map((x) => `grd:${x.id}@${x.period}`));
  }
  const year = /\b(19[5-9]\d|20[0-4]\d)\b/.exec(t);
  if (year && /compar|como (en|fue)|igual|parec|evento|\b19|\b20/.test(t)) {
    const evs = (S.dash.events || []).filter((e) => e.start.slice(0, 4) === year[1] || e.end.slice(0, 4) === year[1]);
    const cur = (S.dash.events || []).find((e) => e.ongoing);
    if (!evs.length) return out(`<p>No hay un evento El Niño o La Niña costero registrado en ${esc(year[1])} según el ICEN oficial.</p>`);
    return out(String(html`<ul>${evs.map((e) => html`<li><strong>${e.name}</strong> ${F.fmtMonth(e.start)} – ${F.fmtMonth(e.end)}: ${e.months} meses, ICEN máximo ${F.fmtValue(e.peak, 'degC')}, magnitud ${e.magnitude}.</li>`)}</ul>
      ${cur ? html`<p>Evento actual: ${cur.name} desde ${F.fmtMonth(cur.start)}, ${cur.months} meses, máximo hasta ahora ${F.fmtValue(cur.peak, 'degC')} (${cur.magnitude}).</p>` : ''}`), evs.map((e) => `evento:${e.start}`).concat(cur ? [`evento:${cur.start}`] : []));
  }
  if (/^(que|quien) (es|son|significa)|definicion|significa/.test(t)) {
    const hit = GLOSSARY.find(([term]) => t.includes(norm(term)));
    if (hit) return out(String(html`<p><strong>${hit[0]}:</strong> ${hit[1]}</p>`), ['glosario']);
  }
  if (/estamos en|hay (un )?(el )?nino|hay nina|el nino (esta|ya)|estado actual|situacion/.test(t)) {
    const a = officialAnswer(S, 'enfen');
    const b = officialAnswer(S, 'noaa');
    const c = seriesAnswer(S, 'icen');
    return out(`${a.html}${b.html}${c.html}<p class="muted small">ENFEN declara para la costa peruana (El Niño Costero) y NOAA para el Pacífico central; pueden no coincidir.</p>`, [...a.evidence, ...b.evidence, ...c.evidence]);
  }
  if (/enfen|comunicado|alerta|vigilancia/.test(t)) return officialAnswer(S, 'enfen');
  if (/noaa|cpc|advisory|advertencia/.test(t)) return officialAnswer(S, 'noaa');
  for (const [k, re] of SERIES) if (re.test(t)) return seriesAnswer(S, k);
  const hit = GLOSSARY.find(([term]) => t.includes(norm(term)));
  if (hit) return out(String(html`<p><strong>${hit[0]}:</strong> ${hit[1]}</p>`), ['glosario']);
  return out('<p>No encontré una respuesta en los datos publicados. Puedo informar sobre: estado oficial de ENFEN o NOAA, últimos valores de ICEN, Niño 1+2, Niño 3.4, RONI, ONI, SOI, vientos y calor bajo la superficie, la señal del equipo GRD, eventos pasados por año y definiciones del glosario.</p>');
}
