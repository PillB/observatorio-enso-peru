# Recolector desde el Perú: imagen mínima que corre todos los días a la hora
# de Lima indicada en ENSO_COLLECT_AT (21:00 por defecto). Ver docs/servidor-peru.md.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Lima PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# Misma estructura que el repositorio (el pipeline busca config/ dos niveles arriba).
WORKDIR /app/python
COPY python/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY config /app/config
COPY python/enso ./enso
COPY python/tools ./tools

RUN useradd --create-home collector
USER collector

ENTRYPOINT ["python", "-m", "tools.peru_collector"]
CMD ["--daemon", "--push", "--dispatch"]
