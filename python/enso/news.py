"""Noticias: feeds RSS/Atom de medios del Perú y del mundo sobre El Niño.

Cada corrida:
  1. Descarga cada feed del catálogo ``FEEDS`` y registra su estado
     (responde, cuántas entradas, fecha de la más reciente). Un feed sin
     entradas nuevas en ``stale_days`` se marca inactivo.
  2. Se queda con las entradas que tratan del ENSO o de sus impactos en el
     Perú (``relevance``). Los feeds temáticos (ReliefWeb Perú, GDACS) usan
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

from .feedparse import LIMA, FeedError, parse as parse_any


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
    #: "feed" (RSS/Atom/JSON Feed) o "gobpe" (listado de noticias de gob.pe, sin RSS).
    adapter: str = "feed"

    @property
    def fixture(self) -> str:
        """Nombre del archivo capturado (fixtures y archivo crudo)."""
        return f"news-{self.id}.{'html' if self.adapter == 'gobpe' else 'xml'}"


_GN = "https://news.google.com/rss/search?q="

#: Catálogo de feeds verificado en vivo desde GitHub Actions el 21 de octubre
#: de 2026 (los nacionales y del mundo con ``tools.capture_sources``; los de
#: regiones, radios y entidades del Estado con ``tools.probe_feeds``, cuyo
#: informe queda en tests/fixtures/news-probe/report.json). Ver
#: docs/catalogo-fuentes.md, donde también figuran los descartados. El estado de
#: cada uno se vuelve a verificar en cada corrida y se publica en ``news/feeds.json``.
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
    Feed("perureports", "Peru Reports", "peru", "https://perureports.com/feed/", lang="en", kind="digital"),
    Feed("gnews-peru", "Google Noticias Perú (búsqueda El Niño)", "peru",
         _GN + "%22El%20Ni%C3%B1o%22%20OR%20ENFEN%20OR%20%22Ni%C3%B1o%20costero%22&hl=es-419&gl=PE&ceid=PE:es-419",
         scope="hazard", stale_days=3, kind="agregador"),
    # Perú · Estado y búsquedas nacionales (sondeo del 21 de octubre de 2026)
    Feed("el-peruano", "El Peruano (diario oficial)", "peru", "https://news.google.com/rss/search?q=site%3Aelperuano.pe&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-ana", "Autoridad Nacional del Agua · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=ana&sheet=1&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-busqueda-peligros", "gob.pe · búsqueda de noticias por peligro", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&sheet=1&sort_by=recent&term=huaico",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-cenepred", "CENEPRED · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=cenepred&sheet=1&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-igp", "Instituto Geofísico del Perú · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=igp&sheet=1&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-indeci", "INDECI (incl. COEN) · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=indeci&sheet=1&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-midagri", "MIDAGRI (sequía, heladas, agro) · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=midagri&sheet=1&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-minam", "Ministerio del Ambiente · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=minam&sheet=1&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-pcm", "PCM (declaratorias de emergencia) · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=pcm&sheet=1&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-presidencia", "Presidencia de la República · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=presidencia&sheet=1&sort_by=recent",
         kind="gobierno", scope="hazard", stale_days=30),
    Feed("gobpe-senamhi", "SENAMHI · gob.pe", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=senamhi&sheet=1&sort_by=recent",
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
    Feed("noticias-ser", "Noticias SER", "peru", "https://www.noticiasser.pe/feed/",
         kind="digital", scope="general", stale_days=7),
    # Amazonas
    Feed("gobpe-regionamazonas", "Gobierno Regional de Amazonas (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionamazonas&sheet=1&sort_by=recent",
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
    Feed("gobpe-regionapurimac", "Gobierno Regional de Apurímac (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionapurimac&sheet=1&sort_by=recent",
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
    Feed("gobpe-regionarequipa", "Gobierno Regional de Arequipa (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionarequipa&sheet=1&sort_by=recent",
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
    Feed("gobpe-regionayacucho", "Gobierno Regional de Ayacucho (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionayacucho&sheet=1&sort_by=recent",
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
    Feed("gobpe-regioncallao", "Gobierno Regional de Callao (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regioncallao&sheet=1&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="07"),
    Feed("gnews-07", "Google Noticias · Callao", "peru", "https://news.google.com/rss/search?q=%28Callao%20OR%20Ventanilla%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="07"),
    Feed("rpp-callao", "RPP Noticias · Callao", "peru", "https://rpp.pe/feed/peru/callao",
         kind="radio", scope="local", stale_days=30, department="07"),
    Feed("nacional-callao-tv", "Nacional Callao TV", "peru", "https://nacionalcallaotv.pe/feed/",
         kind="tv", scope="local", stale_days=21, department="07"),
    Feed("prensa-chalaca", "Prensa Chalaca", "peru", "https://prensachalaca.com/feed/",
         kind="digital", scope="local", stale_days=21, department="07"),
    # Cusco
    Feed("gobpe-regioncusco", "Gobierno Regional de Cusco (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regioncusco&sheet=1&sort_by=recent",
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
    Feed("gobpe-regionhuancavelica", "Gobierno Regional de Huancavelica (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionhuancavelica&sheet=1&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="09"),
    Feed("gnews-09", "Google Noticias · Huancavelica", "peru", "https://news.google.com/rss/search?q=%28Huancavelica%20OR%20Tayacaja%20OR%20Angaraes%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="09"),
    Feed("rpp-huancavelica", "RPP Noticias · Huancavelica", "peru", "https://rpp.pe/feed/peru/huancavelica",
         kind="radio", scope="local", stale_days=30, department="09"),
    Feed("altavoz-huancavelica", "Altavoz · tema Huancavelica", "peru", "https://altavoz.pe/temas/huancavelica/feed/",
         kind="digital", scope="local", stale_days=21, department="09"),
    # Huánuco
    Feed("gobpe-regionhuanuco", "Gobierno Regional de Huánuco (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionhuanuco&sheet=1&sort_by=recent",
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
    Feed("gobpe-regionlalibertad", "Gobierno Regional de La Libertad (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionlalibertad&sheet=1&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="13"),
    Feed("gnews-13", "Google Noticias · La Libertad", "peru", "https://news.google.com/rss/search?q=%28%22La%20Libertad%22%20OR%20Trujillo%20OR%20Pacasmayo%20OR%20Chep%C3%A9n%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="13"),
    Feed("rpp-la-libertad", "RPP Noticias · La Libertad", "peru", "https://rpp.pe/feed/peru/la-libertad",
         kind="radio", scope="local", stale_days=30, department="13"),
    Feed("soltv-la-libertad", "Sol TV · La Libertad", "peru", "https://soltvperu.com/category/regiones/la-libertad-noticias/feed/",
         kind="tv", scope="local", stale_days=21, department="13"),
    # Lambayeque
    Feed("gobpe-regionlambayeque", "Gobierno Regional de Lambayeque (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionlambayeque&sheet=1&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="14"),
    Feed("gnews-14", "Google Noticias · Lambayeque", "peru", "https://news.google.com/rss/search?q=%28Lambayeque%20OR%20Chiclayo%20OR%20Ferre%C3%B1afe%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="14"),
    Feed("rpp-lambayeque", "RPP Noticias · Lambayeque", "peru", "https://rpp.pe/feed/peru/lambayeque",
         kind="radio", scope="local", stale_days=30, department="14"),
    Feed("soltv-lambayeque", "Sol TV · Lambayeque", "peru", "https://soltvperu.com/category/regiones/lambayeque-noticias/feed/",
         kind="tv", scope="local", stale_days=21, department="14"),
    # Lima
    Feed("gobpe-regionlima", "Gobierno Regional de Lima (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionlima&sheet=1&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="15"),
    Feed("gnews-15", "Google Noticias · Lima", "peru", "https://news.google.com/rss/search?q=%28%22Lima%20Metropolitana%22%20OR%20Huaura%20OR%20Huacho%20OR%20Ca%C3%B1ete%20OR%20Huaral%20OR%20Barranca%20OR%20Chosica%20OR%20Huarochir%C3%AD%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=14, department="15"),
    Feed("rpp-lima", "RPP Noticias · Lima/Actualidad", "peru", "https://rpp.pe/feed/lima/actualidad",
         kind="radio", scope="local", stale_days=30, department="15"),
    # Loreto
    Feed("gobpe-regionloreto", "Gobierno Regional de Loreto (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionloreto&sheet=1&sort_by=recent",
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
    Feed("gobpe-regionmadrededios", "Gobierno Regional de Madre de Dios (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionmadrededios&sheet=1&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="17"),
    Feed("gnews-17", "Google Noticias · Madre de Dios", "peru", "https://news.google.com/rss/search?q=%28%22Madre%20de%20Dios%22%20OR%20%22Puerto%20Maldonado%22%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="17"),
    Feed("radio-madre-de-dios", "Radio Madre de Dios", "peru", "https://noticias.madrededios.com/rss/",
         kind="radio", scope="local", stale_days=21, department="17"),
    Feed("rpp-madre-de-dios", "RPP Noticias · Madre de Dios", "peru", "https://rpp.pe/feed/peru/madre-de-dios",
         kind="radio", scope="local", stale_days=30, department="17"),
    # Moquegua
    Feed("gobpe-regionmoquegua", "Gobierno Regional de Moquegua (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionmoquegua&sheet=1&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="18"),
    Feed("gnews-18", "Google Noticias · Moquegua", "peru", "https://news.google.com/rss/search?q=%28Moquegua%20OR%20Ilo%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="18"),
    Feed("rpp-moquegua", "RPP Noticias · Moquegua", "peru", "https://rpp.pe/feed/peru/moquegua",
         kind="radio", scope="local", stale_days=30, department="18"),
    Feed("prensa-regional", "La Prensa Regional (Moquegua)", "peru", "https://prensaregional.pe/feed/",
         kind="diario", scope="local", stale_days=21, department="18"),
    # Pasco
    Feed("gobpe-regionpasco", "Gobierno Regional de Pasco (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionpasco&sheet=1&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="19"),
    Feed("gnews-19", "Google Noticias · Pasco", "peru", "https://news.google.com/rss/search?q=%28Pasco%20OR%20Oxapampa%20OR%20%22Cerro%20de%20Pasco%22%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="19"),
    Feed("rpp-pasco", "RPP Noticias · Pasco", "peru", "https://rpp.pe/feed/peru/pasco",
         kind="radio", scope="local", stale_days=30, department="19"),
    Feed("pasco-libre", "Pasco Libre", "peru", "http://www.pascolibre.com/feeds/posts/default?alt=rss",
         kind="digital", scope="local", stale_days=21, department="19"),
    # Piura
    Feed("gobpe-regionpiura", "Gobierno Regional de Piura (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionpiura&sheet=1&sort_by=recent",
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
    Feed("gobpe-regionpuno", "Gobierno Regional de Puno (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionpuno&sheet=1&sort_by=recent",
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
    Feed("gobpe-regionsanmartin", "Gobierno Regional de San Martín (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionsanmartin&sheet=1&sort_by=recent",
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
    Feed("gobpe-regiontumbes", "Gobierno Regional de Tumbes (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regiontumbes&sheet=1&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="24"),
    Feed("gnews-24", "Google Noticias · Tumbes", "peru", "https://news.google.com/rss/search?q=%28Tumbes%20OR%20Zarumilla%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="24"),
    Feed("rpp-tumbes", "RPP Noticias · Tumbes", "peru", "https://rpp.pe/feed/peru/tumbes",
         kind="radio", scope="local", stale_days=30, department="24"),
    Feed("tumbes-de-miercoles", "Tumbes de Miércoles", "peru", "https://news.google.com/rss/search?q=site%3Atumbesdemiercoles.com.pe&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="digital", scope="local", stale_days=21, department="24"),
    # Ucayali
    Feed("gobpe-regionucayali", "Gobierno Regional de Ucayali (gob.pe)", "peru", "https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=regionucayali&sheet=1&sort_by=recent",
         kind="gobierno", scope="local", stale_days=45, department="25"),
    Feed("gnews-25", "Google Noticias · Ucayali", "peru", "https://news.google.com/rss/search?q=%28Ucayali%20OR%20Pucallpa%29%20%28lluvias%20OR%20huaico%20OR%20inundaci%C3%B3n%20OR%20desborde%20OR%20%22El%20Ni%C3%B1o%22%20OR%20sequ%C3%ADa%20OR%20helada%20OR%20emergencia%20OR%20Senamhi%20OR%20Indeci%29%20when%3A7d&hl=es-419&gl=PE&ceid=PE:es-419",
         kind="agregador", scope="local", stale_days=3, department="25"),
    Feed("rpp-ucayali", "RPP Noticias · Ucayali", "peru", "https://rpp.pe/feed/peru/ucayali",
         kind="radio", scope="local", stale_days=30, department="25"),
    Feed("gaceta-ucayalina", "Gaceta Ucayalina", "peru", "https://www.gacetaucayalina.com/feed/",
         kind="digital", scope="local", stale_days=21, department="25"),
    Feed("gobpe-imarpe", "IMARPE · noticias en gob.pe", "peru", "https://www.gob.pe/institucion/imarpe/noticias",
         kind="gobierno", scope="hazard", stale_days=30, adapter="gobpe"),
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

# --- Relevancia --------------------------------------------------------------

ENSO_RE = re.compile(
    r"\b(el ni[nñ]o|la ni[nñ]a|enso|ni[nñ]o costero|ni[nñ]a costera|enfen|icen|oscilaci[oó]n del sur|"
    r"fen[oó]meno del ni[nñ]o|anomal[ií]as? de (la )?temperatura del mar|calentamiento del mar|"
    r"temperatura superficial del mar|mar peruano|corriente de humboldt|niño 1\+2|niño 3\.4)\b", re.I)
HAZARD_RE = re.compile(
    r"\b(lluvias? (intensas?|fuertes?)|huaicos?|inundaci[oó]n(es)?|desbordes?|sequ[ií]as?|friaje|heladas?|"
    r"oleajes?|deslizamientos?|emergencia|senamhi|indeci|cenepred|imarpe|igp|aviso meteorol[oó]gico|"
    r"flood(s|ing)?|drought|heavy rain|landslides?|cyclone|tropical storm|climate|clima)\b", re.I)
#: Peligros concretos para medios regionales (sin «emergencia» ni «clima», demasiado amplios).
LOCAL_RE = re.compile(
    r"\b(lluvias?|precipitaci[oó]n(es)?|huaicos?|inundaci[oó]n(es)?|inundad[oa]s?|desbordes?|desbord[oó]|"
    r"crecida|caudal|sequ[ií]as?|d[eé]ficit h[ií]drico|friaje|heladas?|nevadas?|granizadas?|oleajes?|"
    r"deslizamientos?|derrumbes?|aluvi[oó]n|activaci[oó]n de quebradas?|quebradas? activad|damnificad[oa]s?|"
    r"estado de emergencia|alerta (roja|naranja|amarilla)|senamhi|indeci|coer|coen|cenepred|"
    r"temperatura del mar|anchoveta|pesca artesanal|dengue)\b", re.I)
PERU_RE = re.compile(r"\b(per[uú]|peruan[oa]s?|lima|piura|tumbes|lambayeque|la libertad|ica|arequipa|"
                     r"ancash|[aá]ncash|loreto|cusco|puno|cajamarca|jun[ií]n)\b", re.I)


def relevance(feed: Feed, title: str, summary: str) -> Optional[str]:
    """Motivo por el que una entrada es relevante, o None."""
    text = f"{title} {summary}"
    if ENSO_RE.search(text):
        return "enso"
    if feed.scope == "hazard" and HAZARD_RE.search(text) and (feed.region == "peru" or PERU_RE.search(text)):
        return "impacto"
    if feed.scope == "local" and LOCAL_RE.search(text):
        return "impacto"
    return None


# --- Lectura de RSS/Atom -----------------------------------------------------
# El lector tolerante (reparaciones, formatos, fechas) está en ``feedparse``.

def parse_feed(body: bytes, base_url: str = "", adapter: str = "feed") -> list[dict]:
    """Entradas homologadas de un feed (RSS 2.0/1.0, Atom, JSON Feed o listado de gob.pe)."""
    return parse_any(body, base_url=base_url, adapter=adapter).items


SOCIAL_RE = re.compile(r"(facebook|instagram|tiktok|twitter|youtube)\.com|//(www\.)?x\.com/|^(Facebook|Instagram|TikTok|X|YouTube)$", re.I)


def _strip_outlet(title: str, outlet: str) -> str:
    """Google Noticias termina los titulares con « - Medio»."""
    for sep in (" - ", " – ", " | "):
        if outlet and title.endswith(sep + outlet):
            return title[: -len(sep + outlet)].rstrip()
    return title


def item_id(link: str, title: str) -> str:
    return hashlib.sha256(f"{link.strip()}|{title.strip().lower()}".encode()).hexdigest()[:16]


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
    u = re.sub(r"[?&](utm_[a-z]+|outputType|ref|fbclid)=[^&#]*", "", u).rstrip("?&#/")
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
    recent = sorted((i for i in items if (i.get("published") or i["first_seen"]) >= since),
                    key=lambda i: i.get("published") or i["first_seen"])
    groups: list[dict] = []
    for it in recent:
        tok = _tokens(it["title"])
        for g in groups:
            if g["region"] == it["region"] and any(_similar(tok, t) for t in g["_tokens"]):
                g["items"].append(it)
                g["_tokens"].append(tok)
                break
        else:
            groups.append({"region": it["region"], "items": [it], "_tokens": [tok]})
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
        own = [x for x in (_without_title(i) for i in its) if x and not _tokens(x) <= _tokens(lead["title"]) | _tokens(_outlet(lead))]
        summary = max(own, key=len, default="")
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
            "departments": list(dict.fromkeys(d for i in its for d in (i.get("departments") or []))),
            "places": places[:6],
            "links": [{"title": i["title"], "url": i["link"], "outlet": _outlet(i), "published": i.get("published"),
                       "kind": i.get("kind") or _kind(i)}
                      for i in its][:8],
        })
    out.sort(key=lambda g: (g["last"], g["count"]), reverse=True)
    return out


# --- Histórico de solo anexar y CSV -------------------------------------------

CSV_FIELDS = ["first_seen", "published", "region", "kind", "feed", "outlet", "relevance", "departments", "places",
              "title", "summary", "link", "id"]


def _csv_value(i: dict, k: str) -> str:
    if k == "departments":
        from .geo import department_names
        names = department_names()
        return "; ".join(names.get(c, c) for c in i.get("departments") or [])
    if k == "places":
        return "; ".join(p["name"] for p in i.get("places") or [])
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


def new_lines(history: list[dict], fresh: list[dict]) -> list[dict]:
    """Entradas de ``fresh`` que aún no están en el histórico (por id)."""
    seen = {h["id"] for h in history}
    out = []
    for f in fresh:
        if f["id"] not in seen:
            seen.add(f["id"])
            out.append(f)
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


def _read_feed(f: Feed, fetch, now: datetime) -> tuple[dict, list[dict], Optional[bytes]]:
    from .geo import gazetteer

    seen_at = now.isoformat(timespec="seconds")
    st = {"id": f.id, "name": f.name, "region": f.region, "url": f.url, "lang": f.lang, "scope": f.scope,
          "kind": f.kind, "department": f.department, "checkedAt": seen_at, "ok": False, "items": 0,
          "relevant": 0, "latest": None, "active": False, "error": "", "format": None, "repairs": []}
    code, body, ctype, err = fetch(f.url)
    st["httpStatus"] = code
    if code != 200 or not body:
        st["error"] = err or f"HTTP {code}"
        return st, [], None
    try:
        parsed = parse_any(body, base_url=f.url, default_tz=LIMA if f.region == "peru" else timezone.utc, now=now,
                           adapter=f.adapter)
    except FeedError as exc:
        st["error"] = str(exc)
        return st, [], body
    entries = parsed.items
    dates = [e["published"] for e in entries if e["published"]]
    st.update({"ok": True, "items": len(entries), "latest": max(dates) if dates else None,
               "format": parsed.format, "repairs": parsed.repairs})
    st["active"] = bool(st["latest"]) and st["latest"] >= (now - timedelta(days=f.stale_days)).isoformat()
    if not entries:
        st["error"] = "feed sin entradas"
    future = (now + timedelta(hours=2)).isoformat()
    gz = gazetteer()
    found = []
    for e in entries:
        outlet = e.get("outlet") or f.name
        if SOCIAL_RE.search(e["link"]) or SOCIAL_RE.search(outlet):
            continue  # publicaciones en redes sociales, no notas de prensa
        title = _strip_outlet(e["title"], outlet)
        why = relevance(f, title, e["summary"])
        if not why:
            continue
        st["relevant"] += 1
        published = e["published"]
        if published and published > future:
            # Algunos medios publican la hora local marcada como UTC.
            st["futureDates"] = st.get("futureDates", 0) + 1
            published = seen_at
        tag = gz.tag([title, e["summary"], " · ".join(e.get("categories") or [])],
                     peru_context=f.region == "peru", default_dep=f.department)
        item = {"id": item_id(e["link"], e["title"]), "first_seen": seen_at, "published": published,
                "region": f.region, "feed": f.id, "kind": f.kind, "outlet": outlet, "relevance": why,
                "title": title, "summary": e["summary"], "link": e["link"]}
        if tag:
            item["departments"] = tag["departments"]
            item["places"] = [{k: p[k] for k in ("code", "level", "name")} for p in tag["places"]]
            item["geoSource"] = tag["source"]
        found.append(item)
    return st, found, body


def collect(fetch, now: datetime, feeds: Optional[list[Feed]] = None,
            workers: int = 8) -> tuple[list[dict], list[dict], dict[str, bytes]]:
    """Descarga los feeds. ``fetch(url)`` devuelve (estado, cuerpo, tipo, error) y debe ser seguro entre hilos.

    Devuelve (entradas relevantes, estado por feed, cuerpos crudos por feed), en el orden del catálogo.
    """
    from concurrent.futures import ThreadPoolExecutor

    feeds = FEEDS if feeds is None else feeds
    results: dict[str, tuple] = {}

    def run_group(group: list[Feed]) -> None:
        for f in group:
            results[f.id] = _read_feed(f, fetch, now)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(run_group, _by_host(feeds)))
    found, status, raw = [], [], {}
    for f in feeds:
        st, items, body = results[f.id]
        status.append(st)
        found.extend(items)
        if body is not None:
            raw[f.id] = body
    return found, status, raw
