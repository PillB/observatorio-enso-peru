# Atribución y licencias — Observatorio ENSO Perú

> Formal Spanish. Atribución requerida de cada fuente y licencia del
> código del observatorio.

## 1. Política de atribución

El Observatorio ENSO Perú es un servicio de divulgación científica que
reutiliza datos públicos de instituciones oficiales. Cada fuente se
atribuye explícitamente en:

- El catálogo de fuentes (`docs/catalogo-fuentes.md`).
- El registro de fuentes en código (`python/enso/sources.py` y
  `src/lib/enso/sources.ts`).
- Los CSV emitidos por el pipeline (cabecera `# source_id=`,
  `# climatology=`, etc.).
- Las respuestas del asistente (cada evidencia cita la institución y la
  URL de la fuente).

## 2. Fuentes y licencias

### 2.1 NOAA (EE. UU.)

**Productos**: ENSO Diagnostic Discussion, RONI, ENSO Evolution PDF,
PSL Niño 1+2/3.4/SOI, GODAS (D20), u850 (NCEP/NCAR Reanalysis), PMEL
TAO/TRITON.

**Licencia**: dominio público (trabajo del Gobierno de EE. Uu.). Los
productos de NOAA son de dominio público y pueden reutilizarise con
atribución.

**Atribución recomendada**: «NOAA / CPC» o «NOAA / PSL» según
corresponda, con la URL del producto.

### 2.2 ENFEN / IMARPE (Perú)

**Productos**: ICEN y estado de alerta costera.

**Licencia**: datos abiertos institucionales (atribución requerida).

**Atribución recomendada**: «Comisión Multisectorial ENFEN / IMARPE
(SIOFEN)», con la URL `https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen`.

### 2.3 SENAMHI (Perú)

**Productos**: Seguimiento del Fenómeno El Niño.

**Licencia**: datos abiertos institucionales (atribución requerida).

**Atribución recomendada**: «SENAMHI Perú», con la URL
`https://www.senamhi.gob.pe/?p=fenomeno-el-nino`.

### 2.4 IGP (Perú)

**Productos**: Índices climáticos (ENFEN, IGP).

**Licencia**: datos abiertos institucionales (atribución requerida).

**Atribución recomendada**: «IGP Perú», con la URL
`http://met.igp.gob.pe/variabclim/indices.html`.

## 3. Atribución en artefactos

Cada CSV emitido por el pipeline incluye una cabecera con la atribución:

```
# indicator_id=nino12
# source_id=noaa-psl-nino12-anom
# climatology=PSL 1981–2010
# sign_convention=Anomalía respecto a la climatología. Positiva ⇒ más cálido que lo normal.
```

El `sources.json` exporta el registro completo con `attribution`,
`license`, `url` y `retrievalDate` por cada fuente.

## 4. Atribución en el asistente

Cada evidencia del asistente incluye:

- `evidenceId` (p. ej. `EVID-nino34`).
- `source`: «NOAA / PSL — Niño 3.4 SST Index — ERSST v5».
- `sourceUrl`: URL canónica de la fuente.
- `retrievalDate`: fecha de verificación.

El usuario puede trazar cada afirmación hasta la fuente original.

## 5. Licencia del código del observatorio

El código del observatorio (frontend, pipeline Python, tests, CI,
documentación) se publica bajo licencia **MIT** (ver `LICENSE` si está
presente, o el encabezado del repositorio). Esto permite reutilización
con atribución.

> Nota: si el repositorio no incluye un archivo `LICENSE`, se recomienda
> añadir uno (MIT o Apache-2.0) antes del despliegue público.

## 6. Uso aceptable

- **Permitido**: reutilizar, adaptar y distribuir los datos y el código
  con atribución.
- **No permitido**: presentar los datos del observatorio como servicio
  oficial de alerta; usar las marcas de las instituciones fuente de
  forma que sugiera respaldo oficial al observatorio.
- **Recomendado**: enlazar a las fuentes originales para que los
  usuarios verifiquen los datos.

## 7. Exención de responsabilidad

El observatorio se ofrece «tal cual», sin garantías. Los datos pueden
contener errores o estar desactualizados. Para decisiones operativas,
consultar las fuentes oficiales directamente. El observatorio no se
responsabiliza por decisiones tomadas con base en su contenido.

## 8. Contacto

Para preguntas sobre atribución o licencias, abrir un issue en el
repositorio del proyecto. Para preguntas sobre los datos, contactar a
la institución fuente correspondiente (ver
`docs/catalogo-fuentes.md`).
