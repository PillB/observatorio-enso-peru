# Boletín de eventos El Niño

Una hoja con lo que pasa hoy por El Niño en el Perú: arriba el país (mapa por nivel, cuántos departamentos hay en
cada nivel y qué se viene), abajo los diez departamentos más críticos con qué podría pasar, cuándo y quién lo dice.
Está en la pestaña **Boletín** (`#/boletin`), sale en cada actualización diaria y es la misma que llega por correo.

Código:

| Archivo | Qué hace |
| --- | --- |
| `python/enso/boletin.py` | Arma `data/boletin.json` desde lo que ya publica el sitio: el mapa de alertas (`feed.json`), el ENFEN (`dashboard.json`) y el escenario del CENEPRED. También el correo (`data/boletin-correo.html`), el texto para WhatsApp y dos CSV |
| `python/enso/observatory.py` | Lo llama al final de la publicación; si falla, la publicación sigue sin boletín (`boletin-exception`) |
| `public/assets/js/boletin.js` | La pestaña. No calcula nada: presenta el JSON |
| `n8n/lib/boletin.js`, `n8n/nodes/boletin*.js` | Cuándo y a quién se manda el correo (flujo «ENSO · Boletín de eventos El Niño por correo») |
| `python/tests/test_boletin.py`, `n8n/test/boletin.test.mjs`, `n8n/test/e2e-boletin.sh` | Pruebas, con la publicación real del 10 de noviembre de 2026 (`python/tests/fixtures/boletin/`) |

## Qué se muestra y de dónde sale

| Parte | Fuente | Regla |
| --- | --- | --- |
| Color de cada departamento | Los avisos vigentes o próximos del mapa de alertas (SENAMHI, INDECI/COEN, DHN, ANA, IGP) | El nivel más alto que la **institución** le dio a un aviso de un peligro de El Niño: lluvias, huaicos, inundaciones, oleaje, sequía o emergencia. No se inventa ningún nivel: un aviso sin nivel queda gris, «sin nivel» |
| Rojo | Nivel 3 de la institución | Peligro alto: actuar según las indicaciones de las autoridades |
| Naranja | Nivel 2 | Peligro: prepararse |
| Amarillo | Nivel 1 | Estar atento |
| Verde | Sin avisos de El Niño vigentes | Que no haya aviso no quiere decir que no haya riesgo |
| Rayado | El aviso todavía no empieza | Se espera, aún no rige |
| Qué se viene | Estado del ENFEN y su comunicado | Las probabilidades salen **solo** de la tabla del informe técnico del ENFEN, con su página; si el informe está vencido o no se leyó, no se muestra ninguna |
| Riesgo de fondo | Escenario de riesgo por lluvias del CENEPRED | Distritos en riesgo muy alto y alto, sin cambios |
| Daños | Reportes del INDECI de las últimas 72 horas | Se cuentan, con su enlace |

Un mismo aviso del SENAMHI difundido también por el INDECI cuenta una vez («también INDECI»). Los avisos que no son de
El Niño (heladas, friaje, calor en la selva, volcanes) se cuentan aparte y no pintan el mapa.

### Orden de los departamentos

1. El nivel más alto de un aviso oficial vigente o próximo.
2. Si ese nivel rige ya o solo se espera.
3. Cuántos avisos tienen ese nivel.
4. Cuántos avisos relacionados con El Niño tiene en total.
5. Cuántos reportes de daños del INDECI hubo en 72 horas.
6. Qué parte de sus distritos el CENEPRED pone en riesgo muy alto.

El mismo orden está escrito al pie de la tabla y en el JSON (`order`).

### Versiones A/B del mapa

La mitad de las visitas ve el mapa real del Perú y la otra mitad un mosaico (un cuadrado por departamento, norte
arriba y costa a la izquierda), que se lee igual de bien en un celular y es el que va en el correo, porque Gmail no
muestra SVG. Quien elige una a mano la conserva. La analítica anónima es la del mapa de alertas
([mapa-alertas](mapa-alertas.md)), experimento `boletin`: vistas, selecciones, detalle y elección.

### Impresión

«Imprimir o guardar en PDF» deja una sola hoja A4 con los diez primeros (dos con los 25). Las pruebas de navegador
lo comprueban con el PDF de Chromium.

## Ediciones y reglas de aviso

Cada actualización diaria compara con el boletín anterior. Si nada cambió, la edición sigue igual («sin cambios
desde …»); si algo cambió, sale una edición nueva con la lista de cambios y la regla de cada uno. `recent` guarda las
últimas 14 ediciones con sus cambios.

| Situación | Regla | Qué se hace |
| --- | --- | --- |
| Un aviso oficial nuevo, rojo o naranja | `aviso-nuevo` | Correo inmediato |
| Un departamento sube a naranja o a rojo | `departamento-sube` | Correo inmediato |
| Un aviso sube a naranja o a rojo | `aviso-sube` | Correo inmediato |
| El ENFEN cambia de estado | `enfen-estado` | Correo inmediato |
| Se cancela un aviso naranja o rojo ya comunicado | `aviso-cancelado` | Correo inmediato |
| Avisos amarillos o sin nivel, departamentos que bajan, un comunicado del ENFEN sin cambio de estado, un escenario nuevo del CENEPRED, otro estado de la NOAA | `resumen` | Van en el resumen diario |
| El mismo aviso difundido por dos instituciones, o una publicación sin cambios | `duplicado` | Nada |

## Correo con n8n y Gmail

El sitio lo publica todo; n8n solo lee `data/boletin.json` del sitio (no depende de que la fuente esté geobloqueada:
lo que solo responde desde el Perú ya llegó por el recolector del Perú) y decide:

- **Primera vez**: manda el boletín completo como «Primer boletín».
- **Algún cambio inmediato**: lo manda ya, con «[Aviso]» en el asunto.
- **Solo cambios de resumen**: espera a la hora del resumen (`digest_hour`, 7:00 en Lima) y manda uno al día con
  «[Resumen]».
- **Sin edición nueva**: nada.

Compara con la última edición que **ese n8n** mandó y junta los cambios de todas las ediciones nuevas, así no se
pierde ninguno si salieron dos entre dos revisiones. Si el boletín publicado tiene más de 36 h, la ejecución falla
(lo ve el «Error workflow» de n8n): la actualización diaria no corrió.

El flujo es `n8n/dist/enso-n8n-boletin.json`: **Cada hora** → **Configuración** → **Leer boletín** → **Decidir envío**
→ **¿Enviar?** → **Enviar por Gmail** → **Guardar estado**. El estado se guarda solo después de que Gmail respondió
bien: si Gmail falla, la hora siguiente lo vuelve a intentar.

### Paso de configuración (lo hace Pablo o el colega de n8n)

Viene con `send = false`: hasta que se cambie, arma el correo y no lo manda (simulacro). Para ponerlo en marcha:

1. En n8n, **Credentials → Add credential → Gmail OAuth2 API** con la cuenta de Gmail que va a mandar los correos.
   Nombre: `Gmail boletín ENSO`. En n8n Cloud basta con «Sign in with Google»; en un n8n propio hay que crear el
   cliente OAuth en Google Cloud con la API de Gmail activa ([guía de n8n](https://docs.n8n.io/integrations/builtin/credentials/google/oauth-single-service/)).
2. Importar `n8n/dist/enso-n8n-boletin.json` y, en **Enviar por Gmail**, elegir esa credencial. (Con
   `N8N_GMAIL_CRED_ID=<id> node n8n/build.mjs` el flujo ya la trae elegida.)
3. En **Configuración**:
   - `to`: las direcciones que reciben, separadas por comas.
   - `bcc`: copias ocultas (para una lista más larga sin mostrar las direcciones).
   - `sender_name`, `digest_hour` (hora de Lima del resumen) y `site` si el sitio cambia de dirección.
4. Probar con **Ejecutar a mano** y `send = false`: la salida de **Decidir envío** muestra el asunto, a quién iría
   y el HTML. Con `send = true` y solo la propia dirección en `to`, llega un correo de prueba.
5. Poner `send = true` y activar el flujo (n8n 1.x) o publicarlo (n8n 2.x).

n8n guarda la última edición enviada solo en las ejecuciones del disparador (no en las manuales): por eso, las
pruebas a mano siempre se comportan como «primer boletín», y la primera hora con el flujo activo manda el boletín
completo una vez.

Gmail permite unos 500 destinatarios por día en una cuenta gratuita y unos 2000 en Google Workspace; para una lista
mayor conviene un grupo de Google como único destinatario.

Prueba con n8n real (sin Gmail de verdad: la credencial es falsa y se comprueba que el correo llega al nodo y que el
estado no se guarda si Gmail falla): `n8n/test/e2e-boletin.sh n8nio/n8n:2.44.4 /tmp/bol`. Corre en `n8n.yml`.

## WhatsApp

**Elegido: compartir a mano, gratis.** La pestaña tiene «Compartir por WhatsApp» (un enlace `wa.me` con el resumen
ya escrito, que abre WhatsApp para elegir el chat o el grupo) y «Copiar resumen». El texto es `whatsapp` del JSON.

**Fase 2, automática: no es gratis.** Mandar mensajes sin que alguien los pulse exige la API de WhatsApp Business
(Cloud API de Meta): un número dedicado, verificación de la empresa, plantillas aprobadas y, desde el 1 de julio de
2025, pago por cada mensaje de plantilla entregado; una alerta a quien no escribió en las últimas 24 h es una
plantilla de «utilidad» y se cobra ([precios de Meta](https://developers.facebook.com/docs/whatsapp/pricing/)).
n8n tiene el nodo «WhatsApp Business Cloud» para cuando se decida: se agregaría a este mismo flujo detrás de
**¿Enviar?**, con el mismo texto. Las vías no oficiales (bots con WhatsApp Web) incumplen las condiciones de WhatsApp
y pueden bloquear el número, así que no se usan.
