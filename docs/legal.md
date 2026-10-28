# Privacy Policy y Terms of Use

El sitio publica dos páginas legales, enlazadas desde el pie de página y el sitemap:

- [`public/privacy.html`](../public/privacy.html): *Privacy Policy (GDPR Enhanced)*, que cubre las leyes de
  privacidad de los estados de EE. UU. y, en su «Notice to European users», el RGPD de la UE y el UK GDPR.
- [`public/terms.html`](../public/terms.html): *Website Terms of Use*.

Son **borradores**: el texto es la plantilla tal cual, con solo los datos del sitio llenados. Lo que falta decidir
se ve resaltado en la página (`<mark class="pending">`) y se lista abajo. No se publican hasta que el propietario
apruebe los cambios.

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

## Qué se llenó

Solo campos para llenar y las elecciones que la propia plantilla plantea («A / B», «select one and delete the
other»):

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

Los pasos están en [`scripts/legal/`](../scripts/legal/): `fill.py` (campos) y `wrap.py` (página). Necesitan
`pandoc` para convertir los `.docx`:

```bash
git clone https://github.com/General-Legal/legal-templates /tmp/gl && cd /tmp/gl && git checkout 6d68054 && cd -
for f in privacy-policy-gdpr-enhanced terms-of-use; do pandoc /tmp/gl/docx-originals/$f.docx -t html5 --wrap=none -o /tmp/$f.html; done
python3 scripts/legal/fill.py /tmp /tmp
python3 scripts/legal/wrap.py /tmp public /tmp/gl/templates/terms-of-use/template.md
```

## Pendiente

Datos que tiene que dar el propietario: nombre legal de quien opera el sitio, correo de contacto (privacidad,
accesibilidad, disputas), dirección postal y, si se quiere, teléfono; y la ley y los tribunales aplicables (la
plantilla pide un estado de EE. UU.).

Cambios de fondo que la plantilla necesita para describir este sitio y que **requieren aprobación** (no se hizo
ninguno):

1. **Privacy Policy, datos que no se recogen.** La plantilla describe datos de contacto, perfil, pagos,
   documentos de identidad, concursos, publicidad por intereses, marketing directo, chat e IA, inicio de sesión con
   redes y geolocalización. El sitio no tiene nada de eso: no hay cuentas públicas, ni cookies en el sitio público, ni publicidad; el
   asistente es determinista y no usa un modelo de IA.
2. **Privacy Policy, lo que sí ocurre.** Registros técnicos del alojamiento (GitHub Pages o Cloudflare Pages),
   contadores diarios anónimos de las versiones de los mapas (`ab.js`, que no envía nada con «No rastrear» o Global
   Privacy Control), preferencias guardadas en `localStorage` (tema, versión del mapa, tutorial) y las cuentas de
   las consolas de revisión, solo para el equipo, con su cookie de sesión.
3. **Privacy Policy, sede.** «We are headquartered in the United States» y «We are a U.S.-based company» no
   corresponden a un proyecto del Perú.
4. **Privacy Policy, tabla CCPA, representantes del RGPD (art. 27) y DPO.** Llenar o quitar.
5. **Privacy Policy, Perú.** Agregar lo que pide la Ley N° 29733: derechos ARCO, reclamo ante la ANPD, banco de
   datos y plazo de conservación.
6. **Terms of Use, licencia.** Las secciones 2.1 (uso personal y no comercial), 2.2 (prohíbe copiar, redistribuir y
   hacer obras derivadas) y 10.7 («All rights reserved») contradicen la licencia MIT del código y las licencias de
   los datos ([atribucion-licencias](atribucion-licencias.md)).
7. **Terms of Use, ley y disputas.** Ley de un estado de EE. UU., arbitraje JAMS y renuncia a acciones colectivas;
   para un operador en el Perú corresponde la ley y los tribunales peruanos.
8. **Terms of Use, avisos por estado de EE. UU., cuentas y edad mínima de 18 años.** Revisar si se mantienen.
9. **Versión en castellano** de ambas páginas (la guía de la ANPD exige informar en castellano).
