# Límites departamentales

`departamentos.geojson`: los 25 departamentos (Callao incluido) de la capa
`SDE.DEPARTAMENTOS` del servicio de límites administrativos del INDECI:

    https://geosinpad.indeci.gob.pe/indeci/rest/services/LimitesAdministrativos/limitesAdministrativos/MapServer/2/query
      ?where=1=1&outFields=*&returnGeometry=true&outSR=4326&maxAllowableOffset=0.01&geometryPrecision=3&f=geojson

Bajada por `tools.scrape_ladder` desde GitHub Actions el 21 de octubre de 2026
(el servidor no responde al contenedor de desarrollo). Simplificada por el
propio servidor a ~1 km (0,01°) y con 3 decimales; se conservan solo
`UBI_DEP` (UBIGEO) y `NOMBDEP`. Información pública del Estado peruano.

Frente a los departamentos que el INPE asigna a sus focos de calor del 20 de
octubre de 2026, `enso.geopoly.department_at` coincide en 399 de 401 y no ubica
en el Perú ninguno de los 259 focos de países vecinos del recuadro
(`tests/test_geopoly.py`).
