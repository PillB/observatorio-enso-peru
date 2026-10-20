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

## Datos que no se muestran

- **D20:** no hay una fuente pública verificada (ver Metodología).
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

Los servidores del ENFEN no siempre son accesibles desde GitHub Actions.
Entonces se usan copias del Internet Archive, que pueden llegar con horas
de retraso. Si ninguna vía funciona, el estado se muestra como vencido.

## Transición a ERSSTv6

NOAA está pasando de ERSSTv5 a ERSSTv6. El archivo ERSSTv5 del CPC puede
dejar de actualizarse; en ese caso la incidencia `stale-*` lo avisará y
habrá que incorporar el archivo v6.
