// Los recorridos del tutorial (tour.js): uno por pestaña, uno de inicio rápido y uno completo.
//
// Un paso:
//   route   la pestaña (#/memoria). Solo se navega si la persona está en otra; los filtros de la vista los fija
//           `ensure`. Puede llevar parámetros para abrir la vista en un estado conocido (?vista=resumen).
//   ensure  estado que necesita el paso, que el tutorial deja en silencio antes de mostrarlo:
//           [{ when: () => hay que cambiarlo, act: acción, ready: selector que debe existir antes }]. Así cada paso
//           se puede mostrar solo, también al volver con «Anterior» o al reanudarlo después de recargar.
//   target  lo que se resalta: un selector, una lista (el primero visible) o una función que devuelve el elemento.
//   demo    lo que el tutorial hace delante de la persona, en orden, con el puntero animado:
//           { click | select (+value) | type (+text, submit) | hover (+at [fx, fy]) | open: selector,
//             say: lo que se anuncia, ready: selector que espera después, target: nuevo resaltado, pause: ms }
//   after   lo que se resalta al terminar la demostración.
//   avoid   más elementos que la ventana no puede tapar (p. ej. el tooltip que abre la demostración).
//   optional  si el elemento no existe en esta publicación (un dato que no llegó), el paso se salta.
//
// Los textos son cortos a propósito: en un teléfono la ventana comparte la pantalla con lo que explica.

const q = (s) => document.querySelector(s);

/** Un botón de alternar (aria-pressed) que debe quedar activo. */
const pressed = (sel, ready = sel) => ({ when: () => !q(`${sel}[aria-pressed="true"]`), act: { click: sel }, ready });
/** Un <select> o <input> con un valor. */
const valued = (sel, value) => ({ when: () => (q(sel)?.value ?? value) !== value, act: { select: sel, value }, ready: sel });
/** Un <details> abierto o cerrado. */
const opened = (sel, open = true) => ({ when: () => Boolean(q(sel)) && q(sel).open !== open, act: { open: sel, value: open }, ready: sel });
/** Un control que debe estar ausente (p. ej. «Quitar filtros» visible = hay filtros): se pulsa. */
const absent = (sel, ready) => ({ when: () => Boolean(q(sel)), act: { click: sel }, ready });

// --- Memoria de desastres ----------------------------------------------------------------------------------
const HZ = '#hz-root';
const HZ_MAP = '.hz-mapbox > svg';
const hzClean = [absent('#hz-filters [data-clear]', '#hz-filters'), absent('.hz-zoomout', '#hz-filters')];
const hzView = (v) => pressed(`.hz-views [data-vista="${v}"]`, '.hz-views');
const hzResumen = [hzView('resumen'), ...hzClean, pressed('[data-nivel="provincia"]', '#hz-filters'), valued('#hz-filters [name="metrica"]', 'anios')];
/** La ficha de Piura abierta en el resumen (por departamento). */
const hzPiura = { when: () => !q('#hz-side .hz-prof-h')?.textContent.includes('Piura'), act: { click: `${HZ_MAP} [data-code="20"]` }, ready: HZ_MAP };

// --- Noticias -----------------------------------------------------------------------------------------------
const AM = '[data-tour-id="alert-map"]';
const amView = (v) => pressed(`.amap-views [data-vista="${v}"]`, '.amap-views');
const amClean = absent(`${AM} .amap-filters [data-clear]`, `${AM} .amap-filters`);
/** El departamento con más avisos (el primero de la lista accesible del mapa) o, si no hay, Piura. */
const amDep = () => q('.amap-a11y [data-dep]')?.dataset.dep || '20';
const amDepShape = () => q(`.amap-svg path.dep[data-dep="${amDep()}"]`) || q('.amap-svg path.dep');
const newsTab = (t) => ({ when: () => q(`[data-tab="${t}"]`)?.getAttribute('aria-selected') !== 'true', act: { click: `[data-tab="${t}"]` }, ready: '[data-tab]' });

// --- Gráficos ----------------------------------------------------------------------------------------------
/** Pasar el puntero por un gráfico (muestra el valor de un mes) y cambiar su periodo. */
const chartDemo = (id, range) => [
  { hover: `#${id} svg.chart`, at: [0.82, 0.5], say: 'Al pasar el puntero (o con las flechas del teclado) se lee el valor de cada mes.', pause: 1400 },
  ...(range ? [{ click: `#${id} [data-range="${range}"]`, say: 'Los botones de arriba cambian el periodo del gráfico.', pause: 900 }] : []),
];
const chartReset = (id, range) => [pressed(`#${id} [data-range="${range}"]`, `#${id} svg.chart`)];

export const TOURS = [
  {
    id: 'inicio', title: 'Inicio rápido', desc: 'Lo esencial en un minuto.',
    steps: [
      { route: '#/', target: '.nav-inner', title: 'Las pestañas', text: 'Cada pestaña es una parte del observatorio. En el teléfono, deslice la barra para ver todas. Cada una tiene su propio recorrido guiado.' },
      { route: '#/', target: '[data-tour-id="official-status"]', title: 'Estados oficiales', text: 'Lo que declaran el ENFEN para la costa peruana y NOAA para el Pacífico, con la fecha del comunicado y la del próximo.' },
      { route: '#/', target: '[data-tour-id="freshest"]', title: 'El dato más reciente', text: (d) => `La medición semanal más nueva${d?.weekly?.nino12 ? ` (semana del ${d.weekly.nino12.latest.date})` : ''}. Es una observación, no una declaración oficial.` },
      { route: '#/', target: '[data-tour-id="indicators"] .grid > :first-child', title: 'Indicadores clave', text: 'Cada tarjeta dice a qué periodo corresponde su valor; si está vencido, dice «Dato actual no disponible». Tóquela para ir a su pestaña.' },
      { route: '#/', target: '[data-tour-id="grd"] .section-head', title: 'Señal operativa del equipo GRD', text: 'Semáforo interno calculado con la tabla de umbrales del equipo GRD. Siempre se distingue de los estados oficiales.' },
      { target: '#help-btn', title: 'Ayuda y tutorial', text: 'Desde aquí vuelve a este tutorial o elige el recorrido de cualquier pestaña. También está el botón «Cómo se usa esta pestaña» al inicio de cada una.' },
    ],
  },
  {
    id: 'completo', title: 'Recorrido completo', desc: 'Una parada en cada pestaña.',
    steps: [
      { route: '#/', target: '[data-tour-id="official-status"]', title: 'Resumen', text: 'Los estados oficiales, el dato más reciente, los indicadores clave y la señal del equipo GRD.' },
      { route: '#/costero', target: '#ch-icen', title: 'El Niño Costero', text: 'El ICEN oficial del ENFEN y su clasificación, con los datos más recientes de Niño 1+2.', demo: chartDemo('ch-icen'), ensure: chartReset('ch-icen', '15') },
      { route: '#/pacifico', target: '#ch-roni', title: 'Pacífico', text: 'El RONI y el ONI de NOAA para el Pacífico central, que influye en el clima de todo el planeta.' },
      { route: '#/oceano', target: '#ch-weekly', title: 'Océano y atmósfera', text: 'Temperatura del mar semanal y mensual, vientos alisios, calor bajo la superficie, termoclina y SOI.' },
      { route: '#/mapa', target: '#map-svg', title: 'Mapa', text: 'Las regiones Niño con su anomalía semanal. Con «Reproducir» se ve la evolución de las últimas 52 semanas.' },
      { route: '#/historia', target: '[data-tour-id="events"] .section-head', title: 'Historia', text: 'Todos los eventos desde 1950 identificados con la definición operacional del ENFEN.' },
      { route: '#/memoria?vista=resumen', target: HZ_MAP, ensure: hzResumen, title: 'Memoria de desastres', text: 'Dónde golpearon antes las inundaciones, los huaycos y las sequías, y cuánto más con El Niño costero. Toque un área para ver su ficha.' },
      { route: '#/noticias', target: `${AM} .amap-head`, title: 'Noticias', text: 'Los avisos oficiales vigentes en un mapa y las noticias de cada departamento, agrupadas cuando varios medios cuentan lo mismo.' },
      { route: '#/datos', target: '[data-tour-id="explorer"] .row', title: 'Datos', text: 'Cada serie completa en tabla y gráfico, y en CSV para descargar.' },
      { route: '#/metodologia', target: '[data-tour-id="sources-health"] .section-head', title: 'Metodología', text: 'El estado de cada fuente en la última corrida diaria, las incidencias y los umbrales que se usan.' },
      { route: '#/asistente', target: '#qa-form', title: 'Asistente', text: 'Preguntas sobre los datos publicados; cada respuesta cita su evidencia.' },
    ],
  },

  // ---------------------------------------------------------------------------------------------------------
  // Una pestaña a la vez (en el orden de la barra)
  // ---------------------------------------------------------------------------------------------------------
  {
    id: 'resumen', tab: '', next: 'costero', title: 'Resumen', desc: 'Estados oficiales, vigencia de los datos e indicadores.',
    steps: [
      { route: '#/', target: '[data-tour-id="freshness"]', ensure: [opened('[data-tour-id="freshness"]', false)], title: '¿Qué tan recientes son estos datos?', text: 'Cada pestaña empieza con este panel: dice si sus datos están al día. Ábralo para ver la fecha y el estado de cada uno.',
        demo: [{ click: '[data-tour-id="freshness"] > summary', say: 'Se abre el panel con cada dato, su fecha y su estado.', target: '[data-tour-id="freshness"]', pause: 900 }] },
      { route: '#/', target: '[data-tour-id="official-status"]', ensure: [opened('[data-tour-id="freshness"]', false)], title: 'Estados oficiales', text: 'Lo que declaran el ENFEN (costa del Perú) y NOAA (Pacífico central), con la fecha del comunicado vigente y la del próximo.' },
      { route: '#/', target: '[data-tour-id="freshest"]', title: 'Lo más reciente', text: 'La temperatura del mar de la última semana en cada región Niño, con su tendencia. Es una observación: no equivale al ICEN ni a una declaración oficial.' },
      { route: '#/', target: '[data-tour-id="indicators"] .grid > :first-child', title: 'Indicadores clave', text: 'Ocho indicadores con su periodo y su fuente. Toque una tarjeta para ir a la pestaña que la explica con su gráfico.' },
      { route: '#/', target: '[data-tour-id="enfen-outlook"]', optional: true, title: 'Perspectiva del ENFEN', text: 'Lo que el ENFEN espera para los próximos meses, citado textualmente de su comunicado.' },
      { route: '#/', target: '[data-tour-id="grd"] .section-head', title: 'Señal operativa del equipo GRD', text: 'Un semáforo interno con la tabla de umbrales del equipo GRD: no es un estado oficial. Lo que la tabla no define queda «Sin clasificación», nunca en verde.' },
      { route: '#/', target: '[data-tour-id="grd"] tbody tr', title: 'Cada fila', text: 'El indicador, su señal, el valor con su periodo, y enlaces a la fuente en vivo y a la copia que bajó el observatorio.' },
    ],
  },
  {
    id: 'costero', tab: 'costero', next: 'pacifico', title: 'El Niño Costero', desc: 'ICEN, Niño 1+2 y el sistema de alerta del ENFEN.',
    steps: [
      { route: '#/costero', target: '[data-tour-id="coastal-status"] .status-card', title: 'Estado del ENFEN', text: 'El ENFEN declara «Vigilancia» cuando es más probable que ocurra un evento a que no, y «Alerta» cuando ya comenzó o se espera que se consolide.' },
      { route: '#/costero', target: '[data-tour-id="enfen-probabilities"] .prob', optional: true, title: 'Probabilidades del ENFEN', text: 'La probabilidad de cada categoría mes a mes, leída de su informe técnico, con el enlace a la página del PDF.' },
      { route: '#/costero', target: '#ch-icen', ensure: chartReset('ch-icen', '15'), title: 'ICEN', text: 'La media de tres meses de Niño 1+2. Por ser centrada, el último valor oficial va unos dos meses detrás. Las bandas marcan las categorías.',
        demo: chartDemo('ch-icen', 'all') },
      { route: '#/costero', target: '[data-tour-id="coastal-scale"]', title: 'Categorías', text: 'Las magnitudes de la Nota Técnica ENFEN 01-2024. Un evento requiere al menos tres meses consecutivos en condición cálida o fría.' },
      { route: '#/costero', target: '#ch-n12w', title: 'Niño 1+2 semanal', text: 'Llega cada lunes y anticipa la tendencia del ICEN, sin reemplazarlo. «Ver los valores en una tabla» muestra las cifras.',
        ensure: [opened('#ch-n12w details.more', false)],
        demo: [{ open: '#ch-n12w details.more', say: 'Cada gráfico tiene su tabla de valores, también para lectores de pantalla.', target: '#ch-n12w', pause: 1000 }] },
    ],
  },
  {
    id: 'pacifico', tab: 'pacifico', next: 'oceano', title: 'Pacífico', desc: 'RONI, ONI y las regiones Niño.',
    steps: [
      { route: '#/pacifico', target: '[data-tour-id="basin-status"]', title: 'Estado de NOAA', text: 'NOAA publica su discusión el segundo jueves de cada mes con un estado: Vigilancia, Advertencia o No activo.' },
      { route: '#/pacifico', target: '#ch-roni', ensure: chartReset('ch-roni', '15'), title: 'RONI y ONI', text: 'Desde febrero de 2026 el RONI es el índice oficial de NOAA. El Niño desde +0,5 °C; La Niña desde −0,5 °C.', demo: chartDemo('ch-roni', '5') },
      { route: '#/pacifico', target: '#ch-regions', title: 'Regiones Niño', text: 'Niño 3, 3.4 y 4 muestran cómo se extiende el calentamiento a lo largo del ecuador.' },
      { route: '#/pacifico', target: '#ch-cvb', title: 'Costa frente a cuenca', text: 'Si la costa (Niño 1+2) se calienta más que el centro (Niño 3.4), es lo típico de El Niño Costero.' },
    ],
  },
  {
    id: 'oceano', tab: 'oceano', next: 'mapa', title: 'Océano y atmósfera', desc: 'Temperatura del mar, vientos, termoclina y SOI.',
    steps: [
      { route: '#/oceano', target: '#ch-weekly', ensure: chartReset('ch-weekly', '2'), title: 'Temperatura del mar semanal', text: 'Valores semanales de NOAA (OISST v2.1), centrados en el miércoles y publicados los lunes.', demo: chartDemo('ch-weekly', '5') },
      { route: '#/oceano', target: '#ch-monthly', title: 'Temperatura del mar mensual', text: 'ERSSTv6 es la reconstrucción que NOAA usa para el RONI; OISST llega unas semanas antes.' },
      { route: '#/oceano', target: '[data-tour-id="ocean-winds"]', title: 'Vientos alisios', text: 'Positivo: viento del este (lo normal). Negativo: flujo de oeste a este, típico de El Niño.' },
      { route: '#/oceano', target: '#ch-heat', title: 'Calor bajo la superficie', text: 'La temperatura media de los 300 m superiores del Pacífico ecuatorial. Su aumento suele anticipar el calentamiento en superficie.' },
      { route: '#/oceano', target: '#ch-d20', title: 'Profundidad de la termoclina', text: 'Si es positiva, la capa cálida es más gruesa y el mar frente al Perú tarda más en enfriarse. Las líneas marcan +20 y +50 m.' },
      { route: '#/oceano', target: '[data-tour-id="ocean-coast-thermo"]', title: 'Frente a Paita y Chicama', text: 'Lo que escriben el informe del ENFEN y el boletín del IMARPE sobre la columna de agua frente a la costa norte, con la cita y el enlace a cada documento.' },
      { route: '#/oceano', target: '#ch-soi', title: 'SOI', text: 'La diferencia de presión Tahití − Darwin en escala Troup. Negativo sostenido (menos de −7) favorece El Niño.' },
    ],
  },
  {
    id: 'mapa', tab: 'mapa', next: 'historia', title: 'Mapa', desc: 'Las regiones Niño y su animación semanal.',
    steps: [
      { route: '#/mapa', target: '#map-svg', ensure: [pressed('[data-view="pacifico"]', '#map-svg svg')], title: 'Regiones Niño', text: 'Cada caja es una región Niño coloreada con su anomalía semanal medida. No es un campo interpolado: es el promedio de cada caja.' },
      { route: '#/mapa', target: '#map-svg', ensure: [pressed('[data-view="pacifico"]', '#map-svg svg')], title: 'Encuadre', text: '«Costa del Perú» acerca el mapa a Niño 1+2, la región que más afecta al país.',
        demo: [{ click: '[data-view="peru"]', say: 'Se acerca a la costa del Perú.', pause: 1200 }, { click: '[data-view="pacifico"]', say: 'Y vuelve a todo el Pacífico.', pause: 400 }] },
      { route: '#/mapa', target: '[data-tour-id="map-controls"]', title: 'Semana a semana', text: 'Arrastre el control para ver otra semana, o use «Reproducir» para animar las últimas 52. La velocidad se elige a la derecha.',
        demo: [
          { select: '#map-range', value: '0', say: 'El control lleva a la primera semana…', target: '#map-svg', keep: '[data-tour-id="map-controls"]', pause: 900 },
          { click: '#map-play', say: '…y «Reproducir» avanza semana a semana.', pause: 2600 },
          { click: '#map-play', say: 'Se pausa con el mismo botón.', target: '[data-tour-id="map-controls"]' },
        ],
        after: '[data-tour-id="map-controls"]' },
      { route: '#/mapa', target: '#map-table', ensure: [opened('[data-tour-id="map"] details.more', true)], title: 'En una tabla', text: 'Los valores de la semana elegida, también para lectores de pantalla.' },
    ],
  },
  {
    id: 'historia', tab: 'historia', next: 'memoria', title: 'Historia', desc: 'Eventos desde 1950 y el evento actual frente a los grandes.',
    steps: [
      { route: '#/historia', target: '#ch-compare', title: 'Frente a los grandes eventos', text: 'El ICEN de cada gran El Niño alineado por su mes de inicio: así se compara el evento actual con 1972, 1982, 1997, 2015 y 2023.',
        demo: [{ hover: '#ch-compare svg.chart', at: [0.35, 0.5], say: 'Pase el puntero para comparar el mismo mes de cada evento.', pause: 1200 }] },
      { route: '#/historia', target: '[data-tour-id="events"] .section-head', ensure: [pressed('[data-ph="all"]')], title: 'Todos los eventos', text: 'Cada fila es un evento con su periodo, duración, ICEN máximo y magnitud. Filtre por El Niño o La Niña.',
        demo: [{ click: '[data-ph="warm"]', say: 'Solo El Niño…', pause: 900 }, { click: '[data-ph="cool"]', say: '…solo La Niña…', pause: 900 }, { click: '[data-ph="all"]', say: '…o todos.' }] },
      { route: '#/historia', target: '[aria-labelledby="imp-h"]', title: 'Impactos documentados', text: 'Lo que dejaron los grandes eventos en el Perú, con su fuente.' },
    ],
  },
  {
    id: 'memoria', tab: 'memoria', next: 'noticias', title: 'Memoria de desastres', desc: 'El mapa de los desastres pasados: filtros, fichas y vistas de detalle.',
    steps: [
      { route: '#/memoria?vista=resumen', target: '.hz-context', ensure: hzResumen, optional: true, title: 'Lo que dice la historia ahora', text: 'Si hay un Niño costero en curso, aquí aparece qué departamentos tuvieron claramente más daños en temporadas con Niño. Cada nombre abre su ficha.' },
      { route: '#/memoria?vista=resumen', target: '.hz-views', ensure: hzResumen, title: 'Resumen y detalle', text: '«Resumen» colorea departamentos, provincias o distritos. Las vistas de detalle muestran cuencas, ríos y lugares, o daños frente a pobreza.' },
      { route: '#/memoria?vista=resumen', target: HZ_MAP, ensure: hzResumen, title: 'El mapa', text: 'Cada provincia según en cuántos años de 1970-2015 tuvo daños. Pase el puntero (o el foco) por un área para leer su resumen.',
        avoid: ['.hz-tip:not([hidden])'],
        demo: [{ hover: `${HZ_MAP} [data-code="2001"]`, say: 'El tooltip resume el área: registros, años con daños y grandes Niños.', pause: 1800 }] },
      { route: '#/memoria?vista=resumen', target: '#hz-filters', ensure: hzResumen, title: 'Filtros', text: 'Elija un evento (por ejemplo, solo los grandes Niños), un peligro o un rango de temporadas. El mapa, la ficha y los rankings se recalculan.',
        demo: [{ select: '#hz-filters [name="evento"]', value: 'grandes', say: 'Evento: solo los grandes Niños.', target: HZ_MAP, keep: '#hz-filters [name="evento"]', pause: 1400 }],
        after: HZ_MAP },
      { route: '#/memoria?vista=resumen', target: '#hz-filters [name="metrica"]', ensure: hzResumen, title: 'Qué se colorea', text: '«Mostrar» cambia la medida del mapa: años con daños, grandes Niños que lo golpearon, cuántos más lugares con daños en años de Niño, fallecidos…',
        demo: [{ select: '#hz-filters [name="metrica"]', value: 'razon', say: 'Ahora: cuántos más lugares con daños hubo en temporadas con Niño.', target: HZ_MAP, keep: '#hz-filters [name="metrica"]', pause: 1400 }],
        after: HZ_MAP },
      { route: '#/memoria?vista=resumen', target: '.hz-f-lvl', ensure: hzResumen, title: 'Nivel', text: 'El mapa se puede ver por departamento, provincia o distrito.',
        demo: [{ click: '[data-nivel="departamento"]', say: 'Por departamento.', target: HZ_MAP, keep: '.hz-f-lvl', pause: 1200 }],
        after: HZ_MAP },
      { route: '#/memoria?vista=resumen', target: HZ_MAP, ensure: [...hzResumen, pressed('[data-nivel="departamento"]', '#hz-filters')], title: 'La ficha de un área', text: 'Toque un área del mapa (o elíjala en un ranking o en «Buscar lugar») para abrir su ficha: frecuencia, peligros, temporadas y sus peores registros.',
        demo: [{ click: `${HZ_MAP} [data-code="20"]`, say: 'Se abre la ficha de Piura.', ready: '#hz-side .hz-prof', target: '#hz-side', pause: 600 }],
        after: '#hz-side' },
      { route: '#/memoria?vista=resumen', target: '#hz-side', ensure: [...hzResumen, pressed('[data-nivel="departamento"]', '#hz-filters'), hzPiura], title: 'Volver a todo el Perú', text: 'La ficha se cierra con su ×. «Ver todo el Perú», debajo del mapa, aleja el mapa; «Quitar filtros» limpia todo.',
        demo: [{ click: '.hz-zoomout, #hz-side .hz-prof-top .icon-btn', say: 'De vuelta al mapa de todo el Perú.', target: HZ_MAP }] },
      { route: '#/memoria?vista=resumen', target: '#hz-q', ensure: hzResumen, title: 'Buscar lugar', text: 'Escriba un distrito, una provincia o un departamento y elíjalo de la lista: se abre su ficha y el mapa se acerca.' },
      { route: '#/memoria?vista=resumen', target: '.hz-views', ensure: hzResumen, title: 'Detalle: cuencas', text: 'Los registros por cuenca hidrográfica de la ANA, con los ríos nombrados encima. Toque una cuenca o un río para ver su ficha.',
        demo: [{ click: '.hz-views [data-vista="cuencas"]', say: 'Se abre la vista de cuencas.', ready: '.hz-svg.hz-det', target: '.hz-svg.hz-det', keep: '.hz-views', pause: 900 }],
        after: '.hz-svg.hz-det' },
      { route: '#/memoria?vista=resumen', target: '.hz-side', ensure: [hzView('cuencas'), ...hzClean], title: 'Las cuencas con más daños', text: 'La lista ordena las cuencas según la medida elegida en «Colorear por». Cada nombre abre su ficha y acerca el mapa.',
        demo: [{ click: '.hz-side [data-cuenca]:not([data-cuenca=""])', say: 'Se abre la ficha de la primera cuenca de la lista.', ready: '.hz-side .hz-prof', target: '.hz-svg.hz-det', keep: '.hz-side', pause: 1200 }],
        after: '.hz-side' },
      { route: '#/memoria?vista=resumen', target: '.hz-views', ensure: [hzView('cuencas'), ...hzClean], title: 'Detalle: ríos y lugares', text: 'Los registros que traen su propio punto: el de campo de la fuente, el centro poblado o el río que nombran. Lejos se agrupan en hexágonos.',
        demo: [{ click: '.hz-views [data-vista="puntos"]', say: 'Se abre la vista de ríos y lugares.', ready: '.hz-svg.hz-det', target: '.hz-svg.hz-det', keep: '.hz-views', pause: 1200 }],
        after: '.hz-svg.hz-det' },
      { route: '#/memoria?vista=resumen', target: '.hz-views', ensure: [hzView('puntos'), ...hzClean], title: 'Detalle: daños y pobreza', text: 'Un mapa bivariado: dónde coinciden los daños frecuentes y la pobreza. Toque una casilla de la leyenda para ver esos distritos.',
        demo: [
          { click: '.hz-views [data-vista="riesgo"]', say: 'Se abre la vista de daños y pobreza.', ready: '.hz-bv-grid', target: '.hz-svg.hz-det', keep: '.hz-views', pause: 900 },
          { click: '[data-celda="22"]', say: 'Casilla de arriba a la derecha: daños frecuentes y pobreza alta.', ready: '.hz-side .hz-prof', target: '.hz-bv', keep: '.hz-side', pause: 1200 },
        ],
        after: '.hz-side' },
      { route: '#/memoria?vista=resumen', target: '[aria-labelledby="hz-tl-h"]', ensure: hzResumen, title: 'Temporada por temporada', text: 'Cuántos lugares tuvieron daños en cada temporada de lluvias. La franja rosada marca los Niños costeros.' },
      { route: '#/memoria?vista=resumen', target: '[aria-labelledby="hz-great-h"] .hz-sms', ensure: hzResumen, title: 'Los grandes Niños', text: 'Un mapa por cada gran Niño, uno al lado del otro, con la misma escala, y su tabla de daños reportados.' },
      { route: '#/memoria?vista=resumen', target: '[aria-labelledby="hz-val-h"] .section-head', ensure: hzResumen, title: '¿La historia anticipa?', text: 'Se probó con 2016-2025: qué tan bien la frecuencia de 1970-2015 ordenó los lugares con daños después. Léalo antes de usar las cifras.' },
      { route: '#/memoria?vista=resumen', target: '#hz-m-h', ensure: hzResumen, title: 'Fuentes y descargas', text: 'De dónde sale cada registro, cómo se ubicó, sus límites y el catálogo completo para descargar.' },
    ],
  },
  {
    id: 'noticias', tab: 'noticias', next: 'datos', title: 'Noticias', desc: 'El mapa de avisos oficiales y las noticias por departamento.',
    steps: [
      { route: '#/noticias?tab=oficial&vista=resumen', target: `${AM} .amap-head`, ensure: [amView('resumen'), amClean, newsTab('oficial')], title: 'Mapa de avisos oficiales', text: 'Los avisos vigentes y próximos del SENAMHI, el INDECI, el IGP y la DHN. El observatorio no asigna niveles: son los de cada institución.' },
      { route: '#/noticias?tab=oficial&vista=resumen', target: '.amap-mapbox', ensure: [amView('resumen'), amClean, newsTab('oficial')], title: 'Cada departamento', text: 'El color dice el nivel más alto vigente. Pase el puntero para ver sus avisos; tóquelo para filtrar la lista de abajo.',
        avoid: ['.amap-tip:not([hidden])'],
        demo: [
          { hover: amDepShape, say: 'El tooltip lista sus avisos.', pause: 1600 },
          { click: amDepShape, say: 'Al tocarlo, se filtran los avisos y las noticias de ese departamento.', pause: 1200 },
        ] },
      { route: '#/noticias?tab=oficial&vista=resumen', target: `${AM} .amap-filters`, ensure: [amView('resumen'), newsTab('oficial')], title: 'Filtros del mapa', text: 'Momento (vigentes, próximos o pasados), nivel y antigüedad. «Quitar filtros» vuelve a todos.',
        demo: [{ click: `${AM} [data-f="fase"][data-v="ahora"]`, say: 'Solo los avisos vigentes ahora.', pause: 1200 }, { click: `${AM} .amap-filters [data-clear]`, say: 'Y de vuelta a todos.' }] },
      { route: '#/noticias?tab=oficial&vista=resumen', target: '.amap-views', ensure: [amView('resumen'), amClean, newsTab('oficial')], title: 'Detalle: avisos por cuenca', text: 'Los avisos repartidos por cuenca hidrográfica y los distritos en aviso con su historia de desastres.',
        demo: [
          { click: '.amap-views [data-vista="cuencas"]', say: 'Vista por cuenca.', ready: '.amap-grid-det .amap-mapbox svg', target: '.amap-mapbox', keep: '.amap-views', pause: 1400 },
          { click: '.amap-views [data-vista="distritos"]', say: 'Distritos en aviso con su memoria de desastres.', ready: '.amap-grid-det .amap-mapbox svg', target: '.amap-mapbox', keep: '.amap-views', pause: 1400 },
          { click: '.amap-views [data-vista="resumen"]', say: 'Y de vuelta al resumen.', target: '.amap-views' },
        ] },
      { route: '#/noticias?tab=oficial&vista=resumen', target: '[data-tour-id="news-tabs"]', ensure: [amView('resumen'), newsTab('oficial')], title: 'Novedades', text: 'Lo último de cada fuente oficial, las noticias del Perú y las del mundo.',
        demo: [{ click: '[data-tab="peru"]', say: 'Las noticias del Perú.', ready: '.news-filters', pause: 600 }] },
      { route: '#/noticias?tab=peru', target: '.news-filters', ensure: [newsTab('peru')], title: 'Filtrar noticias', text: 'Por tipo de medio, departamento y peligro. Cada filtro dice cuántas noticias deja.',
        demo: [{ click: '.news-filters [data-kind="radiotv"]', say: 'Solo radio y TV…', pause: 1100 }, { click: '.news-filters [data-kind=""]', say: '…o todas.' }] },
      { route: '#/noticias?tab=peru', target: '#news-body .feed-item', ensure: [newsTab('peru')], optional: true, title: 'Una noticia', text: 'Varios medios que cuentan lo mismo van juntos. Cada una enlaza a la nota original y a la copia que guardó el observatorio.' },
      { route: '#/noticias?tab=peru', target: '[data-tour-id="news-downloads"]', title: 'Descargas', text: 'El histórico de noticias en CSV y JSON, y el estado de cada feed en esta publicación.' },
    ],
  },
  {
    id: 'datos', tab: 'datos', next: 'metodologia', title: 'Datos', desc: 'Explorador de series y descargas.',
    steps: [
      { route: '#/datos', target: '[data-tour-id="explorer"] .row', ensure: [valued('#ex-sel', 'icen'), valued('#ex-from', ''), valued('#ex-to', '')], title: 'Explorador de series', text: 'Elija una serie y un rango de años: el gráfico y la tabla de abajo se actualizan, y «Descargar CSV» baja esa serie.',
        demo: [
          { select: '#ex-sel', value: 'roni', say: 'Serie: RONI.', ready: '#ex-chart svg', pause: 900 },
          { select: '#ex-from', value: '1997', say: 'Desde 1997…', pause: 500 },
          { select: '#ex-to', value: '1999', say: '…hasta 1999.', target: '#ex-chart', keep: '[data-tour-id="explorer"] .row', pause: 1200 },
        ],
        after: '#ex-chart' },
      { route: '#/datos', target: '#ex-desc', title: 'Qué es cada serie', text: 'La descripción, la unidad y el periodo base de la serie elegida.' },
      { route: '#/datos', target: '[data-tour-id="downloads"]', title: 'Descargas', text: 'Todas las series en CSV y JSON. Cada archivo lleva el identificador de la publicación para saber de qué corrida proviene.' },
    ],
  },
  {
    id: 'metodologia', tab: 'metodologia', next: 'asistente', title: 'Metodología', desc: 'Fuentes, incidencias y umbrales.',
    steps: [
      { route: '#/metodologia', target: '[data-tour-id="sources-health"]', title: 'Estado de las fuentes', text: 'Cada fuente dice si se obtuvo directamente, de una copia de archivo o si se mantuvo el último dato válido, con su fecha.' },
      { route: '#/metodologia', target: '[data-tour-id="incidents"]', title: 'Incidencias', text: 'Lo que falló o cambió en la última corrida. También se registran como issues en GitHub y se cierran solas.' },
      { route: '#/metodologia', target: '[data-tour-id="thresholds"]', title: 'Umbrales', text: 'Todas las tablas de umbrales que se usan, con su fuente y versión.' },
      { route: '#/metodologia', target: '[data-tour-id="architecture"]', title: 'Cómo funciona', text: 'El recorrido de los datos: de cada fuente a esta página, cada día.' },
    ],
  },
  {
    id: 'asistente', tab: 'asistente', next: null, title: 'Asistente', desc: 'Preguntas sobre los datos, con evidencia.',
    steps: [
      { route: '#/asistente', target: '#qa-form', title: 'Pregunte', text: 'Responde con los datos de la publicación vigente y cita su evidencia. No usa IA generativa ni emite alertas o pronósticos.',
        demo: [{ type: '#qa-in', text: '¿Cuál es el último ICEN?', submit: true, say: 'Se escribe una pregunta y se envía.', ready: '#qa-log .qa-a', target: '#qa-log .qa-a:last-child', keep: '#qa-form', pause: 600 }],
        after: '#qa-log .qa-a:last-child' },
      { route: '#/asistente', target: '[data-tour-id="assistant-suggest"]', title: 'Preguntas sugeridas', text: 'Toque una para preguntarla. La evidencia al pie de cada respuesta dice la serie, el periodo y la publicación.' },
    ],
  },
];

export const tourForTab = (name) => TOURS.find((t) => t.tab === name) || null;
