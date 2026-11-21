# Techo de complejidad ciclomática

Cada función de Python y de JavaScript del repositorio debe tener una complejidad ciclomática de **10 o menos**.
Las que ya pasaban de 10 cuando se puso el techo (noviembre de 2026) están en
[`config/complexity-baseline.json`](../config/complexity-baseline.json) con su número de entonces, y ese número
**solo puede bajar**. Lo revisa el job `lint` de [`ci.yml`](../.github/workflows/ci.yml) en cada PR, y la prueba
`python/tests/test_complexity.py` en local.

```bash
npm ci --prefix scripts/lint      # una vez: ESLint con la versión fijada
cd python
python -m tools.complexity        # 0 = bien, 1 = algo que corregir, 2 = no pudo medir
python -m tools.complexity --update      # después de bajar la complejidad de una función de la lista
python -m tools.complexity --report 20   # las 20 funciones más complejas
python -m tools.complexity --python-only # sin Node (las líneas de JavaScript de la lista no se juzgan)
```

## Por qué 10

La complejidad ciclomática v(G) de McCabe (1976) es el número de caminos linealmente independientes del grafo de
control de una función: el mínimo de casos de prueba que recorren cada rama ([NIST SP 500-235, *Structured Testing*,
1996](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication500-235.pdf)). NIST recomienda 10 (§2.5);
admite hasta 15 solo en proyectos con «ventajas operativas» (equipo con experiencia, diseño formal, plan de pruebas
completo) y dice que se elija un límite mayor «solo si se sabe lo que se hace». Este proyecto no tiene esas
ventajas: el techo es 10, en el código (`CEILING` en `python/tools/complexity.py`), no en la lista, para que no se
pueda subir editando un JSON.

## Cómo se cuenta

v(G) = 1 + decisiones, con la regla de NIST SP 500-235 §4.1: **un operador booleano con cortocircuito suma uno**,
porque en el grafo de control es una rama (`a and b` no evalúa `b` si `a` es falso).

| Suma 1 | Python | JavaScript |
|---|---|---|
| Condicional | `if`, `elif`, `x if c else y`, `assert` | `if`, `c ? x : y` |
| Bucle | `for`, `async for`, `while`, cada `for` de una comprensión | `for`, `for…in`, `for…of`, `while`, `do…while` |
| Operador con cortocircuito | cada `and` / `or` | cada `&&`, `\|\|`, `??`, `&&=`, `\|\|=`, `??=`, `?.` |
| Filtro | cada `if` de una comprensión | — |
| Caso | cada `case` cuyo patrón puede no casar (no el comodín `_` ni una captura `case x`, que siempre casan); cada guarda `if`; cada alternativa extra de `a \| b` | cada `case` salvo `default` |
| Excepción | cada `except` | `catch` |
| Valor por omisión | (se cuenta donde se define la función) | cada parámetro con valor por omisión |

No suman: `else`, `finally`, `with`, `break`, `continue`, `return`. Las funciones anidadas, las lambdas y las
funciones flecha son funciones aparte, con su propio número. Los decoradores y valores por omisión de una función
anidada se cuentan en la función que la contiene (se evalúan ahí). El cuerpo de un nodo Code de n8n
(`n8n/nodes/*.js`) se mide como una función, `(n8n Code node)`, porque así lo ejecuta n8n.

- **Python**: `python/tools/complexity.py` sobre el `ast` de la biblioteca estándar, sin dependencias. Da lo mismo
  en Python 3.12 y 3.13 (comprobado sobre las 3.633 funciones del repositorio).
- **JavaScript**: la regla [`complexity`](https://eslint.org/docs/latest/rules/complexity) de ESLint, variante
  clásica, desde `scripts/lint/complexity.mjs`, con ESLint y espree fijados en `scripts/lint/package-lock.json`. El
  nombre calificado (`Tour.show`, `mountAlertMap.draw`, `pointsView.(map callback) #2`) sale del árbol de espree.
  Un comentario `/* eslint-disable */` no apaga la medida (`noInlineConfig`).
- **Alcance**: todo archivo `.py`, `.js`, `.mjs` y `.cjs` que sigue git (también los nuevos sin commit), salvo
  `n8n/dist/` (generado) y `python/tests/fixtures/`. Las pruebas cuentan: una prueba con 20 ramas también es difícil
  de leer y de confiar.

## El trinquete

| Lo que pasó | Qué dice | Qué hacer |
|---|---|---|
| Función nueva (o que cumplía) con más de 10 | `[NUEVA] ruta:línea nombre: complejidad 12 > techo 10` | Dividirla. `--update` no la agrega |
| Función de la lista que creció | `[CRECIÓ] … complejidad 16, creció desde 15` | Dejarla en su número o menos |
| Función de la lista que bajó | `[BAJÓ] … bajó desde 15` | `--update` (baja la línea: el margen ganado no se puede volver a gastar) |
| Función de la lista que quedó en 10 o menos | `[CUMPLE] …` | `--update` (borra la línea) |
| Función de la lista que ya no existe | `[NO EXISTE] …` | `--update` (borra la línea) |
| Función de la lista renombrada, sin cambiar su número | `[NUEVA] … Parece la función «vieja»` | `--update` la traslada (solo si hay una sola candidata en el mismo archivo con el mismo número) |

En GitHub Actions cada hallazgo es además una anotación en la línea del PR. Sale con 2 (no con 1) si no pudo
medir: falta Node o ESLint, un archivo no se analiza, la lista está mal formada o se midió con otra versión.

### Cambiar de versión de ESLint o de la regla de Python

Una versión nueva de ESLint o de espree puede contar distinto (una construcción nueva del lenguaje, un cambio en la regla). La
lista guarda con qué se midió (`tools`); si no coincide, la revisión sale con 2 y lo dice. Para aceptar la subida
(Dependabot la propone una vez al mes): `python -m tools.complexity --rebaseline` en el mismo PR, que reescribe la
lista y lista lo que agregó o subió, para justificarlo en la descripción. Lo mismo al cambiar qué cuenta
`py_score` (subir `PY_METRIC`; `ast-nist-2` dejó de contar como decisión el patrón de `case x if …` o
`case _ if …`, que siempre casa: solo decide la guarda) o el techo (`CEILING`): `--rebaseline` lee la lista
anterior sin validarla. Con `--python-only` conserva las líneas de JavaScript y las versiones de ESLint con que se
midieron.

## Por qué estas herramientas (medido el 21 de noviembre de 2026)

Funciones por encima de 10 / 15 / 20 en el repositorio (todo `python/`, pruebas incluidas; para JavaScript, las
cuatro carpetas de la fila de ESLint), tiempo y lo que se probó contra conteos a mano:

| Opción | Lenguajes | > 10 / 15 / 20 | Tiempo | Instalación | Contra el conteo a mano |
|---|---|---|---|---|---|
| ruff 0.17.4 `C901` (mccabe) | Python | 125 / 46 / 24 | 0,05 s | 24 MB, un binario | No cuenta `and`/`or`, comprensiones ni `x if c else y`; suma las funciones anidadas a la externa. Mide otra cosa |
| radon 6.0.1 | Python | 471 / 255 / 155 | 1,2 s | 0,4 MB + mando | Igual en las 1.826 funciones sin las construcciones de abajo; suma el `else` de bucles y `try`, no mira dentro de `assert`, mete las lambdas en la función y no ve los métodos de una clase definida dentro de una función. Sin versiones desde marzo de 2023 |
| lizard 1.25.0 | Python y JS | Python: 443 / 246 / 152; JS: 123 / 69 / 35 | 0,9 s | pygments (5 MB) + pathspec | Analiza por fichas, no por árbol: atribuye a la función externa lo que hay en una flecha dentro de un template literal (`pointsView` 46 en vez de 32), no cuenta `?.` ni los valores por omisión, cuenta el `case _`. Cuatro versiones entre el 22-10 y el 16-11 |
| ESLint 10.14.0 `complexity` | JS | 129 / 69 / 35 (n8n/lib, functions, public/assets/js, build.mjs) | 1,1 s | 79 paquetes, 16 MB, 3 s con `npm ci` | Igual a los cinco fragmentos contados a mano |
| `ast` propio (elegido para Python) | Python | 574 / 311 / 181 | 1,5 s | nada | Igual a los 15 fragmentos contados a mano y a radon donde las definiciones coinciden |

Un experto en análisis estático preferiría una herramienta conocida a una propia; aquí ninguna de Python cuenta como
NIST, y la diferencia no es de forma: con ruff, 453 de las 574 funciones de Python por encima del techo pasarían sin
aviso. Por eso el conteo propio se prueba contra un oráculo independiente (radon) en todo el repositorio, además de
los fragmentos contados a mano.

## Lo que esto no mide y lo que se decidió

- **Complejidad cognitiva** ([SonarSource, G. Ann Campbell, 2017](https://www.sonarsource.com/docs/CognitiveComplexity.pdf)):
  pesa el anidamiento y no cuenta un `switch` plano como diez ramas. Es mejor medida de legibilidad, pero no hay una
  implementación libre, mantenida y con versión fija para los dos lenguajes; v(G) es la que tiene base en pruebas
  (el número de casos de prueba de NIST). Un `switch` o una tabla de casos largos y planos pasa el techo igual: se
  resuelve con una tabla (dict u objeto).
- **La lista es larga** (734 funciones al ponerla): el techo protege lo nuevo y obliga a que lo viejo no empeore;
  no arregla lo viejo. Bajarlo es trabajo aparte, función por función, empezando por las de `--report`.
- **Los nombres de las funciones anónimas** llevan un número de orden (`(map callback) #2`): si se agrega una antes,
  la de la lista cambia de número y aparece como «NO EXISTE» + «NUEVA». `--update` lo traslada si el número de
  complejidad es el mismo; si además cambió, hay que darle nombre a la función (mejor de todos modos).
- **El renombre** se detecta solo por archivo y número: dos funciones de la lista con el mismo número en el mismo
  archivo no se trasladan solas.
- **Python 3.11**: `python/enso/hazardparse.py` usa comillas repetidas dentro de un f-string (PEP 701, Python 3.12),
  así que en 3.11 no se analiza; la revisión sale con 2 y lo dice. CI usa 3.12.
