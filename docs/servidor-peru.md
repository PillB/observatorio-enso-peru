# Recolector desde el Perú (mini servidor)

SENAMHI, ANA e IMARPE no responden a GitHub Actions y el portal del ENFEN
no resuelve desde allí (ver [catálogo de fuentes](catalogo-fuentes.md)).
El recolector (`python/tools/peru_collector.py`) corre en una máquina que
sí llega a esas fuentes, guarda cada respuesta original y la sube a la
rama `data-peru`. La actualización diaria la usa como canal «relay-peru»:
cuando una URL no responde, toma la copia que el recolector bajó de esa
misma URL, comprueba su sha256 y su antigüedad, y la marca en el registro
de fuentes y en el sitio («vía recolector en el Perú»).

## Cómo encaja en el día

| Hora (Lima) | Qué pasa |
|---|---|
| 21:00 | El recolector descarga el listado y los PDF del ENFEN (incluidos los sondeos de los dos números siguientes) y las páginas de SENAMHI, ANA e IMARPE, y sube la copia a `data-peru` |
| 21:00 + unos minutos | Con `--dispatch`, pide a GitHub la actualización del sitio en el momento |
| 23:37 | Corrida diaria habitual; vuelve a usar la copia de las 21:00 si la fuente sigue sin responder |

Si la última copia tiene más de 36 horas, la corrida diaria registra la
incidencia `relay-stale` (se abre un issue). Copias de más de 7 días no se
usan. Si la rama `data-peru` no existe, el sitio funciona igual que antes.

Las páginas de SENAMHI, ANA e IMARPE quedan guardadas para construir y
probar sus lectores; todavía no alimentan indicadores del sitio.

## Dónde correrlo

**Paso 1, siempre:** comprobar el acceso desde la máquina candidata.

```bash
cd python && pip install -r requirements.txt
python -m tools.peru_collector --probe
```

Muestra `OK` o `NO` por cada URL. Sirve solo una máquina donde las fuentes
peruanas den `OK`.

| Opción | Costo | A favor | En contra |
|---|---|---|---|
| **Equipo en el Perú** (PC, laptop o Raspberry Pi en casa u oficina) — recomendado | Luz (una Raspberry Pi consume ~5 W) | IP peruana residencial: es lo que las fuentes aceptan; sin cuentas en la nube | Depende de que el equipo esté encendido y con internet a las 21:00 |
| Oracle Cloud Always Free (región Santiago, Bogotá o São Paulo) | Gratis | Siempre encendido | No hay región en Lima; una IP de centro de datos fuera del Perú puede estar bloqueada igual. Usar solo si `--probe` da `OK` desde allí. La región de la capa gratuita se fija al crear la cuenta |
| AWS Local Zone Lima | De pago (no entra en la capa gratuita) | IP en Lima | Costo mensual; también es IP de centro de datos |
| Ejecutor propio de GitHub Actions en el Perú | Gratis | Integra con Actions | **No recomendado**: en un repositorio público, cualquier PR podría ejecutar código en esa máquina |

Google Cloud ofrece su máquina gratuita solo en regiones de EE. UU., que
tienen el mismo problema que GitHub Actions.

## Token de GitHub

Crear un token de grano fino en GitHub → Settings → Developer settings →
Fine-grained tokens:

- Repository access: **solo** `PillB/observatorio-enso-peru`.
- Permissions → Repository → **Contents: Read and write** (alcanza para
  subir a `data-peru` y para `--dispatch`).
- Vencimiento: 1 año; anotar la fecha para renovarlo.

El token nunca se guarda en el repositorio.

## Instalación

### Docker (cualquier sistema)

```bash
echo "GITHUB_TOKEN=github_pat_..." > collector/.env
docker compose -f collector/docker-compose.yml up -d --build
docker compose -f collector/docker-compose.yml logs -f   # ver la próxima hora de recolección
```

La imagen usa la hora de Lima y se reinicia sola. Para probar una vez:
`docker compose -f collector/docker-compose.yml run --rm enso-collector --once --push`.

### Linux o Raspberry Pi con systemd

```bash
sudo useradd --system --create-home enso
sudo git clone https://github.com/PillB/observatorio-enso-peru /opt/observatorio-enso-peru
sudo python3 -m venv /opt/observatorio-enso-peru/.venv
sudo /opt/observatorio-enso-peru/.venv/bin/pip install -r /opt/observatorio-enso-peru/python/requirements.txt
echo "GITHUB_TOKEN=github_pat_..." | sudo tee /etc/enso-collector.env && sudo chmod 600 /etc/enso-collector.env
sudo cp /opt/observatorio-enso-peru/collector/enso-collector.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now enso-collector.timer
systemctl list-timers enso-collector.timer      # próxima corrida
sudo systemctl start enso-collector.service     # probar ahora
journalctl -u enso-collector.service -n 50      # registro
```

El temporizador usa la zona `America/Lima` aunque el equipo tenga otra, y
`Persistent=true` recupera la corrida si estaba apagado a las 21:00.

### Windows

Instalar Python 3.12, clonar el repositorio y, en PowerShell dentro de él:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -r python\requirements.txt
[Environment]::SetEnvironmentVariable("GITHUB_TOKEN", "github_pat_...", "User")
powershell -ExecutionPolicy Bypass -File collector\windows-tarea.ps1
```

La tarea corre a las 21:00 de la hora del equipo (que debe ser la de Lima)
y, si estaba apagado, al encenderlo.

## Mantenimiento

- Actualizar el código: `git pull` en la carpeta (o `up -d --build` con
  Docker). Las URL del recolector deben coincidir con las del catálogo del
  pipeline; una prueba lo verifica.
- Si una fuente cambia de dirección, se edita `SOURCES` en
  `peru_collector.py` y en `observatory.py`.
- La rama `data-peru` guarda solo la última copia; el historial de git
  conserva las anteriores y la rama `data-archive` archiva lo que se usó.
