# Aportes voluntarios

El observatorio es gratuito y no muestra publicidad. Para quien quiera
ayudar a sostenerlo hay una página discreta, `#/apoyar`, a la que se llega
desde dos lugares:

- el pie de todas las páginas (columna «Apoyar»), y
- una línea al final de **Datos**, el momento en que alguien acaba de
  aprovechar el trabajo del sitio.

No aparece en la navegación, en los avisos, en ventanas emergentes ni en
el asistente, y no se carga ningún botón ni script de terceros: son enlaces
simples, así que la política de seguridad (CSP) y la privacidad de quien
visita no cambian.

## Cómo activar cada vía

Todo se configura en `SUPPORT`, dentro de `public/assets/js/content.js`.
Una vía vacía no se muestra; con todas vacías, la página solo ofrece las
formas de ayudar que no son dinero.

| Campo | Qué poner |
|---|---|
| `kofi` | La dirección de la página en Ko-fi, p. ej. `https://ko-fi.com/observatorioenso` |
| `yapeQr` | La imagen del QR de Yape guardada dentro de `public/`, p. ej. `assets/apoyo/yape-qr.png` |
| `yapeName` | El nombre del titular que Yape muestra antes de confirmar, para que quien aporta compruebe el destino |
| `githubSponsors` | La dirección del perfil en GitHub Sponsors |

Al publicar en Cloudflare con `--hide-repo`, `githubSponsors` se vacía igual
que los enlaces al repositorio (`python/tools/prepare_site.py`).

## Por qué estas vías (octubre de 2026)

| Vía | Para quién | Costo para el observatorio | Notas |
|---|---|---|---|
| **Yape** (QR) | Personas en el Perú | Sin comisión en cuenta personal | La vía más accesible en el país. El QR muestra el nombre del titular. Las cuentas personales tienen un tope mensual de cobros por QR (5 UIT según la prensa de 2024); confírmelo en la app. Plin y otras billeteras pueden leer el QR de Yape por la interoperabilidad que exige el BCRP: pruébelo antes de anunciarlo. |
| **Ko-fi** | Cualquier país, con tarjeta o PayPal, sin crear cuenta | 0 % de Ko-fi en donaciones únicas; PayPal cobra su comisión | El dinero llega a la cuenta PayPal del titular. Desde el Perú se retira a una cuenta de ahorros de Interbank (≈1,5 %, mínimo USD 17 por retiro según Interbank) o con servicios como Ligo. Conviene acumular y retirar pocas veces. |
| **GitHub Sponsors** | Desarrolladores e instituciones que ya usan GitHub | 0 % en aportes de cuentas personales | El Perú está entre las regiones que pueden recibir pagos. Solo tiene sentido si el repositorio es público. |

Descartadas por ahora:

- **Buy Me a Coffee**: paga por Stripe y no queda claro que admita cuentas
  del Perú.
- **Patreon**: pensado para contenido exclusivo por suscripción, que el
  observatorio no ofrece.
- **Open Collective** (Open Source Collective): da transparencia de gastos,
  pero cobra alrededor del 10 % más el procesador. Vale la pena si un día
  hay varias personas o una institución detrás y se quiere rendir cuentas
  en público.

## Reglas del texto

- Nunca pedir aportes en un aviso, en una alerta ni junto al estado del
  ENFEN: el sitio informa sobre riesgos y no debe parecer que aprovecha
  una emergencia.
- Decir siempre que todo seguirá siendo gratuito y que los aportes no
  cambian lo que el observatorio publica.
- No inventar cifras de costos: si se publican, que sean las reales.

Fuentes: [GitHub Sponsors, regiones admitidas y comisiones](https://docs.github.com/en/sponsors/getting-started-with-github-sponsors/about-github-sponsors),
[Ko-fi, comisiones](https://ko-fi.com/patreon),
[Yape sin comisión para personas (El Peruano)](https://elperuano.pe/noticia/240612-yape-aclara-que-aplicacion-seguira-siendo-gratis-para-usuarios),
[Retirar PayPal en el Perú (Global66)](https://www.global66.com/blog/comision-de-paypal-peru/),
[Comisiones de los anfitriones de Open Collective](https://docs.opencollective.com/help/fiscal-hosts/fiscal-host-fees).
