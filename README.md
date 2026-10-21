# Observatorio ENSO Perú

Sitio público que reúne, cada día, los indicadores oficiales de El Niño y
La Niña que importan para el Perú: el estado del ENFEN, el ICEN, la
temperatura del mar en las regiones Niño, el RONI de NOAA, los vientos
alisios, el Índice de Oscilación del Sur y el contenido de calor del
océano. Está pensado para el público general y para equipos de gestión
del riesgo de desastres.

**Sitio:** https://pillb.github.io/observatorio-enso-peru/ (o la dirección de la
variable `SITE_URL` si se publica en Cloudflare Pages; ver
[despliegue-cloudflare](docs/despliegue-cloudflare.md)).

> El observatorio no emite alertas. Los avisos oficiales en el Perú son
> los comunicados del ENFEN; ante una emergencia siga a INDECI y a su
> gobierno local.

## Qué hay en el repositorio

| Carpeta | Contenido |
|---|---|
| `python/enso/` | Pipeline: descarga, valida, clasifica y publica los datos |
| `python/enso/feeds/` | Lectores de cada formato (NOAA/CPC, IGP, ENFEN) |
| `python/tests/` | Pruebas unitarias, backtesting de formatos y recorridos de navegador |
| `python/tests/fixtures/` | Respuestas reales capturadas de las fuentes, actuales e históricas |
| `python/tools/` | Captura de fuentes, verificación del sitio en vivo, sincronización de incidencias |
| `public/` | Sitio estático (HTML, CSS y JavaScript sin dependencias) |
| `config/threshold-policies/` | Umbrales ICEN 2024 y la tabla del equipo GRD, con su imagen original |
| `collector/` | Recolector desde el Perú: instaladores para Windows, macOS y Linux, lanzadores de doble clic, Docker y systemd |
| `.github/workflows/` | Actualización diaria, vigilante, CI y captura de fuentes |
| `docs/` | Documentación (ver abajo) |

`public/data/` no se versiona: lo genera el pipeline en cada corrida.

## Ejecutar en local

```bash
cd python
pip install -r requirements-dev.txt

# Publicación sin red, a partir de las respuestas capturadas
python -m enso.observatory --out ../public/data --previous '' --fixtures tests/fixtures/sources

# Publicación con datos en vivo
python -m enso.observatory --out ../public/data

# Servir el sitio
python -m http.server -d ../public 8000
```

Pruebas:

```bash
cd python
pytest -q                                   # unitarias y backtesting
python -m playwright install chromium
pytest -q -m browser --site-dir=../public   # recorridos de navegador
```

## Documentación

- [Arquitectura y contrato de datos](docs/arquitectura.md)
- [Metodología e indicadores](docs/metodologia.md)
- [Catálogo de fuentes](docs/catalogo-fuentes.md)
- [Operación diaria, incidencias y recuperación](docs/operaciones.md)
- [Recolector desde el Perú (mini servidor)](docs/servidor-peru.md): kit descargable, instalación en Windows y macOS, verificación y alarmas
- [Publicar en Cloudflare Pages sin enlace al repositorio](docs/despliegue-cloudflare.md)
- [Georreferenciación y consola de lugares](docs/georreferenciacion.md): dónde ocurre cada noticia, con qué confianza, y cómo corregirlo
- [Limitaciones conocidas](docs/limitaciones.md)
- [Atribución y licencias](docs/atribucion-licencias.md)
- [Requisitos del propietario](docs/requisitos-del-propietario.md)

## Licencia

Código bajo licencia MIT. Los datos pertenecen a sus instituciones de
origen (NOAA es dominio público; ENFEN e IGP requieren atribución). Ver
[atribución y licencias](docs/atribucion-licencias.md).
