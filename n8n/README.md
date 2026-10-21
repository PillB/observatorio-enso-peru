# Flujos de n8n

Canal alternativo al servidor del Perú para las fuentes **no** geobloqueadas:
el n8n del colega (AWS, EE. UU.) descarga las fuentes del registro
(`registry/sources.json`) y publica las copias en la rama `data-n8n`, con el
mismo formato que el recolector del Perú. La actualización diaria las usa
cuando una fuente no responde a GitHub Actions (canal «relay-n8n»).

Instalación, configuración y operación: [docs/n8n.md](../docs/n8n.md).

| Carpeta | Qué hay |
|---|---|
| `lib/` | Código que corre dentro de los nodos Code: clasificador de respuestas y bloqueos, SHA-256/SHA-1, PDF del ENFEN, armado de la copia |
| `nodes/` | Cuerpo de cada nodo Code |
| `build.mjs` | Arma `dist/*.json` (los flujos a importar) desde `lib/`, `nodes/` y el registro |
| `dist/` | Flujos listos para importar. **No editar**: se regeneran con `node n8n/build.mjs` |
| `test/` | Pruebas (`node --test n8n/test/*.test.mjs`), API de GitHub falsa y prueba de punta a punta con n8n real (`test/e2e.sh`) |
| `tools/probe.mjs` | El mismo sondeo, sin n8n, desde cualquier máquina con Node |

Regla: los nodos Code no se editan en la interfaz de n8n. Se cambia el
código aquí, se prueba, se vuelve a construir y se vuelve a importar.
