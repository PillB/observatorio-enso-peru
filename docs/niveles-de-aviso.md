# Niveles de aviso: por qué un aviso queda sin nivel, y cuándo eso es un error

Revisión del 23 de noviembre de 2026. Quien probó el sitio vio muchos avisos «Sin nivel» («sin clasificar») en el mapa
de alertas y preguntó si de verdad no tenían nivel o si era un problema de lectura. Eran las dos cosas.

## Qué se midió

- Los 60 avisos publicados en `data/feed.json` el 23 de noviembre (44 «Sin nivel»).
- Los 1178 avisos de las 15 fuentes de peligros de los 60 días anteriores (`data/news/items.jsonl`), pasados por el
  lector de niveles con la copia de la tabla de avisos del SENAMHI del mismo día: 824 «Sin nivel».
- Los 17 PDF de avisos hidrológicos que difundió el COEN en ese periodo, bajados uno por uno, y la capa hidrológica
  del SENAMHI en GEOSINPAD como segunda fuente del mismo aviso.
- La escala que cada capa del SENAMHI declara en su `drawingInfo` (`.../SENAMHI/MapServer/<n>?f=json`), guardada en
  `python/tests/fixtures/sources/geosinpad-senamhi-renderers-20261123.json`.

## Qué estaba mal (causa raíz)

| Caso | Avisos | Causa | Corrección |
|---|---|---|---|
| Peligro de incendios forestales (capa FWI) | 9 de 9 | La capa da INTENSIDAD en palabras (BAJO, MODERADO, ALTO, MUY ALTO, EXTREMO); el lector buscaba «Nivel N» o un color | Escala `senamhi-fwi` tomada del `drawingInfo` de la capa |
| Avisos hidrológicos difundidos por el COEN | 17 de 17 | El umbral está en el PDF («…ubicándose en el umbral amarillo») y no se leía | `documentos.station_threshold`; si el PDF no se leyó, el nivel del mismo aviso en la capa del SENAMHI (cubre 4 de 17: la capa solo lista los vigentes). Las dos fuentes coinciden en los 4 casos comunes |
| Boletines de tsunami de la DHN «en evaluación» | 2 de 12 en 60 días (20 en la copia completa) | Otra redacción («se emite BOLETIN DE INFORMACIÓN - SE INTENSIFICA VIGILANCIA», «se comunica que se ha emitido…») | El lector acepta las dos; el aviso queda «En evaluación», no verde ni «sin nivel» |
| Cancelación de una alerta de tsunami | 2 en la copia completa | «Cancelación de alerta de tsunami» contenía «alerta de tsunami» y se mostraba como alerta vigente (naranja) | Nivel propio, rango 0 («Cancelación de la alerta de tsunami») |
| Avisos verdes (PAGER verde, «no genera tsunami») | 15 | El filtro y la matriz del mapa los contaban como «Sin nivel» | Filtro «Verde» aparte |
| Capa de lluvias con otro vocabulario («Nivel IV») | simulado | El lector descartaba todo valor que no fuera «Nivel 2» a «Nivel 4» como si fuera el nivel 1: la capa desaparecía sin aviso | Solo se descarta el nivel 1 («Nivel 1», «Nivel I»); lo demás se publica y, si no se lee, avisa |
| El mismo nivel escrito de otra forma | simulado | Una expresión por forma: «EXTREMA», «Muy Alta», «alertas naranjas», «Nivel IV», «nivel: 3», «se encuentra en el umbral de color rojo», «ama-⏎rillo» en el PDF, un titular del COEN sin tildes quedaban sin nivel | `enso/textnorm.py` (abajo) |

## Leer el nivel con su forma, no con su grafía (`enso/textnorm.py`)

Cada lector de nivel trabaja sobre el texto plegado y toma la palabra del nivel contra el vocabulario de su escala:

1. **Plegado** (`fold`): NFKC, sin caracteres invisibles (guion blando, ancho cero), rayas y comillas tipográficas a
   ASCII, palabra partida por un guion al final de la línea del PDF unida, sin tildes, minúsculas, espacios simples.
2. **Raíz de flexión** (`stem`): un *light stemmer* del español (Savoy 2002; el `SpanishLightStemFilter` de
   Lucene) que quita solo género y número. No el Snowball: también quita derivación y juntaría «moderado» con
   «moderadamente». Desde 4 letras (Lucene: 5), para que «roja», «alta» y «baja» sean «rojo», «alto» y «bajo».
3. **Números** (`level_number`): «Nivel 4», «Nivel IV», «nivel: 4», «Nivel N° 4», «nivel cuatro». No «Nivel 5»,
   «nivel 10» ni «nivel 4.5».
4. **Errata** (`lookup`): un único término de la escala a distancia de edición 1 (Damerau) y de 5 letras o más
   («amarrillo»). Se publica con «≈» en el mapa, «lectura aproximada de …» en la ficha y la incidencia
   `alert-level-approx`. En el umbral del PDF no se acepta: el aviso queda pendiente y escala.

Las capas del SENAMHI publican la palabra de la escala («Nivel 4», «EXTREMO») aunque la fuente escriba «Nivel IV» o
«EXTREMA», y agrupan por ella; el enlace a la capa cita el valor de la fuente, que es el que su filtro encuentra.

Lo que no se tolera, a propósito: otro idioma («ORANGE»), otras palabras («Grado 4», «CATASTRÓFICO»), «muy extremo»,
un número fuera de la escala y una errata a una letra de dos términos. Esos casos son un vocabulario nuevo: abren
`alert-level-unread`.

Encontrado al probarlo: los boletines de la DHN citan al «Sistema Nacional de Alerta de Tsunamis». La regla vieja
lo esquivaba sin saberlo, porque pedía «tsunami» en singular. Con el plural aceptado, cada boletín informativo se volvía
«Alerta de tsunami». Ahora el nombre de la institución se quita antes de leer el estado (prueba con el boletín
28-2026-1).

## Lo que sí no tiene nivel, y cómo se dice ahora

Cada aviso sin nivel lleva `levelStatus` (`enso/severity.py`, `level_status`) con una razón, una etiqueta y una
explicación que el mapa muestra:

| Razón | Etiqueta | Cuándo | Avisos (60 días) |
|---|---|---|---|
| `no-aplica` | Reporte, sin nivel (o Detección, sin nivel) | Reportes de daños del COEN, detecciones de FIRMS: la institución no les asigna nivel | 653 |
| `sin-escala` | Sin escala de niveles | Avisos especiales de oleaje y viento de la DHN (describe la intensidad, no asigna niveles), mensajes «en este momento» del SENAMHI | 41 |
| `multinivel` | Varios niveles | Boletines de corto plazo del COEN: un mapa con zonas de nivel 2 a 4. Cada zona se ve con su nivel en la capa del SENAMHI del mismo aviso | 60 |
| `no-calculado` | Sin alerta PAGER | Sismos para los que USGS no publicó PAGER; la magnitud es una medida, no un nivel | 40 |
| `en-evaluacion` | En evaluación | La DHN intensifica la vigilancia y aún no dice si hay tsunami | 2 |
| `pendiente` | Nivel pendiente | El nivel está en un documento aún no leído (PDF del COEN, tabla del SENAMHI) | 1 |
| `no-leido` | Nivel no leído | La fuente asigna niveles y no se pudo leer: **abre una incidencia** | 1 (antes del arreglo del lector de la DHN) |
| `sin-regla` | Nivel no revisado | Una fuente de peligros nueva sin regla, o un boletín del COEN de un tipo que ninguna regla conoce: **abre una incidencia** | 0 |

Después del arreglo, de los 1178 avisos: 365 con nivel de color, 15 verdes y 798 sin nivel, todos con su razón.

## Cuándo avisa (incidencias)

`sourcefeed.audit_levels` corre en cada publicación y registra, una por fuente y razón:

- `alert-level-unread`: un aviso de una fuente que asigna niveles a todo lo que publica (`severity.LEVELED`: capas
  del SENAMHI, CENVUL, PTWC, boletines de tsunami de la DHN) llegó sin nivel leído; o un aviso que cita su número
  sigue «pendiente» más de 48 h (`PENDING_HOURS`).
- `alert-level-norule`: una fuente de peligros sin regla en `level_status`. Agregar una fuente obliga a decidir si
  trae niveles.
- `alert-level-conflict`: el PDF del COEN y la capa del SENAMHI dan otro umbral al mismo aviso hidrológico. El mapa
  muestra el del PDF y la ficha marca «≠» con el otro.

El mensaje dice cuántos avisos, los primeros cuatro con su enlace y su razón, y qué revisar. En el mapa esos avisos
figuran «Nivel no leído» con borde de aviso, nunca como verdes ni como «sin nivel».

## Simulación de deriva

`python -m tools.drift_sim` tiene tres mutaciones nuevas:

- `level-vocab` (debe terminar LOUD): el campo NIVEL, INTENSIDAD o COLOR_TEXT de una capa pasa a otro vocabulario
  («Grado 4», «CATASTROFICO», «ORANGE»).
- `level-forms` (debe conservar cada nivel, sin incidencia): el mismo campo escrito de otra forma («Nivel IV»,
  «nivel: 3», «EXTREMA», «MUY  ALTA», «Amarilla», «NARANJAS»). Solo cambian el enlace y el id, porque el filtro de
  la capa cita el valor de la fuente (entrada revisada en `ALLOWLIST`; `tests/test_textnorm.py` comprueba que no
  cambia nada más).
- `status-wording`: la DHN escribe el estado con otras palabras («se informa que…», «no se espera tsunami»).

`tests/test_niveles_de_aviso.py` y `tests/test_textnorm.py` las corren para las capas de quebradas, lluvias, FWI e
hidrológica y para la DHN.

## Qué hacer cuando llega una incidencia

1. Abrir la respuesta archivada de la fuente (`data/archive/feeds/` o la rama `data-archive`) y buscar el campo
   del nivel del aviso que cita la incidencia.
2. Si es un valor nuevo de la escala de la institución: agregarlo a `SCALES` con su orden, citando de dónde sale
   (el `drawingInfo` de la capa, el documento técnico), y una prueba con la respuesta real.
3. Si la institución cambió la redacción: ampliar el lector de esa fuente y guardar la respuesta como prueba.
4. Si el aviso de verdad no tiene nivel: agregar la regla en `level_status` con su razón, nunca un nivel inventado.

## Costos y límites (decisiones tomadas)

- **Una errata se lee, no se calla ni se adivina en silencio**: con distancia 1, ninguna palabra de una escala está a
  menos de 3 de otra (lo prueba `test_fuzzy_candidates_are_far_apart`), así que la errata no puede caer en el nivel
  equivocado. Costo: «rajo» (a 1 de «rojo», 4 letras) no se lee. Las palabras cortas no se aproximan porque una letra
  es un cuarto de la palabra.
- **El día que una capa cambia la grafía del nivel** («EXTREMO» a «EXTREMA»), el enlace del aviso cambia y el aviso
  puede figurar dos veces en el historial (id nuevo). El nivel y el titular no cambian.

- **Muy alto y extremo comparten el rango 3** (rojo) en la escala común del mapa: el mapa tiene tres colores de
  aviso para todas las instituciones; la etiqueta («Peligro extremo») los distingue y la ficha muestra el color
  morado de la capa. Agregar un cuarto rango solo para el FWI cambiaría la leyenda de todas las fuentes.
- **Los avisos de la DHN no se colorean por intensidad** («oleaje moderado», «brisa fresca»): la DHN no publica
  niveles de aviso; convertir su descripción en un color sería inventar una escala.
- **El boletín de corto plazo del COEN no toma un nivel único**: el nivel más alto pintaría de rojo provincias que
  están en amarillo. Su mapa por zonas es una imagen; el mismo aviso ya se dibuja por zonas desde la capa del
  SENAMHI.
- **La lectura del umbral en los PDF depende de la frase «ubicándose en el umbral …»** (17 de 17 PDF de octubre y
  noviembre de 2026). Si cambia, el aviso queda «pendiente» y a las 48 h abre `alert-level-unread`. Los PDF ya leídos
  antes de este cambio se vuelven a leer una vez (`documentos.READ_VERSION`).
- **Un aviso «pendiente» de Telegram sin número no escala**: los mensajes del canal que empiezan «Aviso del SENAMHI»
  sin número se buscan en la tabla por fechas y palabras; si no aparecen, quedan pendientes sin incidencia, porque
  algunos son comunicados y no avisos (uno en 60 días).
