"""Observatorio ENSO Perú: adquisición, validación y publicación de datos.

Módulos:
    feeds        lectores tolerantes a cambios de formato (NOAA/CPC, ENFEN, IGP).
    fetch        descarga defensiva con canales alternativos y procedencia.
    signals      señal operativa del equipo GRD y categorías científicas.
    observatory  orquestador de la publicación diaria (``python -m enso.observatory``).
"""

__version__ = "4.0.0"
