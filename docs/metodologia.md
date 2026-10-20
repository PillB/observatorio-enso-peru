# Metodología e indicadores

El observatorio no recalcula los índices oficiales: publica los valores
que difunden las instituciones, con su categoría y su antigüedad. Solo
calcula dos cosas propias, ambas documentadas aquí: el SOI en escala
Troup y la señal del equipo GRD.

## 1. Estado oficial

| Sistema | Fuente | Cuándo se actualiza |
|---|---|---|
| ENFEN (Perú) | Comunicado oficial más reciente (PDF) | Normalmente cada dos semanas; con más frecuencia durante un evento |
| NOAA (EE. UU.) | ENSO Diagnostic Discussion del CPC | Segundo jueves de cada mes |

El estado del ENFEN se lee del propio comunicado (tipo de alerta, número
y fecha) y la fecha del siguiente se toma del texto. Si se publica un
comunicado nuevo que no se pudo leer, o si pasa la fecha prevista del
siguiente, el estado se marca vencido. El de NOAA se marca vencido tres
días después del segundo jueves esperado.

## 2. ICEN (Índice Costero El Niño)

- **Qué es:** media corrida de tres meses de la anomalía de TSM en la
  región Niño 1+2 (0°–10°S, 90°–80°O), calculada por el ENFEN con
  ERSSTv5.
- **Climatología:** periodos de 30 años que se actualizan cada cinco
  años; la vigente es 1991–2020.
- **Fuente:** `met.igp.gob.pe/datos/ICEN.txt` (IGP, miembro del ENFEN).
- **Magnitudes** (Nota Técnica ENFEN 01-2024, vigente desde diciembre de
  2024), en °C:

| Categoría | Rango |
|---|---|
| Fría fuerte | < −1,3 |
| Fría moderada | −1,3 a < −1,1 |
| Fría débil | −1,1 a < −0,7 |
| Neutra | −0,7 a +0,5 |
| Cálida débil | > +0,5 a +1,3 |
| Cálida moderada | > +1,3 a +2,1 |
| Cálida fuerte | > +2,1 a +3,5 |
| Cálida extraordinaria | > +3,5 |

La tabla vive en `config/threshold-policies/enfen-icen-2024.yaml` y una
prueba verifica que el código la aplique igual.

**Eventos:** un evento El Niño (o La Niña) costero requiere al menos tres
meses consecutivos en condición cálida (o fría). Su magnitud es la máxima
alcanzada. El observatorio reconstruye la lista desde la serie publicada;
la prueba de backtesting confirma que coincide con el registro oficial
(1982–83 y 1997–98 extraordinarios, 2015–16 fuerte, 2017 moderado,
2023–24 fuerte).

## 3. Temperatura del mar por región

| Serie | Producto | Uso |
|---|---|---|
| Semanal Niño 1+2, 3, 3.4 y 4 | NOAA OISST v2.1, base 1991–2020 | Lo más reciente disponible (días de retraso); alimenta el mapa |
| Mensual por región | OISST v2.1 | Seguimiento mensual de las cuatro regiones y señal GRD |
| Mensual Niño 1+2 y 3.4 | NOAA ERSSTv6 (PSL), llevada de la base 1981–2010 a 1991–2020 | Serie larga desde 1950, la reconstrucción que NOAA usa para el RONI |

NOAA dejó de actualizar ERSSTv5 en 2026 (el último mes disponible es
junio). El cambio de base se hace restando, para cada mes del año, la
media de 1991–2020; frente a ERSSTv5 la diferencia media es de 0,2 °C en
Niño 1+2 y 0,14 °C en Niño 3.4.

**Por qué no hay un «ICEN estimado»:** una media de tres meses de
ERSSTv6 difiere del ICEN oficial hasta 0,7 °C (en agosto de 2026, 3,28
frente a 3,98) y coincide en la categoría solo el 71 % de los meses desde
1991. Mostrarlo confundiría la magnitud del evento, así que solo se
publica el ICEN oficial.

## 4. RONI y ONI

- **RONI** (Índice Oceánico Relativo de El Niño): índice oficial de NOAA
  desde el 1 de febrero de 2026. Es la anomalía de Niño 3.4 menos la
  anomalía media de los trópicos, reescalada; corrige la tendencia del
  calentamiento global.
- **ONI:** índice tradicional, se muestra solo como referencia.
- Umbral de condición El Niño o La Niña: ±0,5 °C en la media trimestral.
  NOAA declara un episodio cuando la condición persiste y la atmósfera
  responde; el observatorio muestra el estado que NOAA declara, no lo
  deduce.

## 5. Índice de Oscilación del Sur (SOI)

- Se publica el **SOI de NOAA/CPC** (estandarizado) y un **SOI en escala
  Troup** (×10), que es el que usa la tabla del equipo GRD.
- Troup se calcula con las presiones de Tahití y Darwin del CPC:
  `SOI = 10 × (ΔP − media mensual) / desviación mensual`, con
  `ΔP = Tahití − Darwin` y base 1951–1992 (el periodo común más largo en
  los archivos del CPC; BoM usa 1933–1992).
- Validación: frente a 64 meses del SOI mensual archivado de BoM, la
  diferencia media absoluta es 0,70 y la fase (±7) coincide.
- Negativo sostenido (< −7) acompaña a El Niño; positivo (> +7), a La Niña.

## 6. Vientos alisios

Índices del CPC a 850 hPa en el Pacífico occidental, central y oriental.
El signo sigue la convención del CPC: **positivo = viento del este**
(alisios reforzados); negativo = viento del oeste, típico del inicio o
refuerzo de El Niño.

## 7. Contenido de calor del océano

Índice del CPC (GODAS): anomalía de la temperatura media de los 300 m
superiores en tres franjas ecuatoriales (130°E–80°O, 160°E–80°O y
180°–100°O), base 1981–2010. Un aumento suele anticipar el calentamiento
en superficie.

**Por qué no se muestra la profundidad de la isoterma de 20 °C (D20):**
no hay una fuente pública que la publique como serie lista para usar. El
campo `dbss_obil` de GODAS es la profundidad de la capa isotérmica, no
D20, y usarlo como si lo fuera daría valores erróneos. Por eso la señal
GRD de termoclina figura como «sin dato» y se explica el motivo.

## 8. Señal del equipo GRD

Es una interpretación operativa basada en la tabla que entregó el equipo
de gestión del riesgo (imagen original y su SHA-256 en
`config/threshold-policies/`). **No es** el sistema oficial de alertas
del ENFEN ni el de NOAA, y el sitio lo dice junto a la señal.

| Indicador | Dato usado | Normal | Amarillo | Rojo |
|---|---|---|---|---|
| TSM costera | Anomalía mensual Niño 1+2 | −0,7 a +0,5 °C | +1,3 a +2,0 °C | > +2,1 °C |
| TSM de cuenca | Anomalía mensual Niño 3.4 | −0,5 a +0,5 °C | > +1,0 a +1,5 °C | > +1,5 °C |
| Vientos (costero y global) | Índice CPC 850 hPa oriental y central | Del este | — | Del oeste |
| Termoclina | D20 | −20 a +20 m | 30 a 50 m | > 50 m |
| SOI | Troup | −7 a +7 | — | < −7 |

Reglas:

- Un valor que cae en un hueco de la tabla (por ejemplo +1,0 °C en la TSM
  costera) queda **sin clasificar** y se explica por qué; nunca se pinta
  de verde.
- Un dato vencido o ausente no recibe color.
- La señal se calcula solo en el pipeline (`signals.py`); el navegador la
  muestra tal cual.

## 9. Frescura

Cada fuente tiene una cadencia y una antigüedad máxima aceptable del
último periodo observado (por ejemplo, 16 días para el semanal OISST y
100 días para el ICEN, que se publica con un trimestre de retraso). Pasado
ese límite el valor se marca vencido y se registra una incidencia.
