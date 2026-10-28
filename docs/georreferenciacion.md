# Georreferenciación y consola de lugares

Cada noticia, aviso y alerta del observatorio dice **dónde** ocurre: país,
departamento, provincia y distrito, hasta donde la evidencia lo permite,
con una **confianza** y **cómo se obtuvo** cada lugar. Las ubicaciones
dudosas van a una cola de revisión en una consola con usuario y
contraseña; las correcciones quedan registradas y se aplican en cada
actualización diaria.

## El objeto `geo`

Cada nota (`news/items.jsonl`, `geo/items.json`) y cada aviso de
`feed.json` llevan:

```json
{
  "country": "PE",
  "scope": "local",
  "places": [
    {"code": "150107", "level": "distrito", "name": "Chaclacayo", "department": "Lima",
     "province": "Lima", "confidence": 0.9, "method": "texto",
     "evidence": "en el distrito de Chaclacayo", "rule": "nombre único"}
  ],
  "departments": ["15"],
  "suggested": [],
  "confidence": 0.9,
  "method": "texto",
  "review": {"action": "set", "rev": 2, "at": "2026-10-21T15:04:05Z"},
  "v": 2
}
```

- `code`: UBIGEO del INEI (2, 4 o 6 dígitos). El Callao es `07` y su
  provincia `0701`.
- `scope`: `local` (provincia o distrito), `regional` (hasta 3
  departamentos), `nacional` (todo el país o sin lugar específico) o
  `internacional`.
- `suggested`: lugares con confianza menor a 0,5. No se publican; la
  consola los muestra como sugerencia.
- `review`: solo si alguien de la consola corrigió o confirmó la nota.
- Los campos de antes (`departments`, `places`, `geoSource`) se siguen
  publicando, derivados de `geo`, para no romper el sitio ni los CSV.

## Métodos y confianza

| Método | De dónde sale | Confianza |
|---|---|---|
| `campo` | La fuente trae UBIGEO o «distrito de X, provincia de Y, departamento de Z» (SENAMHI, INDECI, FIRMS, DHN), o el PDF del COEN los lista (`documentos.py`, ver `mapa-alertas.md`) | 0,95–0,97 |
| `coordenadas` | Punto dentro de los límites del INDECI (sismos de USGS, focos de calor) | 0,95 distrito; 0,9 provincia o departamento; 0,75 en el mar |
| `texto` | El titular o el resumen nombran el lugar | 0,55–0,95 según la regla |
| `medio` | Un medio regional que no nombra lugar: su departamento | 0,5 (0,6 gobiernos regionales; 0,35 búsquedas de Google Noticias, que no se publica) |
| `correccion` | Una persona en la consola | 1,0 |
| `region` | Solo en el mapa de alertas: un aviso del SENAMHI sin PDF ni boletín del mismo aviso, por las regiones que nombra («sierra sur») | 0,6 (se marca «≈») |
| `anterior` | Notas guardadas antes de esta versión, sin pistas para volver a ubicarlas | 0,7 |

Se publica todo lugar con confianza ≥ 0,5. La consola pone en la cola de
revisión lo que tiene confianza < 0,8, sugerencias, el departamento del
medio, o noticias de impactos sin lugar.

### Reglas del texto (`python/enso/geo.py`)

- **Nivel explícito**: «distrito de», «provincia de», «región» deciden
  el nivel cuando un nombre existe en varios (Lampa, Pisco, Lima).
- **Enumeraciones**: «Pampas, Colcabamba y Huachocolpa (Huancavelica)»:
  el departamento entre paréntesis o tras guion respalda a toda la
  lista, aunque el último nombre no esté en el nomenclátor; si el nombre
  se repite después sin paréntesis, es el mismo lugar.
- **Contenedores**: «21 distritos de Arequipa», «distritos de Ayacucho,
  Huancavelica y Cusco» nombran departamentos, no sus capitales.
- **Referencias, no lugares**: «a 71 km al S de Camaná», «frente a las
  costas de Pisco», «al suroeste de Zorritos»: se afirma el departamento
  (o la provincia si está a 10 km o menos) con menos confianza.
- **No son lugares**: ríos, quebradas, calles, clubes, instituciones,
  personas («río Piura», «Alianza Lima», «Hospital Loayza»), y
  negaciones («fuera de Lima»). Pero «Hospital de Chosica» o «valle de
  Ica» sí ubican.
- **Homónimos extranjeros**: Jaén (España), Loreto (Hidalgo), Junín
  (Ecuador y Argentina), Cañete (Chile)… Se descartan por la lista de
  países y ciudades, por «Loreto, Hidalgo», por el nombre o el dominio
  del medio.
- **Alcance nacional**: si el texto habla del país, de «regiones» o de
  instituciones nacionales sin nombrar lugar, no se usa el departamento
  del medio.
- **Hitos y gentilicios**: «lago Titicaca» → Puno, «Cordillera Blanca» →
  Áncash, «limeños» → Lima.

## Coordenadas (`python/enso/limites.py`)

Límites administrativos vigentes del INDECI (GEOSINPAD, capas `SDE.DISTRITOS`,
`SDE.PROVINCIAS` y `SDE.DEPARTAMENTOS`: los 1 891 distritos con su UBIGEO, la
misma cartografía con la que el INDECI ubica los reportes del COEN y el SINPAD),
simplificados a unos 110 m (`python/enso/data/limites-ign.json.gz`, 1,4 MB; se
regenera con `python -m tools.build_limites`, que respeta el robots.txt del
servidor). Hasta octubre de 2026 se usaban los del IGN vía OCHA HDX
(`cod-ab-per`, límites de 2020, 1 873 distritos; `--zip` los sigue leyendo):
sobre 8 000 puntos al azar ambos dan el mismo distrito en el 98,8 %; la
diferencia son los distritos creados después de 2020 (0,9 %) y límites
interdepartamentales en controversia.

- **Incertidumbre del punto**: el epicentro preliminar de USGS se conoce
  con unos 10 km de error (5 km si lo revisó un sismólogo). Si el punto
  está más cerca que eso del límite del distrito, se afirma la
  provincia; si también está cerca del límite provincial, el
  departamento.
- **Mar y lago**: un sismo frente a la costa (al oeste o suroeste de un
  departamento costero, a menos de 100 km) se ubica en ese departamento
  con la distancia en la evidencia. En el lago Titicaca, del lado
  peruano, Puno. Puntos en Chile, Ecuador o Bolivia quedan sin lugar, salvo que la fuente los refiera al Perú («a 37 km al ESE
  de Cañaveral, Perú») y estén a 25 km o menos del límite: el departamento más cercano, con confianza 0,55
  («≈», va a revisión).
- **Distritos nuevos**: los límites del INDECI tienen todos los distritos del
  nomenclátor, también los creados después de 2020 (Putis, Unión Asháninka,
  Boquerón, Alto Trujillo…) y Mazamari y Pangoa por separado. Si el
  nomenclátor llegara a tener un distrito sin polígono (uno recién creado), en
  su provincia el distrito sale con confianza 0,75 y queda para revisión.

## Más fino que el distrito: centros poblados y cuencas (`python/enso/lugares.py`)

El objeto `geo` llega al distrito. Para ubicar un aviso o un registro dentro del distrito hay dos tablas más, que se
arman a mano (`python -m tools.build_lugares`, desde el geoportal de la IDEP de la PCM) y no en cada corrida:

- **Centros poblados** (`python/enso/data/lugares.json.gz`, 2,5 MB): 103 mil, con su nombre, su punto, su
  categoría, su código y su población. Juntan los del censo 2017 del INEI (`CENTROS_POBLADOS_DISPERSOS/0`), los del
  IGN (`CENTROS_POBLADOS/3`) y los de la SDOT (`CENTROS_POBLADOS_DISPERSOS/1`). Cada uno va al distrito en que cae
  su punto según los límites del INDECI; uno que cae en otra provincia que la de su código, o fuera del Perú, se
  descarta (858). Si el INEI y el IGN ubican el mismo código a más de 5 km (2 844), el lugar lleva un radio de 5 km.
- **Cuencas** (`python/enso/data/cuencas.json.gz`, 320 kB): las 231 unidades hidrográficas de la ANA (cuencas e
  intercuencas, metodología Pfafstetter, R.M. N° 033-2008-AG, `INSTITUCIONALES/ANA_WMS/7`), simplificadas a unos 220 m, con la parte
  de cada distrito que cae en cada una.

`lugares.candidates` saca del texto los nombres que suelen ir antes de un centro poblado («sector», «caserío»,
«anexo», «C.P.», «localidad de», «comunidad campesina», «A.H.») y `Lugares.find` los busca **solo dentro del
distrito** ya ubicado: así un nombre común (hay cientos de «San Juan») no lleva a otro lado. Un nombre que se repite
dentro del distrito no se elige. Las palabras de, del, la, los no cuentan. `localities` hace lo mismo con todo el
texto, para los reportes del COEN (en el campo «UBICACIÓN» de su tabla los nombres van pegados: se buscan entre los
del distrito, `documentos.table_localities`).

`basin_at(lat, lon)` da la cuenca de un punto; `district_basin(code)`, la del distrito si el 80 % o más de su área
está en una sola (1 588 de los 1 891).

Validación (`python/tests/test_lugares.py`): con 1 de cada 40 lugares, que cada uno cae a 1,15 km o menos de su
distrito; las cuencas no se superponen y cubren el país; las 8 estaciones hidrológicas del SENAMHI caen en la
cuenca que el SENAMHI les asigna; y, con los registros de la memoria de desastres cuyo punto de la fuente es bueno,
el centro poblado que nombran queda a una mediana de 0,34 km de ese punto (81 % a menos de 2 km, 93 % a menos de
5 km). Los volcanes van en el punto de su cumbre según el Global Volcanism Program del Smithsonian, que cae en la
provincia que nombra el IGP.

## Ríos, quebradas y lagunas (`python/enso/aguas.py`)

Muchos reportes no nombran un caserío sino el cauce: «crecida del río Chiguata», «huaico en la quebrada Pedregal»,
«desborde de la laguna…». Para esos hay una tercera tabla, `python/enso/data/aguas.json.gz` (700 kB), armada a mano
con `python -m tools.build_aguas` desde la Carta Nacional 1:100 000 del IGN en el geoportal de la IDEP
(`PERU_100K`, capas «Río Lineal», «Lago y Laguna» y «Toponimia»; su robots.txt responde 404, sin reglas):

- **47 mil nombres por distrito**: 38 mil ríos y quebradas, 8 800 lagunas, 540 nevados, 28 volcanes y 108 abras.
  Cada tramo con nombre se densifica (un punto cada 400 m) y cada punto va al distrito que lo contiene. Por distrito
  y nombre, el **punto** es el del cauce más cercano al centro de su tramo en el distrito (siempre sobre el agua), el
  **radio** es la distancia al punto más lejano del tramo y la **cuenca** es la de la ANA donde cae la mayor parte del
  tramo. Un río y una quebrada del mismo nombre en un distrito son un mismo curso (el IGN llama «Quebrada» al tramo de
  arriba). Una laguna en el límite de dos distritos queda en cada uno con la parte de su orilla que cae en él.
- **Los nombres de la Carta se corrigen** donde la errata cambia la clave: «¥» por «ñ» («Le¥a» → «Leña»), «R¡o»,
  comillas y signos sueltos, mayúsculas con tilde dentro de una palabra («GavilÁn»), palabras pegadas («RioTirutaña»),
  abreviaturas («Qda.», «Lag.»). Los nombres alternativos que trae la Carta («Río Chili (Sumbay)», «Río Salla o
  Cotacucho», «Volcán Yucamane (Ver Yucamani)») también se reconocen (`alias`).

`Aguas.find` busca un nombre **solo detrás de la palabra que dice qué es** («río», «quebrada», «qda.», «riachuelo»,
«laguna», «nevado», «volcán», «abra»…), solo en el distrito ya ubicado y solo con esa clase (una «laguna X» no es la
quebrada X). Reglas para no confundir:

- Un nombre que también es adjetivo («Seca», «Honda», «Grande», «Negra») solo cuenta con mayúscula en un texto que
  no está todo en mayúsculas, o en un campo de lugar: «la quebrada seca» describe, «la quebrada Seca» nombra.
- De varias palabras se toma el nombre más largo que existe; uno más corto solo si lo que sigue no puede ser parte
  del nombre: «río Santa Eulalia» no es el río Santa.
- Una lista («ríos Moche y Chicama») con un nombre que no está en el distrito no da punto: el lugar no es solo el
  tramo del otro.
- El nombre da **punto** solo si su radio es de 10 km o menos y menor que tres cuartos del radio del distrito; si no
  (un río que cruza el distrito de punta a punta), da solo la **cuenca**, si el 60 % o más del tramo está en una.
  Al radio se le suma un margen (2 km para un cauce, 1 km para una laguna, un nevado o un abra): el daño está cerca
  del cauce, no sobre él.
- Si la fuente también nombra un centro poblado, aunque sea la capital del distrito («inundación en Aucayacu por
  desborde del río Huallaga»), el lugar es ese y no el tramo del río.

Validación (`python/tests/test_aguas.py`): cada nombre es válido y su cuenca existe; 1 de cada 25 puntos cae en su
distrito; los casos de arriba; y, contra las fichas del SINPAD con punto de campo que nombran un río o una quebrada
con tramo corto (49), el punto del nombre queda a una mediana de 2,6 km del medido (la capital del distrito, a 11,5
km), el 73 % dentro del radio y el 84 % más cerca que la capital.

## Exactitud geográfica: cómo se verifica

`tests/test_geolocalizacion.py` contrasta todo con la lista oficial de distritos del INDECI
(`tests/geo/indeci-distritos.csv`):

- El nomenclátor (`ubigeo.json`) y los límites tienen exactamente los 1 891 distritos oficiales: Alto Trujillo
  (130112, Ley N° 31644) se agrega aunque la fuente del INEI aún no lo traiga, y Santa María de Huachipa, que
  esa fuente lista como distrito, es un centro poblado de Lurigancho (la Ley N° 30888 solo declara de interés su
  creación): se quita (`tools/build_ubigeo.py`, `NOT_DISTRICTS` y `NEW_DISTRICTS`).
- Cada grafía oficial («IHUAYLLO», «SAN PEDRO DE LARAOS», «HEROES ALBARRACIN») llega a su distrito.
- La capital de cada distrito, provincia y departamento cae dentro de su polígono (5 capitales a metros del
  borde se toleran así de cerca). Los 17 distritos sin coordenadas de su capital en la fuente reciben un punto
  interior de su polígono, marcado `"point": "interior"`.
- Los puntos del mapa de alertas caen en su provincia o distrito.
- **Homónimos**: «Huaico en el distrito de X (Departamento)», como titula el COEN, para los 1 891 distritos,
  y lo mismo con la provincia: el resultado es el distrito o algo que lo contiene, nunca otro lugar. Cuando el
  nombre se repite en el departamento (Santa Rosa en Puno, Sancos en Ayacucho, Huallanca en Áncash, San
  Antonio en Lima) sin provincia, queda el departamento. «(Lima)» acota al departamento, no a Lima
  Metropolitana. Dos excepciones documentadas en la prueba: Surco (Huarochirí) sin provincia y Buenos Aires
  (Picota), que no se ubica.

## Calidad medida

Conjuntos etiquetados a mano en `python/tests/geo/`, con notas reales de
los feeds: `gold-noticias` (370, desarrollo), `holdout-noticias` (200,
guardado aparte) y `review-tercera` (120, revisión de predicciones de una
muestra nueva). Métrica principal: **notas mal ubicadas** (al menos un
lugar que no corresponde) entre las ubicadas.

| Conjunto | Ubicador anterior | Primera pasada del nuevo | Ahora |
|---|---|---|---|
| Desarrollo (370) | 13,4 % mal ubicadas | — | 0 % (precisión departamental 1,0; exhaustividad distrital 0,98) |
| Guardado aparte (200) | 15,5 % | 5,8 % | 0 % |
| Tercera muestra (120) | — | 1,7 % (2 notas) | 0 % |

Las cifras de «ahora» están medidas sobre conjuntos que sirvieron para
corregir reglas generales; la estimación honesta de error sobre notas
nunca vistas es la de primera pasada: **entre 1 y 6 %**. Las pruebas
(`tests/test_geo.py`) fallan si la proporción de mal ubicadas supera el
2 % o la precisión departamental baja de 0,98. `geo/quality.json`
publica en cada corrida cuántas notas tienen lugar, con qué método y
cuántas esperan revisión.

```bash
cd python
python -m tools.geo_eval                                   # conjunto de desarrollo
python -m tools.geo_eval --gold tests/geo/holdout-noticias.jsonl --errors
```

## Consola de lugares

Dirección: `https://<sitio>/admin/` (no está enlazada desde el sitio y
pide a los buscadores no indexarla). Solo funciona en Cloudflare Pages,
porque usa una Pages Function (`functions/api/geo/[[path]].js`) y una
base D1.

- **Por revisar**: la cola de notas dudosas. **Todas**: buscador por
  título, medio o lugar, y filtro por departamento. **Corregidas** y
  **Registro de cambios** (ingresos y correcciones de todos).
- Por nota: **Confirmar** (la ubicación es correcta), **Corregir…**
  (departamento → provincia → distrito, o búsqueda por nombre; varios
  lugares si hace falta; nota opcional), **Nacional / sin lugar**, **No
  es del Perú**, **Deshacer corrección** e **Historial**.
- Las correcciones se guardan al instante en D1 y llegan al sitio en la
  siguiente actualización diaria: el pipeline lee
  `/api/geo/overrides` (pública, sin usuarios ni notas), vuelve a ubicar
  todo el histórico y aplica la última corrección de cada nota. Si la
  consola no responde, usa las de la publicación anterior
  (`data/geo/overrides.json`); una corrección nunca se pierde.
- Nada se borra: cada cambio es una fila nueva con usuario, hora,
  ubicación anterior y nota. Si dos personas corrigen la misma nota a la
  vez, la segunda recibe un aviso y ve el cambio de la primera.

### Puesta en marcha en Cloudflare (una sola vez)

El token del flujo diario (Cloudflare Pages · Edit) ya basta para
desplegar la Function. Lo demás se hace en el panel de Cloudflare, con
la cuenta del propietario:

1. **Crear la base**: *Storage & Databases → D1 SQL Database → Create*.
   Nombre: `enso-geo`. (Las tablas se crean solas en la primera
   solicitud.)
2. **Vincularla al sitio**: *Workers & Pages → enso-peru → Settings →
   Bindings → Add → D1 database*. Nombre de la variable: `GEO_DB`; base:
   `enso-geo`. Guardar (en *Production*; repetir en *Preview* si se usa).
3. **Cargar los usuarios**: *Workers & Pages → enso-peru → Settings →
   Variables and Secrets → Add*. Tipo *Secret*, nombre `GEO_USERS`, valor:
   el contenido de `GEO_USERS.json` (solo hashes; ver abajo). Guardar.
4. **Volver a desplegar** para que tomen efecto: *GitHub → Actions →
   observatory → Run workflow* (o esperar la corrida de las 23:37).
5. Abrir `https://enso-peru.pages.dev/admin/` e ingresar.

No hace falta `wrangler.toml` (si se agrega uno en la raíz, el vínculo
`GEO_DB` debe declararse ahí, porque ese archivo reemplaza la
configuración del panel). Si el sitio usa un dominio propio, el
pipeline toma la dirección de `SITE_URL`; la variable del repositorio
`GEO_OVERRIDES_URL` permite fijar otra.

### Cuentas

```bash
cd python
python -m tools.geo_users --out ~/consola-claves            # pablo (admin) + revisor01…revisor10
python -m tools.geo_users --out ~/consola-claves --keep ~/consola-claves/GEO_USERS.json --testers 15   # agregar
python -m tools.geo_users --out ~/consola-claves --keep ~/consola-claves/GEO_USERS.json --renew revisor03  # nueva clave
```

Escribe `GEO_USERS.json` (para el secreto, solo hashes PBKDF2-SHA256 con
5 000 iteraciones; ver Seguridad) y `contrasenas-consola-PRIVADO.csv` (para repartir;
no se guarda en ningún otro lado). Se niega a escribir dentro del
repositorio. Para **dar de baja** una cuenta, quitarla de
`GEO_USERS.json` y volver a cargar el secreto: sus sesiones dejan de
valer de inmediato.

### Seguridad

- Contraseñas aleatorias de 16 caracteres (~93 bits); en Cloudflare solo
  hay hashes con sal. Se usan 5 000 iteraciones de PBKDF2-SHA256 y no las
  600 000 que OWASP pide para claves elegidas por personas, porque el
  plan gratuito de Workers da 10 ms de CPU por solicitud. Medido en
  workerd (el motor de Cloudflare): 5 000 iteraciones ≈ 4 ms, 20 000 ≈
  18 ms, 100 000 ≈ 49 ms; la Function rechaza hashes de más de 8 000.
  Las iteraciones solo suman log2(n) bits (5 000 ≈ 12 bits, 600 000 ≈ 19):
  lo que protege es la entropía de la clave. Con el secreto filtrado, una
  RTX 4090 prueba ~1,8 millones de claves por segundo a 5 000 iteraciones
  (8,9 millones con 999 en hashcat 6.2.6, modo 10900) y necesitaría unos
  10^14 años para una clave de 93 bits. Por eso las claves las genera
  siempre `tools/geo_users.py` y nunca las elige una persona. El secreto
  admite 5 KB: unas 35 cuentas. Un usuario inexistente tarda lo mismo
  que una clave equivocada y recibe el mismo mensaje.
- Sesión de 12 horas en una cookie `__Host-` `HttpOnly`, `Secure`,
  `SameSite=Strict`; en D1 se guarda el SHA-256 del token, no el token.
- Bloqueo de 15 minutos tras 8 fallos por usuario o 30 por IP; tope de
  600 correcciones por hora y usuario. Un intento bloqueado no escribe
  nada y los nombres inexistentes no crean contadores, para que una
  avalancha de intentos no agote las escrituras diarias de D1. Riesgo que
  queda: muchos atacantes desde muchas IP podrían agotar las 100 000
  solicitudes diarias de Functions; eso apaga la consola hasta las 00:00
  UTC, pero no el sitio público (solo `/api/geo/*` invoca Functions, según
  el `_routes.json` que genera Cloudflare) ni las correcciones ya hechas
  (el pipeline usa las de la publicación anterior).
- Escrituras solo desde el mismo origen y con JSON (CSRF); códigos
  UBIGEO validados contra el nomenclátor publicado; cuerpos de más de
  16 KB rechazados.
- Respuestas `no-store`, `noindex`, sin marcos y con CSP estricta; la
  página de la consola no carga nada de terceros y muestra los títulos de
  los medios como texto, nunca como HTML.

### Consumo del plan gratuito

| Operación | Viajes a D1 | Filas leídas | Filas escritas |
|---|---|---|---|
| Ingreso correcto | 2 | 2 contadores + sesiones vencidas | ~5 (sesión, registro, limpieza) |
| Ingreso fallido | 2 | 2 | 2–3 |
| Ingreso bloqueado | 1 | 2 | 0 |
| Cada pedido con sesión | 1 | 1 | 0 |
| Corrección | 3 | 3 (sesión, revisión vigente, contador) | ~6 con índices |
| Lista vigente (consola y pipeline) | 1 | 1 por nota corregida | 0 |

La tabla `current` guarda la última corrección de cada nota, así nada
recorre el historial completo; el tope por hora es un contador, no un
`COUNT(*)`. Las tablas se crean solas la primera vez que una consulta no
las encuentra (no en cada arranque). Los límites gratuitos (5 M filas
leídas y 100 000 escritas por día) alcanzan para miles de correcciones
diarias. La consola descarga `geo/items.json` (~1,3 MB, ~0,4 MB
comprimido) una vez por sesión y luego lo revalida (304 si no cambió).

## Archivos

| Archivo | Qué hace |
|---|---|
| `python/enso/geo.py` | Nomenclátor, reglas del texto, `locate_item` y el objeto `geo` |
| `python/enso/limites.py` | Punto en polígono con incertidumbre, mar y lago |
| `python/enso/lugares.py` | Centros poblados y cuencas dentro del distrito |
| `python/enso/aguas.py`, `python/tools/build_aguas.py` | Ríos, quebradas, lagunas, nevados y abras dentro del distrito, y su regeneración desde la Carta Nacional del IGN |
| `python/tools/build_lugares.py`, `build_cuencas_mapa.py` | Regeneran los centros poblados, las cuencas y su trazo para los mapas (`public/assets/cuencas-mapa.json`) |
| `python/enso/geo_overrides.py` | Reubica el histórico, aplica correcciones y publica `geo/*.json` |
| `python/tools/geo_eval.py` | Mide la precisión sobre los conjuntos etiquetados |
| `python/tools/build_limites.py`, `build_ubigeo.py` | Regeneran los datos geográficos |
| `python/tools/geo_users.py` | Cuentas de la consola |
| `functions/_lib/geo-console.js` | API de la consola (sesiones, correcciones, auditoría) |
| `public/admin/` | Página de la consola |
| `python/tests/test_geo.py`, `test_geo_console.py`, `tests/js/` | Pruebas (incluye la API con D1 simulada y un recorrido en Chromium) |
