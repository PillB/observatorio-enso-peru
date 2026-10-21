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
| `campo` | La fuente trae UBIGEO o «distrito de X, provincia de Y, departamento de Z» (SENAMHI, INDECI, FIRMS, DHN) | 0,95–0,97 |
| `coordenadas` | Punto dentro de los límites del IGN (sismos de USGS, focos de calor) | 0,95 distrito; 0,9 provincia o departamento; 0,75 en el mar |
| `texto` | El titular o el resumen nombran el lugar | 0,55–0,95 según la regla |
| `medio` | Un medio regional que no nombra lugar: su departamento | 0,5 (0,6 gobiernos regionales; 0,35 búsquedas de Google Noticias, que no se publica) |
| `correccion` | Una persona en la consola | 1,0 |
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

Límites del IGN (OCHA HDX `cod-ab-per`, CC BY-IGO), simplificados a unos
110 m (`python/enso/data/limites-ign.json.gz`, 1,5 MB; se regenera con
`python -m tools.build_limites`). Frente a los límites completos, 3 500
puntos al azar dan 99,9 % de acuerdo (4 diferencias, todas en bordes
departamentales a metros de distancia).

- **Incertidumbre del punto**: el epicentro preliminar de USGS se conoce
  con unos 10 km de error (5 km si lo revisó un sismólogo). Si el punto
  está más cerca que eso del límite del distrito, se afirma la
  provincia; si también está cerca del límite provincial, el
  departamento.
- **Mar y lago**: un sismo frente a la costa (al oeste o suroeste de un
  departamento costero, a menos de 100 km) se ubica en ese departamento
  con la distancia en la evidencia. En el lago Titicaca, del lado
  peruano, Puno. Puntos en Chile, Ecuador o Bolivia quedan sin lugar.
- **Distritos nuevos**: la fuente tiene los límites de 2020; en las
  provincias con distritos creados después (Huachipa en Lima, Kumpirushiato
  en La Convención…) el distrito sale con confianza 0,75 y queda para
  revisión. Mazamari y Pangoa, unidos en la fuente, quedan como
  provincia de Satipo.

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
| `python/enso/geo_overrides.py` | Reubica el histórico, aplica correcciones y publica `geo/*.json` |
| `python/tools/geo_eval.py` | Mide la precisión sobre los conjuntos etiquetados |
| `python/tools/build_limites.py`, `build_ubigeo.py` | Regeneran los datos geográficos |
| `python/tools/geo_users.py` | Cuentas de la consola |
| `functions/_lib/geo-console.js` | API de la consola (sesiones, correcciones, auditoría) |
| `public/admin/` | Página de la consola |
| `python/tests/test_geo.py`, `test_geo_console.py`, `tests/js/` | Pruebas (incluye la API con D1 simulada y un recorrido en Chromium) |
