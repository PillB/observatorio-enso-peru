# Revisión del boletín (noviembre de 2026)

Revisión a fondo de la pestaña **Boletín** (`#/boletin`), del correo, del texto para WhatsApp y del envío con n8n:
pruebas de rotura (datos vacíos, fechas inválidas, estado anterior dañado, enlaces `javascript:`, fórmulas en los
CSV, 25 departamentos en rojo, avisos vencidos), comparación con los boletines de referencia y seis problemas por
sección, cada uno con su arreglo. Lo que se construyó a partir de esto (suscripción, versión C, correo adaptable,
canal Atom) se explica en [boletin.md](boletin.md).

## Investigación

| Referencia | Qué se tomó |
| --- | --- |
| NOAA CPC, [*ENSO Diagnostic Discussion*](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml) | Abrir con el estado del sistema de alerta, una sinopsis de una frase y la fecha de la próxima edición |
| BoM (Australia), [retiro del *ENSO Outlook* dial](https://www.bom.gov.au/climate/enso/) (diciembre de 2024) | Un indicador de vigilancia/alerta se lee como pronóstico: la escalera del ENFEN se muestra como su estado oficial, sin porcentajes inventados |
| Met Office, [matriz de impacto](https://www.metoffice.gov.uk/weather/guides/warnings) | Por color: qué se espera y qué hacer |
| OMM, [avisos basados en impactos](https://library.wmo.int/records/item/54669-wmo-guidelines-on-multi-hazard-impact-based-forecast-and-warning-services) | El mensaje dice qué va a pasar y a quién, no solo el peligro |
| [Meteoalarm](https://meteoalarm.org/) | Juntar avisos oficiales sin crear niveles propios; leyenda siempre visible |
| Gmail y Yahoo, [requisitos para remitentes](https://support.google.com/a/answer/81126) (2024) | Baja en un clic (RFC 8058, `List-Unsubscribe-Post`), baja atendida al momento |
| Gmail, recorte de mensajes de más de 102 KB | El correo pesa muy por debajo |
| [Can I email](https://www.caniemail.com/) | Sin grid, flex ni degradados; tablas para Outlook; modo oscuro con `color-scheme` |
| Ley 29733 y su reglamento (DS 016-2024-JUS) | Consentimiento expreso, finalidad única, datos mínimos, baja y borrado |

## Problemas y arreglos por sección

### Encabezado y contadores

1. La edición no decía de cuándo era sin leer la letra chica. → «Edición N° X del *fecha*» en el título.
2. Faltaba una frase que resuma todo. → «En una frase» arriba (también en el correo, WhatsApp y Atom: `summary`).
3. Los contadores eran decorativos. → Son botones que filtran la tabla (`aria-pressed`), deshabilitados cuando el número es 0.
4. Contadores de menos de 44 px de alto en el celular. → Alto mínimo de 44 px y ancho flexible.
5. Un enlace de fuente con `javascript:` o sin esquema se pintaba tal cual. → `safe_url` en Python y `safeUrl` en la página.
6. Fechas inválidas o sin zona rompían el texto («Invalid Date»). → `iso()` en el pipeline; `when()` y `isOld()` tratan lo inválido como viejo.

### ENFEN y cambios

1. El estado del ENFEN no decía en qué paso de su escala está. → `enfen.step` y escalera No activo → Vigilancia → Alerta (forma C).
2. «Comunicado oficial N° None» con datos incompletos. → Texto sin número cuando falta.
3. La fecha del próximo comunicado vencida se mostraba como futura. → Se marca «debió salir el …».
4. Los cambios no decían qué tan importantes eran. → Etiquetas Importante / Menor según la regla.
5. Los cambios no decían de qué departamento eran. → `changes[].deps`, que usa también n8n para filtrar por suscriptor.
6. Un estado anterior dañado tumbaba la publicación. → `clean_state()`: el boletín vuelve a la N° 1 con su incidencia.

### Mapa (versión A)

1. El Callao era un punto que no se podía elegir con el teclado. → Punto con foco, nombre y `data-dep`.
2. Los avisos vencidos se veían igual que los vigentes. → Atenuados (`gone`) y en la leyenda.
3. La ficha del departamento aparecía lejos del mapa. → `#bol-dep` debajo del mapa, se cierra con Escape y devuelve el foco.
4. Al redibujar se perdía el foco. → Se restaura sobre el mismo elemento.
5. El departamento elegido no se podía compartir. → `#/boletin?dep=20` (con `history.replaceState`).
6. La analítica contaba cada movimiento del ratón. → Solo el paso por el mapa y el mosaico.

### Mosaico (versión B)

1. Celdas de ancho fijo que se salían a 320 px. → Grilla fluida (seis columnas de 1fr, máximo 380 px).
2. El rayado blanco de «aviso próximo» no se veía en amarillo y gris. → Rayas oscuras en esos colores.
3. Con el teclado había que pasar por los 25 cuadrados. → Un solo tabulador y flechas (patrón *roving tabindex*).
4. Siglas sin explicar. → Lista de siglas debajo y rumbo (norte arriba, costa a la izquierda).
5. «Próximo» se distinguía solo por el color. → Texto «próx.» en el cuadrado.
6. El correo usaba celdas de 50 px que desbordaban en el celular. → Celdas de 16,66 % con máximo de 300 px.

### Qué se viene y probabilidades

1. Solo se mostraban dos categorías, sin decir que había más. → «Otras categorías» con el resto (y todas, de fría a cálida, en la forma C).
2. La probabilidad no enlazaba a su fuente. → Enlace al informe técnico con su página.
3. Sin consejo práctico. → «Qué hacer según el color» (INDECI y SENAMHI), plegado en A y B y como tabla en C.
4. No se veía cuándo empieza cada aviso. → `timeline`: hoy, próximas 24 h, 24 a 72 h, más adelante.
5. La NOAA no tenía enlace ni se distinguía del ENFEN. → Al final de la línea, en gris y con su enlace, como referencia.
6. Las barras no decían nada a un lector de pantalla. → Cada barra lleva su porcentaje (`role="img"`).

### Tabla de los diez

1. Con 19 en rojo no se explicaba por qué solo diez. → Nota de empate con botón «Ver los 19».
2. Las instituciones se cortaban. → `institutionsAll` completas en la fila y en la ficha.
3. Un aviso vencido seguía como «Rige hasta». → «Venció *fecha*» y fila atenuada.
4. El nombre del departamento no abría nada. → Botón que abre su ficha.
5. Un CSV con `=`, `+`, `-`, `@`, tabulador o salto de línea al inicio se volvía fórmula en Excel. → `_cell()` en todos los campos de texto.
6. El encabezado no decía qué filtro estaba puesto. → «Departamentos en naranja (N)» y «Quitar el filtro».

### Ficha del departamento

1. Muchos avisos alargaban la ficha sin fin. → Los cinco primeros y «Y N avisos más en la tabla».
2. No se cerraba con Escape. → Se cierra y devuelve el foco.
3. Sin escenario del CENEPRED salía «0 de 0». → «Sin escenario del CENEPRED».
4. No decía si el aviso ya venció. → «Venció» con la fecha.
5. Enlaces a fuentes sin revisar. → `safeUrl`.
6. En el celular tapaba el mapa. → Va debajo, en el flujo.

### Recibir el boletín (tarjeta de entrega y reglas)

1. No había forma de suscribirse. → Formulario con doble confirmación, frecuencia y departamentos.
2. Sin aviso de privacidad. → «Sus datos», junto al formulario (Ley 29733).
3. Sin alternativa sin correo. → Canal Atom (`data/boletin.xml`).
4. La tabla de reglas ocupaba media pantalla. → Plegada en «Cuándo llega un correo».
5. Las ediciones anteriores no se podían ver. → «Ediciones anteriores y sus cambios».
6. Sin backend (GitHub Pages, local) el formulario fallaría en silencio. → Se deshabilita y lo dice.

### Barra de acciones

1. La acción principal (recibir) no estaba. → «Recibir por correo» primero.
2. «Compartir por WhatsApp» funcionaba antes de tener el texto. → `aria-disabled` hasta que carga.
3. «Copiar resumen» fallaba sin permiso al portapapeles. → Cuadro de texto para copiar a mano.
4. Sin compartir nativo en el celular. → `navigator.share` cuando existe.
5. Demasiados botones en una fila. → CSV, Atom y «Ver como correo» dentro de «Más».
6. Imprimir sacaba dos hojas en algunas formas. → Una A4 en las tres, comprobado con el PDF de Chromium.

### Correo

1. Ancho fijo de 640 px: en el celular había que desplazarse. → Una columna fluida de hasta 600 px (tabla MSO para Outlook).
2. Tabla de diez columnas ilegible en 320 px. → Una tarjeta por departamento.
3. El modo oscuro dejaba texto oscuro sobre fondo oscuro. → `color-scheme` y clases `tx`, `soft`, `warn` con sus colores.
4. Verde de bajo contraste. → `#1f7a4c` (AA con texto blanco).
5. Sin texto previo: la bandeja mostraba el primer texto suelto. → Texto previo con relleno.
6. Sin enlace de baja ni cabeceras de baja en un clic. → Pie con baja y preferencias; `List-Unsubscribe` y `List-Unsubscribe-Post` desde n8n.

### WhatsApp

1. Con más de cinco departamentos el texto se cortaba sin aviso. → «… y N departamentos más».
2. Podía leerse como alerta oficial. → «No es una alerta oficial».
3. Hora sin zona. → «hora de Lima».
4. Más de cinco líneas de departamentos se pierden en un chat. → Cinco como máximo, del más crítico al menos.
5. El asunto del correo podía llevar saltos de línea y romper las cabeceras. → `subject` sin saltos.
6. El ENFEN sin número de comunicado dejaba «N° None». → El número solo cuando existe.

### Actualizaciones (segunda pasada, a pedido)

1. Cada aviso reenviaba el boletín entero (mapa, diez departamentos, qué hacer). → Solo qué cambió, la frase, los contadores y el botón; el completo va en el primer correo.
2. El estado del ENFEN salía tres veces (frase, recuadro y «Qué se viene») y las probabilidades dos. → «Qué se viene» usa su versión corta; el recuadro del ENFEN solo va en un correo de cambios si el ENFEN cambió.
3. Un aviso para muchos departamentos daba una línea por departamento. → Una línea con «(suben a naranja: …)».
4. Un cambio que se deshizo entre dos correos se contaba dos veces. → Cambio neto, o nada.
5. El asunto repetía el estado («19 en rojo…») en cada aviso. → Lleva el cambio principal.
6. WhatsApp y los demás canales iban sin imagen. → `data/boletin.png` con el mosaico, vista previa Open Graph, «Compartir» con la imagen y la imagen en el canal Atom.

## Pruebas

- `python/tests/test_boletin.py`: entradas rotas, enlaces seguros, fórmulas en CSV, peso y contraste del correo, WhatsApp, Atom.
- `python/tests/js/boletin-subs.test.mjs`: la API de suscripción con una D1 y un servidor de correo de mentira.
- `n8n/test/boletin.test.mjs`: envío por suscriptor (frecuencia, departamentos, cabeceras, MIME).
- `python/tests/test_browser.py` (`-k boletin`): las tres formas, impresión en una A4, filtros, teclado, enlaces de
  confirmación y baja que piden un clic, el formulario con y sin backend, y el correo a 320, 375, 414, 600 y 1024 px,
  en claro y oscuro, con y sin hoja de estilos.
