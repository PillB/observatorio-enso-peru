# Comparativa de fuentes gratuitas vs pagadas — Observatorio ENSO Perú

> Formal Spanish. Análisis comparativo de fuentes de datos ENSO
> gratuitas y pagadas, con justificación de la selección.

## 1. Criterios de selección

El observatorio prioriza fuentes que cumplan:

1. **Acceso público gratuito** (preferente).
2. **Autoridad científica reconocida** (NOAA, ENFEN/IMARPE, SENAMHI,
   IGP).
3. **Licencia clara** que permita reutilización con atribución.
4. **Endpoint estable** y esquema documentado.
5. **Cobertura histórica suficiente** (≥ 30 años para climatología).
6. **Frecuencia de actualización** acorde al monitoreo operacional.

## 2. Fuentes gratuitas adoptadas

Todas las fuentes del observatorio son **gratuitas y públicas**:

| Fuente | Producto | Acceso | Licencia |
|--------|----------|--------|----------|
| NOAA / CPC | ENSO Diagnostic Discussion | HTML público | Dominio público (EE. UU.) |
| NOAA / CPC | RONI | HTML + tablas | Dominio público |
| NOAA / CPC | ENSO Evolution PDF | PDF público | Dominio público |
| NOAA / PSL | Niño 1+2, Niño 3.4, SOI | CSV/texto público | Dominio público |
| NOAA / CPC | GODAS (D20) | NetCDF/gráficos | Dominio público |
| NOAA / CPC | u850 (NCEP/NCAR Reanalysis) | HTML/derivados | Dominio público |
| NOAA / PMEL | TAO/TRITON | NetCDF/boya | Dominio público |
| ENFEN / IMARPE | ICEN + alerta costera | HTML/panel | Datos abiertos institucionales |
| SENAMHI Perú | Seguimiento El Niño | HTML | Datos abiertos institucionales |
| IGP | Índices climáticos | HTML | Datos abiertos institucionales |

## 3. Fuentes pagadas (no adoptadas) — comparativa

| Fuente pagada | Producto | Razón para no adoptar |
|---------------|----------|-----------------------|
| Climate Data Online (CDO) premium de NOAA | Acceso prioritario / bulk | La versión gratuita de PSL/CPC es suficiente para los indicadores del observatorio. |
| Copernicus CDS (ERA5) | Reanálisis atmosférico avanzado | NCEP/NCAR Reanalysis (gratuito) cubre u850; ERA5 es superior pero requiere cuenta y tiene cuotas. |
| Mercator Ocean (Copernicus Marine) | TSM/termoclina operacional | GODAS + PSL cubren las necesidades; Mercator es de pago para uso intensivo. |
| IRI Data Library (premium) | Múltiples índices | La librería pública es suficiente; el tier premium no aporta indicadores nuevos para el observatorio. |
| Servicios comerciales de pronóstico ENSO | Pronósticos estacionales | El observatorio no emite pronósticos; no los necesita. |

## 4. Justificación de la selección 100% gratuita

- **Sostenibilidad**: un servicio gratuito es sostenible a largo plazo
  sin depender de presupuestos de suscripción.
- **Reproducibilidad**: cualquier persona puede reproducir los datos
  del observatorio desde las fuentes públicas.
- **Atribución clara**: todas las fuentes son instituciones oficiales
  con políticas de atribución explícitas.
- **Cobertura suficiente**: las fuentes gratuitas cubren todos los
  indicadores necesarios (costero y de cuenca, superficie y
  subsuperficie, océano y atmósfera).

## 5. Brechas y mitigaciones

| Brecha | Mitigación |
|--------|------------|
| Cobertura irregular de TAO/TRITON | Preservar NaN; no rellenar. |
| Latencia semanal/mensual de algunas fuentes | Marcar `stale` y mostrar la fecha de corte. |
| Diferencias de baseline (ONI vs RONI) | Documentar y usar RONI como operacional. |
| Cambios de esquema en endpoints | Validación estricta + preservación del último válido. |
| Caída temporal de una fuente | Respaldo declarado (`fallbackSourceId`) + caché. |

## 6. Conclusión

El observatorio opera exclusivamente con fuentes públicas y gratuitas de
instituciones científicas oficiales. Esto garantiza sostenibilidad,
reproducibilidad y atribución clara. Las fuentes pagadas evaluadas no
aportan indicadores nuevos necesarios para el monitoreo costero vs
cuenca del observatorio.
