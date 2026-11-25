"""Normalización del texto de las fuentes antes de leer un nivel de aviso.

Las instituciones escriben el mismo nivel de muchas formas: «Nivel 4», «NIVEL 4», «Nivel IV», «nivel: 4»,
«Nivel N° 4», «nivel cuatro»; «alerta amarilla», «ALERTA AMARILLA», «avisos amarillos»; «EXTREMO» y «Extrema»;
«cancelación» y «cancelacion»; un PDF corta «ama-\\nrillo» al final de la línea. Leer cada variante con su propia
expresión regular es lo que dejó avisos «sin nivel» hasta noviembre de 2026 (docs/niveles-de-aviso.md). Aquí se hace
una sola vez, en este orden:

1. ``fold``: NFKC (ancho completo, ligaduras), sin caracteres invisibles (guion blando, espacio de ancho cero),
   guiones y comillas tipográficas a ASCII, palabras partidas por un guion al final de la línea unidas de nuevo,
   sin tildes ni diéresis, minúsculas (``casefold``) y espacios simples.
2. ``stem``: un *light stemmer* del español (Savoy 2002, el de Lucene ``SpanishLightStemFilter``) que solo quita
   la flexión de género y número (-o, -a, -e, -s, -es, -ces → -z). No el Snowball, que también quita derivación
   («moderado» y «moderadamente», «alerta» y «alertar» a la misma raíz): en un vocabulario cerrado eso junta
   palabras que la institución distingue. Diferencia con Lucene, a propósito: aquí se acortan palabras desde 4
   letras (Lucene, desde 5), porque «rojo», «alto» y «bajo» son niveles y deben coincidir con «roja», «alta» y
   «baja». Que el vocabulario de cada escala siga siendo distinguible después de acortar lo prueba
   ``tests/test_textnorm.py``.
3. ``lookup``: la palabra (o frase) acortada contra el vocabulario de la escala; si no está, una lectura
   aproximada solo si hay un único término a distancia de edición 1 (Damerau, transposición incluida) y ambos
   tienen al menos 5 letras («amarrillo», «naraja»). Una lectura aproximada se marca (``how="aproximado"``) y la
   publicación lo registra (``alert-level-approx``): nunca se absorbe en silencio.

Lo que no se hace, a propósito: traducir de otro idioma («ORANGE»), adivinar un número fuera de la escala
(«Nivel 5») ni tomar la palabra más parecida cuando hay dos: esos casos quedan sin leer y abren una incidencia
(``alert-level-unread``), porque son un vocabulario nuevo que alguien tiene que revisar.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Union

_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"), None)
_PUNCT = str.maketrans({**{c: "-" for c in "‐‑‒–—―−"},
                        **{c: "'" for c in "‘’‚‛"}, **{c: '"' for c in "“”„"},
                        "º": "o", "ª": "a"})
# «ama-\nrillo» (corte de línea de un PDF). Solo con salto de línea: «Nivel-4» o «PDF-COEN» no se unen.
_HYPHEN_BREAK_RE = re.compile(r"(\w)-[ \t]*\r?\n[ \t]*(\w)")
_SPACE_RE = re.compile(r"\s+")

#: Distancia de edición máxima y largo mínimo de una lectura aproximada.
FUZZY_MAX, FUZZY_MIN_LEN = 1, 5


def fold(text: str) -> str:
    """El texto para comparar: sin tildes, minúsculas, puntuación tipográfica en ASCII y espacios simples."""
    s = unicodedata.normalize("NFKC", text or "").translate(_INVISIBLE).translate(_PUNCT)
    s = _HYPHEN_BREAK_RE.sub(r"\1\2", s)
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    return _SPACE_RE.sub(" ", s.casefold()).strip()


def stem(word: str) -> str:
    """Raíz de flexión de una palabra ya plegada (``fold``): sin género ni número."""
    n = len(word)
    if n < 4 or not word.isalpha():
        return word
    if word.endswith("eses"):
        return word[:-2]
    if word.endswith("ces"):
        return word[:-3] + "z"
    if word[-1] == "s" and word[-2] in "oae":
        return word[:-2]
    if word[-1] in "oae":
        return word[:-1]
    return word


def stem_phrase(phrase: str) -> str:
    return " ".join(stem(w) for w in fold(phrase).split())


def distance(a: str, b: str) -> int:
    """Distancia de Damerau-Levenshtein (alineación óptima): inserción, borrado, sustitución y transposición."""
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


@dataclass(frozen=True)
class Match:
    key: str  # la clave del vocabulario (la de ``severity.SCALES``)
    how: str  # exacto | flexion | aproximado
    raw: str  # lo que decía la fuente


Vocab = Union[Mapping[str, str], Iterable[str]]


def _index(vocab: Vocab) -> dict[str, str]:
    pairs = vocab.items() if isinstance(vocab, Mapping) else ((v, v) for v in vocab)
    return {stem_phrase(variant): key for variant, key in pairs}


def _fuzzy(st: str, index: dict[str, str]) -> Optional[str]:
    if len(st) < FUZZY_MIN_LEN:
        return None
    near = {key for s, key in index.items() if len(s) >= FUZZY_MIN_LEN and distance(st, s) <= FUZZY_MAX}
    return near.pop() if len(near) == 1 else None  # dos candidatos: ambiguo, no se elige


def lookup(phrase: str, vocab: Vocab, fuzzy: bool = True) -> Optional[Match]:
    """La clave del vocabulario que nombra ``phrase`` (con sus variantes de forma), o ``None``.

    ``vocab``: claves, o variantes → clave (``{"muy alto": "muy alto", "muy alta": "muy alto"}``)."""
    folded = fold(phrase)
    if not folded:
        return None
    index = _index(vocab)
    exact = {fold(v): k for v, k in (vocab.items() if isinstance(vocab, Mapping) else ((v, v) for v in vocab))}
    if folded in exact:
        return Match(exact[folded], "exacto", phrase)
    st = stem_phrase(folded)
    if st in index:
        return Match(index[st], "flexion", phrase)
    key = _fuzzy(st, index) if fuzzy else None
    return Match(key, "aproximado", phrase) if key else None


# ---------------------------------------------------------------------------
# Números de nivel: «Nivel 4», «Nivel IV», «nivel: 4», «Nivel N° 4», «nivel cuatro»
# ---------------------------------------------------------------------------
_NUMBERS = {"1": 1, "2": 2, "3": 3, "4": 4, "i": 1, "ii": 2, "iii": 3, "iv": 4,
            "uno": 1, "dos": 2, "tres": 3, "cuatro": 4}
_NUM_ALT = "|".join(sorted(_NUMBERS, key=len, reverse=True))
#: Sobre texto plegado. El número va solo: «nivel 10», «nivel 5» o «nivel 4.5» no son niveles de la escala 1 a 4.
NIVEL_RE = re.compile(rf"\bnivel\s*(?:n[o°.]*\s*|:\s*|-\s*|#\s*)?({_NUM_ALT})(?![\w.,]\d|\w)")


def level_number(text: str) -> Optional[int]:
    """El nivel (1 a 4) que nombra el texto («Nivel IV» → 4), o ``None``."""
    m = NIVEL_RE.search(fold(text))
    return _NUMBERS[m.group(1)] if m else None
