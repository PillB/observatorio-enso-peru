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
| Capa de lluvias con otro vocabulario («Nivel IV») | simulado | El lector descartaba todo valor que no fuera «Nivel 2» a «Nivel 4» como si fuera el nivel 1: la capa desaparecía sin aviso | Solo se descarta «Nivel 1»; lo demás se publica y, si no se lee, avisa |

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

`python -m tools.drift_sim` tiene dos mutaciones nuevas que deben terminar LOUD:

- `level-vocab`: el campo NIVEL, INTENSIDAD o COLOR_TEXT de una capa pasa a otro vocabulario («Nivel IV»,
  «EXTREMA», «ORANGE»).
- `status-wording`: la DHN escribe el estado con otras palabras («se informa que…», «no se espera tsunami»).

`tests/test_niveles_de_aviso.py` las corre para las capas de quebradas, lluvias, FWI e hidrológica y para la DHN.

## Qué hacer cuando llega una incidencia

1. Abrir la respuesta archivada de la fuente (`data/archive/feeds/` o la rama `data-archive`) y buscar el campo
   del nivel del aviso que cita la incidencia.
2. Si es un valor nuevo de la escala de la institución: agregarlo a `SCALES` con su orden, citando de dónde sale
   (el `drawingInfo` de la capa, el documento técnico), y una prueba con la respuesta real.
3. Si la institución cambió la redacción: ampliar el lector de esa fuente y guardar la respuesta como prueba.
4. Si el aviso de verdad no tiene nivel: agregar la regla en `level_status` con su razón, nunca un nivel inventado.

## Costos y límites (decisiones tomadas)

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
