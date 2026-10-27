# Atribución y licencias

## Datos

| Institución | Productos usados | Condición |
|---|---|---|
| NOAA / CPC (EE. UU.) | ENSO Diagnostic Discussion, RONI, ONI, TSM por región (OISST v2.1 y ERSSTv5), SOI, presiones de Tahití y Darwin, vientos a 850 hPa, contenido de calor (GODAS) | Dominio público; se cita «NOAA / CPC» con la URL del producto |
| ENFEN (Perú) | Comunicados oficiales | Se cita «Comisión Multisectorial ENFEN» con el enlace al comunicado |
| IGP (Perú) | ICEN | Se cita «ENFEN / IGP» con `met.igp.gob.pe/datos/ICEN.txt` |
| Bureau of Meteorology (Australia) | SOI archivado, solo para validar | No se republica |
| Natural Earth | Línea de costa del mapa | Dominio público |
| INDECI, GEOSINPAD (límites administrativos) | Límites de distritos, provincias y departamentos para ubicar coordenadas (`python/enso/data/limites-ign.json.gz`, simplificados), dibujar el mapa de alertas (`public/assets/peru-map.json`) y el de la memoria de desastres (`public/assets/historico/mapa.json`), y dar un punto interior a los distritos sin capital en el nomenclátor | Información pública del Estado peruano (Ley N° 27806); se cita «INDECI (GEOSINPAD)» |
| INEI, compilado por J. M. Castagnetto (`ubigeo-peru-aumentado`) | Códigos UBIGEO, nombres y capitales (`python/enso/data/ubigeo.json`) | MIT; DOI 10.5281/zenodo.4589185 |

Dónde aparece la atribución:

- En cada tarjeta y gráfico del sitio (fuente, periodo y fecha de
  descarga).
- En `sources.json` y `sources/*.json`: URL usada, canal, fecha de
  descarga y SHA-256 de la respuesta original.
- En cada CSV, en las columnas `fuente` y `publicacion`.
- En las respuestas del asistente, que citan la serie y la publicación
  de cada dato.

## Memoria de desastres

El catálogo histórico (`public/assets/historico/`, [memoria-desastres](memoria-desastres.md)) junta 66 fuentes; la
licencia de cada una está en `data/historico/fuentes.json` y cada fila del catálogo la repite en la columna `Licencia`,
con su enlace en `Fuente` y la cita legible en `FuenteCita`.

| Institución o fuente | Productos usados | Condición |
|---|---|---|
| DesInventar Sendai (UNDRR / Corporación OSSO) | Base de pérdidas del Perú, 1970-2015 | Uso libre con atribución |
| INDECI | SINPAD (portal público desde 2019 y la copia 2015-2018 subida por terceros a ArcGIS Online, no oficial) y reportes del COEN | Información pública (Ley N° 27806); se cita el INDECI con el enlace a cada emergencia o reporte |
| IDMC | Desplazamientos por desastres (IDU y eventos) | **CC BY-NC-SA 3.0 IGO**: las filas con `Origen = idmc` no se pueden usar con fines comerciales y lo que se derive de ellas se comparte con la misma licencia |
| El Peruano | Declaratorias de emergencia y sus prórrogas | Normas legales, dominio público (D. Leg. 822, art. 9) |
| INGEMMET, IGP, ANA, MINSA (vía CENEPRED) | Inventarios y zonas críticas, informes técnicos, puntos críticos, establecimientos de salud afectados en 2023 | Información pública (Ley N° 27806) |
| NASA | Global Landslide Catalog | Dominio público; se cita Kirschbaum et al. (2010, 2015) |
| Lützow y Veh (Zenodo) | Glacial Lake Outburst Flood Database v4.2 | CC BY 4.0; doi:10.5281/zenodo.23370149 |
| IFRC GO | Llamamientos y DREF | Datos públicos; se cita a la Federación Internacional de la Cruz Roja |
| 44 medios en línea (RPP, Exitosa, Caretas y medios regionales) | Titular, fecha y extracto de hasta 200 caracteres de cada nota, con su enlace | Cita (D. Leg. 822, art. 44); el texto completo es del medio y no se redistribuye |
| Chronicling America (Biblioteca del Congreso de EE. UU.) | Páginas de periódicos de 1836 a 1963: metadatos y extracto OCR de hasta 200 caracteres con enlace | Dominio público o sin restricciones conocidas |
| Estudios históricos (García-Herrera et al., Eguiguren, PIRCC 2017) | Registros curados, cada uno con su cita | Cada registro cita su fuente; los de antes de 1900 son de dominio público |

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
