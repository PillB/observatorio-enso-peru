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
| INEI (Censos Nacionales 2017), IGN y SDOT-PCM, vía el geoportal de la IDEP (PCM) | Centros poblados con su punto, categoría y código, para ubicar un aviso o un registro dentro de su distrito (`python/enso/data/lugares.json.gz`) | Información pública del Estado peruano (Ley N° 27806); se cita la institución y la capa de la IDEP |
| ANA, vía el geoportal de la IDEP (PCM) | Unidades hidrográficas (metodología Pfafstetter, R.M. N° 033-2008-AG) para la cuenca de cada punto y la capa de cuencas de los dos mapas (`python/enso/data/cuencas.json.gz`, `public/assets/cuencas-mapa.json`) | Información pública (Ley N° 27806); se cita «ANA» |
| IGN, Carta Nacional 1:100 000, vía el geoportal de la IDEP (PCM) | Ríos, quebradas, lagunas, nevados, volcanes y abras con nombre (capas «Río Lineal», «Lago y Laguna» y «Toponimia» de `PERU_100K`), para ubicar un aviso o un registro que nombra uno de ellos dentro de su distrito y dar su cuenca (`python/enso/data/aguas.json.gz`); y el trazo de los 405 ríos, quebradas y lagunas que nombran los registros, en la vista de detalle del mapa de la memoria (`public/assets/capas/rios-mapa.json`) | Información pública del Estado peruano (Ley N° 27806); se cita «IGN, Carta Nacional 1:100 000» y la capa de la IDEP |
| CENEPRED, SIGRID (escenario de riesgo ante El Niño 2026-2027, servicio `sectores/COEN_FEN_2027`, capas 57, 58 y 61), con población y viviendas del censo 2017 (INEI) por manzana | Manzanas de Piura, Tumbes y Lambayeque con su nivel de riesgo: el punto central, el distrito, el centro poblado, el nivel y la población y las viviendas de la manzana, en la vista «Daños y pobreza» del mapa de la memoria (`public/assets/capas/manzanas-riesgo.json`). Solo esos campos agregados por manzana: ninguna capa con datos de personas | Información pública (Ley N° 27806); se cita «CENEPRED (SIGRID)» con el enlace al servicio. El robots.txt del SIGRID prohíbe `/arcgis/`: por decisión del proyecto para instituciones públicas peruanas se consulta igual, con 5 s entre pedidos (ver `docs/memoria-desastres.md`) |
| SENAMHI, vía GEOSINPAD (INDECI) | Polígonos de los avisos de precipitación y de peligro de incendios, quebradas por distrito y estaciones hidrológicas, dibujados en el mapa de alertas | Información pública (Ley N° 27806); cada aviso enlaza su consulta a la capa |
| Global Volcanism Program, Smithsonian Institution | Coordenadas de la cumbre de 14 volcanes del sur del Perú (`python/enso/hazardparse.py`, `VOLCANO_POINTS`) | Se cita «Global Volcanism Program, Volcanoes of the World (Smithsonian Institution)» con el enlace a la ficha de cada volcán |

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
| INDECI | SINPAD (portal público desde 2019 y la copia 2015-2018 subida por terceros a ArcGIS Online, no oficial), la capa de emergencias del GEOSINPAD (cifras de la evaluación de daños, EDAN, y punto de cada emergencia desde 2016) y reportes del COEN | Información pública (Ley N° 27806); se cita el INDECI con el enlace a cada emergencia o reporte, y «evaluación (EDAN) del SINPAD, capa de emergencias del GEOSINPAD (INDECI)» en cada fila que trae sus cifras |
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
