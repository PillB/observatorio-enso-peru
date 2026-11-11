"""Conciliación de las cifras de personas con la población oficial de su área.

Una fila no puede tener más personas afectadas, damnificadas, evacuadas, reubicadas o desplazadas que habitantes
tiene su área en el año del evento (``Territory.population_at``: las estimaciones del INEI de 1990-2005, el censo de
2017 y las proyecciones de 2018-2022). Cuando las tiene, la cifra no se descarta ni se deja fuera de las sumas: se
investiga (el texto de la fila, las fichas de los mismos días en el área, la población de cada nivel) y se corrige por
una de estas rutas, que quedan en ``Conciliacion``:

- ``cifra-de-area``: la cifra es la de un área mayor (la provincia o el departamento) puesta en un distrito
  («80 000 pobladores aislados» en uno de 1 578 habitantes). Se queda en la fila y ``AreaCifras`` dice de qué área es:
  las sumas la cuentan en esa área y en las que la contienen, no en las menores (``counts_at``);
- ``homonimo``: la fuente nombró un departamento o una provincia y se ubicó en el distrito del mismo nombre
  («Ola de frío en Junín»): la fila pasa a esa área;
- ``duplicado``: la cifra repite la de otra fila que la consolida (el total de Puno de la sequía de 1983 en
  Pilcuyo): se quita de esta fila y se cuenta una vez, en la otra;
- ``consolidado``: la fila es el total de un área cuyas partes tienen sus propias filas: cuenta solo el resto;
- ``transcripcion``: la cifra se corrige con la propia fila (80 000 afectados por 1 600 viviendas a 5 personas por
  vivienda son 8 000);
- ``tope-poblacion``: una ficha de un distrito (el SINPAD registra cada emergencia en uno) con más personas que
  habitantes: se cuenta toda la población del distrito, que es lo más que pudo afectar.

Las rutas se investigan fila por fila y están en ``data/historico/conciliaciones.yaml`` con su motivo y su evidencia
(``apply``; los topes investigados, en ``cap``). Tres reglas se aplican solas a lo que queda, en este orden:

- ``duplicates``: dos fichas de la misma fuente, día, distrito y peligro con las mismas cifras en todas las columnas
  de impacto, cuando eso no puede ser casualidad (la misma nota de prensa, o cifras que no se repiten por azar: tres
  columnas o más, 20 personas, 10 viviendas o 50 hectáreas). El SINPAD registró algunas emergencias dos veces con
  la misma evaluación (Colán, 20 de febrero de 2017: 2 147 afectados en las fichas 82062 y 83459) y DesInventar
  repite el total de una nota en cada lugar que nombra. Se cuenta la primera (``duplicado``, ``ImpactoEnTotales =
  no`` en las demás, que conservan sus cifras);
- ``cap``: el tope en la población de las fichas que siguen pasándola;
- ``overlaps``: fichas del mismo día, peligro y distrito que juntas pasan su población se solapan (dos evaluaciones
  de la misma emergencia): cuenta la mayor (``duplicado``).

Las cifras que cambian guardan su valor de la fuente en ``CifrasFuente`` («Afectados=11705»), la descripción lleva
una nota y ``log`` las reúne en ``conciliaciones.csv``. Todo se deshace y se vuelve a hacer en cada construcción
(``restore``), también con ``--desde-catalogo``. ``inconsistent`` comprueba al final que ninguna fila ni ningún día
de un área pase su población.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import yaml

from .esquema import IMPACT_COLUMNS, IMPACT_LABELS

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "data" / "historico" / "conciliaciones.yaml"

PEOPLE = ("Afectados", "Damnificados", "Evacuados", "Reubicados", "Desplazados")
HOUSES = ("ViviendasDestruidas", "ViviendasAfectadas")
#: Las columnas que sigue ``AreaCifras``: personas, viviendas y los demás daños. Los fallecidos, desaparecidos y
#: heridos se cuentan siempre en el área de la fila.
CASUALTIES = ("Fallecidos", "Desaparecidos", "Heridos")
AREA_COLUMNS = tuple(c for c in IMPACT_COLUMNS if c not in CASUALTIES)
ROUTES = {
    "cifra-de-area": "cifra de un área mayor",
    "homonimo": "área homónima",
    "duplicado": "duplicado de otra fila",
    "consolidado": "total consolidado",
    "transcripcion": "error de transcripción",
    "tope-poblacion": "tope en la población",
}
NOTE = "Conciliación del observatorio"
_NOTE = re.compile(r"\s*\[" + NOTE + r"[^\]]*\]")
LOG_COLUMNS = ["Id", "Date", "Ubigeo", "Departamento", "Provincia", "Distrito", "Conciliacion", "Ruta", "CifrasFuente",
               "CifrasConciliadas", "AreaCifras", "AreaCifrasNombre", "Poblacion", "PoblacionFuente", "Razon", "Motivo",
               "Evidencia", "Nota"]


def _n(v) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _int(v: float):
    return int(v) if v == int(v) else round(v, 2)


def _fmt(v) -> str:
    v = _n(v)
    return f"{_int(v):,}".replace(",", " ")


def people(r: dict) -> float:
    """Personas de una fila: afectadas más damnificadas (el INDECI las cuenta por separado), o las evacuadas,
    reubicadas o desplazadas (parte de las anteriores), lo que sea mayor."""
    return max(_n(r.get("Afectados")) + _n(r.get("Damnificados")), _n(r.get("Evacuados")), _n(r.get("Reubicados")),
               _n(r.get("Desplazados")))


def houses(r: dict) -> float:
    return _n(r.get("ViviendasDestruidas")) + _n(r.get("ViviendasAfectadas"))


def area_of(r: dict) -> str:
    """El área de las cifras de personas y viviendas de la fila."""
    return r.get("AreaCifras") or r["Ubigeo"]


def counts_at(r: dict, level: Optional[int]) -> bool:
    """Si las cifras de personas y viviendas de la fila cuentan en un área de ``level`` dígitos de UBIGEO (2, 4 o 6;
    None para la macrorregión y el país, que contienen cualquier área)."""
    ap = r.get("AreaCifras") or ""
    return not ap or level is None or level <= len(ap)


def year_of(r: dict) -> int:
    return int(r["Date"][:4])


def population_source(year: int) -> str:
    """De dónde sale la población de ``Territory.population_at`` para un año."""
    if year < 1990:
        return "INEI, estimación de 1990 (Boletín Especial N° 16; no hay cifras por distrito anteriores)"
    if year <= 2005:
        return f"INEI, estimación de {year} (Boletín Especial N° 16)"
    if year < 2017:
        return "INEI, la mayor de la estimación de 2005 (Boletín Especial N° 16) y el censo de 2017"
    if year == 2017:
        return "INEI, la mayor del censo de 2017 y la proyección de 2018 (Boletín Especial N° 27)"
    if year <= 2022:
        return f"INEI, proyección de {year} (Boletín Especial N° 27)"
    return "INEI, proyección de 2022 (Boletín Especial N° 27, la última)"


def _place(territory, code: str) -> str:
    return ", ".join(x for x in territory.names(code)[::-1] if x) or "Perú"


def _source_values(r: dict) -> dict[str, str]:
    return dict(p.split("=", 1) for p in (r.get("CifrasFuente") or "").split("; ") if "=" in p)


def _remember(r: dict, cols) -> None:
    """Guarda en ``CifrasFuente`` el valor de la fuente de las columnas que se van a cambiar (la primera vez)."""
    old = _source_values(r)
    for c in cols:
        old.setdefault(c, str(r.get(c) if r.get(c) is not None else ""))
    r["CifrasFuente"] = "; ".join(f"{k}={v}" for k, v in old.items())


def without_note(text: str) -> str:
    """El texto de la fuente sin la nota de la conciliación (que nombra otras áreas: no sirve para ubicar la fila)."""
    return _NOTE.sub("", text or "").strip()


def _note(r: dict, text: str, append: bool = False) -> None:
    """La nota de la conciliación al final de la descripción (``append``: después de la que ya tiene)."""
    text = " ".join(text.translate(str.maketrans("[]", "()")).split())  # un corchete cerraría la nota
    old = _NOTE.search(r.get("Descripción") or "")
    if append and old:
        text = f"{old.group(0).strip()[len(NOTE) + 3:-1]} {text}"
    r["Descripción"] = f"{without_note(r.get('Descripción'))} [{NOTE}: {text}]".strip()


def _mark(r: dict, route: str, text: str) -> None:
    """Pone la ruta después de las que ya tiene la fila (un consolidado cuyas pérdidas son además un error de
    transcripción; una ficha llevada a la población que además se solapa con otra) y su nota después de las suyas."""
    again = bool(r.get("Conciliacion"))
    r["Conciliacion"] = "; ".join(dict.fromkeys(filter(None, [*(r.get("Conciliacion") or "").split("; "), route])))
    _note(r, f"{ROUTES[route]}: {text}", append=again)


def _set_area(r: dict, territory, code: str) -> None:
    r["Ubigeo"] = code
    r["Departamento"], r["Provincia"], r["Distrito"] = territory.names(code)
    r["NivelUbigeo"] = {2: "departamento", 4: "provincia", 6: "distrito"}[len(code)]
    r["Region"], r["AltitudCapital"] = territory.region(code), territory.altitude(code) or ""


def restore(records: list[dict], territory) -> int:
    """Deshace las conciliaciones de una corrida anterior (las cifras y el UBIGEO de la fuente, sin la nota) para
    aplicarlas de nuevo con los datos y las reglas vigentes. Devuelve cuántas filas deshizo."""
    n = 0
    for r in records:
        if not (r.get("Conciliacion") or r.get("CifrasFuente") or r.get("AreaCifras")):
            continue
        for k, v in _source_values(r).items():
            if k == "Ubigeo":
                _set_area(r, territory, v)
            else:
                r[k] = v
        r["Descripción"] = without_note(r.get("Descripción"))
        r["Conciliacion"] = r["AreaCifras"] = r["CifrasFuente"] = ""
        n += 1
    return n


def load(path: Path = PATH) -> list[dict]:
    entries = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("conciliaciones", []) if path.exists() else []
    for e in entries:
        if e.get("ruta") not in ROUTES:
            raise SystemExit(f"conciliaciones.yaml: {e.get('id')}: ruta desconocida «{e.get('ruta')}»")
    return entries


def _context(territory, code: str, year: int) -> str:
    pop = territory.population_at(code, year)
    return f"población de {_place(territory, code)} en {year}: {_fmt(pop)}" if pop else ""


def apply(records: list[dict], territory, path: Path = PATH, strict: bool = True) -> Counter:
    """Aplica las conciliaciones investigadas de ``conciliaciones.yaml`` menos los topes, que van en ``cap`` (después de
    unir las filas del IDMC, que pueden traer las personas desplazadas). ``strict``: cada una debe coincidir con una
    fila. Devuelve cuántas filas tocó cada ruta."""
    entries = load(path)
    by_id = {r["Id"]: r for r in records}
    stats: Counter = Counter()
    missing = [e["id"] for e in entries if e["id"] not in by_id]
    if strict and missing:
        raise SystemExit(f"conciliaciones.yaml: {len(missing)} conciliaciones sin fila: {', '.join(missing[:10])}")
    # Los consolidados al final: restan las cifras de sus partes ya conciliadas.
    for e in sorted((e for e in entries if e["id"] in by_id and e["ruta"] != "tope-poblacion"),
                    key=lambda e: e["ruta"] == "consolidado"):
        r = by_id[e["id"]]
        route, why = e["ruta"], " ".join(str(e.get("motivo", "")).split())
        year = year_of(r)
        here = r["Ubigeo"]
        if route == "cifra-de-area":
            code = _area_of_entry(e, here)
            if not code:
                raise SystemExit(f"conciliaciones.yaml: {e['id']}: cifra-de-area sin área")
            r["AreaCifras"] = code
            cols = [c for c in AREA_COLUMNS if r.get(c) not in (None, "")]
            text = (f"las cifras de {', '.join(IMPACT_LABELS[c] for c in cols)} son de {_place(territory, code)}, no de "
                    f"{_place(territory, here)}: se suman en esa área y no en las menores. {why} "
                    f"({_context(territory, here, year)}; {_context(territory, code, year)}).")
        elif route == "homonimo":
            code = str(e["ubigeo"])
            _remember(r, ["Ubigeo"])
            _set_area(r, territory, code)
            # El punto del distrito no es el del evento: va la capital del área (la que pone ``relocate``).
            r["Latitud"], r["Longitud"], r["PrecisionGeo"] = territory.point(code)
            r["PuntoFuente"] = ""
            if r.get("Confianza") == "alta":
                r["Confianza"] = "media"
            text = f"la fila pasa de {_place(territory, here)} ({here}) a {_place(territory, code)} ({code}). {why}"
        elif route in ("duplicado", "consolidado", "transcripcion"):
            # Un consolidado o una cifra corregida pueden ser también de un área mayor (``area``).
            code = _area_of_entry(e, here)
            if code:
                r["AreaCifras"] = code
            if route == "transcripcion":
                new = {k: v for k, v in (e.get("cifras") or {}).items()}
            elif route == "duplicado":
                cols = e.get("columnas") or [c for c in PEOPLE if r.get(c) not in (None, "")]
                new = {c: "" for c in cols}
            else:
                parts = [by_id[i] for i in e.get("partes") or [] if i in by_id]
                if strict and len(parts) != len(e.get("partes") or []):
                    raise SystemExit(f"conciliaciones.yaml: {e['id']}: falta una de sus partes")
                cols = e.get("columnas") or [c for c in AREA_COLUMNS
                                             if r.get(c) not in (None, "") and any(_n(p.get(c)) for p in parts)]
                new = {c: _int(max(_n(r.get(c)) - sum(_n(p.get(c)) for p in parts), 0)) for c in cols}
            unknown = set(new) - set(IMPACT_COLUMNS)
            if unknown:
                raise SystemExit(f"conciliaciones.yaml: {e['id']}: columnas que no son de daños: {sorted(unknown)}")
            _remember(r, new)
            src = _source_values(r)
            for c, v in new.items():
                r[c] = v
            change = ", ".join(f"{c} {_fmt(src[c])} → {_fmt(v) if v != '' else 'vacío'}" for c, v in new.items())
            ref = f" (fila {e['de']})" if route == "duplicado" else \
                f" (partes: {', '.join(e.get('partes') or [])})" if route == "consolidado" else ""
            text = f"{change}{ref}. {why}"
            if code:
                text += f" Las cifras son de {_place(territory, code)}: se suman en esa área y no en las menores."
        _mark(r, route, text)
        stats[route] += 1
    return stats


def _area_of_entry(e: dict, here: str) -> str:
    """El ``area`` de una conciliación (un departamento o una provincia que contiene la fila), o vacío."""
    if e.get("area") in (None, ""):
        return ""
    code = str(e["area"])
    if not here.startswith(code) or len(code) >= len(here) or len(code) not in (2, 4):
        raise SystemExit(f"conciliaciones.yaml: {e['id']}: el área {code} no contiene {here}")
    return code


def _cap(r: dict, territory) -> str:
    """Lleva las personas de la fila a la población de su área en el año del evento; devuelve el texto de la nota
    (vacío si no pasaban de ella)."""
    year = year_of(r)
    code = area_of(r)
    pop = territory.population_at(code, year)
    if not pop or people(r) <= pop:
        return ""
    a, d = _n(r.get("Afectados")), _n(r.get("Damnificados"))
    new = {}
    if a + d > pop:
        if d >= pop:
            new["Damnificados"] = pop
            if r.get("Afectados") not in (None, ""):
                new["Afectados"] = 0
        else:
            new["Afectados"] = pop - d
    for c in ("Evacuados", "Reubicados", "Desplazados"):
        if _n(r.get(c)) > pop:
            new[c] = pop
    _remember(r, new)
    src = _source_values(r)
    for c, v in new.items():
        r[c] = _int(v)
    change = ", ".join(f"{c} {_fmt(src[c])} → {_fmt(v)}" for c, v in new.items())
    return (f"{change}: no puede haber más personas que habitantes, así que se cuenta toda la población de "
            f"{_place(territory, code)} en {year}, {_fmt(pop)} ({population_source(year)}).")


def cap(records: list[dict], territory, path: Path = PATH, strict: bool = True, auto: bool = True) -> int:
    """``tope-poblacion``: con ``auto=False``, las investigadas de ``conciliaciones.yaml``, con su motivo; si no, sola,
    cada fila sin otra conciliación que suma a los totales y tiene más personas que habitantes en su área (después de
    las investigadas). Devuelve cuántas tocó."""
    by_id = {r["Id"]: r for r in records}
    n = 0
    for e in [] if auto else load(path):
        if e["ruta"] != "tope-poblacion":
            continue
        if e["id"] not in by_id:
            if strict:
                raise SystemExit(f"conciliaciones.yaml: {e['id']}: no hay fila")
            continue
        r = by_id[e["id"]]
        text = _cap(r, territory)
        if not text:
            if strict:
                raise SystemExit(f"conciliaciones.yaml: {e['id']}: no pasa la población de su área")
            continue
        _mark(r, "tope-poblacion", f"{text} {' '.join(str(e.get('motivo', '')).split())}")
        n += 1
    for r in records if auto else []:
        if r.get("ImpactoEnTotales") == "no" or r.get("Conciliacion"):
            continue
        text = _cap(r, territory)
        if text:
            _mark(r, "tope-poblacion", text)
            n += 1
    return n


def _signature(r: dict) -> tuple:
    return tuple(_n(r.get(c)) for c in IMPACT_COLUMNS)


def _not_by_chance(r: dict, first: dict) -> bool:
    """Si las mismas cifras de dos fichas del mismo día, distrito y peligro no pueden ser casualidad (``duplicates``):
    la misma nota de prensa (DesInventar repite el total en cada lugar), o cifras que no se repiten por azar. Dos
    fichas del SINPAD con una vivienda y cuatro personas son dos familias."""
    if r["Origen"] not in ("sinpad", "idmc") and r.get("FuenteCita") and r.get("FuenteCita") == first.get("FuenteCita"):
        return True
    return (sum(1 for v in _signature(r) if v) >= 3 or people(r) >= 20 or houses(r) >= 10
            or _n(r.get("HectareasCultivo")) >= 50)


def _registered(r: dict) -> tuple:
    """El orden en que la fuente registró la ficha: el número de su Id (el código del SINPAD, el orden de
    DesInventar, que pone primero la ficha general de una nota y después una por lugar)."""
    m = re.fullmatch(r"[a-z-]+-(\d+)", r["Id"])
    return int(m.group(1)) if m else 0, r["Id"]


def _count_once(r: dict, kept: dict, text: str) -> None:
    """La ficha no suma a los totales (``ImpactoEnTotales = no``, como un resumen curado): sus cifras se cuentan en
    ``kept``. Conserva sus cifras de la fuente."""
    _remember(r, ["ImpactoEnTotales"])
    r["ImpactoEnTotales"] = "no"
    _mark(r, "duplicado", f"{text} Se cuentan una vez, en {kept['Id']}; esta fila conserva sus cifras pero no "
                          "suma a los totales.")


def duplicates(records: list[dict]) -> int:
    """``duplicado`` automático: las fichas con las mismas cifras que otra de la misma fuente, día, distrito y peligro
    (``_not_by_chance``) no suman: se cuenta la primera que registró la fuente. Devuelve cuántas tocó."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("ImpactoEnTotales") == "no" or r.get("Conciliacion"):
            continue
        sig = _signature(r)
        if any(sig):
            groups[(r["Origen"], r["Date"], r["Ubigeo"], r.get("DangerType"), sig)].append(r)
    n = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue
        first, *rest = sorted(rows, key=_registered)
        for r in rest:
            if _not_by_chance(r, first):
                same = "de la misma nota" if r.get("FuenteCita") == first.get("FuenteCita") else "de la misma fuente"
                _count_once(r, first, f"las mismas cifras que la fila {first['Id']}, {same}, del mismo día, distrito "
                                      f"y peligro ({r.get('DangerType')}).")
                n += 1
    return n


def surfaces(records: list[dict], territory) -> int:
    """``cifra-de-area`` automática: una fila con más hectáreas que la superficie de su área no puede ser de ella (las
    de un valle o de una provincia puestas en un distrito: «valles de Lambayeque» en Monsefú). Se cuenta en la menor
    área que la contiene y puede tenerlas. Las que tienen otra conciliación se quedan para ``inconsistent``. Devuelve
    cuántas tocó."""
    n = 0
    for r in records:
        if r.get("ImpactoEnTotales") == "no" or r.get("Conciliacion") not in (None, "", "cifra-de-area"):
            continue
        ha, code = _n(r.get("HectareasCultivo")), area_of(r)
        km2 = territory.surface(code)
        if not ha or not km2 or ha <= km2 * 100:
            continue
        up = next((code[:k] for k in (4, 2) if k < len(code) and (territory.surface(code[:k]) or 0) * 100 >= ha), "")
        if not up:
            continue
        r["AreaCifras"] = up
        cols = [c for c in AREA_COLUMNS if r.get(c) not in (None, "")]
        _mark(r, "cifra-de-area", f"{_fmt(ha)} hectáreas no caben en {_place(territory, code)} "
              f"({_fmt(round(km2 * 100))} ha de superficie): son de un área mayor (un valle, la provincia), así que "
              f"las cifras de {', '.join(IMPACT_LABELS[c] for c in cols)} se suman en {_place(territory, up)} "
              f"({_fmt(round(territory.surface(up) * 100))} ha), la menor que la contiene y puede tenerlas, y no "
              "en las menores.")
        n += 1
    return n


def _day_groups(records: list[dict]) -> dict[tuple, list[dict]]:
    """Las fichas que suman personas, por día, peligro y cada área en la que cuentan (``counts_at``)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("ImpactoEnTotales") == "no" or not people(r):
            continue
        code = area_of(r)
        for level in (2, 4, 6):
            if len(code) >= level:
                groups[(r["Date"], r.get("DangerType"), code[:level])].append(r)
    return groups


def overlaps(records: list[dict], territory) -> int:
    """Fichas del mismo día, peligro y distrito que juntas tienen más personas que habitantes: se solapan (dos
    evaluaciones de la misma emergencia), así que cuenta la mayor (``duplicado``). En una provincia o un departamento
    no se decide solo: lo dice ``inconsistent``. Devuelve cuántas tocó."""
    n = 0
    for (day, kind, code), rows in _day_groups(records).items():
        if len(code) != 6 or len(rows) < 2:
            continue
        pop = territory.population_at(code, int(day[:4]))
        total = sum(people(r) for r in rows)
        if not pop or total <= pop:
            continue
        first, *rest = sorted(rows, key=lambda r: (-people(r), _registered(r)))
        for r in rest:
            _count_once(r, first, f"con la fila {first['Id']}, del mismo día y peligro ({kind}), "
                                  f"suma {_fmt(total)} personas en {_place(territory, code)}, que tenía {_fmt(pop)} "
                                  f"habitantes ({population_source(int(day[:4]))}): se solapan, y la mayor las "
                                  "incluye.")
            n += 1
    return n


def peak_population(territory, code: str, year: int) -> Optional[int]:
    """La mayor población del área entre 1990 (o el año del evento, si es anterior) y el año del evento: las viviendas
    se quedan cuando la gente se va (Santiago de Quirahuara tenía 822 habitantes en 2005 y 311 en 2022, y el SINPAD
    contó 314 viviendas en 2025), así que se comparan con ella y no con la del año."""
    vals = [territory.population_at(code, y) for y in range(min(year, 1990), max(year, 1990) + 1)]
    return max((v for v in vals if v), default=None)


def inconsistent(records: list[dict], territory) -> list[str]:
    """Lo que sigue sin conciliar (debe ser nada después de ``apply``, ``duplicates``, ``surfaces``, ``cap`` y
    ``overlaps``): las filas que suman a los totales con más personas que habitantes en el área de sus cifras, con más
    viviendas que la mayor población que tuvo o con más hectáreas que su superficie, y los días en que las fichas de un
    peligro en un área pasan su población."""
    out = []
    for r in records:
        if r.get("ImpactoEnTotales") == "no":
            continue
        code, year = area_of(r), year_of(r)
        pop = territory.population_at(code, year)
        ha = _n(r.get("HectareasCultivo"))
        if pop and (people(r) > pop or houses(r) > pop and houses(r) > peak_population(territory, code, year)) or \
                ha and ha > (territory.surface(code) or ha) * 100:
            out.append(r["Id"])
    for (day, kind, code), rows in _day_groups(records).items():
        if len(rows) > 1:
            pop = territory.population_at(code, int(day[:4]))
            if pop and sum(people(r) for r in rows) > pop:
                out.append(f"{day} {kind} {code} ({', '.join(r['Id'] for r in rows[:5])})")
    return out


def log(records: list[dict], territory, path: Path = PATH) -> list[list]:
    """Las filas de ``conciliaciones.csv``: cada fila conciliada con su ruta, sus cifras de la fuente y las
    conciliadas, la población de su área en el año del evento, la razón entre ambas, el motivo y la evidencia de la
    investigación (o el motivo de la regla automática) y la nota que lleva la descripción."""
    entries: dict[str, list[dict]] = defaultdict(list)
    for e in load(path):
        entries[e["id"]].append(e)
    out = []
    for r in records:
        if not r.get("Conciliacion"):
            continue
        routes = r["Conciliacion"].split("; ")
        # En el orden en que se aplicaron, como la ruta y la nota.
        mine = sorted(entries.get(r["Id"], []), key=lambda x: routes.index(x["ruta"]) if x["ruta"] in routes else 99)
        e = {k: [str(x.get(k)) for x in mine if x.get(k)] for k in ("motivo", "evidencia")}
        # Las rutas sin entrada investigada (una ficha conciliada a mano que además tocó una regla) dicen su regla.
        e["motivo"] += [AUTOMATIC[x] for x in routes if x not in {m["ruta"] for m in mine} and x in AUTOMATIC]
        src = _source_values(r)
        year = year_of(r)
        here = src.get("Ubigeo") or r["Ubigeo"]
        pop = territory.population_at(here, year)
        before = {c: _n(src.get(c, r.get(c))) for c in PEOPLE}
        p = max(before["Afectados"] + before["Damnificados"], before["Evacuados"], before["Reubicados"],
                before["Desplazados"])
        conciled = "; ".join(f"{c}={r.get(c) if r.get(c) not in (None, '') else ''}" for c in src if c != "Ubigeo")
        if "Ubigeo" in src:
            conciled = "; ".join(x for x in (f"Ubigeo={r['Ubigeo']}", conciled) if x)
        note = _NOTE.search(r.get("Descripción") or "")
        out.append([r["Id"], r["Date"], here, *territory.names(here), r["Conciliacion"],
                    "; ".join(ROUTES[x] for x in routes),
                    r.get("CifrasFuente") or "", conciled, r.get("AreaCifras") or "",
                    _place(territory, r["AreaCifras"]) if r.get("AreaCifras") else "", pop or "",
                    population_source(year), round(p / pop, 2) if pop else "",
                    " | ".join(" ".join(x.split()) for x in e["motivo"]),
                    " | ".join(" ".join(x.split()) for x in e["evidencia"]),
                    note.group(0).strip()[len(NOTE) + 3:-1] if note else ""])
    return out


#: El motivo en ``conciliaciones.csv`` de las conciliaciones automáticas.
AUTOMATIC = {
    "cifra-de-area": "Automática: más hectáreas que la superficie del área; se cuentan en la menor área que la contiene "
                     "y puede tenerlas",
    "tope-poblacion": "Automática: ficha con más personas que habitantes en su área; se cuenta toda su población",
    "duplicado": "Automática: las mismas cifras que otra ficha del mismo día, distrito y peligro, o una ficha que con "
                 "otra del mismo día y peligro pasa la población del distrito; se cuenta una vez",
}
