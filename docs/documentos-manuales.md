# Documentos que hay que bajar a mano

Algunos documentos oficiales no se pueden bajar con un programa: la réplica de la DHN responde con una
**verificación humana** a GitHub Actions, a n8n y a veces al equipo del Perú, y el portal del ENFEN no responde
fuera del Perú. El observatorio nunca intenta pasar esa verificación. Cuando el comunicado más reciente del
ENFEN o su informe técnico no llegan por ninguna ruta (portal, DHN, repositorio del IMARPE, recolector del Perú,
n8n, Internet Archive),
una persona los baja en su navegador y los sube en la **consola de documentos**.

## Cómo funciona

1. **El pipeline anota lo que falta** (`python/enso/manual.py`). Escribe `data/manual-needed.json` con cada
   documento pendiente: el motivo, los enlaces para abrirlo en un navegador (la página de descarga del portal y
   el PDF de la DHN) y las URL con que lo busca. Además deja la incidencia `manual-download-needed`
   (advertencia), que abre un issue en GitHub y se cierra sola cuando ya no falta nada.
2. **Una persona lo baja.** En la consola (`/admin/documentos.html`, con la cuenta de la consola de lugares)
   abre el enlace, pasa la verificación si aparece y guarda el PDF.
3. **Lo sube.** El navegador revisa el archivo antes de enviarlo: que sea un PDF (si es la página de la
   verificación guardada por error, lo dice), que esté completo (`%%EOF`) y que no pase de 25 MB. La persona
   confirma que es el documento indicado.
4. **La API lo guarda** (`functions/_lib/doc-uploads.js`) en la rama `data-manual`, con el formato de los
   recolectores (`enso-relay/1`, canal `relay-manual`), y pide una actualización del sitio
   (`repository_dispatch` `enso-refresh`): no hay que esperar a las 23:37.
5. **El pipeline lo valida** como cualquier otra copia. El comunicado tiene que ser el número buscado; el
   informe, del periodo del comunicado (fecha de corte) y con tablas que pasen las reglas. Si no lo es, no se
   publica, el documento sigue pendiente y la consola muestra el motivo («El PDF es el comunicado 17-2026, no el
   18-2026»). Si lo es, el sitio lo usa y la consola lo lista en «Leídos de una copia subida».

## Seguridad

- Solo suben las cuentas con un rol de `DOCS_UPLOAD_ROLES` (por omisión, solo `admin`). Los revisores de
  lugares ven la lista pero no suben.
- Solo se aceptan documentos que el pipeline pidió (`manual-needed.json`): nadie puede guardar un archivo bajo
  una URL cualquiera. Las URL salen de la lista, no de quien sube.
- Mismo origen y JSON (protección contra CSRF), sesión de la consola, 10 subidas por hora y por cuenta, y cada
  subida queda en la tabla `uploads` y en el registro de la consola (`documento-subido`) con usuario y hora.
- El token de GitHub vive solo en Cloudflare y es de grano fino: **Contents: Read and write** en este
  repositorio y nada más. El navegador nunca lo ve.
- El pipeline vuelve a calcular el sha256, exige `%PDF-` y solo lee el texto del PDF (no ejecuta nada).

## Límites del plan gratuito de Cloudflare

Cada solicitud tiene 10 ms de CPU. Un PDF de 15 MB no se puede decodificar ni copiar en ese tiempo, así que el
navegador lo codifica en base64 con el formato exacto de la API de blobs de GitHub y la función lo pasa en flujo
(`FixedLengthStream`) sin leerlo entero: solo mira el principio (`%PDF-`) y el final (`%%EOF`). El cuerpo de una
solicitud puede pesar hasta 100 MB; el límite de 25 MB deja margen.

## Configurar (una vez)

1. En GitHub: **Settings → Developer settings → Fine-grained tokens → Generate new token**. Repositorio: solo
   este. Permisos: **Contents: Read and write** (incluye `repository_dispatch`). Vencimiento: un año, con un
   recordatorio para renovarlo.
2. En Cloudflare Pages (proyecto del sitio): **Settings → Variables and Secrets**, agregar el secreto
   `DOCS_GITHUB_TOKEN` con ese token. Opcional: `DOCS_GITHUB_REPO` si el repositorio cambia de nombre y
   `DOCS_UPLOAD_ROLES=admin,tester` para que los revisores también suban.
3. Volver a desplegar (o esperar al siguiente despliegue). La consola muestra «La subida no está configurada»
   mientras falte el secreto.

La base D1 y las cuentas son las de la consola de lugares ([georreferenciacion.md](georreferenciacion.md)); la
tabla `uploads` se crea sola. Con GitHub Pages no hay API: la página existe pero no sube.

## Casos borde

| Caso | Qué pasa |
| --- | --- |
| Se sube la página de la verificación guardada en vez del PDF | El navegador lo detecta y lo dice; si llegara, la API la rechaza (no empieza con `%PDF-`). |
| Descarga cortada | Falta `%%EOF`: se rechaza en el navegador y en la API. |
| PDF de otro número u otro periodo | Se guarda, pero el pipeline no lo publica; el documento sigue pendiente con el motivo. |
| Dos personas suben a la vez | La segunda rehace su commit sobre el de la primera (avance sin forzar, un reintento). Gana la última subida de cada documento. |
| El documento ya no está pendiente (lo trajo otra ruta) | La API responde «ya no está pendiente»: recargar la lista. |
| No se pudo pedir la actualización | La subida queda guardada y se lee en la corrida diaria de las 23:37; la consola lo avisa. |
| Copias viejas | El índice olvida las de más de 120 días y su archivo sale del árbol de la rama. |
| El comunicado no trae la URL del informe y ningún listado responde | El informe se guarda con la clave `manual://enfen-informe/<comunicado>`; la procedencia publicada es el listado oficial de informes. |
