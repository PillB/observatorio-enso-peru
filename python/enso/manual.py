"""Documentos que hay que bajar a mano: los que ninguna ruta automática trae.

La réplica de la DHN responde con una verificación humana a GitHub Actions, a n8n y a veces al equipo del Perú,
y el portal del ENFEN no responde fuera del Perú. Cuando el comunicado más reciente o su informe técnico no se
pueden bajar por ninguna ruta, el pipeline los anota aquí:

- ``data/manual-needed.json`` (lo lee la consola de documentos, ``/admin/documentos.html``): cada documento con
  las URL que una persona puede abrir en su navegador (allí sí puede pasar la verificación) y las URL con que
  el pipeline lo busca;
- la incidencia ``manual-download-needed`` (advertencia), que abre un issue en GitHub.

La persona baja el PDF y lo sube en la consola; la consola lo guarda en la rama ``data-manual`` con el mismo
formato que el recolector del Perú (``enso-relay/1``, canal «relay-manual») y pide una actualización del
sitio. El pipeline lo lee con la misma URL que buscaba y lo valida como cualquier otra copia: si no es el
documento esperado (otro número, otro periodo, no es un PDF), no se publica y el documento sigue pendiente.
El pipeline nunca intenta pasar la verificación humana.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Optional

#: Prefijo de las URL sin dirección real (el informe de un comunicado cuando ningún listado responde).
KEY_PREFIX = "manual://"
#: Días que vale una copia subida a mano (un comunicado o un informe no cambia una vez publicado).
MAX_AGE_DAYS = 120

_CHALLENGE_RE = re.compile(r"verificaci[oó]n|challenge|captcha|human|antirobots", re.I)


def key(kind: str, ident: str) -> str:
    """URL sintética con que se guarda un documento que no tiene una URL conocida."""
    return f"{KEY_PREFIX}{kind}/{ident}"


def reason_from(attempts: Optional[list], default: str) -> str:
    """El motivo para la persona: verificación humana si algún intento la recibió; si no, ``default``."""
    for a in attempts or []:
        # Un PDF que responde 200 con una página web es la verificación humana de la DHN (o una parecida).
        page_for_pdf = a.get("status") == 200 and "tipo inesperado" in str(a.get("note") or "") \
            and str(a.get("url") or "").lower().endswith(".pdf")
        if page_for_pdf or _CHALLENGE_RE.search(" ".join(str(a.get(k) or "") for k in ("note", "error", "class"))):
            return "La réplica de la DHN pide verificación humana a los servidores automáticos y las demás rutas no dieron el PDF."
    return default


class ManualNeeds:
    """Lo que esta corrida no pudo bajar y una persona puede subir, y lo que se leyó de una copia subida."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.used: list[dict] = []

    def add(self, doc_id: str, kind: str, label: str, urls: list[str], open_urls: list[str], reason: str,
            expect: Optional[dict] = None, problem: Optional[str] = None) -> None:
        """``urls``: con las que el pipeline busca el documento (la primera es la principal, el resto alias);
        ``open_urls``: las que una persona abre en su navegador. ``problem``: por qué no valió una copia subida."""
        urls = list(dict.fromkeys(u for u in urls if u))
        if not urls:
            return
        item = self.items.setdefault(doc_id, {"id": doc_id, "kind": kind, "label": label, "urls": [], "open": [],
                                              "reason": reason})
        item["urls"] = list(dict.fromkeys(item["urls"] + urls))
        item["open"] = list(dict.fromkeys(item["open"] + [u for u in open_urls if u and not u.startswith(KEY_PREFIX)]))
        if expect:
            item["expect"] = expect
        if problem:
            item["problem"] = problem[:300]

    def mark_used(self, doc_id: str, label: str, url: str, at: Optional[str]) -> None:
        self.used.append({"id": doc_id, "label": label, "url": url, "uploadedAt": at})

    def log(self, log) -> None:
        """Una incidencia por documento (su propio issue de GitHub, con su aviso, que se cierra solo cuando ese
        documento ya no falta)."""
        for i in self.items.values():
            log.add("warning", f"manual-{i['id']}", "fetch", "manual-download-needed",
                    f"Hay que bajar a mano: {i['label']}. {i['reason']}"
                    + (f" Abrir: {', '.join(i['open'][:2])}." if i["open"] else "")
                    + (f" La copia subida no sirvió: {i['problem']}" if i.get("problem") else "")
                    + " Abrirlo en un navegador, pasar la verificación si aparece, guardar el PDF y subirlo en la "
                    "consola de documentos; la actualización que se inicia al subirlo lo lee y lo valida.")

    def as_json(self, previous: Optional[dict], today: date) -> dict:
        """El archivo ``manual-needed.json``. ``since`` se conserva de la publicación anterior."""
        since = {i.get("id"): i.get("since") for i in ((previous or {}).get("pending") or []) if isinstance(i, dict)}
        pending = [{**i, "since": since.get(i["id"]) or today.isoformat()} for i in self.items.values()]
        return {"version": 1, "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "pending": pending, "used": self.used}


def dump(needs: ManualNeeds, previous: Optional[dict], today: date) -> str:
    return json.dumps(needs.as_json(previous, today), ensure_ascii=False, indent=1)
