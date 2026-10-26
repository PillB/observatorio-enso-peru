# Limitaciones conocidas

## No es un servicio de alerta

El observatorio reúne y explica datos públicos. Los avisos oficiales en el
Perú son los comunicados del ENFEN; la respuesta ante emergencias la
coordinan INDECI, CENEPRED y los gobiernos regionales y locales. SENAMHI
emite los avisos meteorológicos.

## Retraso de los datos

- La TSM semanal llega con unos días de retraso; los índices mensuales,
  después de cerrar el mes.
- El ICEN se publica con un trimestre de retraso porque es una media de
  tres meses centrada.
- El estado oficial cambia solo cuando el ENFEN o NOAA publican.

## Profundidad de la termoclina (D20)

- Se calcula con GODAS (ver Metodología §7b) y llega unas dos semanas
  después de cerrado cada mes. Frente a la costa GODAS tiene pocas
  observaciones: el valor de Niño 1+2 es una estimación regional.
- La tabla GRD no dice qué producto usar; la elección del observatorio
  está pendiente de confirmación.

## Datos que no se muestran

- **Pronósticos:** no se reproducen los modelos; se enlaza a los
  pronósticos oficiales del ENFEN y de NOAA.
- **Mapa:** muestra el promedio medido de cada región Niño, no un campo
  interpolado.

## Señal del equipo GRD

La tabla tiene huecos (por ejemplo, entre +0,5 y +1,3 °C de TSM costera).
Esos valores quedan sin clasificar hasta que el equipo los defina. La
política está en estado borrador.

## SOI Troup

Se calcula con la base 1951–1992 de las presiones del CPC; BoM usa
1933–1992. La diferencia típica frente a BoM es de 0,7 unidades.

## Acceso a las fuentes

El portal del ENFEN no responde fuera del Perú (su nombre no resuelve
desde GitHub Actions ni desde n8n), y la réplica de la DHN, cuyo listado sí
responde, pide una verificación humana a los servidores para sus PDF
(también a n8n y al recolector del Perú); esa página se registra y nunca se
intenta pasar. El PDF del comunicado llega entonces de la copia más
reciente del [recolector desde el Perú](servidor-peru.md) (que sí alcanza
el portal), de n8n o de la [consola de documentos](documentos-manuales.md)
y, si no hay, del Internet Archive o del repositorio del IMARPE, que recibe
cada comunicado unos 3 días después
([catálogo de fuentes](catalogo-fuentes.md#cómo-se-obtiene-lo-más-reciente-del-enfen)).
Si ninguna vía funciona, el estado se muestra como vencido y el comunicado
queda pendiente en la consola de documentos.

Las páginas web del SENAMHI y de la ANA no responden a servidores fuera
del Perú; el recolector desde el Perú las descarga cada día a las 21:00 si
está instalado. De ellas el sitio usa hoy solo la tabla de avisos
meteorológicos del SENAMHI (`?p=aviso-meteorologico`): da el nivel y la
vigencia de esos avisos en el mapa de alertas ([mapa-alertas](mapa-alertas.md)).
Sin la copia del Perú, un aviso meteorológico queda «Sin nivel» salvo que
su texto cite el color, y con la vigencia que diga su texto. Las demás
páginas del SENAMHI y de la ANA se archivan, pero todavía no alimentan
indicadores. Del IMARPE, el repositorio no responde a GitHub Actions desde
el 22 de octubre de 2026 y sí desde el Perú: la sonda semanal asigna sus
búsquedas al recolector del Perú. Su sitio web responde a n8n; a Actions le
pide una verificación anti-robots (medido el 26 de octubre de 2026).

## ERSSTv6

NOAA dejó de actualizar ERSSTv5 en 2026. Las series mensuales largas de
Niño 1+2 y 3.4 usan ERSSTv6 de PSL llevado a la base 1991–2020, que no es
idéntico a lo que usa ENFEN para el ICEN; por eso no se publica un ICEN
propio.
