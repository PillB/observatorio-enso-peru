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
  ['ICEN', 'Índice Costero El Niño: media móvil de tres meses de la anomalía de temperatura del mar en Niño 1+2. Lo calcula y publica ENFEN.'],
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

