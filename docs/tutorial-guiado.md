# Tutorial guiado

El botón «Ayuda y tutorial» de la cabecera y el botón «Cómo se usa esta pestaña» al inicio de cada pestaña abren
recorridos guiados: uno por pestaña, uno de inicio rápido y uno completo (una parada por pestaña). Cada paso lleva a su
pestaña, deja la vista en el estado que necesita, desplaza la página hasta la sección, la resalta y, cuando hace falta,
la usa delante de la persona: pulsa la vista de detalle de un mapa, elige un filtro, abre la ficha de un área, mueve
la animación semanal o escribe una pregunta en el asistente, con un puntero animado.

Código:

| Archivo | Qué hace |
| --- | --- |
| `public/assets/js/tour-pasos.js` | Los recorridos y sus pasos (texto, sección, estado previo y demostración). |
| `public/assets/js/tour.js` | El motor: navegación, estado previo, desplazamiento, resaltado, ventana, demostraciones, progreso. |
| `public/assets/js/tour-geo.js` | Geometría pura: dónde va la ventana y cuánto desplazar la página. |
| `python/tests/test_tour.py` | Pruebas de navegador (ver abajo). |

## La regla: la ventana nunca tapa lo que muestra

La ventana del paso no se cruza nunca con:

- lo que se resalta (con su borde y su halo), en la parte que se ve bajo la cabecera fija;
- el control que el tutorial está tocando, en el momento de tocarlo;
- el tooltip que abre un mapa durante la demostración;
- el control que tiene el foco del teclado (WCAG 2.2, criterio 2.4.11 «Foco no oculto»).

Cómo se cumple:

1. **Se planea el desplazamiento** (`planScroll`). Si el elemento y la ventana caben uno encima del otro, se centran
   juntos (con la ventana debajo o encima, lo que pida menos desplazamiento). Si no, y la pantalla es ancha, la
   ventana va al lado. Si el elemento es más alto que la pantalla, la ventana va arriba y el elemento empieza justo
   debajo (se ve su comienzo; el resto sigue más abajo, sin nada encima). Si la página no alcanza a desplazarse lo
   necesario (una sección al final), se agrega espacio temporal arriba o abajo mientras dura el paso.
2. **Se coloca en cada cuadro** (`placePopover`): solo en posiciones que no tocan ningún rectángulo a evitar. Primero
   al lado del elemento (abajo, arriba, derecha, izquierda, con tres alineaciones cada una), después en cualquier
   espacio libre de la pantalla. Así sigue valiendo si la vista se redibuja, si cambia el tamaño de la ventana, si
   la persona desplaza la página o lleva el foco a otro control. Las coordenadas se redondean antes de comprobarlas.
3. **Si no cabe en ningún lado**, la ventana se reduce a una píldora («3/9 · título · Ver el paso») sobre la cabecera
   fija: lo que hay debajo de la cabecera ya estaba tapado por ella. Si nadie desplazó la página, se vuelve a planear
   (algo cambió de tamaño, como un gráfico que terminó de dibujarse). La píldora tiene su propio botón «›» para
   seguir; si lo que estorba es el tooltip que abrió la demostración, el tooltip se cierra.
4. **En pantallas muy bajas** (KaiOS, la pantalla externa de un plegable, un teléfono acostado) la ventana se
   compacta y puede acortarse hasta dejar a la vista solo el título y los botones: el texto se desplaza por dentro.
   Ningún plan deja el elemento fuera de la pantalla o tras la cabecera.

## Pasos que usan los mapas y los gráficos

Un paso declara el estado que necesita (`ensure`: la vista del mapa, los filtros, el nivel, una ficha abierta) y el
tutorial lo deja así en silencio antes de mostrarlo. Por eso cada paso se puede mostrar solo: al avanzar, al volver
con «Anterior», al repetir la demostración o al reanudar tras recargar la página. La demostración (`demo`) usa los
mismos controles que la persona (clic, `change` en un `<select>`, `pointermove` sobre el mapa o el gráfico, texto en el
asistente), así que el tutorial no puede mostrar algo que la página no haga.

Lo que pulsa el tutorial no cuenta en la analítica de las versiones de los mapas ni cambia la vista que la persona
tiene asignada (`ab.js`: lo trata como un enlace compartido).

## Accesibilidad y uso

- No es modal: la página sigue usable durante el recorrido (el oscurecido no toma clics). La ventana es un
  `role="dialog"` con `aria-modal="false"`, título y descripción; cada paso se anuncia en la región viva.
- Esc pausa. Las flechas avanzan y retroceden solo con el foco en la ventana: sobre un gráfico o el deslizador del
  mapa siguen siendo de la página.
- Si la persona se va a otra pestaña por su cuenta, el recorrido queda en pausa y se reanuda desde «Ayuda».
- Con «reducir movimiento», el desplazamiento es instantáneo y el puntero no viaja.
- Funciona en tema claro y oscuro (el oscurecido y el borde del resaltado cambian con el tema) y desde 240 px de ancho.
- No arranca solo: los estudios de Nielsen Norman Group con tutoriales al inicio no encontraron mejoras en el éxito de
  las tareas; por eso cada recorrido es opcional y está junto a lo que explica.

## Pruebas

`python/tests/test_tour.py` corre en cada PR (CI, paso «Browser journeys»). Un vigilante en la página revisa cada
cuadro mientras dura un recorrido y falla si la ventana toca el resaltado, el punto que toca el puntero o un tooltip,
o si sale de la pantalla.

- Geometría: 5000 casos al azar de `placePopover` y `planScroll`.
- Los 13 recorridos en un teléfono de 320×640, uno de 390×844 en tema oscuro, una tableta y un escritorio en tema
  oscuro: cada paso encuentra su sección y nunca se cruza.
- Con animaciones, en un teléfono: el puntero llega a cada control.
- Cambio de tamaño a mitad de un paso (escritorio, teléfono, teléfono acostado, tableta) y cambio de tema.
- Teclado: Esc, flechas sobre un gráfico, reanudar tras recargar, pausa al irse a otra pestaña.
- Las versiones de los mapas y su analítica no cambian.
- Los dispositivos de referencia (`python/tools/devices.py`, de KaiOS 240×320 a 1920×960) con su motor: Chromium,
  WebKit (Safari) y Firefox.

Para agregar un paso: escriba su `route`, su `target` (un selector que exista en esa vista) y, si hace falta, el
estado previo con los ayudantes `pressed`, `valued`, `opened` y `absent` de `tour-pasos.js`. Las pruebas recorren
todos los pasos: un selector que no existe hace fallar la prueba.
