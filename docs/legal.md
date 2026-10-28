# Política de Privacidad y Términos de Uso

El sitio publica cuatro páginas legales, enlazadas desde el pie de página y el sitemap:

| Página | Contenido |
|---|---|
| [`public/privacidad.html`](../public/privacidad.html) · [`public/privacy.html`](../public/privacy.html) | Política de Privacidad / *Privacy Policy*: leyes de privacidad de los estados de EE. UU., RGPD de la UE y UK GDPR, y la Ley N° 29733 del Perú |
| [`public/terminos.html`](../public/terminos.html) · [`public/terms.html`](../public/terms.html) | Términos de Uso / *Terms of Use* |

Las cuatro se generan con `python3 scripts/legal/build.py` a partir de su texto en
[`scripts/legal/src/`](../scripts/legal/src/); `tests/test_legal_pages.py` falla si una página no coincide con su
fuente. Los datos que el propietario todavía no ha dado se ven resaltados en la página (`<mark class="pending">`) y
se listan al final.

## De dónde sale el texto

Plantillas de [General Legal](https://general.legal/library) (bufete de EE. UU.), publicadas en
[General-Legal/legal-templates](https://github.com/General-Legal/legal-templates) bajo **CC0 1.0**: se pueden usar
y modificar sin atribución. Su README pide conservar la nota al pie de crédito, y se conserva al final de cada
página. Versión usada: commit `6d68054` (22 de septiembre de 2026), archivos `.docx` originales de
`docx-originals/`:

| Página | Plantilla | Ficha |
|---|---|---|
| `privacy.html` | `privacy-policy-gdpr-enhanced.docx` | <https://general.legal/library/privacy-policy-gdpr-enhanced> |
| `terms.html` | `terms-of-use.docx` | <https://general.legal/library/terms-of-use> |

Se eligieron frente a las alternativas revisadas porque son las únicas encontradas que a la vez están redactadas
por abogados, actualizadas en 2026, tienen licencia abierta explícita y son plantillas para llenar (no la política
de una empresa):

- Políticas de Automattic ([legalmattic](https://github.com/Automattic/legalmattic), CC BY-SA 4.0) y de Basecamp
  ([basecamp/policies](https://github.com/basecamp/policies), CC BY 4.0): las más citadas en foros, pero son las
  políticas de sus productos y exigirían reescribirlas.
- Plantilla de [GDPR.eu](https://gdpr.eu/privacy-notice/) (Proton AG): «All Rights Reserved», sin permiso de reuso.
- Plantilla de términos de Discourse: sin licencia declarada
  ([meta.discourse.org](https://meta.discourse.org/t/copyright-license-for-default-terms-of-service-and-faq/232353)).
- Generadores (Termly, TermsFeed, iubenda, GetTerms): texto propietario generado por cuestionario.
- Perú y Latinoamérica: no se encontró ninguna plantilla en castellano con licencia abierta. La ANPD (Ley N° 29733,
  reglamento D.S. N° 016-2024-JUS) publica la *Guía práctica para la observancia del deber de informar*
  (R.D. N° 80-2019-JUS/DGTAIPD), que dice qué informar y exige hacerlo en castellano, pero no trae un texto modelo.

## Primera versión: la plantilla con los datos llenados

La primera versión (commit `f8b7931`, solo en inglés) era la plantilla tal cual, con solo los campos para llenar y
las elecciones que la propia plantilla plantea («A / B», «select one and delete the other»):

| Campo | Valor |
|---|---|
| Fecha (`[DATE]`, «Last revised») | October 28, 2026 |
| `[Full Company Name]`, `[CompanyName]`, `[Company]`, `[Company Name]` | Observatorio ENSO Perú |
| `[DESCRIPTION OF BUSINESS]` | free public website that publishes official El Niño and La Niña (ENSO) indicators for Peru |
| `[DOMAIN NAME]` | https://pillb.github.io/observatorio-enso-peru/ (`tools.prepare_site` la cambia al desplegar en otra dirección) |
| URL de la Privacy Policy, «Cookie Policy / Privacy Policy» | `privacy.html` |
| Copia imprimible («here») | `privacy.html` |
| Copyright `202[_] [Company]` | 2026 Observatorio ENSO Perú |
| Publicidad dirigida, perfiles, venta de datos | las opciones «We do not …» |
| Menores de 16 años, datos sensibles | «Consumers under 16 …», «We do not intentionally collect or process Sensitive Personal Information» |
| «are/may be» | may be |
| «Notice to European users» | se conserva (alcance UE) |
| Arbitraje | opción A (JAMS); la B (DecisionLayer) se borró, como indica la plantilla |

Además, solo de presentación: el encabezado de borrador de la plantilla («TEMPLATE PRIVACY POLICY…») se cambió por
la línea de fecha, los enlaces del índice apuntan al título correcto (la conversión del `.docx` los desplazaba), los
títulos bajan un nivel bajo el `<h1>` de la página y se quitaron los anchos de columna en línea que la CSP bloquea.

Esa versión se reproduce con `scripts/legal/fill.py` (campos) y `wrap.py` (página), que necesitan `pandoc` para
convertir los `.docx`:

```bash
git clone https://github.com/General-Legal/legal-templates /tmp/gl && cd /tmp/gl && git checkout 6d68054 && cd -
for f in privacy-policy-gdpr-enhanced terms-of-use; do pandoc /tmp/gl/docx-originals/$f.docx -t html5 --wrap=none -o /tmp/$f.html; done
python3 scripts/legal/fill.py /tmp /tmp
mkdir -p /tmp/legal-v1 && python3 scripts/legal/wrap.py /tmp /tmp/legal-v1 /tmp/gl/templates/terms-of-use/template.md
```

## Cambios aprobados por el propietario (28 de octubre de 2026)

El propietario aprobó adaptar las plantillas al sitio y traducirlas al castellano. Sobre la primera versión:

1. **Datos que no se recogen.** Se quitaron de la Política de Privacidad los datos de contacto, perfil, transacciones,
   marketing, finanzas, documentos de identidad, pagos, concursos y datos de terceros; la publicidad por intereses,
   el marketing directo, los eventos, el chat y la IA (el asistente del sitio es determinista), el inicio de sesión
   con redes sociales, la geolocalización, las invitaciones y los perfiles públicos; y en los Términos, la publicidad
   de terceros y la interacción entre usuarios.
2. **Lo que sí ocurre.** Se describe, con el texto de la plantilla donde servía: los datos de comunicaciones, las
   cuentas de las consolas de revisión (usuario, hash de la contraseña, sesión y registro de acciones con su IP), las
   fuentes públicas que el sitio vuelve a publicar, los registros del alojamiento, que el sitio público no usa
   cookies, las preferencias en `localStorage` y los contadores anónimos de los mapas (`ab.js`), que no se envían con
   «No rastrear» o Global Privacy Control. La plantilla decía «We currently do not respond to Do Not Track
   signals», que aquí no es cierto.
3. **Sede.** «Headquartered in the United States» y «U.S.-based company» pasan a «estamos en el Perú», con los
   proveedores de alojamiento (GitHub Pages y Cloudflare Pages) en EE. UU.
4. **Tabla CCPA, representantes del RGPD (art. 27) y DPO.** Se quitaron, junto con los formularios y teléfonos para
   ejercer derechos (todo va al correo de contacto) y los avisos de Nevada, Texas y «Shine the Light» de California.
   La tabla de bases jurídicas del RGPD quedó con las finalidades reales. Las transferencias a EE. UU. citan el Marco
   de Privacidad de Datos UE-EE. UU. (decisión de adecuación del 10 de julio de 2023), que la plantilla no
   mencionaba: decía que EE. UU. no tiene decisión de adecuación.
5. **Perú.** Nueva sección «Aviso para usuarios en el Perú» (Ley N° 29733 y su reglamento, D.S. N° 016-2024-JUS):
   titular y banco de datos, finalidades, datos obligatorios y consecuencia de no darlos, transferencias,
   conservación, derechos ARCO gratuitos y reclamación ante la ANPD.
6. **Licencia.** En los Términos, las secciones 2.1 y 2.2 (uso personal y no comercial; prohibido copiar,
   redistribuir y hacer obras derivadas) pasan a una licencia que remite a la MIT del código y a las condiciones de
   cada fuente de datos; «All rights reserved» se quitó.
7. **Ley y disputas.** Ley peruana y tribunales de Lima, sin perjuicio de los derechos imperativos del consumidor en
   su país; se quitaron el arbitraje JAMS, la renuncia a acciones colectivas y al jurado, la renuncia a la sección
   1542 del Código Civil de California, la cláusula de control de exportaciones de EE. UU. y el tope de
   responsabilidad atado a «lo pagado» (el sitio es gratuito: queda en 50 dólares).
8. **Avisos por estado de EE. UU., cuentas y edad mínima.** Se quitaron la sección 9 de los Términos (sus derechos de
   privacidad siguen en la Política) y el requisito de tener 18 años; las cuentas se limitan a las consolas de
   revisión. En la Política, «menores de edad» deja de fijar 18 años y dice que el sitio no está dirigido a menores.
9. **Castellano.** `privacidad.html` y `terminos.html` traducen fielmente las versiones en inglés adaptadas. La
   nota al pie de General Legal se conserva en inglés en las cuatro páginas.

Además se corrigieron enlaces muertos de la plantilla: la lista de autoridades de protección de datos del EDPB y el
texto del UK GDPR (ahora en legislation.gov.uk).

## Pendiente

Datos que tiene que dar el propietario y que siguen resaltados en las cuatro páginas:

- nombre legal de quien opera el sitio (responsable y titular del banco de datos);
- correo de contacto (privacidad, derechos ARCO y del RGPD, accesibilidad);
- dirección postal;
- nombre y código de inscripción del banco de datos personales ante la ANPD, si está inscrito.
