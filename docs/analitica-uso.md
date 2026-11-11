# Versiones del sitio, selector y analítica de uso

El sitio tiene dos versiones con el mismo contenido. Sirven para saber, con
datos, cuál resulta más cómoda.

| | A · Clásica | B · Agrupada |
|---|---|---|
| Navegación | Las trece pestañas en una fila (en el teléfono se desliza) | Cinco secciones con submenú: Inicio, El Niño, Lugares, Datos y Asistente; bajo la cabecera, las pestañas de la sección actual |
| Secciones largas de consulta | Desplegadas | Plegadas con una vista previa y «Mostrar toda la sección» |
| Listas de más de 15 entradas | Completas | Las 12 primeras y «Ver N más» |

Nada se quita en la B: todo sigue a un clic, el tutorial abre lo que tiene
que mostrar y al imprimir sale todo desplegado.

| Sección de la B | Pestañas |
|---|---|
| Inicio | Resumen, Boletín |
| El Niño | El Niño Costero, Pacífico, Océano y atmósfera, Historia |
| Lugares | Mi zona, Noticias, Memoria de desastres, Mapa |
| Datos | Datos, Metodología |
| Asistente | Asistente |

Lo que la B pliega (`FOLD` en `public/assets/js/sitio.js`): en Resumen, «¿Qué
significa para el Perú?» y «Fuentes oficiales»; en Boletín, cómo llega el
correo; en Historia, los impactos documentados; en Memoria de desastres, los
cuatro análisis a fondo y «Fuentes, método, límites y descargas»; en
Noticias, «Descargas y estado de los feeds»; en Metodología, la arquitectura,
«Cómo funciona» y el glosario.

## Quién ve cada versión

- En el sitio publicado en Cloudflare, la primera visita recibe A o B al azar
  (experimento `sitio` de `ab.js`, con las mismas reglas que los mapas: si un
  día hay una ganadora, 4 de cada 5 primeras visitas la reciben).
- En local y en el espejo de GitHub Pages, que no tienen servidor de
  analítica, se ve la A mientras la persona no elija otra.
- El botón **Versión** de la cabecera dice cuál se está viendo y deja
  cambiarla. La elección queda en ese navegador (`localStorage`).
- En las pestañas con versiones propias (Noticias, Memoria de desastres,
  Boletín) el mismo botón deja cambiar también la del mapa.
- `#/datos?sitio=B` muestra la B a quien abre el enlace sin cambiar su
  elección ni contarla.

## Qué se mide

Al ocultarse o cerrarse la página, el navegador manda a `/api/uso/e` un
resumen de la visita desde el envío anterior:

| Medida | Qué cuenta |
|---|---|
| `sesion` | Sesiones nuevas (30 minutos sin actividad cierran una sesión) |
| `visita` | Qué número de visita de ese navegador era, en tramos: 1, 2, 3-5, 6-10, 11+ |
| `vuelta` | Para quien vuelve, los días desde la visita anterior: hoy, 1-7, 8-30, 31+ |
| `vista` | Veces que se abrió cada pestaña |
| `seg` | Segundos en cada pestaña con la página visible y en uso; sin tocar nada en 60 s el reloj se detiene |
| `abrir` | Secciones plegadas o listas cortadas que se abrieron (versión B) |
| `cambio` | Versiones que se cambiaron: `sitio:A>B`, `mapa:A>C`… |

El servidor (`functions/_lib/uso.js`) solo suma esos números por día y
versión del sitio en la tabla `uso_daily` de la base D1 de la consola.

## Privacidad

- No hay cookies, identificador de visitante, IP, página de origen ni huella
  del navegador. La tabla tiene cinco columnas: día, versión, medida, clave y
  número.
- El contador de visitas vive en el navegador de cada persona
  (`enso-uso-visitas`); al servidor solo llega el tramo.
- No se usa ningún servicio de terceros: la página solo puede conectarse a
  su propio origen (`connect-src 'self'`).
- Con «No rastrear», Global Privacy Control o la casilla **No participar en
  la medición** del selector no se manda nada.
- El servidor solo acepta envíos del propio sitio, valida cada campo contra
  listas cerradas (un texto que no está en la lista no se guarda), limita los
  segundos por pestaña y envío a 1800 y las filas por día a 30 000.

## El tablero

`/admin/analitica.html`, con la misma cuenta de la consola de revisores
(«Ingresar» en la cabecera del sitio y luego **Analítica**). Muestra, para 7,
30 o 90 días y comparando A con B:

- sesiones, proporción de quienes vuelven, tiempo en uso y pestañas por
  sesión, con una lectura en una frase (no compara con menos de 30 sesiones
  por versión);
- sesiones por día;
- dónde se pasa el tiempo y qué pestañas se abren;
- visitas repetidas y hace cuánto fue la anterior;
- qué versiones se cambian (cuántos pasan de A a B y de B a A);
- qué secciones plegadas de la B se abren, para saber si algo no debería
  estar plegado;
- los experimentos de los mapas y del sitio con su decisión.

La lectura (`/api/uso/stats`) pide la sesión de la consola: sin ella responde
401.

## Cómo leerlo

Más tiempo no es mejor por sí solo: en la B hay menos que recorrer para
llegar a lo mismo. Conviene mirar juntas tres cosas: si la gente vuelve más
con una versión, hacia cuál se cambian quienes prueban las dos, y si en la B
alguna pestaña se abre menos que en la A (lo que el menú esconde) o alguna
sección plegada se abre casi siempre (lo que no debería plegarse).

## Pruebas

`python/tests/test_uso.py` y `python/tests/js/uso.test.mjs`: la API con una
D1 de mentira (validación, origen, topes, sesión para leer), las trece
pestañas en la B sin desbordes en cuatro anchos, el selector, el teclado, la
vista previa por enlace, el envío de una visita y el tablero.

## «Cómo leer esto»

En las dos versiones, cada gráfico, mapa y tabla lleva una clave de lectura
plegable (`public/assets/js/leer.js`): qué se ve, qué quiere decir cada
color, cómo leer los valores y la escala (qué es normal, qué favorece a El
Niño o a La Niña) y qué no concluir. Las etiquetas de color dicen además su
significado al pasar el puntero. Las guías repiten umbrales que el sitio ya
publica (ICEN, RONI, tabla GRD); no clasifican nada. Para agregar una, se
añade una entrada a `GUIDES` con el id del título de la sección.
