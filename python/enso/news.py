"""Noticias: feeds RSS/Atom de medios del Perú y del mundo sobre El Niño.

Cada corrida:
  1. Descarga cada feed del catálogo ``FEEDS`` y registra su estado
     (responde, cuántas entradas, fecha de la más reciente). Un feed sin
     entradas nuevas en ``stale_days`` se marca inactivo.
  2. Se queda con las entradas que tratan del ENSO o de sus impactos en el
     Perú (``relevance``). Los feeds temáticos (GDACS, alertas, Google Noticias) usan
     un filtro más amplio de peligros.
  3. Agrega las nuevas al histórico de solo anexar ``news/items.jsonl``
     (una línea por entrada, nunca se reescriben las anteriores) y genera
     ``news/items.csv`` con todo el histórico.
  4. Agrupa las entradas similares de los últimos días (``cluster``): cada
     grupo lleva el titular más temprano, cuántos medios lo publicaron, un
     resumen extractivo y el enlace a cada fuente.

Solo se guarda lo que el medio publica en su feed (título, resumen, fecha
y enlace); no se copian los artículos completos.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .archive import news_page
from .feedparse import LIMA, FeedError, parse as parse_any, truncated
from .geo import FOREIGN_RE, PERU_RE as PERU_WORD_RE


@dataclass(frozen=True)
class Feed:
    id: str
    name: str
    region: str  # "peru" | "mundo"
    url: str
    lang: str = "es"
    #: "general": medio general (se exige un término ENSO);
    #: "hazard": feed de emergencias o clima (basta un peligro asociado).
    #: "local": medio regional (basta un peligro: lluvias, huaico, friaje…).
    scope: str = "general"
    stale_days: int = 7
    #: "gobierno" | "diario" | "radio" | "tv" | "digital" | "agregador" | "organismo"
    kind: str = "diario"
    #: Código UBIGEO de 2 dígitos del departamento que cubre el medio, si es regional.
    department: Optional[str] = None
    #: "feed" (RSS/Atom/JSON Feed), "gobpe" (listado de noticias de gob.pe, sin RSS) o
    #: uno de los lectores de fuentes de peligros sin RSS (``hazardparse.ADAPTERS``).
    adapter: str = "feed"
    #: Las entradas más antiguas se ignoran (listados que acumulan años de boletines).
    max_age_days: Optional[int] = None
    #: Peligros que cubre una fuente oficial de alertas (para el registro de fuentes).
    covers: tuple[str, ...] = ()
    #: Capa de ArcGIS (``adapter="arcgis"``): el nombre que la capa del URL tiene en el servidor. Una capa vacía no
    #: trae campos, así que «sin avisos vigentes» y «la capa se renumeró o se retiró» se ven iguales: cuando llega
    #: vacía se comprueba el nombre en el listado del servicio (``check_layer``).
    layer: str = ""
    #: El enlace de cada entrada identifica la nota (``identity_key``). ``False`` en un feed que pone el mismo enlace
    #: a entradas distintas (FIRMS: el resumen del día siempre enlaza al mismo mapa).
    link_is_id: bool = True

    @property
    def fixture(self) -> str:
        """Nombre del archivo capturado (fixtures y archivo crudo)."""
        return f"news-{self.id}.{ADAPTER_EXT.get(self.adapter, 'xml')}"


#: Extensión de la captura según lo que devuelve cada lector.
ADAPTER_EXT = {"gobpe": "html", "dhn": "html", "dhn-avisos": "html", "cenvul": "html", "telegram": "html", "geojson": "json",
               "arcgis": "json", "ptwc-text": "txt", "firms": "csv"}


_GN = "https://news.google.com/rss/search?q="

#: Catálogo de feeds verificado en vivo desde GitHub Actions el 21 de octubre
#: de 2026 (los nacionales y del mundo con ``tools.capture_sources``; los de
#: regiones, radios y entidades del Estado con ``tools.probe_feeds``, cuyo
#: informe queda en tests/fixtures/news-probe/report.json). Ver
#: docs/catalogo-fuentes.md, donde también figuran los descartados. El estado de
#: cada uno se vuelve a verificar en cada corrida y se publica en ``news/feeds.json``
#: (los que se leen una vez al día, ``registry.reader_urls``, repiten su última lectura).
FEEDS: list[Feed] = [
    # Perú
    Feed("andina", "Andina (agencia estatal)", "peru", "https://andina.pe/agencia/rss/3.xml", kind="gobierno"),
    Feed("elcomercio", "El Comercio", "peru", "https://elcomercio.pe/arcio/rss/"),
    Feed("gestion", "Gestión", "peru", "https://gestion.pe/arcio/rss/"),
    Feed("correo", "Diario Correo", "peru", "https://diariocorreo.pe/arcio/rss/"),
    Feed("larepublica", "La República", "peru", "https://larepublica.pe/rss/sociedad.xml"),
    Feed("rpp", "RPP Noticias", "peru", "https://rpp.pe/rss", kind="radio"),
    Feed("infobae-peru", "Infobae Perú", "peru", "https://www.infobae.com/arc/outboundfeeds/rss/category/peru/",
         kind="digital"),
    Feed("caretas", "Caretas", "peru", "https://caretas.pe/feed/"),
    # Publica a rachas: entre el 15-04 y el 20-11-2026 hubo huecos de 6, 15, 40 y 115 días (feed del 21-11-2026).
    Feed("perureports", "Peru Reports", "peru", "https://perureports.com/feed/", lang="en", kind="digital",
         stale_days=21),
    Feed("gnews-peru", "Google Noticias Perú (búsqueda El Niño)", "peru",
         _GN + "%22El%20Ni%C3%B1o%22%20OR%20ENFEN%20OR%20%22Ni%C3%B1o%20costero%22&hl=es-419&gl=PE&ceid=PE:es-419",
         scope="hazard", stale_days=3, kind="agregador"),
    # Perú · Estado y búsquedas nacionales (sondeo del 21 de octubre de 2026)
    Feed("el-peruano", "El Peruano (diario oficial)", "peru", "https://news.google.com/rss/search?q=site%3Aelperuano.pe&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-ana", "Autoridad Nacional del Agua · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=ana&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-busqueda-peligros", "gob.pe · búsqueda de noticias por peligro", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&sort_by=recent&term=huaico",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-cenepred", "CENEPRED · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=cenepred&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-igp", "Instituto Geofísico del Perú · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=igp&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-indeci", "INDECI (incl. COEN) · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=indeci&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-midagri", "MIDAGRI (sequía, heladas, agro) · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=midagri&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-minam", "Ministerio del Ambiente · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=minam&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-pcm", "PCM (declaratorias de emergencia) · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=pcm&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-presidencia", "Presidencia de la República · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=presidencia&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-senamhi", "SENAMHI · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=senamhi&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("imarpe", "IMARPE", "peru", "https://www.imarpe.gob.pe/feed/",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gnews-peligros-nacional", "Google Noticias · peligros (Perú)", "peru", "https://news.google.com/rss/search?q=%28huaico%20OR%20huaicos%20OR%20%22activaci%C3%B3n%20de%20quebrada%22%20OR%20inundaci%C3%B3n%20OR%20desborde%29%20Per%C3%BA%20when%3A3d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="hazard", stale_days=3),
    Feed("exitosa", "Exitosa Noticias", "peru", "https://www.exitosanoticias.pe/feed/",
         kind="radio", scope="general", stale_days=7),
    Feed("radio-nacional", "Radio Nacional del Perú", "peru", "https://news.google.com/rss/search?q=site%3Aradionacional.gob.pe&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="radio", scope="general", stale_days=7),
    Feed("radio-santa-rosa", "Radio Santa Rosa (Santa Rosa Radio TV)", "peru", "https://radiosantarosa.com.pe/feed/",
         kind="radio", scope="general", stale_days=7),
    Feed("rpp-peru-actualidad", "RPP Noticias · Perú/Actualidad", "peru", "https://rpp.pe/feed/peru/actualidad",
         kind="radio", scope="hazard", stale_days=7),
    Feed("canal-n", "Canal N", "peru", "https://canaln.pe/feed",
         kind="tv", scope="general", stale_days=7),
    Feed("panamericana", "Panamericana TV (24 Horas)", "peru", "https://news.google.com/rss/search?q=site%3Apanamericana.pe&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="tv", scope="general", stale_days=7),
    Feed("tvperu", "TV Perú Noticias", "peru", "https://news.google.com/rss/search?q=site%3Atvperu.gob.pe/noticias&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="tv", scope="general", stale_days=7),
    Feed("correo-ediciones", "Diario Correo · ediciones regionales", "peru", "https://diariocorreo.pe/arc/outboundfeeds/rss/category/edicion/?outputType=xml",
         kind="diario", scope="general", stale_days=7),
    Feed("elcomercio-peru", "El Comercio · Perú (regiones)", "peru", "https://elcomercio.pe/arc/outboundfeeds/rss/category/peru/?outputType=xml",
         kind="diario", scope="general", stale_days=7),
    Feed("actualidad-ambiental", "Actualidad Ambiental (SPDA)", "peru", "https://www.actualidadambiental.pe/feed/",
         kind="digital", scope="general", stale_days=7),
    Feed("altavoz", "Altavoz", "peru", "https://altavoz.pe/feed/",
         kind="digital", scope="general", stale_days=7),
    Feed("mongabay-latam-peru", "Mongabay Latam · Perú", "peru", "https://es.mongabay.com/feed/?location=peru",
         kind="digital", scope="general", stale_days=7),
    # «Noticias SER» (www.noticiasser.pe) se quitó el 21-11-2026: desde el 17-04-2026 el dominio publica guías de
    # finanzas y trámites en tandas (143 entradas, todas en la categoría «general»: tarjetas de crédito, seguros,
    # «cómo invertir en minería»), no las noticias de la Asociación SER. Cero notas relevantes en todas sus lecturas.
    # Amazonas
    Feed("gobpe-regionamazonas", "Gobierno Regional de Amazonas (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionamazonas&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="01"),
    Feed("gnews-01", "Google Noticias · Amazonas", "peru", "https://news.google.com/rss/search?q=%28Chachapoyas%20OR%20Bagua%20OR%20Utcubamba%20OR%20%22regi%C3%B3n%20Amazonas%22%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="01"),
    Feed("esfera-radio", "Esfera Radio (Chachapoyas)", "peru", "https://news.google.com/rss/search?q=site%3Aesferaradio.net&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="radio", scope="local", stale_days=21, department="01"),
    Feed("reina-de-la-selva", "Radio Reina de la Selva (Chachapoyas)", "peru", "https://reinadelaselva.pe/feed/",
         kind="radio", scope="local", stale_days=21, department="01"),
    Feed("rpp-amazonas", "RPP Noticias · Amazonas", "peru", "https://rpp.pe/feed/peru/amazonas",
         kind="radio", scope="local", stale_days=30, department="01"),
    Feed("chachapoyas-online", "Chachapoyas Online", "peru", "https://news.google.com/rss/search?q=site%3Achachapoyasonline.com&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="digital", scope="local", stale_days=21, department="01"),
    # Áncash
    Feed("gnews-02", "Google Noticias · Áncash", "peru", "https://news.google.com/rss/search?q=%28%C3%81ncash%20OR%20Ancash%20OR%20Huaraz%20OR%20Chimbote%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="02"),
    Feed("rpp-ancash", "RPP Noticias · Áncash", "peru", "https://rpp.pe/feed/peru/ancash",
         kind="radio", scope="local", stale_days=30, department="02"),
    Feed("diario-de-chimbote", "Diario de Chimbote", "peru", "https://diariodechimbote.com/feed/",
         kind="diario", scope="local", stale_days=21, department="02"),
    # Apurímac
    Feed("gobpe-regionapurimac", "Gobierno Regional de Apurímac (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionapurimac&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="03"),
    Feed("gnews-03", "Google Noticias · Apurímac", "peru", "https://news.google.com/rss/search?q=%28Apur%C3%ADmac%20OR%20Abancay%20OR%20Andahuaylas%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="03"),
    Feed("radio-titanka", "Radio Titanka (Andahuaylas/Abancay)", "peru", "https://news.google.com/rss/search?q=site%3Aradiotitanka.pe&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="radio", scope="local", stale_days=21, department="03"),
    Feed("rpp-apurimac", "RPP Noticias · Apurímac", "peru", "https://rpp.pe/feed/peru/apurimac",
         kind="radio", scope="local", stale_days=30, department="03"),
    Feed("chaski-apurimac", "Diario Chaski (Abancay)", "peru", "https://news.google.com/rss/search?q=site%3Achaski.pe&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="diario", scope="local", stale_days=21, department="03"),
    Feed("pregon-apurimac", "Diario Pregón (Abancay)", "peru", "https://pregon.com.pe/index.php/regionales?format=feed&type=rss",
         kind="diario", scope="local", stale_days=21, department="03"),
    # Arequipa
    Feed("gobpe-regionarequipa", "Gobierno Regional de Arequipa (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionarequipa&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="04"),
    Feed("gnews-04", "Google Noticias · Arequipa", "peru", "https://news.google.com/rss/search?q=%28Arequipa%20OR%20Caman%C3%A1%20OR%20Caylloma%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="04"),
    Feed("radio-yaravi", "Radio Yaraví", "peru", "https://radioyaravi.org.pe/feed/",
         kind="radio", scope="local", stale_days=21, department="04"),
    Feed("rpp-arequipa", "RPP Noticias · Arequipa", "peru", "https://rpp.pe/feed/peru/arequipa",
         kind="radio", scope="local", stale_days=30, department="04"),
    Feed("diario-sin-fronteras", "Diario Sin Fronteras (Arequipa · Tacna · Puno · Moquegua)", "peru", "https://diariosinfronteras.com.pe/category/arequipa/feed/",
         kind="diario", scope="local", stale_days=21, department="04"),
    Feed("el-buho", "El Búho", "peru", "https://elbuho.pe/feed/",
         kind="digital", scope="local", stale_days=21, department="04"),
    # Ayacucho
    Feed("gobpe-regionayacucho", "Gobierno Regional de Ayacucho (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionayacucho&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="05"),
    Feed("gnews-05", "Google Noticias · Ayacucho", "peru", "https://news.google.com/rss/search?q=%28Ayacucho%20OR%20Huamanga%20OR%20Huanta%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="05"),
    Feed("rpp-ayacucho", "RPP Noticias · Ayacucho", "peru", "https://rpp.pe/feed/peru/ayacucho",
         kind="radio", scope="local", stale_days=30, department="05"),
    Feed("diario-jornada", "Diario Jornada (Ayacucho)", "peru", "https://jornada.com.pe/feed/",
         kind="diario", scope="local", stale_days=21, department="05"),
    # Cajamarca
    Feed("gnews-06", "Google Noticias · Cajamarca", "peru", "https://news.google.com/rss/search?q=%28Cajamarca%20OR%20Ja%C3%A9n%20OR%20Chota%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="06"),
    Feed("rpp-cajamarca", "RPP Noticias · Cajamarca", "peru", "https://rpp.pe/feed/peru/cajamarca",
         kind="radio", scope="local", stale_days=30, department="06"),
    Feed("soltv-cajamarca", "Sol TV · Cajamarca", "peru", "https://soltvperu.com/category/regiones/cajamarca-noticias/feed/",
         kind="tv", scope="local", stale_days=21, department="06"),
    Feed("sin-rodeos-cajamarca", "Sin Rodeos Cajamarca", "peru", "https://sinrodeoscajamarca.com/feed/",
         kind="digital", scope="local", stale_days=21, department="06"),
    # Callao
    Feed("gobpe-regioncallao", "Gobierno Regional de Callao (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regioncallao&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="07"),
    Feed("gnews-07", "Google Noticias · Callao", "peru", "https://news.google.com/rss/search?q=%28Callao%20OR%20Ventanilla%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="07"),
    Feed("rpp-callao", "RPP Noticias · Callao", "peru", "https://rpp.pe/feed/peru/callao",
         kind="radio", scope="local", stale_days=30, department="07"),
    # Casi no publica en la web: entradas del 18-03, 27-03, 29-03, 22-04, 26-06, 15-10 y 22-10-2026 (feed y API de
    # WordPress del 21-11-2026). Su sitemap a veces responde con la verificación de Imunify360 («One moment…»).
    Feed("nacional-callao-tv", "Nacional Callao TV", "peru", "https://nacionalcallaotv.pe/feed/",
         kind="tv", scope="local", stale_days=60, department="07"),
    Feed("prensa-chalaca", "Prensa Chalaca", "peru", "https://prensachalaca.com/feed/",
         kind="digital", scope="local", stale_days=21, department="07"),
    # Cusco
    Feed("gobpe-regioncusco", "Gobierno Regional de Cusco (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regioncusco&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="08"),
    Feed("gnews-08", "Google Noticias · Cusco", "peru", "https://news.google.com/rss/search?q=%28Cusco%20OR%20Quillabamba%20OR%20%22La%20Convenci%C3%B3n%22%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="08"),
    Feed("rpp-cusco", "RPP Noticias · Cusco", "peru", "https://rpp.pe/feed/peru/cusco",
         kind="radio", scope="local", stale_days=30, department="08"),
    Feed("diario-del-cusco", "El Diario del Cusco", "peru", "https://diariodelcusco.pe/feed/",
         kind="diario", scope="local", stale_days=21, department="08"),
    Feed("cusco-post", "Cusco Post", "peru", "https://cuscopost.pe/feed/",
         kind="digital", scope="local", stale_days=21, department="08"),
    # Huancavelica
    Feed("gobpe-regionhuancavelica", "Gobierno Regional de Huancavelica (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionhuancavelica&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="09"),
    Feed("gnews-09", "Google Noticias · Huancavelica", "peru", "https://news.google.com/rss/search?q=%28Huancavelica%20OR%20Tayacaja%20OR%20Angaraes%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="09"),
    Feed("rpp-huancavelica", "RPP Noticias · Huancavelica", "peru", "https://rpp.pe/feed/peru/huancavelica",
         kind="radio", scope="local", stale_days=30, department="09"),
    # La etiqueta tiene 17 notas desde 2024 (huecos de hasta 173 días; API de WordPress, 21-11-2026). Las notas
    # sobre Huancavelica sin la etiqueta (alertas del SENAMHI para varias regiones) llegan por el feed «altavoz».
    Feed("altavoz-huancavelica", "Altavoz · tema Huancavelica", "peru", "https://altavoz.pe/temas/huancavelica/feed/",
         kind="digital", scope="local", stale_days=60, department="09"),
    # Huánuco
    Feed("gobpe-regionhuanuco", "Gobierno Regional de Huánuco (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionhuanuco&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="10"),
    Feed("gnews-10", "Google Noticias · Huánuco", "peru", "https://news.google.com/rss/search?q=%28Hu%C3%A1nuco%20OR%20%22Tingo%20Mar%C3%ADa%22%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="10"),
    Feed("rpp-huanuco", "RPP Noticias · Huánuco", "peru", "https://rpp.pe/feed/peru/huanuco",
         kind="radio", scope="local", stale_days=30, department="10"),
    Feed("diario-ahora-huanuco", "Diario Ahora (Huánuco)", "peru", "https://ahora.com.pe/feed.xml",
         kind="diario", scope="local", stale_days=21, department="10"),
    Feed("tu-diario-huanuco", "Tu Diario Huánuco", "peru", "https://tudiariohuanuco.pe/feed/",
         kind="digital", scope="local", stale_days=21, department="10"),
    # Ica
    Feed("gnews-11", "Google Noticias · Ica", "peru", "https://news.google.com/rss/search?q=%28%22regi%C3%B3n%20Ica%22%20OR%20Ica%20OR%20Pisco%20OR%20Chincha%20OR%20Nasca%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="11"),
    Feed("rpp-ica", "RPP Noticias · Ica", "peru", "https://rpp.pe/feed/peru/ica",
         kind="radio", scope="local", stale_days=30, department="11"),
    # Junín
    Feed("gnews-12", "Google Noticias · Junín", "peru", "https://news.google.com/rss/search?q=%28Jun%C3%ADn%20OR%20Huancayo%20OR%20Satipo%20OR%20Chanchamayo%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="12"),
    Feed("radio-huancayo", "Radio Huancayo", "peru", "https://radiohuancayo.com.pe/wp54/feed/",
         kind="radio", scope="local", stale_days=21, department="12"),
    Feed("rpp-junin", "RPP Noticias · Junín", "peru", "https://rpp.pe/feed/peru/junin",
         kind="radio", scope="local", stale_days=30, department="12"),
    # La Libertad
    Feed("gobpe-regionlalibertad", "Gobierno Regional de La Libertad (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionlalibertad&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="13"),
    Feed("gnews-13", "Google Noticias · La Libertad", "peru", "https://news.google.com/rss/search?q=%28%22La%20Libertad%22%20OR%20Trujillo%20OR%20Pacasmayo%20OR%20Chep%C3%A9n%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="13"),
    Feed("rpp-la-libertad", "RPP Noticias · La Libertad", "peru", "https://rpp.pe/feed/peru/la-libertad",
         kind="radio", scope="local", stale_days=30, department="13"),
    Feed("soltv-la-libertad", "Sol TV · La Libertad", "peru", "https://soltvperu.com/category/regiones/la-libertad-noticias/feed/",
         kind="tv", scope="local", stale_days=21, department="13"),
    # Lambayeque
    Feed("gobpe-regionlambayeque", "Gobierno Regional de Lambayeque (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionlambayeque&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="14"),
    Feed("gnews-14", "Google Noticias · Lambayeque", "peru", "https://news.google.com/rss/search?q=%28Lambayeque%20OR%20Chiclayo%20OR%20Ferre%C3%B1afe%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="14"),
    Feed("rpp-lambayeque", "RPP Noticias · Lambayeque", "peru", "https://rpp.pe/feed/peru/lambayeque",
         kind="radio", scope="local", stale_days=30, department="14"),
    Feed("soltv-lambayeque", "Sol TV · Lambayeque", "peru", "https://soltvperu.com/category/regiones/lambayeque-noticias/feed/",
         kind="tv", scope="local", stale_days=21, department="14"),
    # Lima
    Feed("gobpe-regionlima", "Gobierno Regional de Lima (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionlima&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="15"),
    Feed("gnews-15", "Google Noticias · Lima", "peru", "https://news.google.com/rss/search?q=%28%22Lima%20Metropolitana%22%20OR%20Huaura%20OR%20Huacho%20OR%20Ca%C3%B1ete%20OR%20Huaral%20OR%20Barranca%20OR%20Chosica%20OR%20Huarochir%C3%AD%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=14, department="15"),
    Feed("rpp-lima", "RPP Noticias · Lima/Actualidad", "peru", "https://rpp.pe/feed/lima/actualidad",
         kind="radio", scope="local", stale_days=30, department="15"),
    # Loreto
    Feed("gobpe-regionloreto", "Gobierno Regional de Loreto (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionloreto&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="16"),
    Feed("gnews-16", "Google Noticias · Loreto", "peru", "https://news.google.com/rss/search?q=%28Loreto%20OR%20Iquitos%20OR%20Yurimaguas%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="16"),
    Feed("rpp-loreto", "RPP Noticias · Loreto", "peru", "https://rpp.pe/feed/peru/loreto",
         kind="radio", scope="local", stale_days=30, department="16"),
    Feed("diario-la-region", "Diario La Región (Iquitos)", "peru", "https://diariolaregion.com/feed/",
         kind="diario", scope="local", stale_days=21, department="16"),
    Feed("pro-y-contra", "Pro & Contra (Iquitos)", "peru", "https://www.proycontra.com.pe/rss.xml",
         kind="diario", scope="local", stale_days=21, department="16"),
    # Madre de Dios
    Feed("gobpe-regionmadrededios", "Gobierno Regional de Madre de Dios (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionmadrededios&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="17"),
    Feed("gnews-17", "Google Noticias · Madre de Dios", "peru", "https://news.google.com/rss/search?q=%28%22Madre%20de%20Dios%22%20OR%20%22Puerto%20Maldonado%22%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="17"),
    Feed("radio-madre-de-dios", "Radio Madre de Dios", "peru", "https://noticias.madrededios.com/rss/",
         kind="radio", scope="local", stale_days=21, department="17"),
    Feed("rpp-madre-de-dios", "RPP Noticias · Madre de Dios", "peru", "https://rpp.pe/feed/peru/madre-de-dios",
         kind="radio", scope="local", stale_days=30, department="17"),
    # Moquegua
    Feed("gobpe-regionmoquegua", "Gobierno Regional de Moquegua (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionmoquegua&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="18"),
    Feed("gnews-18", "Google Noticias · Moquegua", "peru", "https://news.google.com/rss/search?q=%28Moquegua%20OR%20Ilo%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="18"),
    Feed("rpp-moquegua", "RPP Noticias · Moquegua", "peru", "https://rpp.pe/feed/peru/moquegua",
         kind="radio", scope="local", stale_days=30, department="18"),
    Feed("prensa-regional", "La Prensa Regional (Moquegua)", "peru", "https://prensaregional.pe/feed/",
         kind="diario", scope="local", stale_days=21, department="18"),
    # Pasco
    Feed("gobpe-regionpasco", "Gobierno Regional de Pasco (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionpasco&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="19"),
    Feed("gnews-19", "Google Noticias · Pasco", "peru", "https://news.google.com/rss/search?q=%28Pasco%20OR%20Oxapampa%20OR%20%22Cerro%20de%20Pasco%22%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="19"),
    Feed("rpp-pasco", "RPP Noticias · Pasco", "peru", "https://rpp.pe/feed/peru/pasco",
         kind="radio", scope="local", stale_days=30, department="19"),
    Feed("pasco-libre", "Pasco Libre", "peru", "http://www.pascolibre.com/feeds/posts/default?alt=rss",
         kind="digital", scope="local", stale_days=21, department="19"),
    # Piura
    Feed("gobpe-regionpiura", "Gobierno Regional de Piura (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionpiura&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="20"),
    Feed("gnews-20", "Google Noticias · Piura", "peru", "https://news.google.com/rss/search?q=%28Piura%20OR%20Sullana%20OR%20Talara%20OR%20Chulucanas%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="20"),
    Feed("radio-cutivalu", "Radio Cutivalú", "peru", "https://www.cutivalu.pe/feed/",
         kind="radio", scope="local", stale_days=21, department="20"),
    Feed("rpp-piura", "RPP Noticias · Piura", "peru", "https://rpp.pe/feed/peru/piura",
         kind="radio", scope="local", stale_days=30, department="20"),
    Feed("soltv-piura", "Sol TV · Piura", "peru", "https://soltvperu.com/category/regiones/piura-noticias/feed/",
         kind="tv", scope="local", stale_days=21, department="20"),
    Feed("el-tiempo-piura", "El Tiempo (Piura)", "peru", "https://eltiempo.pe/feed/",
         kind="diario", scope="local", stale_days=21, department="20"),
    # Puno
    Feed("gobpe-regionpuno", "Gobierno Regional de Puno (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionpuno&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="21"),
    Feed("gnews-21", "Google Noticias · Puno", "peru", "https://news.google.com/rss/search?q=%28Puno%20OR%20Juliaca%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="21"),
    Feed("pachamama-radio", "Pachamama Radio (Puno/Juliaca)", "peru", "https://pachamamaradio.org/feed/",
         kind="radio", scope="local", stale_days=21, department="21"),
    Feed("radio-onda-azul", "Radio Onda Azul (Puno)", "peru", "https://radioondaazul.com/feed/",
         kind="radio", scope="local", stale_days=21, department="21"),
    Feed("rpp-puno", "RPP Noticias · Puno", "peru", "https://rpp.pe/feed/peru/puno",
         kind="radio", scope="local", stale_days=30, department="21"),
    Feed("los-andes", "Diario Los Andes (Puno)", "peru", "https://losandes.com.pe/feed/",
         kind="diario", scope="local", stale_days=21, department="21"),
    Feed("sin-fronteras-puno", "Diario Sin Fronteras · Puno", "peru", "https://diariosinfronteras.com.pe/category/puno/feed/",
         kind="diario", scope="local", stale_days=21, department="21"),
    # San Martín
    Feed("gobpe-regionsanmartin", "Gobierno Regional de San Martín (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionsanmartin&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="22"),
    Feed("gnews-22", "Google Noticias · San Martín", "peru", "https://news.google.com/rss/search?q=%28%22regi%C3%B3n%20San%20Mart%C3%ADn%22%20OR%20Tarapoto%20OR%20Moyobamba%20OR%20Tocache%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="22"),
    Feed("rpp-san-martin", "RPP Noticias · San Martín", "peru", "https://rpp.pe/feed/peru/san-martin",
         kind="radio", scope="local", stale_days=30, department="22"),
    Feed("diario-hoy-san-martin", "Diario HOY (San Martín)", "peru", "https://news.google.com/rss/search?q=site%3Adiario-hoy.com.pe&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="diario", scope="local", stale_days=21, department="22"),
    Feed("diario-voces", "Diario Voces (Tarapoto)", "peru", "https://diariovoces.com.pe/feed/",
         kind="diario", scope="local", stale_days=21, department="22"),
    # Tacna
    Feed("gnews-23", "Google Noticias · Tacna", "peru", "https://news.google.com/rss/search?q=%28Tacna%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="23"),
    Feed("radio-uno-tacna", "Radio Uno 93.7 (Tacna)", "peru", "https://radiouno.pe/feed/",
         kind="radio", scope="local", stale_days=21, department="23"),
    Feed("rpp-tacna", "RPP Noticias · Tacna", "peru", "https://rpp.pe/feed/peru/tacna",
         kind="radio", scope="local", stale_days=30, department="23"),
    Feed("sin-fronteras-tacna", "Diario Sin Fronteras · Tacna", "peru", "https://diariosinfronteras.com.pe/category/tacna/feed/",
         kind="diario", scope="local", stale_days=21, department="23"),
    # Tumbes
    Feed("gobpe-regiontumbes", "Gobierno Regional de Tumbes (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regiontumbes&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="24"),
    Feed("gnews-24", "Google Noticias · Tumbes", "peru", "https://news.google.com/rss/search?q=%28Tumbes%20OR%20Zarumilla%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="24"),
    Feed("rpp-tumbes", "RPP Noticias · Tumbes", "peru", "https://rpp.pe/feed/peru/tumbes",
         kind="radio", scope="local", stale_days=30, department="24"),
    Feed("tumbes-de-miercoles", "Tumbes de Miércoles", "peru", "https://news.google.com/rss/search?q=site%3Atumbesdemiercoles.com.pe&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="digital", scope="local", stale_days=21, department="24"),
    # Ucayali
    Feed("gobpe-regionucayali", "Gobierno Regional de Ucayali (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionucayali&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="25"),
    Feed("gnews-25", "Google Noticias · Ucayali", "peru", "https://news.google.com/rss/search?q=%28Ucayali%20OR%20Pucallpa%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="25"),
    Feed("rpp-ucayali", "RPP Noticias · Ucayali", "peru", "https://rpp.pe/feed/peru/ucayali",
         kind="radio", scope="local", stale_days=30, department="25"),
    Feed("gaceta-ucayalina", "Gaceta Ucayalina", "peru", "https://www.gacetaucayalina.com/feed/",
         kind="digital", scope="local", stale_days=21, department="25"),
    Feed("gobpe-imarpe", "IMARPE · noticias en gob.pe", "peru", "https://www.gob.pe/institucion/imarpe/noticias",
         kind="gobierno", scope="hazard", stale_days=30, adapter="gobpe"),
    # Alertas oficiales de peligros sin RSS (enso.hazardparse). Para cada una se usa la vía más
    # simple que trae el dato desde EE. UU. (tools.scrape_ladder, informe en la rama bot/scrape-ladder/…).
    Feed("indeci-coen", "INDECI · COEN, reportes de emergencias", "peru", "https://portal.indeci.gob.pe/emergencias/feed/?paged=1",
         kind="gobierno", scope="hazard", stale_days=3, adapter="indeci-coen",
         covers=("lluvias", "inundacion", "huaico", "frio", "calor", "viento", "incendio", "oleaje", "sismo", "volcan", "emergencia")),
    # El RSS de arriba trae solo las últimas ~14 publicaciones (unas horas de reportes): un boletín de aviso se pierde
    # entre corridas. La búsqueda de WordPress trae los boletines de los últimos días; su detalle está en el PDF
    # que enlaza cada uno (``documentos``).
    Feed("indeci-coen-boletines", "INDECI · COEN, boletines de avisos", "peru",
         "https://portal.indeci.gob.pe/emergencias/feed/?s=boletin+informativo",
         kind="gobierno", scope="hazard", stale_days=4, adapter="indeci-coen",
         covers=("lluvias", "huaico", "frio", "calor", "viento", "oleaje")),
    Feed("senamhi-quebradas", "SENAMHI · avisos de activación de quebradas (servidor GEOSINPAD del INDECI)", "peru",
         "https://geosinpad.indeci.gob.pe/indeci/rest/services/Ent_Tecnico_Cientificas/SENAMHI/MapServer/2"
         "/query?where=1%3D1&outStatistics=%5B%7B%22statisticType%22%3A%22count%22%2C%22onStatisticField%22%3A%22OBJECTID%22%2C%22outStatisticFieldName%22%3A%22n%22%7D%5D&groupByFieldsForStatistics=NIVEL%2CNOMBDEP%2CNOMBPROV%2CNOMBDIST%2CFECHA&f=json",
         kind="gobierno", scope="hazard", stale_days=4, adapter="arcgis", layer="SDE.SENAMHI_AvisoActQuebrada24H",
         covers=("huaico", "lluvias")),
    Feed("senamhi-hidrologicos", "SENAMHI · avisos hidrológicos (servidor GEOSINPAD del INDECI)", "peru",
         "https://geosinpad.indeci.gob.pe/indeci/rest/services/Ent_Tecnico_Cientificas/SENAMHI/MapServer/4/query?where=1%3D1&outFields=*&returnGeometry=false&f=json",
         kind="gobierno", scope="hazard", stale_days=10, adapter="arcgis", layer="SDE.SENAMHI_AvisoHidrologico24H",
         covers=("inundacion", "sequia")),
    Feed("senamhi-incendios", "SENAMHI · peligro de incendios forestales, índice FWI (servidor GEOSINPAD del INDECI)", "peru",
         "https://geosinpad.indeci.gob.pe/indeci/rest/services/Ent_Tecnico_Cientificas/SENAMHI/MapServer/3/query?where=1%3D1"
         "&outFields=*&returnGeometry=true&outSR=4326&maxAllowableOffset=0.02&geometryPrecision=3&f=geojson",
         kind="gobierno", scope="hazard", stale_days=4, adapter="arcgis", layer="SDE.SENAMHI_AvisoFWI24H", covers=("incendio",)),
    Feed("senamhi-lluvias", "SENAMHI · avisos de precipitaciones para 24 horas (servidor GEOSINPAD del INDECI)", "peru",
         "https://geosinpad.indeci.gob.pe/indeci/rest/services/Ent_Tecnico_Cientificas/SENAMHI/MapServer/5/query?where=1%3D1"
         "&outFields=NIVEL,FECHA&returnGeometry=true&outSR=4326&maxAllowableOffset=0.02&geometryPrecision=3&f=geojson",
         kind="gobierno", scope="hazard", stale_days=4, adapter="arcgis", layer="SDE.SENAMHI_AvisoPP24H", covers=("lluvias",)),
    Feed("firms-focos", "NASA FIRMS · focos de calor (VIIRS, NOAA-20)", "peru",
         "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_South_America_24h.csv",
         kind="organismo", scope="hazard", stale_days=2, adapter="firms", covers=("incendio",), link_is_id=False),
    Feed("usgs-sismos", "USGS · sismos de magnitud 4 o más (Perú y alrededores)", "peru",
         "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minlatitude=-20&maxlatitude=1"
         "&minlongitude=-84&maxlongitude=-68&minmagnitude=4&orderby=time&limit=100",
         kind="organismo", scope="hazard", stale_days=14, adapter="geojson", max_age_days=30,
         covers=("sismo", "tsunami")),
    Feed("dhn-tsunamis", "DHN · boletines de sismo y tsunami", "peru", "https://www.dhn.mil.pe/portal/boletin-sismo-tsunami",
         kind="gobierno", scope="hazard", stale_days=90, adapter="dhn", max_age_days=30,
         covers=("sismo", "tsunami")),
    Feed("dhn-avisos", "DHN · avisos especiales de oleaje y de viento", "peru", "https://www.dhn.mil.pe/portal/avisos-especiales",
         kind="gobierno", scope="hazard", stale_days=30, adapter="dhn-avisos", max_age_days=30,
         covers=("oleaje", "viento")),
    Feed("ptwc-mensajes", "PTWC · mensajes de tsunami del Pacífico", "mundo", "https://www.tsunami.gov/events/xml/PHEBAtom.xml",
         lang="en", kind="organismo", scope="hazard", stale_days=365, max_age_days=30,
         covers=("tsunami",)),
    Feed("ptwc-wepa40", "PTWC · último mensaje de tsunami (texto)", "mundo",
         "https://tgftp.nws.noaa.gov/data/raw/we/wepa40.pheb.tsu.pac.txt",
         lang="en", kind="organismo", scope="hazard", stale_days=365, adapter="ptwc-text", max_age_days=30,
         covers=("tsunami",)),
    Feed("igp-cenvul-boletines", "IGP · boletines vulcanológicos (CENVUL)", "peru",
         "https://cenvul.igp.gob.pe/productos/boletines-vulcanologicos",
         kind="gobierno", scope="hazard", stale_days=30, adapter="cenvul", max_age_days=60,
         covers=("volcan",)),
    Feed("igp-cenvul-alertas", "IGP · alertas vulcanológicas (CENVUL)", "peru",
         "https://cenvul.igp.gob.pe/productos/alertas-vulcanologicas",
         kind="gobierno", scope="hazard", stale_days=30, adapter="cenvul", max_age_days=30,
         covers=("volcan",)),
    Feed("senamhi-telegram", "SENAMHI · canal oficial de Telegram (avisos)", "peru", "https://t.me/s/Senamhi_Peru",
         kind="gobierno", scope="hazard", stale_days=7, adapter="telegram",
         covers=("lluvias", "frio", "calor", "viento", "incendio", "sequia", "enso")),
    # Mundo
    Feed("gnews-world", "Google News (search El Niño)", "mundo",
         _GN + "%22El%20Ni%C3%B1o%22%20OR%20%22La%20Ni%C3%B1a%22%20OR%20ENSO&hl=en-US&gl=US&ceid=US:en",
         lang="en", scope="hazard", stale_days=3, kind="agregador"),
    Feed("bbc-mundo", "BBC News Mundo", "mundo", "https://feeds.bbci.co.uk/mundo/rss.xml", kind="digital"),
    Feed("un-news-clima", "Noticias ONU · Clima", "mundo",
         "https://news.un.org/feed/subscribe/es/news/topic/climate-change/feed/rss.xml", scope="hazard", stale_days=14, kind="organismo"),
    Feed("gdacs", "GDACS (alertas de desastres)", "mundo", "https://www.gdacs.org/xml/rss.xml", lang="en", scope="hazard",
         kind="organismo"),
    Feed("carbonbrief", "Carbon Brief", "mundo", "https://www.carbonbrief.org/feed/", lang="en", stale_days=14, kind="digital"),
    Feed("ciifen", "CIIFEN", "mundo", "https://ciifen.org/feed/", scope="hazard", stale_days=120, kind="organismo"),
]

FEED_BY_ID = {f.id: f for f in FEEDS}

# --- Relevancia ---------------------------------------------------------------
# Una entrada es relevante si trata del ENSO o de un peligro que el observatorio
# debe alertar: lluvias, inundaciones, huaicos, sequía, calor, frío (friaje,
# heladas), vientos, oleaje, sismos, tsunamis, volcanes, incendios y
# emergencias. ``hazards`` dice cuáles; ``relevance`` decide si se guarda.

def _rx(pattern: str, flags: int = re.I) -> re.Pattern:
    return re.compile(r"\b(?:" + pattern + r")\b", flags)


#: «El Niño» y «La Niña» con mayúscula (en minúscula son un niño o una niña), o en MAYÚSCULAS.
_ENSO_CASED = re.compile(r"\b(?:[Ee]l|EL) (?:Ni[ñn]o|NI[ÑN]O)\b|\b(?:[Ll]a|LA) (?:Ni[ñn]a|NI[ÑN]A)\b|\bFEN\b|\bENSO\b|\bENFEN\b|\bICEN\b")
ENSO_RE = _rx(r"fen[oó]meno (?:del?|de el|de la) ni[nñ][oa]|ni[nñ]o costero|ni[nñ]a costera|enfen|icen|enso|"
              r"oscilaci[oó]n del sur|anomal[ií]as? de (?:la )?temperatura (?:superficial )?del mar|"
              r"calentamiento (?:anómalo )?del mar|temperatura superficial del mar|niño 1\+2|niño 3\.4")

#: Peligros concretos (cuentan aunque estén solo en el resumen).
HAZARDS: dict[str, tuple[str, re.Pattern]] = {
    "lluvias": ("Lluvias", _rx(r"lluvias? (?:intensas?|fuertes?|torrenciales?|extremas?)|(?:intensas?|fuertes?|torrenciales?) lluvias?|"
                               r"precipitaciones (?:intensas|fuertes|extremas)|tormentas? el[eé]ctricas?|aguaceros?|heavy rain(?:s|fall)?|"
                               r"avisos? (?:meteorol[oó]gicos? )?(?:de|por) lluvias?|aviso meteorol[oó]gico[^.:]{0,30}: precipitaciones|"
                               r"(?:se (?:presentar|registrar|esperar?|prev)\w*|continuar\w*(?: las)?|ocurrencia de) precipitaciones(?! (?:ligeras|d[eé]biles|aisladas))")),
    "inundacion": ("Inundaciones", _rx(r"inundaci[oó]n(?:es)?|inundad[oa]s?|inunda(?:n|ron)?|inund[oó]|desbordes?|desbord(?:a|an|[oó]|aron)|"
                                       r"crecidas?|aniegos?|anegad[oa]s?|floods?|flooding|(?:incremento|aumento|ascenso) del (?:nivel|caudal) del r[ií]o|"
                                       r"tendencia ascendente en su nivel|(?:ascenso|incremento|aumento) en su nivel")),
    "huaico": ("Huaicos y deslizamientos", _rx(r"huaicos?|aluvi[oó]n(?:es)?|activaci[oó]n de (?:las )?quebradas?|quebradas? activad\w*|"
                                               r"deslizamientos?|derrumbes?|landslides?|mudslides?")),
    "sequia": ("Sequía", _rx(r"sequ[ií]as?|d[eé]ficit h[ií]drico|estr[eé]s h[ií]drico|escasez (?:de|del) agua|condiciones secas|"
                             r"d[eé]ficit de lluvias|lluvias deficitarias|drought|vaciantes?|descenso del (?:nivel|caudal) del r[ií]o|"
                             r"tendencia descendente en su nivel|descenso en su nivel")),
    "calor": ("Calor", _rx(r"olas? de calor|altas temperaturas|temperaturas? (?:extremas|r[eé]cord)|calor (?:extremo|intenso)|"
                           r"intenso calor|incremento de (?:la )?temperatura|radiaci[oó]n (?:uv|ultravioleta)(?: (?:extrema|muy alta))?|"
                           r"alta radiaci[oó]n|heat ?waves?")),
    "frio": ("Frío, friaje y heladas", _rx(r"friajes?|heladas?|nevadas?|granizadas?|granizo|aguanieve|nieve|olas? de fr[ií]o|bajas temperaturas|"
                                           r"descenso de (?:la )?temperatura|temperaturas? bajo cero|cold waves?")),
    "viento": ("Vientos", _rx(r"vientos? (?:fuertes|intensos|paracas)|(?:fuertes|intensos) vientos|r[aá]fagas(?: de viento)?|"
                              r"vientos? de hasta \d+|incremento de (?:la )?(?:velocidad del )?vientos?|"
                              r"(?:incrementar[aá]|aumentar[aá]) la velocidad del viento|avisos? especial(?:es)? de vientos?|brisas? (?:fuertes?|frescas?)|vientos? (?:de moderada|moderados?) a (?:fuerte|extrema)")),
    "oleaje": ("Oleaje", _rx(r"oleajes?|maretazos?|bravezas? (?:del? )?mar|cierre de puertos|swells?")),
    "sismo": ("Sismos y tsunamis", _rx(r"sismos?|terremotos?|temblor(?:es)?|r[eé]plicas? s[ií]smicas?|tsunamis?|maremotos?|earthquakes?")),
    "volcan": ("Volcanes", _rx(r"volc[aá]n(?:es)?|erupci[oó]n(?:es)?|ceniza volc[aá]nica|ubinas|sabancaya|volcano(?:es)?")),
    "incendio": ("Incendios", _rx(r"incen[dc]ios?|quemas? agr[ií]colas?|focos? de calor|wildfires?|forest fires?")),
    "emergencia": ("Emergencias", _rx(r"estado de emergencia|damnificad[oa]s?|alerta (?:roja|naranja)|aviso meteorol[oó]gico|"
                                      r"peligro inminente|zona de desastre|declaratoria de emergencia|evacuad[oa]s?|evacuaci[oó]n")),
    "salud": ("Salud", _rx(r"dengue|leptospirosis|zancudos?|fiebre amarilla|infecciones respiratorias|neumon[ií]as?")),
}
HAZARD_LABELS = {k: v[0] for k, v in HAZARDS.items()} | {"enso": "El Niño / La Niña"}
#: Palabras de peligro que solo cuentan en el titular (en el resumen suelen ser de paso: «durante las lluvias»).
WEAK_RE = _rx(r"lluvias?|precipitaci[oó]n(?:es)?|caudal|alerta amarilla|"
              r"defensas? ribere[ñn]as?|descolmataci[oó]n|limpieza de (?:la )?(?:quebrada|cauces?|drenes?)|temporada de lluvias")
#: Peligros hidrometeorológicos (los que salvan a una nota de salud, de un accidente o de una emergencia policial).
HYDRO = ("lluvias", "inundacion", "huaico", "sequia", "calor", "frio", "oleaje")
#: Temas que no son peligros aunque usen sus palabras.
OFFTOPIC_RE = {
    "accidente": _rx(r"accidentes? (?:de tr[aá]nsito|vehicular(?:es)?|de carretera)|despist[eóa]\w*|volcadura|"
                     r"choque (?:frontal|vehicular)|conducir con precauci[oó]n|cay[oó] a un abismo"),
    "seguridad": _rx(r"criminalidad|crimen organizado|delincuencia|inseguridad ciudadana|extorsi[oó]n|sicari\w+|"
                     r"miner[ií]a ilegal|contra la miner[ií]a|toque de queda|narcotr[aá]fico"),
    "empleo": _rx(r"convocatoria (?:para|de) (?:la )?contrataci[oó]n|contrataci[oó]n de (?:un|una|personal)|"
                  r"ofertas? laboral(?:es)?|bolsa de trabajo|convocatoria cas"),
    "rutina": _rx(r"(?:pron[oó]stico del )?(?:clima|tiempo)(?: para)?(?: en [\w ]{2,30})? (?:de )?hoy"),
}
#: Comunicado de una entidad de alerta («Senamhi advierte…», «Indeci alerta…»): cuenta aunque no nombre el peligro.
OFFICIAL_ALERT_RE = _rx(r"(?:senamhi|indeci|igp|dhn|enfen|cenepred|coen|coer|ana)\W+(?:\w+\W+){0,3}?"
                        r"(?:alerta|alertan|advierte|advierten|emite|activa|declara|pronostica|prev[eé]|avisos?)")
#: «sismo de magnitud 3.5»: los sismos leves que el IGP reporta a diario no son una alerta.
MAGNITUDE_RE = re.compile(r"magnitud (?:de )?(\d+(?:[.,]\d)?)", re.I)
#: Incendios que no son forestales: solo cuentan en feeds de emergencias o regionales.
FOREST_FIRE_RE = _rx(r"incen[dc]ios? forestal(?:es)?|quemas? agr[ií]colas?|focos? de calor|wildfires?|forest fires?")
PERU_RE = re.compile(r"\b(per[uú]|peruan[oa]s?|peruvian|lima|piura|tumbes|lambayeque|la libertad|ica|arequipa|"
                     r"ancash|[aá]ncash|loreto|cusco|puno|cajamarca|jun[ií]n)\b", re.I)


def hazards(title: str, summary: str = "") -> list[str]:
    """Tipos de peligro de una entrada (claves de ``HAZARDS`` y «enso»)."""
    text = f"{title} {summary}"
    out = ["enso"] if _ENSO_CASED.search(text) or ENSO_RE.search(text) else []
    out += [k for k, (_, rx) in HAZARDS.items() if rx.search(text)]
    if "salud" in out and not any(h in out for h in ("enso", *HYDRO)) and not WEAK_RE.search(text):
        out.remove("salud")  # dengue sin lluvias ni El Niño: tema de salud, no de clima
    return out


def relevance(feed: Feed, title: str, summary: str) -> Optional[str]:
    """Motivo por el que una entrada es relevante («enso» o «impacto»), o None."""
    text = f"{title} {summary}"
    found = hazards(title, summary)
    if OFFTOPIC_RE["empleo"].search(title):
        return None
    if "enso" in found:
        return "enso"
    if OFFTOPIC_RE["rutina"].search(title) and not any(rx.search(title) for k, (_, rx) in HAZARDS.items()
                                                        if k not in ("lluvias", "emergencia")):
        return None  # la página diaria «Pronóstico del clima hoy» no es una alerta
    hydro = [h for h in found if h in HYDRO]
    if OFFTOPIC_RE["accidente"].search(text) and "huaico" not in found and "inundacion" not in found:
        return None
    if OFFTOPIC_RE["seguridad"].search(text) and not hydro:
        return None
    strong = [h for h in found if h != "salud" or hydro]
    if strong == ["sismo"] or strong == ["sismo", "emergencia"]:
        mags = [float(m.replace(",", ".")) for m in MAGNITUDE_RE.findall(text)]
        if mags and max(mags) < 4.0:
            return None
    if OFFICIAL_ALERT_RE.search(title):
        strong = strong or ["aviso"]
    if feed.scope == "general":
        # Medios generales: el peligro debe estar en el titular (y un incendio, ser forestal).
        in_title = [h for h in hazards(title) if h not in ("emergencia", "salud")]
        if "incendio" in in_title and not FOREST_FIRE_RE.search(title):
            in_title.remove("incendio")
        return "impacto" if in_title else None
    if feed.scope == "hazard" and feed.region != "peru" and not PERU_RE.search(text):
        return None
    if strong or WEAK_RE.search(title):
        return "impacto"
    return None


# --- Lectura de RSS/Atom -----------------------------------------------------
# El lector tolerante (reparaciones, formatos, fechas) está en ``feedparse``.

def parse_feed(body: bytes, base_url: str = "", adapter: str = "feed") -> list[dict]:
    """Entradas homologadas de un feed (RSS 2.0/1.0, Atom, JSON Feed o listado de gob.pe)."""
    return parse_any(body, base_url=base_url, adapter=adapter).items


SOCIAL_RE = re.compile(r"(facebook|instagram|tiktok|twitter|youtube)\.com|//(www\.)?x\.com/|^(Facebook|Instagram|TikTok|X|YouTube)$", re.I)


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower().strip()


_URL_SUFFIX_RE = re.compile(r"\s[-–|]\s+https?://(?:www\.)?([^/\s]+)/?$", re.I)


def _strip_outlet(title: str, outlet: str) -> str:
    """Google Noticias (y algunos medios) terminan los titulares con « - Medio»."""
    m = _URL_SUFFIX_RE.search(title)
    if m and outlet and m.group(1).lower() == outlet.lower().removeprefix("www."):
        return title[: m.start()].rstrip()  # « - https://medio.pe/» cuando el medio viene como URL
    for sep in (" - ", " – ", " | "):
        if outlet and title.endswith(sep + outlet):
            return title[: -len(sep + outlet)].rstrip()
    for sep in (" - ", " – ", " | "):
        if outlet and sep in title and _fold(title.rsplit(sep, 1)[1]) in (_fold(outlet), _fold(outlet).replace(" ", "")):
            return title.rsplit(sep, 1)[0].rstrip()
    return title


def _strip_summary(summary: str, raw_title: str, title: str, outlet: str) -> str:
    """El resumen de Google Noticias repite el titular y el nombre del medio: no aporta y confunde la ubicación."""
    s = summary.strip()
    for t in (raw_title, title):
        if t and s.startswith(t):
            s = s[len(t):].strip(" -–|·")
            break
    suffix = raw_title.rsplit(" - ", 1)[1] if " - " in raw_title else ""
    if _fold(s) in {_fold(outlet), _fold(suffix), ""} or (suffix and _fold(s).endswith(_fold(suffix)) and len(s) <= len(suffix) + 3):
        return ""
    for name in (outlet, suffix):
        if name and _fold(s).endswith(" " + _fold(name)):
            s = s[: -len(name)].rstrip(" -–|·")
    return s


#: Dominios de otros países (Google Noticias mezcla el Junín de Argentina con el del Perú).
FOREIGN_TLD_RE = re.compile(r"\.(ar|bo|br|cl|co|cr|cu|do|ec|es|gt|hn|mx|ni|pa|py|sv|uy|ve|us|uk|it|fr|de)(?:/|$)", re.I)


def item_id(link: str, title: str) -> str:
    return hashlib.sha256(f"{link.strip()}|{title.strip().lower()}".encode()).hexdigest()[:16]


#: Parámetros de consulta que no cambian la nota: campañas, clics de redes y anuncios, AMP.
_TRACKING_RE = re.compile(r"(utm_[a-z_]+|fbclid|gclid|dclid|msclkid|mc_[ce]id|igshid|ref|ref_src|outputtype|cmpid|amp)", re.I)


def canonical_link(url: str) -> str:
    """El enlace con que se identifica una nota: ``https``, el servidor en minúsculas sin «www.» ni puerto por
    omisión, sin parámetros de seguimiento (``_TRACKING_RE``) y sin barra final. La ruta, el resto de la consulta y
    el fragmento se conservan tal cual: distinguen mayúsculas (los identificadores de Google Noticias) y el
    fragmento es lo único que distingue un aviso de otro en los lectores sin RSS (``avisos-especiales#5356`` de la
    DHN, ``boletines-vulcanologicos#IGP-CENVUL-SAB-BV-2026-0043`` del CENVUL).

    El mismo servidor escribe la misma nota con otro esquema o servidor según quién la pida: el feed de Pro &
    Contra arma los enlaces con el servidor y el esquema del pedido (en data-archive, 57 copias del feed con cuatro
    variantes: ``http``/``https`` y con o sin ``www``), y GDACS alterna ``http`` y ``https``."""
    raw = (url or "").strip()
    try:
        p = urlsplit(raw)
    except ValueError:
        return raw
    if p.scheme.lower() not in ("http", "https") or not p.netloc:
        return raw
    host = (p.hostname or "").lower().removeprefix("www.")
    try:
        port = p.port
    except ValueError:
        port = None
    if port and port not in (80, 443):
        host = f"{host}:{port}"
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING_RE.fullmatch(k)])
    return urlunsplit(("https", host, p.path.rstrip("/") or "", query, p.fragment))


def _title_key(title: str) -> str:
    """El titular comparable: sin diferencias de mayúsculas ni de espacios (también los de no separación)."""
    return " ".join(unicodedata.normalize("NFC", title or "").split()).casefold()


def _link_ids(f_id: str) -> bool:
    f = FEED_BY_ID.get(f_id)
    return f.link_is_id if f else True


def _shared_links(items: list[dict]) -> set[tuple[str, str]]:
    """Enlaces que un feed puso, en una misma lectura, a entradas con titulares distintos: ahí el enlace no
    identifica la nota (la portada del medio, un mapa)."""
    seen: dict[tuple[str, str, str], str] = {}
    shared = set()
    for i in items:
        k = (i.get("feed") or "", i.get("first_seen") or "", canonical_link(i.get("link") or ""))
        t = _title_key(i.get("title") or "")
        if seen.setdefault(k, t) != t:
            shared.add(k[:1] + k[2:])
    return shared


def identity_key(item: dict, shared: frozenset | set = frozenset()) -> tuple:
    """Qué nota es una entrada: el feed y su enlace canónico (``canonical_link``), o el ``id`` si el enlace no la
    identifica (``Feed.link_is_id`` falso, o el enlace está en ``shared``).

    El ``id`` (``item_id``) sale del enlace y del titular tal como llegaron, así que cambia con cada variante del
    mismo servidor (``http``/``https``, «www.»), con el nombre del medio que Google Noticias agrega al titular y
    con cada corrección del titular: en data-archive, 397 de 13 458 notas eran otra copia de una nota ya
    guardada (21-11-2026). El ``id`` no cambia (lo usan las anclas del archivo y el histórico ya publicado)."""
    feed = item.get("feed") or ""
    link = canonical_link(item.get("link") or "")
    if not link or not _link_ids(feed) or (feed, link) in shared:
        return (feed, "id", item.get("id") or "")
    return (feed, link)


# --- Agrupación de entradas similares ----------------------------------------

STOP = set("""a al ante con de del desde e el en entre es la las lo los para por que se sin su sus un una y o
the of in on to for and a an is are as at by from with its it this that""".split())


def _tokens(title: str) -> set[str]:
    t = unicodedata.normalize("NFKD", title.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    # Google Noticias añade « - Medio» al final del titular.
    t = re.sub(r"\s[-–|]\s[^-–|]{2,40}$", "", t)
    return {w.strip(".") for w in re.findall(r"[a-z0-9+.]{3,}", t) if w.strip(".") not in STOP and len(w.strip(".")) >= 3}


def _similar(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    return inter >= 3 and inter / min(len(a), len(b)) >= 0.6


def _first_sentence(text: str) -> str:
    m = re.match(r"(.{40,320}?[.!?])(\s|$)", text)
    return (m.group(1) if m else text[:280]).strip()


def _outlet(i: dict) -> str:
    return i.get("outlet") or (FEED_BY_ID[i["feed"]].name if i["feed"] in FEED_BY_ID else i["feed"])


def _norm_link(url: str) -> str:
    """Enlace comparable: sin esquema, «www.», parámetros de campaña ni barra final."""
    u = re.sub(r"^https?://(www\.)?", "", url.strip().lower())
    u = re.sub(r"(?<=[?&])(utm_[a-z]+|outputtype|ref|fbclid)=[^&#]*&?", "", u).rstrip("?&#/")
    return u


def _kind(i: dict) -> str:
    """Tipo de fuente para entradas del histórico anteriores a este campo."""
    f = FEED_BY_ID.get(i["feed"])
    return f.kind if f else "diario"


def _without_title(i: dict) -> str:
    """El resumen sin el titular repetido al comienzo (algunos medios lo repiten)."""
    summ, title = i["summary"].strip(), i["title"].strip().rstrip(".")
    if summ.lower().startswith(title.lower()):
        summ = summ[len(title):].lstrip(" .:-–")
    return summ


def cluster(items: list[dict], now: datetime, days: int = 14) -> list[dict]:
    """Grupos de entradas similares de los últimos ``days`` días, más recientes primero."""
    since = (now - timedelta(days=days)).isoformat()
    items = latest_versions(items)  # la misma nota con otro enlace o titular, una vez (la última versión)
    recent = sorted((i for i in items if (i.get("published") or i["first_seen"]) >= since),
                    key=lambda i: i.get("published") or i["first_seen"])
    groups: list[dict] = []
    for it in recent:
        tok = _tokens(it["title"])
        for g in groups:
            # Solo se compara con el titular que abrió el grupo y con los que se le parecen a él («_core»). Si
            # bastara parecerse a cualquiera, los grupos se encadenan (A~B, B~C, C~D…) y dos semanas de lluvias,
            # sismos y reportes del COEN terminan bajo un solo titular.
            # Dos notas con departamentos distintos no son el mismo hecho, aunque el titular siga la misma plantilla
            # («Incendio forestal en el distrito de X (Áncash)» y «… de Y (Puno)» del COEN).
            deps = set(it.get("departments") or [])
            if g["region"] == it["region"] and not (deps and g["_deps"] and deps.isdisjoint(g["_deps"])) \
                    and any(_similar(tok, t) for t in g["_core"]):
                g["items"].append(it)
                g["_tokens"].append(tok)
                if _similar(tok, g["_core"][0]):
                    g["_core"].append(tok)
                break
        else:
            groups.append({"region": it["region"], "items": [it], "_tokens": [tok], "_core": [tok],
                           "_deps": set(it.get("departments") or [])})
    out = []
    for g in groups:
        # La misma nota puede llegar por el feed del medio y por Google Noticias.
        uniq: dict = {}
        links: set = set()
        for i, tok in zip(g["items"], g["_tokens"]):
            link = _norm_link(i["link"])
            if link in links:
                continue  # la misma nota llegó por dos feeds (el del medio y una búsqueda)
            if uniq.setdefault((_outlet(i).lower(), frozenset(tok)), i) is i:
                links.add(link)
        its = list(uniq.values())
        lead = its[0]
        # El resumen acompaña al titular que se muestra: primero el de esa misma nota; si no trae, el de otra nota
        # del grupo cuyo titular se le parece. Nunca el de una nota que solo entró por parecerse a una tercera.
        lead_tok = _tokens(lead["title"])
        said = lead_tok | _tokens(_outlet(lead))
        own = [x for x in (_without_title(i) for i in its if i is lead or _similar(_tokens(i["title"]), lead_tok))
               if x and not _tokens(x) <= said]
        mine = _without_title(lead)
        summary = mine if mine in own else max(own, key=len, default="")
        outlets = list(dict.fromkeys(_outlet(i) for i in its))
        places = list({p["code"]: p for i in its for p in (i.get("places") or [])}.values())
        out.append({
            "id": lead["id"], "region": g["region"], "title": lead["title"],
            "summary": _first_sentence(summary) if summary else "",
            "first": lead.get("published") or lead["first_seen"],
            "last": max(i.get("published") or i["first_seen"] for i in its),
            "relevance": "enso" if any(i["relevance"] == "enso" for i in its) else "impacto",
            "count": len(its), "outlets": outlets,
            "kinds": list(dict.fromkeys(i.get("kind") or _kind(i) for i in its)),
            "hazards": list(dict.fromkeys(h for i in its for h in (i.get("hazards") or hazards(i["title"], i.get("summary", ""))))),
            "departments": list(dict.fromkeys(d for i in its for d in (i.get("departments") or []))),
            "places": places[:6],
            "links": [{"id": i["id"], "title": i["title"], "url": i["link"], "outlet": _outlet(i),
                       "published": i.get("published"), "kind": i.get("kind") or _kind(i),
                       "archive": news_page(i)}
                      for i in its][:8],
        })
    out.sort(key=lambda g: (g["last"], g["count"]), reverse=True)
    return out


# --- Histórico de solo anexar y CSV -------------------------------------------

CSV_FIELDS = ["first_seen", "published", "region", "kind", "feed", "outlet", "relevance", "hazards", "departments",
              "places", "title", "summary", "link", "id"]


def _csv_value(i: dict, k: str) -> str:
    if k == "departments":
        from .geo import department_names
        names = department_names()
        return "; ".join(names.get(c, c) for c in i.get("departments") or [])
    if k == "places":
        return "; ".join(p["name"] for p in i.get("places") or [])
    if k == "hazards":
        return "; ".join(HAZARD_LABELS.get(h, h) for h in i.get("hazards") or [])
    return i.get(k) or ""


def read_jsonl(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue  # una línea dañada no invalida el resto del histórico
        if isinstance(obj, dict) and obj.get("id") and obj.get("link"):
            out.append(obj)
    return out


def new_lines(history: list[dict], fresh: list[dict], skipped: Optional[list] = None) -> list[dict]:
    """Entradas de ``fresh`` que aún no están en el histórico.

    Una entrada ya está si su ``id`` ya está o si es la misma nota (``identity_key``) con un titular ya visto: otra
    variante del enlace (``http``/``https``, «www.», parámetros de seguimiento) o el mismo titular con otro sufijo
    del medio o con otros espacios. Esas se anotan en ``skipped``. Si el titular es otro, es una corrección (el
    USGS recalcula el lugar y la magnitud, el COEN completa el reporte, un medio cambia el titular): se agrega con
    ``revises``, el ``id`` de la primera versión, y ``cluster`` muestra la última."""
    seen = {h["id"] for h in history}
    shared = _shared_links(fresh)
    first: dict[tuple, str] = {}
    titles: dict[tuple, set[str]] = {}
    for h in history:
        k = identity_key(h, shared)
        first.setdefault(k, h.get("revises") or h["id"])
        titles.setdefault(k, set()).add(_title_key(h.get("title") or ""))
    out = []
    for f in fresh:
        if f["id"] in seen:
            continue
        seen.add(f["id"])
        k = identity_key(f, shared)
        t = _title_key(f.get("title") or "")
        if k in titles and t in titles[k]:
            if skipped is not None:
                skipped.append(f)
            continue
        if k in first:
            f = dict(f, revises=first[k])
        else:
            first[k] = f["id"]
        titles.setdefault(k, set()).add(t)
        out.append(f)
    return out


def latest_versions(items: list[dict]) -> list[dict]:
    """Una entrada por nota (``identity_key``): la última versión vista, en el lugar de la primera. Las copias
    del histórico anteriores a ``new_lines`` con ``revises`` (otra variante del enlace o del titular) se juntan
    igual, porque la clave sale del enlace canónico y no de ese campo."""
    shared = _shared_links(items)
    pos: dict[tuple, int] = {}
    out: list[dict] = []
    for i in items:
        k = identity_key(i, shared)
        if k not in pos:
            pos[k] = len(out)
            out.append(i)
        elif (i.get("first_seen") or "") >= (out[pos[k]].get("first_seen") or ""):
            out[pos[k]] = i
    return out


def _csv_safe(v) -> str:
    """Evita que una hoja de cálculo interprete un titular como fórmula."""
    s = str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def to_csv(items: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for i in sorted(items, key=lambda i: i.get("published") or i["first_seen"], reverse=True):
        w.writerow({k: _csv_safe(_csv_value(i, k)) for k in CSV_FIELDS})
    return buf.getvalue()


# --- Recolección -------------------------------------------------------------

def _by_host(feeds: list[Feed]) -> list[list[Feed]]:
    """Feeds agrupados por servidor: cada grupo se descarga en serie (cortesía), los grupos en paralelo."""
    groups: dict[str, list[Feed]] = {}
    for f in feeds:
        groups.setdefault(re.sub(r"^https?://([^/]+).*", r"\1", f.url), []).append(f)
    return list(groups.values())


def longest_gap_days(dates: list[str]) -> Optional[int]:
    """Días del hueco más largo entre dos entradas consecutivas (fechas ISO, en cualquier orden); None con menos de dos
    fechas distintas o alguna ilegible. Dice cuánto suele callar un medio que publica a rachas (``feed-stale``)."""
    try:
        ts = sorted({datetime.fromisoformat(d) for d in dates if d})
    except (TypeError, ValueError):
        return None
    if len(ts) < 2:
        return None
    return int(max((b - a).total_seconds() for a, b in zip(ts, ts[1:])) // 86400)


def _status(f: Feed, now: datetime, error: str = "") -> dict:
    return {"id": f.id, "name": f.name, "region": f.region, "url": f.url, "lang": f.lang, "scope": f.scope,
            "kind": f.kind, "department": f.department, "checkedAt": now.isoformat(timespec="seconds"), "ok": False,
            "items": 0, "relevant": 0, "latest": None, "active": False, "error": error, "format": None, "repairs": []}


def _layer_listing_url(url: str) -> Optional[str]:
    m = re.match(r"(https?://[^?]+/(?:MapServer|FeatureServer))/\d+(?:/query)?(?:\?|$)", url)
    return f"{m.group(1)}?f=json" if m else None


def _layer_name(name: str) -> str:
    """El nombre de una capa sin el esquema de la base («SDE.») ni mayúsculas: republicar la capa desde otra base no
    es moverla."""
    return str(name or "").rsplit(".", 1)[-1].strip().lower()


def check_layer(f: Feed, fetch, st: dict, listings: Optional[dict] = None) -> str:
    """Comprueba en el listado del servicio (``MapServer?f=json``) que la capa del URL de ``f`` sigue llamándose
    ``f.layer``. Devuelve el error si se renumeró, se renombró o se retiró, y "" si coincide o no se pudo comprobar
    (``st["layerCheck"]`` dice cuál): un listado que no llega no convierte en falla una capa vacía. ``listings``
    guarda el listado de cada servicio durante una recolección: varias capas vacías del mismo servicio (o un servidor
    que no responde) cuestan un solo pedido."""
    listing = _layer_listing_url(f.url)
    m = re.search(r"/(?:MapServer|FeatureServer)/(\d+)", f.url)
    if not listing or not m:
        st["layerCheck"] = "no verificado: el URL no es de una capa de ArcGIS"
        return ""
    lid = int(m.group(1))
    try:
        if listings is not None and listing in listings:
            got = listings[listing]
        else:
            try:
                got = fetch(listing)
            except Exception as exc:  # noqa: BLE001
                got = (None, b"", "", f"{type(exc).__name__}")
            if listings is not None:
                listings[listing] = got
        code, body = got[0], got[1]
        if code is None and len(got) > 3 and got[3] and not body:
            raise LookupError(str(got[3]))
        layers = json.loads(body.decode("utf-8-sig"))["layers"] if code == 200 and body else None
        names = {int(x["id"]): str(x.get("name") or "") for x in layers}
    except Exception as exc:  # noqa: BLE001 — sin listado la capa vacía sigue siendo «sin avisos vigentes»
        why = str(exc) if isinstance(exc, LookupError) and not isinstance(exc, KeyError) else type(exc).__name__
        st["layerCheck"] = f"no verificado: {why}"[:120]
        return ""
    if layers is None:
        st["layerCheck"] = f"no verificado: el listado respondió HTTP {code}"
        return ""
    if _layer_name(names.get(lid)) == _layer_name(f.layer):
        st["layerCheck"] = "ok"
        return ""
    st["layerCheck"] = "distinta"
    now_at = [i for i, n in names.items() if _layer_name(n) == _layer_name(f.layer)]
    return (f"la capa {lid} del servidor ya no es «{f.layer}»: es «{names.get(lid) or 'inexistente'}»"
            + (f"; «{f.layer}» está ahora en la capa {now_at[0]} (actualizar el URL del feed)" if now_at else
               f"; «{f.layer}» no figura en el listado del servicio (¿se retiró?)") + f" — {listing}")


def _quiet_empty(f: Feed, parsed) -> bool:
    """La respuesta sin entradas quiere decir «no hay avisos vigentes», no un feed vaciado: una capa de avisos o FIRMS
    sin focos, o el último mensaje del PTWC cuando es un simulacro (PACWAVE26: sin esto el feed quedaba «empty» y
    escalaba a issue a los 14 días aunque nada hubiera cambiado en la fuente)."""
    from .hazardparse import PTWC_EXERCISE

    return f.adapter in ("arcgis", "firms") or (f.adapter == "ptwc-text" and PTWC_EXERCISE in parsed.repairs)


def _read_feed(f: Feed, fetch, now: datetime, listings: Optional[dict] = None) -> tuple[dict, list[dict], Optional[bytes]]:
    from .geo import legacy_fields, locate_item

    seen_at = now.isoformat(timespec="seconds")
    st = _status(f, now)
    got = fetch(f.url)
    code, body, ctype, err = got[:4]
    via = got[4] if len(got) > 4 and isinstance(got[4], dict) else {}
    if via.get("requested") is not False:  # sin «httpStatus»: no se le pidió nada al servidor
        st["httpStatus"] = code
    if via.get("channel") not in (None, "direct"):
        # Copia de otro recolector (Perú, n8n) o réplica: el sitio dice de cuándo es y por qué canal llegó.
        st["channel"] = via["channel"]
        st["copyAt"] = via.get("copyAt")
        if via.get("directError"):
            st["directError"] = via["directError"]  # por qué no sirvió el pedido directo
        if via.get("upstreamDown"):
            # El recolector arrastró su última copia buena: el servidor no la está dando (n8n: HTTP 500 del CENVUL
            # el 20-11-2026 con la copia del 19 publicada como si el feed respondiera).
            st["upstreamDown"] = via["upstreamDown"]
    if code != 200 or not body:
        st["error"] = err or f"HTTP {code}"
        return st, [], None
    try:
        parsed = parse_any(body, base_url=f.url, default_tz=LIMA if f.region == "peru" else timezone.utc, now=now,
                           adapter=f.adapter)
    except FeedError as exc:
        st["error"] = str(exc)
        st["formatError"] = True  # respondió, pero con otra forma (una capa renumerada, otro formato)
        return st, [], body
    except Exception as exc:  # noqa: BLE001 — un feed raro no debe detener la recolección de los demás
        st["error"] = f"error inesperado al leer el feed: {type(exc).__name__}: {exc}"[:300]
        return st, [], body
    if f.adapter == "arcgis" and f.layer:
        from .hazardparse import arcgis_kind_error

        wrong = arcgis_kind_error(f.layer, parsed.title)
        if wrong:
            st.update({"error": wrong, "formatError": True})
            return st, [], body
    entries = parsed.items
    cut = truncated(body, f.adapter)
    if cut:
        st["truncated"] = cut  # las entradas rescatadas se usan; ``persistent`` lo cuenta como ilegible
    dates = [e["published"] for e in entries if e["published"]]
    st.update({"ok": True, "items": len(entries), "latest": max(dates) if dates else None,
               "format": parsed.format, "repairs": parsed.repairs})
    st["active"] = bool(st["latest"]) and st["latest"] >= (now - timedelta(days=f.stale_days)).isoformat()
    gap = longest_gap_days(dates)
    if gap is not None:
        st["longestGapDays"] = gap  # el hueco más largo entre dos entradas del feed: lo que el medio suele callar
    if not entries and not _quiet_empty(f, parsed):  # una capa de avisos vacía es que no hay avisos vigentes
        st["error"] = "feed sin entradas"
    if not entries and f.layer:
        # Vacía: o no hay avisos vigentes, o la capa del URL ya no es la de estos avisos (sin campos no se distingue).
        moved = check_layer(f, fetch, st, listings)
        if moved:
            st.update({"ok": False, "active": False, "error": moved, "formatError": True})
            return st, [], body
    future = (now + timedelta(hours=2)).isoformat()
    oldest = (now - timedelta(days=f.max_age_days)).isoformat() if f.max_age_days else ""
    found = []
    for e in entries:
        if oldest and (not e["published"] or e["published"] < oldest):
            continue  # sin fecha no se puede saber si es de hace años
        outlet = e.get("outlet") or f.name
        if SOCIAL_RE.search(e["link"]) or SOCIAL_RE.search(outlet):
            continue  # publicaciones en redes sociales, no notas de prensa
        title = _strip_outlet(e["title"], outlet)
        summary = _strip_summary(e["summary"], e["title"], title, outlet)
        why = relevance(f, title, summary)
        if not why:
            continue
        text = f"{title} {summary}"
        named_peru = bool(PERU_WORD_RE.search(text))
        if f.region == "peru" and not named_peru and FOREIGN_TLD_RE.search(e.get("outletUrl") or ""):
            continue  # medio de otro país en una búsqueda de Google Noticias (Junín de Argentina, Jaén de España…)
        # Lo que ubica la nota además del texto: códigos, coordenadas, lugares en campos propios y, en medios
        # nacionales, las categorías (las de un medio regional son sus secciones: «Trujillo», «Edición Impresa»).
        hint = {k: e[k] for k in ("ubigeo", "coords", "geo") if e.get(k)}
        if e.get("categories") and not f.department:
            hint["categories"] = e["categories"]
        try:
            g = locate_item({"title": title, "summary": summary, "outlet": outlet, **hint}, f, f.region)
        except Exception:  # noqa: BLE001 — una nota con texto raro queda sin lugar, no sin noticias
            g = None
        located = bool(g and g["places"] and g["method"] != "medio")
        if why == "impacto" and not named_peru and FOREIGN_RE.search(text) and not located:
            continue  # inundaciones en España publicadas por un medio regional: no es una alerta para el Perú
        st["relevant"] += 1
        published = e["published"]
        if published and published > future:
            # Algunos medios publican la hora local marcada como UTC.
            st["futureDates"] = st.get("futureDates", 0) + 1
            published = seen_at
        item = {"id": item_id(e["link"], e["title"]), "first_seen": seen_at, "published": published,
                "region": f.region, "feed": f.id, "kind": f.kind, "outlet": outlet, "relevance": why,
                "hazards": hazards(title, summary), "title": title, "summary": summary, "link": e["link"]}
        if hint:
            item["geoHint"] = hint  # para volver a ubicar la nota cuando mejore el nomenclátor
        # Lo que la fuente ubica más fino que un distrito, para el mapa de alertas: estaciones, epicentros, focos de
        # calor y volcanes (``points``), polígonos de los avisos (``shapes``) y distritos con quebradas (``areas``).
        detail = {k: e[k] for k in ("points", "shapes", "areas") if e.get(k)}
        if detail:
            item["detail"] = detail
        if g:
            item["geo"] = g
            item.update(legacy_fields(g))
        found.append(item)
    return st, found, body


def collect(fetch, now: datetime, feeds: Optional[list[Feed]] = None, workers: int = 8,
            deadline: Optional[float] = None, host_failures: int = 2,
            on_result=None) -> tuple[list[dict], list[dict], dict[str, bytes]]:
    """Descarga los feeds. ``fetch(url)`` devuelve (estado, cuerpo, tipo, error[, {channel, copyAt}]) y debe
    ser seguro entre hilos. ``on_result(feed, estado, entradas, cuerpo)``, si se da, se llama en cuanto termina
    cada feed (también seguro entre hilos); un error suyo no detiene la recolección.

    Los feeds de un mismo servidor se piden en serie (cortesía). Tras ``host_failures``
    fallos de red seguidos se omiten los demás feeds de ese servidor, y pasados
    ``deadline`` segundos no se empiezan feeds nuevos: un servidor lento no puede
    dejar al sitio sin noticias. Un error inesperado en un feed no afecta a los demás.

    Devuelve (entradas relevantes, estado por feed, cuerpos crudos por feed), en el orden del catálogo.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    feeds = FEEDS if feeds is None else feeds
    results: dict[str, tuple] = {}
    listings: dict[str, tuple] = {}  # listados de servicios ArcGIS (``check_layer``): uno por servicio y corrida
    started = time.monotonic()

    def run_group(group: list[Feed]) -> None:
        fails = 0
        for f in group:
            if fails >= host_failures:
                results[f.id] = (_status(f, now, "omitido: el servidor no respondió a los feeds anteriores")
                                 | {"omitted": "host"}, [], None)
                continue
            if deadline is not None and time.monotonic() - started > deadline:
                results[f.id] = (_status(f, now, "omitido: se agotó el tiempo de la recolección de noticias")
                                 | {"omitted": "deadline"}, [], None)
                continue
            try:
                results[f.id] = _read_feed(f, fetch, now, listings)
            except Exception as exc:  # noqa: BLE001 — un feed que falla de forma inesperada no detiene a los demás
                results[f.id] = (_status(f, now, f"error inesperado: {type(exc).__name__}: {exc}"[:300]), [], None)
            if on_result is not None:
                try:
                    on_result(f, *results[f.id])
                except Exception:  # noqa: BLE001
                    pass
            st = results[f.id][0]
            # Sin respuesta, o 429 (el servidor pide que se le pida menos): cuenta para dejar de pedirle.
            fails = fails + 1 if not st["ok"] and st.get("httpStatus") in (None, 429) else 0

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(run_group, _by_host(feeds)))
    found, status, raw, seen = [], [], {}, set()
    for f in feeds:
        st, items, body = results[f.id]
        status.append(st)
        # La misma nota puede llegar por dos feeds del mismo medio (Correo y sus ediciones regionales).
        found.extend(i for i in items if not (i["id"] in seen or seen.add(i["id"])))
        if body is not None:
            raw[f.id] = body
    return found, status, raw
