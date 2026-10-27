# Semillas del catálogo histórico

Copias de fuentes que un programa no puede volver a bajar sin una clave, para que `tools/build_historico` y la cosecha
de GitHub Actions (`.github/workflows/memoria-cosecha.yml`) funcionen sin ella. Cada una figura en
`data/historico/fuentes.json` (campo `semilla`) y se descomprime en la caché solo si falta la clave; su SHA-256 es el
del manifiesto.

| Archivo | Fuente | Licencia |
|---|---|---|
| `idmc-idu-per.csv.gz` | Internal Displacement Monitoring Centre (IDMC), actualizaciones de desplazamiento interno (IDU) del Perú: la exportación del IDMC publicada en HDX (https://data.humdata.org/dataset/per-idmc-idu-events), 26-10-2026 | CC BY-NC-SA 3.0 IGO, © IDMC |
| `idmc-desplazamientos-desastres-per.csv.gz` | IDMC, desplazamientos nuevos asociados a desastres en el Perú (https://data.humdata.org/dataset/idmc-idp-data-per), 26-10-2026 | CC BY-NC-SA 3.0 IGO, © IDMC |

Con la clave de la API del IDMC (`IDMC_CLIENT_ID`; ver `docs/memoria-desastres.md`) se piden datos al día y no se usan.
