"""Catálogo histórico de desastres en el Perú (la pestaña «Memoria de desastres»).

Reúne eventos pasados (inundaciones, huaycos, lluvias intensas, sequías, heladas, oleajes…) de fuentes
con procedencia citada, los ubica en su UBIGEO y les asigna la fase ENSO del mes en que ocurrieron,
para responder a una pregunta concreta: **si vuelve a ocurrir un Niño como los anteriores, ¿dónde
golpeó antes y con qué frecuencia?**

* ``esquema``: columnas del catálogo (las del equipo de gestión del riesgo más metadatos de análisis)
  y la clasificación de peligros.
* ``territorio``: tabla de distritos (nombres, coordenadas, altitud, población, pobreza) y resolución
  de nombres a UBIGEO.
* ``fuentes``: lectores de cada fuente (DesInventar, registros curados con cita).
* ``enso``: fase ENSO de cada mes (ICEN del ENFEN y ONI de NOAA) y nombre del evento.
* ``indicadores``: recurrencia, probabilidad anual, razón de tasas en El Niño, impactos y un índice
  relativo de priorización por departamento, provincia y distrito.

El catálogo se construye con ``python -m tools.build_historico`` y se publica en
``public/assets/historico/``; ver ``docs/memoria-desastres.md``.
"""
