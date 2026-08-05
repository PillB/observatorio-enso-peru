// Glosario climático del Observatorio ENSO Perú.
// Términos ENSO en español formal, comprensible internacionalmente y apto para Perú.
// Cada entrada incluye: término, categoría, definición, etimología/origen cuando aplica,
// y referencias a los indicadores del observatorio cuando corresponde.

export interface GlossaryEntry {
  id: string;
  term: string;
  category: "costero" | "cuenca" | "general" | "institucional" | "físico";
  shortDef: string;
  fullDef: string;
  related?: string[]; // ids de indicadores relacionados
  seeAlso?: string[]; // ids de otras entradas
}

export const GLOSSARY: GlossaryEntry[] = [
  {
    id: "enso",
    term: "ENSO",
    category: "general",
    shortDef: "El Niño–Oscilación del Sur: modo acoplado océano–atmósfera del Pacífico ecuatorial.",
    fullDef:
      "El Niño–Oscilación del Sur (ENSO, por sus siglas en inglés) es el modo dominante de " +
      "variabilidad climática interanual del Pacífico ecuatorial, resultante del acoplamiento " +
      "entre la temperatura superficial del mar y la circulación atmosférica (Oscilación del Sur). " +
      "Tiene tres fases: El Niño (fase cálida), La Niña (fase fría) y Neutral. Sus impactos se " +
      "extienden globalmente vía teleconexiones atmosféricas.",
    related: ["nino34", "roni", "soi"],
    seeAlso: ["el-nino", "la-nina", "el-nino-costero"],
  },
  {
    id: "el-nino",
    term: "El Niño",
    category: "cuenca",
    shortDef: "Fase cálida del ENSO de cuenca: anomalía de TSM en Niño 3.4 ≥ +0.5 °C sostenida.",
    fullDef:
      "El Niño es la fase cálida del ENSO de cuenca. Operacionalmente, NOAA/CPC lo declara cuando " +
      "el RONI (media móvil de 3 meses de la anomalía de TSM en Niño 3.4) alcanza o supera " +
      "+0.5 °C de forma sostenida. Se acompaña de un debilitamiento de los alisios, una " +
      "profundización de la termoclina en el Pacífico oriental y un SOI negativo.",
    related: ["nino34", "roni", "soi", "d20", "u850"],
    seeAlso: ["la-nina", "roni", "enso"],
  },
  {
    id: "la-nina",
    term: "La Niña",
    category: "cuenca",
    shortDef: "Fase fría del ENSO de cuenca: anomalía de TSM en Niño 3.4 ≤ −0.5 °C sostenida.",
    fullDef:
      "La Niña es la fase fría del ENSO de cuenca. Se declara cuando el RONI reaches o baja " +
      "−0.5 °C de forma sostenida. Se acompaña de un fortalecimiento de los alisios, una " +
      "somerización de la termoclina en el Pacífico oriental y un SOI positivo.",
    related: ["nino34", "roni", "soi", "d20", "u850"],
    seeAlso: ["el-nino", "roni", "enso"],
  },
  {
    id: "el-nino-costero",
    term: "El Niño Costero",
    category: "costero",
    shortDef: "Modalidad de ENSO que afecta el Pacífico oriental frente a Ecuador y el norte del Perú.",
    fullDef:
      "El Niño Costero es la modalidad de ENSO que se manifiesta en el Pacífico oriental frente a " +
      "Ecuador y el norte del Perú. ENFEN lo monitorea mediante el ICEN (media móvil de 3 meses " +
      "de la anomalía de TSM en Niño 1+2). Puede ocurrir junto con El Niño de cuenca o por " +
      "separado (caso paradigmático: 2017, El Niño Costero fuerte sin El Niño de cuenca).",
    related: ["nino12", "icen"],
    seeAlso: ["icen", "enso", "el-nino"],
  },
  {
    id: "icen",
    term: "ICEN",
    category: "costero",
    shortDef: "Índice Costero El Niño: media móvil de 3 meses de la anomalía de TSM en Niño 1+2.",
    fullDef:
      "El Índice Costero El Niño (ICEN) es el indicador operacional de ENFEN para el monitoreo de " +
      "El Niño Costero. Se calcula como la media móvil de 3 meses de las anomalías mensuales de " +
      "temperatura superficial del mar en la región Niño 1+2 (90–80°O, 10°S–0°). La activación de " +
      "un evento costero requiere persistencia (3 meses consecutivos sobre el umbral ±0.4 °C). " +
      "Las categorías de intensidad (débil, moderado, fuerte, muy fuerte) siguen la metodología ENFEN.",
    related: ["icen", "nino12"],
    seeAlso: ["nino12", "el-nino-costero", "enfen"],
  },
  {
    id: "roni",
    term: "RONI",
    category: "cuenca",
    shortDef: "Índice Oceánico Relativo del Niño: índice operacional actual de NOAA/CPC para ENSO de cuenca.",
    fullDef:
      "El Relative Oceanic Niño Index (RONI) es el índice operacional actual de NOAA/CPC para el " +
      "monitoreo y predicción de ENSO de cuenca. Es la media móvil de 3 meses de la anomalía de " +
      "TSM en Niño 3.4, con una línea base adaptativa de 30 años que reduce el sesgo por el " +
      "calentamiento secular. Reemplaza al ONI heredado (base fija 1971–2000). Umbral operacional: " +
      "±0.5 °C sostenido.",
    related: ["roni", "nino34"],
    seeAlso: ["oni", "nino34", "el-nino", "la-nina"],
  },
  {
    id: "oni",
    term: "ONI",
    category: "cuenca",
    shortDef: "Oceanic Niño Index: índice heredado de NOAA/CPC con base fija 1971–2000.",
    fullDef:
      "El Oceanic Niño Index (ONI) es el índice heredado de NOAA/CPC: media móvil de 3 meses de " +
      "la anomalía de TSM en Niño 3.4 con base fija 1971–2000 (ERSST v5). Ha sido reemplazado " +
      "operacionalmente por el RONI, que usa una línea base adaptativa. El observatorio prioriza " +
      "el RONI como índice vigente y no hard-codea el ONI obsoleto.",
    related: ["nino34"],
    seeAlso: ["roni", "nino34"],
  },
  {
    id: "soi",
    term: "SOI",
    category: "cuenca",
    shortDef: "Índice de Oscilación del Sur: anomalía estandarizada de la diferencia de presión Tahiti–Darwin.",
    fullDef:
      "El Índice de Oscilación del Sur (SOI) es la anomalía estandarizada de la diferencia de " +
      "presión superficial media entre Tahiti (Pacífico central-sur) y Darwin (norte de Australia). " +
      "Es la componente atmosférica del ENSO y se interpreta a escala de cuenca: SOI negativo " +
      "sostenido acompaña a El Niño; SOI positivo a La Niña. IMPORTANTE: no existe un «SOI costero» " +
      "con respaldo metodológico equivalente; el observatorio no lo define.",
    related: ["soi"],
    seeAlso: ["enso", "el-nino", "la-nina"],
  },
  {
    id: "nino12",
    term: "Niño 1+2",
    category: "costero",
    shortDef: "Región del Pacífico oriental: 0–10°S, 90–80°O (frente a Ecuador y norte del Perú).",
    fullDef:
      "Niño 1+2 es la región de monitoreo de TSM más oriental del Pacífico ecuatorial, definida " +
      "entre 0–10°S y 90–80°O. Abarca la costa de Ecuador y el norte del Perú. Es la región " +
      "usada por ENFEN para el cálculo del ICEN y, por tanto, el indicador primario de la " +
      "condición costera.",
    related: ["nino12", "icen"],
    seeAlso: ["nino34", "nino-regions", "icen"],
  },
  {
    id: "nino34",
    term: "Niño 3.4",
    category: "cuenca",
    shortDef: "Región del Pacífico central: 5°S–5°N, 170–120°O.",
    fullDef:
      "Niño 3.4 es la región de monitoreo de TSM del Pacífico central ecuatorial, definida entre " +
      "5°S–5°N y 170–120°O. Es la región usada por NOAA/CPC para el cálculo del RONI (y " +
      "anteriormente del ONI) y, por tanto, el indicador primario de la condición de cuenca.",
    related: ["nino34", "roni"],
    seeAlso: ["nino12", "nino-regions", "roni"],
  },
  {
    id: "nino-regions",
    term: "Regiones Niño",
    category: "general",
    shortDef: "Conjunto de regiones del Pacífico ecuatorial usadas para monitorear ENSO.",
    fullDef:
      "Las regiones Niño son cuatro áreas delimitadas del Pacífico ecuatorial: Niño 1+2 (0–10°S, " +
      "90–80°O), Niño 3 (5°S–5°N, 150–90°O), Niño 3.4 (5°S–5°N, 170–120°O) y Niño 4 (5°S–5°N, " +
      "160°E–150°O). Cada una captura una faceta distinta de la evolución de ENSO.",
    seeAlso: ["nino12", "nino34", "enso"],
  },
  {
    id: "d20",
    term: "D20",
    category: "físico",
    shortDef: "Profundidad de la isoterma de 20 °C: proxy de la profundidad de la termoclina.",
    fullDef:
      "D20 es la profundidad a la que la temperatura del océano alcanza 20 °C. En el Pacífico " +
      "ecuatorial, es un proxy de la profundidad de la termoclina. Una anomalía positiva significa " +
      "una termoclina más profunda (típica de El Niño de cuenca); una negativa, más somera " +
      "(típica de La Niña). Fuente: GODAS (NOAA/CPC).",
    related: ["d20"],
    seeAlso: ["termoclina", "el-nino", "la-nina"],
  },
  {
    id: "termoclina",
    term: "Termoclina",
    category: "físico",
    shortDef: "Capa de transición entre agua cálida superficial y agua fría profunda.",
    fullDef:
      "La termoclina es la capa del océano donde la temperatura disminuye rápidamente con la " +
      "profundidad, separando la capa superficial cálida (mezclada) del agua profunda fría. En el " +
      "Pacífico ecuatorial, su profundidad varía con ENSO: se profundiza en el oriente durante " +
      "El Niño y se someriza durante La Niña. D20 es un proxy de su profundidad.",
    related: ["d20"],
    seeAlso: ["d20", "el-nino", "la-nina"],
  },
  {
    id: "u850",
    term: "Viento zonal a 850 hPa",
    category: "físico",
    shortDef: "Componente zonal (este–oeste) del viento en bajo nivel (850 hPa).",
    fullDef:
      "El viento zonal a 850 hPa es la componente este–oeste del viento en bajo nivel (aprox. 1.5 km " +
      "de altitud). Convención: u > 0 significa flujo hacia el este (componente del oeste / westerly); " +
      "u < 0 significa flujo hacia el oeste (componente del este / easterly). Las anomalías del " +
      "oeste favorecen El Niño de cuenca al desplazar la masa de agua cálida hacia el este. Se " +
      "distingue del viento de superficie (10 m) y del valor observado vs anomalía.",
    related: ["u850"],
    seeAlso: ["alisios", "el-nino", "enso"],
  },
  {
    id: "alisios",
    term: "Alisios",
    category: "físico",
    shortDef: "Vientos del este que soplan en los trópicos hacia el ecuador.",
    fullDef:
      "Los vientos alisios son los vientos del este que soplan en los trópicos, desde los " +
      "subtrópicos hacia el ecuador. En el Pacífico ecuatorial, empujan el agua superficial cálida " +
      "hacia el oeste. Su fortalecimiento está asociado a La Niña; su debilitamiento, a El Niño. " +
      "No se etiqueta todo viento costero como «alisios»: se respeta la terminología de la fuente.",
    seeAlso: ["u850", "el-nino", "la-nina"],
  },
  {
    id: "enfen",
    term: "ENFEN",
    category: "institucional",
    shortDef: "Comisión Multisectorial encargada del Estudio Nacional del Fenómeno «El Niño» (Perú).",
    fullDef:
      "ENFEN es la Comisión Multisectorial encargada del Estudio Nacional del Fenómeno «El Niño» " +
      "del Perú. La integran SENAMHI, IMARPE, IGP, DHN, ANA y otras instituciones. Es la autoridad " +
      "oficial para la declaración de El Niño Costero y La Niña Costera en Perú, y publica el ICEN " +
      "y los estados de alerta costera.",
    related: ["icen"],
    seeAlso: ["icen", "el-nino-costero", "senamhi"],
  },
  {
    id: "senamhi",
    term: "SENAMHI",
    category: "institucional",
    shortDef: "Servicio Nacional de Meteorología e Hidrología del Perú.",
    fullDef:
      "El SENAMHI es el Servicio Nacional de Meteorología e Hidrología del Perú. Es miembro de " +
      "ENFEN y responsable del monitoreo meteorológico e hidrológico, incluyendo pronósticos " +
      "estacionales y evaluaciones de impacto. El observatorio deriva a SENAMHI las consultas " +
      "sobre impacto regional.",
    seeAlso: ["enfen", "igp", "indeci"],
  },
  {
    id: "igp",
    term: "IGP",
    category: "institucional",
    shortDef: "Instituto Geofísico del Perú.",
    fullDef:
      "El Instituto Geofísico del Perú (IGP) es una institución de investigación científica y " +
      "tecnológica. Participa en ENFEN y publica índices climáticos y pronósticos estacionales " +
      "para Perú. El observatorio usa sus productos para validación cruzada.",
    seeAlso: ["enfen", "senamhi"],
  },
  {
    id: "indeci",
    term: "INDECI",
    category: "institucional",
    shortDef: "Instituto Nacional de Defensa Civil del Perú.",
    fullDef:
      "El INDECI es el Instituto Nacional de Defensa Civil del Perú. Es la autoridad rectora en " +
      "gestión de riesgos de desastres. El observatorio NO es un servicio oficial de alerta; " +
      "deriva a INDECI las consultas sobre emergencias y gestión de desastres.",
    seeAlso: ["cenepred", "senamhi", "enfen"],
  },
  {
    id: "cenepred",
    term: "CENEPRED",
    category: "institucional",
    shortDef: "Centro Nacional de Estimación, Prevención y Reducción del Riesgo de Desastres (Perú).",
    fullDef:
      "El CENEPRED es el Centro Nacional de Estimación, Prevención y Reducción del Riesgo de " +
      "Desastres del Perú. Coordina la estimación y prevención del riesgo. El observatorio deriva " +
      "a CENEPRED las consultas sobre prevención y reducción de riesgos.",
    seeAlso: ["indeci", "senamhi"],
  },
  {
    id: "teleconexion",
    term: "Teleconexión",
    category: "general",
    shortDef: "Influencia climática a distancia ejercida por ENSO sobre otras regiones del planeta.",
    fullDef:
      "Una teleconexión es un patrón de correlación entre anomalías climáticas en regiones " +
      "distantes. ENSO genera teleconexiones globales vía ondas atmosféricas (p. ej., mayor " +
      "precipitación en la costa norte del Perú durante El Niño Costero, sequías en Australia " +
      "durante El Niño de cuenca).",
    seeAlso: ["enso", "el-nino", "la-nina"],
  },
  {
    id: "climatologia",
    term: "Climatología",
    category: "general",
    shortDef: "Valor promedio de una variable sobre un periodo base (típicamente 30 años).",
    fullDef:
      "La climatología es el valor promedio de una variable climática calculado sobre un periodo " +
      "base, típicamente de 30 años. La anomalía es la diferencia entre el valor observado y la " +
      "climatología. El periodo base afecta los valores de anomalía: NOAA/PSL usa 1981–2010; " +
      "RONI usa una base adaptativa de 30 años. El observatorio documenta la climatología de " +
      "cada indicador.",
    seeAlso: ["anomalia", "roni", "oni"],
  },
  {
    id: "anomalia",
    term: "Anomalía",
    category: "general",
    shortDef: "Diferencia entre un valor observado y su climatología.",
    fullDef:
      "Una anomalía es la diferencia entre un valor observado (p. ej., TSM de un mes) y el valor " +
      "climatológico correspondiente. Las anomalías permiten aislar la señal de variabilidad " +
      "(como ENSO) del ciclo estacional. Una anomalía positiva indica un valor por encima de lo " +
      "normal; negativa, por debajo.",
    seeAlso: ["climatologia", "enso"],
  },
  {
    id: "preliminar",
    term: "Dato preliminar",
    category: "general",
    shortDef: "Dato sujeto a revisión en publicaciones posteriores.",
    fullDef:
      "Un dato preliminar es un valor publicado de forma provisional que puede revisarse en " +
      "publicaciones posteriores a medida que se incorporan observaciones adicionales o se " +
      "mejoran los controles de calidad. El observatorio marca visiblemente los datos " +
      "preliminares y nunca los sustituye por valores fabricados.",
    seeAlso: ["climatologia", "anomalia"],
  },
];

export function searchGlossary(query: string): GlossaryEntry[] {
  const q = query.toLowerCase().trim();
  if (!q) return GLOSSARY;
  return GLOSSARY.filter((e) => {
    const haystack = `${e.term} ${e.shortDef} ${e.fullDef} ${e.category}`.toLowerCase();
    return haystack.includes(q);
  });
}

export const GLOSSARY_CATEGORIES: { id: GlossaryEntry["category"]; label: string }[] = [
  { id: "costero", label: "Costero" },
  { id: "cuenca", label: "Cuenca" },
  { id: "general", label: "General" },
  { id: "físico", label: "Físico / oceanográfico" },
  { id: "institucional", label: "Institucional" },
];
