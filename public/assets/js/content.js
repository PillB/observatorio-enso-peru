// Contenido editorial del observatorio. Los textos científicos remiten a
// fuentes primarias (ver docs/metodologia.md). Los valores actuales nunca
// se escriben aquí: siempre provienen de la publicación de datos.

export const SITE = {
  name: 'Observatorio ENSO Perú',
  tagline: 'El Niño y La Niña, con datos abiertos y fuentes oficiales',
  repo: 'https://github.com/PillB/observatorio-enso-peru',
  issues: 'https://github.com/PillB/observatorio-enso-peru/issues',
};

export const DISCLAIMER =
  'Este observatorio no es un servicio oficial de alertas. Las declaraciones oficiales en el Perú las emite la Comisión Multisectorial ENFEN; ' +
  'para emergencias siga a INDECI, SENAMHI, CENEPRED y a su gobierno regional o local.';

/** Enlaces oficiales para quien necesita actuar. */
export const OFFICIAL_LINKS = [
  { name: 'ENFEN — Comunicados oficiales', url: 'https://enfen.imarpe.gob.pe/comunicados/', note: 'Estado del sistema de alerta ante El Niño Costero / La Niña Costera.' },
  { name: 'SENAMHI — Avisos meteorológicos', url: 'https://www.senamhi.gob.pe/?p=aviso-meteorologico', note: 'Lluvias intensas, temperaturas y avisos por región.' },
  { name: 'INDECI — Centro de Operaciones de Emergencia Nacional', url: 'https://www.gob.pe/indeci', note: 'Emergencias, recomendaciones y reportes de daños.' },
  { name: 'CENEPRED — Escenarios de riesgo', url: 'https://www.gob.pe/cenepred', note: 'Escenarios de riesgo por lluvias asociados a El Niño.' },
  { name: 'NOAA/CPC — Discusión diagnóstica ENSO', url: 'https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml', note: 'Estado ENSO de escala cuenca (en inglés).' },
];

/** Qué suele significar cada fase para el Perú. Redacción prudente, sin causalidad determinista. */
export const PERU_IMPACTS = {
  warm: [
    'Mar más cálido frente a la costa norte y centro: la anchoveta tiende a replegarse hacia el sur y a mayor profundidad, con efectos en la pesca y la acuicultura.',
    'Mayor probabilidad de lluvias intensas en la costa norte (Tumbes, Piura, Lambayeque) durante el verano, con riesgo de inundaciones, huaicos y daños a vías y cultivos.',
    'Temperaturas del aire más altas en la costa, con efectos en la salud (golpes de calor, dengue) y en la agricultura.',
    'En los Andes del sur, El Niño de escala cuenca suele asociarse a menos lluvia y riesgo de sequía; el efecto depende de cada evento.',
  ],
  cool: [
    'Mar más frío en la costa: suele favorecer la disponibilidad de anchoveta, aunque con cambios en su distribución.',
    'Temperaturas del aire más bajas en la costa y posibles heladas más intensas en zonas altoandinas.',
    'Lluvias escasas en la costa norte; en los Andes, el efecto en las lluvias varía según el evento.',
  ],
  neutral: [
    'Condiciones cercanas a lo normal en el mar peruano. Aun así, pueden ocurrir eventos locales de lluvia o calor no relacionados con El Niño.',
  ],
  source: 'Síntesis basada en ENFEN (comunicados oficiales) y en Yglesias-González et al. (2023), PLoS ONE 18(9):e0290767, doi:10.1371/journal.pone.0290767.',
};

/** Impactos documentados de eventos pasados, con su fuente. */
export const PAST_IMPACTS = [
  { start: '1982', text: 'El Niño extraordinario 1982–83: el PBI del Perú cayó alrededor de 10 %, cerca de la mitad de esa caída vinculada al clima (CAF).', source: 'Yglesias-González et al. (2023), PLoS ONE 18(9):e0290767' },
  { start: '1997', text: 'El Niño extraordinario 1997–98: la actividad pesquera cayó 35,6 % en 1998 (BCRP); lluvias e inundaciones afectaron gran parte de la costa norte.', source: 'Yglesias-González et al. (2023), PLoS ONE 18(9):e0290767' },
  { start: '2017', text: 'El Niño Costero 2017: 169 fallecidos, 18 desaparecidos, cerca de 1,9 millones de personas afectadas y unos 7 700 millones de dólares estimados para la reconstrucción; el caudal pico del río Piura fue cerca de 6 veces el normal.', source: 'Yglesias-González et al. (2023), PLoS ONE 18(9):e0290767' },
  { start: '2023', text: 'El Niño Costero 2023–24: ENFEN advirtió riesgo de inundaciones en las cuencas de Tumbes, Chira, Piura y Lambayeque y el repliegue de la anchoveta; se canceló la primera temporada de pesca de anchoveta de 2023.', source: 'ENFEN, Comunicado Oficial N° 04-2023; prensa especializada' },
];

export const GLOSSARY = [
  ['ENSO', 'El Niño–Oscilación del Sur: ciclo natural de calentamiento (El Niño) y enfriamiento (La Niña) del Pacífico ecuatorial, acoplado con la atmósfera.'],
  ['El Niño Costero', 'Calentamiento anómalo del mar frente a Ecuador y el Perú (región Niño 1+2). ENFEN lo identifica con el ICEN. Puede ocurrir sin El Niño en el Pacífico central, como en 2017.'],
  ['ICEN', 'Índice Costero El Niño: media móvil de tres meses de la anomalía de temperatura del mar en Niño 1+2 (ERSSTv5). Lo calcula y publica ENFEN.'],
  ['RONI', 'Índice Oceánico Relativo de El Niño: índice oficial de NOAA desde febrero de 2026. Resta al Niño 3.4 el calentamiento promedio de todo el trópico para aislar la señal ENSO.'],
  ['ONI', 'Índice Oceánico de El Niño: media de tres meses de la anomalía de Niño 3.4. Fue el índice principal de NOAA hasta 2026.'],
  ['Anomalía', 'Diferencia entre el valor observado y el promedio de un periodo de referencia (climatología), por ejemplo 1991–2020.'],
  ['TSM', 'Temperatura superficial del mar.'],
  ['Regiones Niño', 'Cajas del Pacífico ecuatorial usadas para vigilar ENSO: Niño 1+2 (costa de Ecuador y Perú), Niño 3, Niño 3.4 (centro) y Niño 4 (oeste).'],
  ['Vientos alisios', 'Vientos del este que soplan sobre el Pacífico ecuatorial. Cuando se debilitan o se invierten (viento del oeste), el agua cálida avanza hacia Sudamérica.'],
  ['Termoclina', 'Capa del océano donde la temperatura baja rápidamente con la profundidad. Se suele medir por la profundidad de la isoterma de 20 °C (D20). Una termoclina más profunda frente al Perú reduce el afloramiento de agua fría.'],
  ['Contenido de calor', 'Temperatura promedio de los 300 m superiores del océano. Su aumento suele anticipar el calentamiento en superficie.'],
  ['SOI', 'Índice de Oscilación del Sur: diferencia de presión atmosférica entre Tahití y Darwin. Valores negativos sostenidos acompañan a El Niño. Es un índice de escala cuenca: no existe un «SOI costero».'],
  ['Ondas Kelvin', 'Ondas oceánicas que cruzan el Pacífico ecuatorial de oeste a este en unos dos meses y profundizan la termoclina al llegar a la costa peruana.'],
  ['Señal operativa del equipo GRD', 'Semáforo interno de gestión del riesgo de desastres, calculado con la tabla de umbrales del equipo GRD. No es una alerta oficial.'],
];

/** Modos del tutorial. Cada paso apunta a un elemento con data-tour-id y,
 *  si hace falta, a una ruta. «text» puede ser función de los datos. */
export const TOUR_MODES = [
  {
    id: 'inicio', title: 'Inicio rápido', desc: 'Lo esencial en un minuto.',
    steps: [
      { route: '#/', target: 'official-status', title: 'Estados oficiales', text: 'Aquí ve lo que declaran ENFEN para la costa peruana y NOAA para el Pacífico, con la fecha del comunicado y la del próximo.' },
      { route: '#/', target: 'freshest', title: 'El dato más reciente', text: (d) => `Esta franja muestra la medición semanal más nueva${d?.weekly?.nino12 ? ` (semana del ${d.weekly.nino12.latest.date})` : ''}. Es una observación, no una declaración oficial.` },
      { route: '#/', target: 'indicators', title: 'Indicadores clave', text: 'Cada tarjeta indica el periodo al que corresponde el valor. Si un dato está vencido, se muestra «Dato actual no disponible».' },
      { route: '#/', target: 'grd', title: 'Señal operativa del equipo GRD', text: 'Semáforo interno calculado con la tabla de umbrales del equipo GRD. Se distingue siempre de los estados oficiales.' },
      { target: 'help-button', title: 'Ayuda y tutorial', text: 'Puede volver a este tutorial o elegir otro tema cuando quiera desde este botón.' },
    ],
  },
  {
    id: 'completo', title: 'Recorrido completo', desc: 'Todas las secciones del observatorio.',
    steps: [
      { route: '#/', target: 'official-status', title: 'Resumen', text: 'El resumen reúne los estados oficiales, el dato más reciente y los indicadores clave.' },
      { route: '#/costero', target: 'coastal-icen', title: 'El Niño Costero', text: 'El ICEN oficial de ENFEN y su clasificación, junto con los datos más recientes de Niño 1+2.' },
      { route: '#/pacifico', target: 'basin-roni', title: 'ENSO de escala cuenca', text: 'RONI y ONI de NOAA para el Pacífico central, que influye en el clima de todo el planeta.' },
      { route: '#/oceano', target: 'ocean-weekly', title: 'Océano y atmósfera', text: 'Temperatura del mar semanal y mensual, vientos alisios, termoclina y SOI.' },
      { route: '#/mapa', target: 'map', title: 'Mapa', text: 'Las regiones Niño con su anomalía semanal. Puede animar las últimas semanas.' },
      { route: '#/historia', target: 'events', title: 'Historia', text: 'Todos los eventos desde 1950 identificados con la definición operacional de ENFEN.' },
      { route: '#/datos', target: 'downloads', title: 'Datos y descargas', text: 'Tablas completas y archivos CSV de cada serie.' },
      { route: '#/metodologia', target: 'sources-health', title: 'Fuentes y vigencia', text: 'Estado de cada fuente en la última corrida diaria, con su canal y fecha.' },
      { route: '#/asistente', target: 'assistant', title: 'Asistente', text: 'Haga preguntas sobre los datos publicados; las respuestas citan su evidencia.' },
    ],
  },
  {
    id: 'costero', title: 'El Niño Costero', desc: 'ICEN, Niño 1+2 y el sistema de alerta de ENFEN.',
    steps: [
      { route: '#/costero', target: 'coastal-status', title: 'Estado de ENFEN', text: 'ENFEN declara «Vigilancia» cuando es más probable que ocurra un evento a que no ocurra, y «Alerta» cuando el evento ya comenzó o se espera que se consolide.' },
      { route: '#/costero', target: 'coastal-icen', title: 'ICEN', text: 'El ICEN es la media de tres meses de Niño 1+2. Por ser centrado, el último valor oficial va unos dos meses detrás.' },
      { route: '#/costero', target: 'coastal-scale', title: 'Categorías', text: 'Las magnitudes de la Nota Técnica ENFEN 01-2024. Un evento requiere al menos tres meses consecutivos en condición cálida o fría.' },
      { route: '#/costero', target: 'coastal-recent', title: 'Datos más recientes', text: 'Niño 1+2 semanal y mensual llegan antes que el ICEN y permiten anticipar su tendencia, sin reemplazarlo.' },
    ],
  },
  {
    id: 'cuenca', title: 'ENSO de escala cuenca', desc: 'RONI, ONI y Niño 3.4.',
    steps: [
      { route: '#/pacifico', target: 'basin-status', title: 'Estado de NOAA', text: 'NOAA publica su discusión el segundo jueves de cada mes con un estado: Vigilancia, Advertencia o No activo.' },
      { route: '#/pacifico', target: 'basin-roni', title: 'RONI y ONI', text: 'Desde febrero de 2026 el RONI es el índice oficial de NOAA. Umbral: ±0,5 °C.' },
      { route: '#/pacifico', target: 'basin-regions', title: 'Regiones', text: 'Niño 3, 3.4 y 4 muestran cómo se extiende el calentamiento a lo largo del ecuador.' },
    ],
  },
  { id: 'tsm', title: 'Temperatura superficial del mar', desc: 'Datos semanales y mensuales.', steps: [
    { route: '#/oceano', target: 'ocean-weekly', title: 'TSM semanal', text: 'Valores semanales de NOAA (OISST v2.1), centrados en el miércoles y publicados los lunes.' },
    { route: '#/oceano', target: 'ocean-monthly', title: 'TSM mensual', text: 'Las series mensuales ERSSTv5 son las que usan los índices oficiales; OISST llega antes.' },
  ] },
  { id: 'vientos', title: 'Vientos', desc: 'Alisios a 850 hPa.', steps: [
    { route: '#/oceano', target: 'ocean-winds', title: 'Vientos alisios', text: 'Índices de NOAA en tres franjas del Pacífico. Positivo = viento del este (normal); negativo = flujo de oeste a este, típico de El Niño.' },
  ] },
  { id: 'termoclina', title: 'Termoclina', desc: 'Calor bajo la superficie.', steps: [
    { route: '#/oceano', target: 'ocean-heat', title: 'Contenido de calor', text: 'Temperatura media de los 300 m superiores. El observatorio no muestra D20 porque no hay una fuente pública verificada; se explica en Metodología.' },
  ] },
  { id: 'soi', title: 'SOI y presión', desc: 'La componente atmosférica.', steps: [
    { route: '#/oceano', target: 'ocean-soi', title: 'SOI', text: 'Diferencia de presión Tahití − Darwin. Se muestra en dos escalas: la estandarizada de NOAA y la de Troup (×10) que usa la tabla del equipo GRD.' },
  ] },
  { id: 'semaforos', title: 'Semáforos y estados oficiales', desc: 'Qué es oficial y qué no.', steps: [
    { route: '#/', target: 'official-status', title: 'Oficial', text: 'Solo ENFEN y NOAA emiten estados oficiales. El observatorio los reproduce con su fecha y enlace.' },
    { route: '#/', target: 'grd', title: 'Equipo GRD', text: 'El semáforo GRD es una interpretación operativa interna. Los intervalos que la tabla no define quedan «Sin clasificación», nunca en verde.' },
    { route: '#/metodologia', target: 'thresholds', title: 'Umbrales', text: 'Todas las tablas de umbrales, con su fuente y versión.' },
  ] },
  { id: 'mapas', title: 'Mapas y animaciones', desc: 'Regiones Niño en el mapa.', steps: [
    { route: '#/mapa', target: 'map', title: 'Mapa', text: 'Cada caja es una región Niño, coloreada con su anomalía semanal medida. No es un campo interpolado.' },
    { route: '#/mapa', target: 'map-controls', title: 'Animación', text: 'Reproduzca, pause o arrastre para ver la evolución semana a semana. Las flechas del teclado también funcionan.' },
  ] },
  { id: 'tablas', title: 'Tablas y descargas', desc: 'Datos completos.', steps: [
    { route: '#/datos', target: 'explorer', title: 'Explorador', text: 'Elija una serie para ver su tabla completa, filtrar por años y descargarla.' },
    { route: '#/datos', target: 'downloads', title: 'Descargas', text: 'Todos los CSV llevan el identificador de publicación para saber exactamente de qué corrida provienen.' },
  ] },
  { id: 'fuentes', title: 'Fuentes, vigencia y metodología', desc: 'De dónde viene cada dato.', steps: [
    { route: '#/metodologia', target: 'sources-health', title: 'Estado de fuentes', text: 'Cada fuente muestra si se obtuvo directamente, de una copia de archivo o si se mantuvo el último dato válido.' },
    { route: '#/metodologia', target: 'incidents', title: 'Incidencias', text: 'Lo que falló o cambió en la última corrida. Estas incidencias también se registran como issues en GitHub.' },
  ] },
  { id: 'asistente', title: 'Uso del asistente conversacional', desc: 'Preguntas sobre los datos.', steps: [
    { route: '#/asistente', target: 'assistant', title: 'Asistente', text: 'Responde con los datos de la publicación vigente y cita la evidencia. No emite alertas ni pronósticos propios.' },
    { route: '#/asistente', target: 'assistant-suggest', title: 'Pruebe', text: 'Por ejemplo: «¿Qué indica el valor más reciente de Niño 1+2 y cuál es su periodo de validez?»' },
  ] },
];
