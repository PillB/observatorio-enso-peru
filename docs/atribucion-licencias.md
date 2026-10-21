# Atribución y licencias

## Datos

| Institución | Productos usados | Condición |
|---|---|---|
| NOAA / CPC (EE. UU.) | ENSO Diagnostic Discussion, RONI, ONI, TSM por región (OISST v2.1 y ERSSTv5), SOI, presiones de Tahití y Darwin, vientos a 850 hPa, contenido de calor (GODAS) | Dominio público; se cita «NOAA / CPC» con la URL del producto |
| ENFEN (Perú) | Comunicados oficiales | Se cita «Comisión Multisectorial ENFEN» con el enlace al comunicado |
| IGP (Perú) | ICEN | Se cita «ENFEN / IGP» con `met.igp.gob.pe/datos/ICEN.txt` |
| Bureau of Meteorology (Australia) | SOI archivado, solo para validar | No se republica |
| Natural Earth | Línea de costa del mapa | Dominio público |
| Instituto Geográfico Nacional (IGN), vía OCHA HDX (`cod-ab-per`) | Límites de distritos, provincias y departamentos para ubicar coordenadas (`python/enso/data/limites-ign.json.gz`, simplificados) | CC BY-IGO; se cita «IGN, vía OCHA HDX» |
| INEI, compilado por J. M. Castagnetto (`ubigeo-peru-aumentado`) | Códigos UBIGEO, nombres y capitales (`python/enso/data/ubigeo.json`) | MIT; DOI 10.5281/zenodo.4589185 |

Dónde aparece la atribución:

- En cada tarjeta y gráfico del sitio (fuente, periodo y fecha de
  descarga).
- En `sources.json` y `sources/*.json`: URL usada, canal, fecha de
  descarga y SHA-256 de la respuesta original.
- En cada CSV, en las columnas `fuente` y `publicacion`.
- En las respuestas del asistente, que citan la serie y la publicación
  de cada dato.

## Impactos históricos

Los textos sobre impactos de eventos pasados en el Perú citan sus fuentes
en el propio sitio (por ejemplo, Yglesias-González et al., 2023, PLoS
ONE).

## Código

El código se publica bajo licencia MIT (ver `LICENSE`).

## Uso aceptable

Se pueden reutilizar los datos y el código con atribución. No se debe
presentar el observatorio como servicio oficial de alerta ni usar las
marcas de las instituciones de modo que sugiera su respaldo. El
observatorio se ofrece tal cual, sin garantías; para decisiones
operativas, consulte las fuentes oficiales.
