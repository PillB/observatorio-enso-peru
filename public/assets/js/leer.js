// «Cómo leer esto»: una clave de lectura plegable junto a cada gráfico, mapa y tabla de todas las pestañas.
//
// Cada guía dice qué se ve, qué quiere decir cada color, cómo leer los valores y la escala (qué es normal, qué es
// alto, qué favorece a El Niño o a La Niña) y qué no hay que concluir. Las guías se cuelgan del id del título de la
// sección (o de un selector), así no hay que tocar cada vista: ``applyGuides`` las inserta cuando la vista se pinta y
// cada vez que cambia. El texto de aquí repite umbrales que ya publica el sitio (ICEN: Nota Técnica ENFEN 01-2024;
// RONI: ±0,5 °C; tabla del equipo GRD); no clasifica nada: eso lo hace el pipeline.

import { ICON } from './icons.js';

// Muestras de color: clase CSS (.lsw-…) → se ve igual que en el gráfico al que acompaña.
const WARM = ['warm', 'Rojo: más cálido que lo normal (anomalía positiva).'];
const COOL = ['cool', 'Azul: más frío que lo normal (anomalía negativa).'];
const HOVER = 'Pase el puntero o toque el gráfico para ver el valor de cada fecha; con el teclado, las flechas lo recorren. Los botones de años cambian el periodo y «Ver los valores en una tabla» los da en números.';
const ANOM = 'Una anomalía es la diferencia con el promedio de 1991–2020 para esa época del año: 0 es lo normal, no «sin temperatura».';
const NEITHER = 'Ni lo cálido ni lo frío es «bueno»: lo normal está cerca de cero, y los dos extremos traen impactos distintos.';

export const GUIDES = {
  // --- Todas las pestañas -----------------------------------------------------------------------------------------
  '.fresh-panel': {
    que: 'Dice si los datos de esta pestaña son los más recientes que publicó cada institución.',
    colores: [['ok', 'Al día: es el último que publicó la fuente.'], ['watch', 'Atrasado: ya debió llegar uno más nuevo, o se leyó de una copia.'], ['alert', 'Vencido: es demasiado antiguo y no se muestra como dato actual.'], ['na', 'Sin dato: la fuente no lo dio en esta actualización.']],
    ojo: 'Un dato mensual no está «atrasado» por tener semanas: cada fuente tiene su propio calendario. Abra el recuadro para ver la fecha de cada dato.',
  },
  // --- Resumen ----------------------------------------------------------------------------------------------------
  '[data-tour-id="official-status"]': {
    que: 'Lo que declaran las dos autoridades: el ENFEN para la costa del Perú y NOAA para el Pacífico central. Son declaraciones oficiales, no cálculos del observatorio.',
    colores: [['ok', 'Verde: no activo; no se espera un evento.'], ['watch', 'Ámbar: vigilancia; hay condiciones para que se forme.'], ['alert', 'Rojo: alerta o advertencia; el evento está en curso o se espera.'], ['na', 'Gris, «Dato actual no disponible»: no se pudo leer el comunicado vigente; se muestra cuál fue el último leído.']],
    valores: ['Los dos estados pueden no coincidir: El Niño Costero puede ocurrir con el Pacífico central neutral, y al revés.', '«Próximo» es la fecha en que la institución anunció su siguiente comunicado.'],
    ojo: 'El observatorio no emite alertas. Para decisiones use el documento oficial enlazado en cada tarjeta.',
  },
  'fresh-h': {
    que: 'La medición semanal más nueva de la temperatura del mar en las cuatro regiones Niño, de este (costa) a oeste.',
    colores: [WARM, COOL],
    valores: [ANOM, 'Niño 1+2 es la costa de Ecuador y el norte del Perú; Niño 3.4, el Pacífico central que usa NOAA para declarar El Niño.', 'La línea pequeña es la tendencia de las últimas semanas: lo que importa es si sube o baja, además del valor.'],
    ojo: 'Es una observación semanal: no se le aplican las categorías del ICEN ni equivale a una declaración oficial.',
  },
  'ind-h': {
    que: 'Ocho indicadores con su último valor, el periodo al que corresponde y su tendencia.',
    colores: [WARM, COOL, ['na', 'Gris, «Dato actual no disponible»: el dato venció; se dice cuál fue el último válido.']],
    valores: ['▲ y ▼ comparan con el periodo anterior: ▲ quiere decir que el número subió, no que la situación mejoró.', 'La etiqueta de la esquina (por ejemplo «Cálida fuerte») es la categoría oficial de ese índice, cuando existe.', 'Vientos y SOI se leen al revés que la temperatura: un valor negativo es el que favorece a El Niño.', 'Toque una tarjeta para ir a su pestaña, con el gráfico y la explicación.'],
    ojo: NEITHER,
  },
  'grd-h': {
    que: 'La tabla de umbrales del equipo de gestión del riesgo aplicada a los datos de hoy. Es una señal operativa interna, no un estado oficial.',
    colores: [['ok', 'Normal: el valor está dentro del rango normal de la tabla.'], ['watch', 'Amarilla: pasó el primer umbral.'], ['alert', 'Roja: pasó el umbral de activación.'], ['na', 'Sin clasificación: el valor cae en un intervalo que la tabla no define (no es verde). No disponible: el dato venció o falta.']],
    valores: ['La última columna cita los umbrales de la tabla para ese indicador, y debajo por qué quedó en ese nivel.', 'Cada fila dice de qué periodo es el dato y enlaza a su fuente.'],
    ojo: 'La política está en borrador. Un dato vencido nunca enciende un color.',
  },
  // --- El Niño Costero --------------------------------------------------------------------------------------------
  'ch-icen-h': {
    que: 'El ICEN, el índice con que el ENFEN clasifica la costa: la anomalía de la temperatura del mar en Niño 1+2 promediada en tres meses.',
    colores: [WARM, COOL],
    valores: ['Las líneas horizontales son los umbrales del ENFEN: de −0,7 a +0,5 °C es neutro; sobre +0,5 cálida débil; +1,3 moderada; +2,1 fuerte; +3,5 extraordinaria. Bajo −0,7, condición fría.', 'Un evento necesita tres meses seguidos en condición cálida o fría; un mes aislado no lo es.', 'El último punto va unos dos meses detrás de hoy: cada valor necesita el mes siguiente para calcularse.', HOVER],
    ojo: 'Más alto no es «mejor»: sobre +0,5 °C aumentan las lluvias en la costa norte en verano; valores muy negativos se asocian a déficit de lluvias y mar frío.',
  },
  'scale-h': {
    que: 'Las ocho categorías del ICEN, de la más fría a la más cálida, con la actual resaltada.',
    colores: [['warm', 'Punto rojo: condiciones cálidas (El Niño Costero).'], ['cool', 'Punto azul: condiciones frías (La Niña Costera).'], ['na', 'Punto gris: neutro.']],
    valores: ['Los intervalos están en grados de anomalía. El neutro no es simétrico: va de −0,7 a +0,5 °C.', 'La magnitud de un evento es la categoría más alta que alcanzó.'],
  },
  'ch-n12w-h': {
    que: 'La anomalía de cada semana en Niño 1+2 (costa). Llega cada lunes y adelanta hacia dónde irá el ICEN.',
    colores: [WARM, COOL],
    valores: [ANOM, 'Mire la tendencia de varias semanas, no una sola: el valor semanal salta más que el mensual.', HOVER],
    ojo: 'No se le aplican las categorías del ICEN: son promedios distintos.',
  },
  'pr-h': {
    que: 'La probabilidad que da el ENFEN a cada condición en los próximos meses, leída de su informe técnico.',
    valores: ['Cada mes suma 100 %. La condición con el número más alto es la más probable, no una certeza.', 'Cada valor enlaza al PDF, la página y el texto de donde se leyó.'],
    ojo: 'Es el pronóstico del ENFEN tal como lo publica; el observatorio no lo calcula ni lo ajusta.',
  },
  // --- Pacífico ---------------------------------------------------------------------------------------------------
  'ch-roni-h': {
    que: 'Los dos índices de NOAA para el Pacífico central: el RONI (el oficial desde 2026, relativo al resto del trópico) y el ONI.',
    colores: [WARM, COOL],
    valores: ['Las líneas de ±0,5 °C son el umbral: sobre +0,5, condiciones de El Niño; bajo −0,5, de La Niña; entre ambas, neutro.', 'NOAA habla de episodio cuando se mantiene cinco trimestres móviles seguidos.', 'Cada punto es un trimestre móvil (por ejemplo «ASO» es agosto a octubre).', HOVER],
    ojo: 'Mide el Pacífico central, no la costa del Perú. «Débil, moderado, fuerte» (cada 0,5 °C) es una convención de uso, no una categoría oficial.',
  },
  'ch-regions-h': {
    que: 'La anomalía mensual de la temperatura del mar en cada región Niño, de la costa (1+2) al oeste (4).',
    valores: [ANOM, 'Cada color es una región (vea la leyenda del gráfico). Si la línea de la costa sube antes que las demás, el calentamiento empezó frente al Perú.', HOVER],
    ojo: NEITHER,
  },
  'ch-cvb-h': {
    que: 'La costa (Niño 1+2) frente al Pacífico central (Niño 3.4) en el mismo gráfico.',
    valores: ['Cuando las dos líneas se separan, la costa y la cuenca viven condiciones distintas: es lo que distingue a un Niño Costero de un El Niño de todo el Pacífico.', ANOM, HOVER],
  },
  // --- Océano y atmósfera -----------------------------------------------------------------------------------------
  'ch-weekly-h': { que: 'La anomalía semanal de la temperatura del mar en las cuatro regiones Niño.', valores: [ANOM, 'Cada color es una región; la leyenda del gráfico dice cuál.', HOVER], ojo: 'Los valores semanales saltan más que los mensuales: mire la tendencia.' },
  'ch-monthly-h': { que: 'La anomalía mensual de la temperatura del mar en las cuatro regiones Niño.', valores: [ANOM, 'Sirve para comparar con los índices oficiales, que también son mensuales o trimestrales.', HOVER], ojo: NEITHER },
  'wind-h': {
    que: 'Los vientos alisios soplan de este a oeste sobre el Pacífico ecuatorial. Las tarjetas dan su anomalía a 850 hPa (unos 1500 m de altura).',
    colores: [['warm', 'Negativo: alisios más débiles que lo normal, o viento del oeste. Favorece el calentamiento (El Niño).'], ['cool', 'Positivo: alisios más fuertes que lo normal. Favorece el enfriamiento (La Niña).']],
    ojo: 'Aquí el signo se lee al revés que en la temperatura: lo negativo es lo que acompaña a El Niño.',
  },
  'ch-wind-h': {
    que: 'La anomalía mensual de los alisios en tres zonas del Pacífico ecuatorial.',
    valores: ['Bajo cero: alisios debilitados (favorece El Niño). Sobre cero: reforzados (favorece La Niña).', 'Un debilitamiento que dura varios meses pesa más que un mes aislado.', HOVER],
    ojo: 'Es un índice de altura (850 hPa) sobre el océano abierto, no el viento que se siente en la costa.',
  },
  'ch-heat-h': {
    que: 'El calor guardado en los primeros 300 m del Pacífico ecuatorial, como anomalía de temperatura.',
    colores: [WARM, COOL],
    valores: ['Positivo: hay más calor que lo normal bajo la superficie; suele llegar a la superficie semanas o meses después.', 'Por eso se mira como señal temprana: sube antes que la temperatura del mar y baja antes de que el evento termine.', HOVER],
  },
  'ch-d20-h': {
    que: 'La profundidad de la termoclina: la capa donde el agua pasa de cálida a fría, medida por la isoterma de 20 °C.',
    valores: ['Anomalía positiva: la termoclina está más profunda que lo normal, con más agua cálida encima (acompaña a El Niño). Negativa: más superficial, con agua fría cerca de la superficie.', 'La tabla del equipo GRD toma ±20 m como normal, 30 a 50 m como amarillo y más de 50 m como rojo.', HOVER],
    ojo: 'Lo calcula el observatorio con el análisis GODAS de NOAA; es una estimación por región, no una medición frente a un puerto.',
  },
  'ch-soi-h': {
    que: 'El Índice de Oscilación del Sur: la diferencia de presión entre Tahití y Darwin, en la escala Troup.',
    colores: [['warm', 'Negativo sostenido: favorece a El Niño.'], ['cool', 'Positivo sostenido: favorece a La Niña.']],
    valores: ['Entre −7 y +7 se considera normal; la tabla del equipo GRD marca rojo por debajo de −7.', 'Salta mucho de un mes a otro: cuenta lo que se mantiene varios meses.', HOVER],
    ojo: 'Mide toda la cuenca del Pacífico. No existe un «SOI costero».',
  },
  'coast-thermo-h': { que: 'Lo que el ENFEN y el IMARPE dicen en sus informes sobre la termoclina frente a Paita y Chicama.', valores: ['Son frases de los informes, con el enlace al documento, la página y el texto exacto. No son una serie de datos: no hay número que graficar.'], ojo: 'Si el informe es antiguo se dice su fecha; no se presenta como la condición de hoy.' },
  // --- Mapa -------------------------------------------------------------------------------------------------------
  'map-h': {
    que: 'La anomalía de la temperatura del mar de una semana, pintada sobre las cuatro regiones Niño.',
    colores: [WARM, COOL, ['na', 'Claro o blanco: cerca de lo normal.']],
    valores: ['El color de cada rectángulo es el valor de toda la región: no es un mapa de satélite punto por punto.', 'El control de reproducción recorre las semanas; la tabla de abajo da los mismos valores en números.'],
    ojo: 'Los rectángulos son las regiones con que se calculan los índices; lo que pasa entre ellos o pegado a la costa no se ve aquí.',
  },
  // --- Historia ---------------------------------------------------------------------------------------------------
  'ch-compare-h': {
    que: 'El evento actual junto a los grandes eventos del pasado, alineados por el mes en que empezaron.',
    valores: ['El eje horizontal son meses desde el inicio de cada evento, no fechas: así se compara la forma y la altura de cada uno.', 'Cada color es un evento (vea la leyenda). Si la línea actual va por encima de otra en el mismo mes, este evento va más intenso a esa altura.', HOVER],
    ojo: 'Parecerse a un evento pasado no predice cómo terminará este.',
  },
  'ev-h': {
    que: 'Todos los eventos El Niño y La Niña costeros del registro, identificados con la definición del ENFEN sobre el ICEN oficial.',
    colores: [['warm', 'Etiqueta roja: El Niño Costero (condición cálida).'], ['cool', 'Etiqueta azul: La Niña Costera (condición fría).']],
    valores: ['«ICEN máximo» es el valor más extremo del evento y «Magnitud» su categoría: débil, moderada, fuerte o extraordinaria.', '«Meses» es cuánto duró: un evento largo y moderado puede pesar tanto como uno corto y fuerte.'],
    ojo: 'La magnitud describe el mar, no los daños: estos dependen también de la época del año y de la preparación.',
  },
  // --- Memoria de desastres ---------------------------------------------------------------------------------------
  'hz-map-h': {
    que: 'Dónde hay registros de desastres en el catálogo, por departamento, provincia o distrito, según la medida elegida arriba del mapa.',
    valores: ['Más oscuro es más de lo que mide la medida elegida (registros, años con daños, personas afectadas…); la leyenda del mapa da los intervalos.', 'Gris o sin color: sin registros en las fuentes. No quiere decir que no haya pasado nada: quiere decir que nadie lo registró.', 'Pase el puntero por un área para ver sus cifras y tóquela para filtrar todo lo demás.'],
    ojo: 'Las áreas con más población y más prensa tienen más registros. Compare un lugar consigo mismo en el tiempo antes que con otro.',
  },
  'hz-tl-h': {
    que: 'Cuántos lugares distintos tuvieron daños en cada temporada de lluvias (de julio a junio).',
    colores: [['warm', 'Franja rosada: temporadas con El Niño Costero en el pico de lluvias.']],
    valores: ['Una barra alta en una franja rosada es un Niño que golpeó muchos lugares.', 'El salto desde 2016 es un cambio de fuente (el SINPAD registra muchas más emergencias), no un aumento real de esa magnitud.'],
    ojo: 'No compare barras de antes y después de 2016 entre sí.',
  },
  'hz-great-h': {
    que: 'Las provincias con al menos un registro en cada uno de los grandes Niños.',
    colores: [['alert', 'En color: la provincia tuvo registros en ese evento.'], ['na', 'En gris: sin registros en las fuentes de ese evento.']],
    valores: ['Solo dice si hubo registros, no cuántos: cada evento viene de fuentes distintas y no se pueden comparar cantidades.', 'Lo útil es qué provincias se repiten de un evento a otro: están en la lista de abajo.'],
  },
  'hz-rank-h': { que: 'Las provincias ordenadas por la cantidad de años en que tuvieron daños entre 1970 y 2015.', valores: ['Cuenta años, no eventos: una provincia con daños en 30 de 46 años los sufre casi todos los años.', 'La barra más larga es la provincia con daños más frecuentes, no necesariamente los más graves.'], ojo: 'Es frecuencia histórica, no un pronóstico.' },
  'hz-tbl-h': { que: 'Los registros del catálogo que cumplen los filtros del mapa, uno por fila.', valores: ['Las 13 primeras columnas son las del tablero del equipo de prevención. Una celda vacía quiere decir que la fuente no trae ese dato, no que sea cero.', 'El botón de descarga baja exactamente lo que se ve con los filtros puestos.'] },
  // --- Mi zona ----------------------------------------------------------------------------------------------------
  'zn-hoy': { que: 'Los avisos oficiales vigentes o próximos que tocan el lugar elegido.', colores: [['alert', 'Rojo: el nivel más alto que da la institución.'], ['orange', 'Naranja: nivel intermedio.'], ['watch', 'Amarillo: el primer nivel.'], ['na', 'Gris: la fuente no dio un nivel.']], ojo: 'Que no haya avisos no quiere decir que no haya peligro: abajo se dice qué fuentes respondieron hoy.' },
  'zn-rie': {
    que: 'El riesgo que el CENEPRED espera para este distrito por las lluvias del trimestre: uno por huaycos y deslizamientos y otro por inundaciones.',
    colores: [['alert', 'Muy alto.'], ['orange', 'Alto.'], ['watch', 'Medio.'], ['na', 'Bajo.']],
    valores: ['Las cifras (personas, viviendas, colegios, vías) son lo que hay en las áreas más susceptibles del distrito, no en todo el distrito.', 'Un cero con nivel alto quiere decir que no se ubicaron personas en esas áreas, no que no haya riesgo.'],
    ojo: 'Es el escenario del CENEPRED para ese trimestre; el observatorio solo lo muestra.',
  },
  'zn-est': {
    que: 'En qué meses del año se concentraron los registros de cada peligro en este lugar.',
    colores: [['seq', 'Más oscuro: más registros en ese mes. Cada fila se colorea respecto de su propio mes más alto.']],
    valores: ['Lea cada fila por separado: el color no compara un peligro con otro. Para eso está la columna «Total».', 'Una celda vacía quiere decir que no hay registros con ese mes, no que no pueda ocurrir.'],
    ojo: 'Dice cuándo pasó con más frecuencia, no cuándo volverá a pasar.',
  },
  // --- Noticias ---------------------------------------------------------------------------------------------------
  'amap-h': {
    que: 'Los avisos oficiales vigentes y próximos por departamento. El nivel es el que dio cada institución: el observatorio no asigna niveles.',
    colores: [['alert', 'Rojo: el nivel más alto de la institución.'], ['orange', 'Naranja: intermedio.'], ['watch', 'Amarillo: el primer nivel.'], ['na', 'Gris: aviso sin nivel en la fuente, o solo reportes y avisos pasados.']],
    valores: ['Cada departamento lleva el color de su aviso más alto. Pase el puntero para ver cuáles son y tóquelo para filtrar la lista de abajo.', 'Los filtros eligen el momento (vigentes, próximos, pasados), el nivel y la antigüedad.'],
    ojo: 'Un departamento sin color no está «a salvo»: puede que su fuente no haya respondido hoy. La línea bajo la lista dice cuáles se leyeron.',
  },
  // --- Boletín ----------------------------------------------------------------------------------------------------
  'bol-h': {
    que: 'Lo que cambió desde la edición anterior: avisos que empiezan, suben de nivel o terminan, por departamento.',
    colores: [['alert', 'Rojo.'], ['orange', 'Naranja.'], ['watch', 'Amarillo.'], ['na', 'Gris: sin nivel o sin avisos.']],
    valores: ['Los colores son los niveles que dio cada institución, con la misma leyenda que acompaña al mapa.', '«Qué se viene» lista lo que empieza en los próximos días; «más críticos», los departamentos con el nivel más alto.'],
    ojo: 'Es un resumen de avisos oficiales, no una alerta propia.',
  },
  // --- Datos y Metodología ----------------------------------------------------------------------------------------
  'ex-h': { que: 'Cualquier serie publicada, con su gráfico, su tabla y su descarga.', valores: ['Debajo del selector están la descripción de la serie, su unidad y el periodo base de la anomalía.', 'La tabla muestra primero lo más reciente; «prelim.» marca un valor que la fuente todavía puede corregir.', HOVER], ojo: 'Las series tienen frecuencias distintas (semanal, mensual, trimestral): compare solo las que comparten periodo.' },
  'sh-h': {
    que: 'Cada fuente que se consultó en la última actualización y cómo se obtuvo.',
    colores: [['ok', 'Verde, «Directa»: se bajó de la institución.'], ['watch', 'Ámbar: se usó una copia (otro recolector, Internet Archive) o se conservó el último dato válido.'], ['alert', 'Rojo, «Falló»: no se pudo obtener.']],
    valores: ['«Obtenido» es cuándo se bajó; «Frecuencia», cada cuánto publica la institución.'],
    ojo: 'Una fuente en ámbar sigue siendo el dato oficial; solo cambia el camino por el que llegó.',
  },
  'inc-h': { que: 'Lo que no salió normal en la última actualización.', colores: [['watch', 'Aviso: algo llegó tarde o por un camino de respaldo.'], ['alert', 'Error o crítico: una fuente falló o un dato no pasó la validación y no se publicó.']], ojo: 'Una incidencia no quiere decir que el sitio muestre un dato malo: lo que no pasa la validación no se publica.' },
};

/** Las guías en el orden en que se buscan: ids de título y selectores. */
const ENTRIES = Object.entries(GUIDES).map(([k, g]) => [/^[a-z][a-z0-9-]*$/i.test(k) ? `#${k}` : k, g, k]);

function guideEl(g, key) {
  const d = document.createElement('details');
  d.className = 'leer';
  d.dataset.leer = key;
  const s = document.createElement('summary');
  s.innerHTML = `${ICON.info}<span>Cómo leer esto</span>`;
  d.append(s);
  const body = document.createElement('div');
  body.className = 'leer-body';
  const p = (text, cls) => { const el = document.createElement('p'); if (cls) el.className = cls; el.textContent = text; return el; };
  body.append(p(g.que));
  if (g.colores?.length) {
    const ul = document.createElement('ul');
    ul.className = 'leer-colores';
    for (const [c, t] of g.colores) {
      const li = document.createElement('li');
      const sw = document.createElement('span');
      sw.className = `lsw lsw-${c}`;
      sw.setAttribute('aria-hidden', 'true');
      li.append(sw, t);
      ul.append(li);
    }
    body.append(ul);
  }
  if (g.valores?.length) {
    const ul = document.createElement('ul');
    ul.className = 'leer-valores';
    for (const t of g.valores) { const li = document.createElement('li'); li.textContent = t; ul.append(li); }
    body.append(ul);
  }
  if (g.ojo) { const o = p('', 'leer-ojo'); const b = document.createElement('strong'); b.textContent = 'Ojo: '; o.append(b, g.ojo); body.append(o); }
  d.append(body);
  return d;
}

/** Inserta las guías que falten en la vista pintada. Se puede llamar las veces que haga falta. */
export function applyGuides(root) {
  if (!root) return 0;
  let n = 0;
  for (const [sel, g, key] of ENTRIES) {
    let el;
    try { el = root.querySelector(sel); } catch { continue; }
    if (!el) continue;
    const isHeading = /^H[1-6]$/.test(el.tagName);
    const d = guideEl(g, key);
    if (el.tagName === 'DETAILS') {
      // Un recuadro plegable (el de vigencia): la guía va dentro, después de su resumen.
      if (el.querySelector(':scope > .leer')) continue;
      (el.querySelector(':scope > summary') || el.firstElementChild).after(d);
    } else if (!isHeading) {
      if (el.nextElementSibling?.classList.contains('leer')) continue;
      d.classList.add('leer-out');
      el.after(d);
    } else {
      const host = el.closest('section, .card') || el.parentElement;
      if ([...host.querySelectorAll('.leer')].some((x) => x.dataset.leer === key)) continue;
      const head = el.closest('.section-head') || el;
      // Después del título y de su párrafo de descripción, antes del gráfico.
      let after = head;
      while (after.nextElementSibling && after.nextElementSibling.matches('p.muted, p.chart-desc, p.small')) after = after.nextElementSibling;
      after.after(d);
    }
    n += 1;
  }
  return n;
}
