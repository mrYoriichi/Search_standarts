"""Идентификатор документа из имени файла.

Отдельный лёгкий модуль: его импортирует бэкенд при каждом старте, поэтому
здесь не должно быть тяжёлых зависимостей (docling/torch живут в parser.py
и грузятся только при индексации).
"""

import re
import unicodedata
from pathlib import Path

# Cyrillic -> Latin, lowercase only (applied after lower()). Keys are \u
# escapes (U+0430..U+044F = a..ya) so the source contains no Cyrillic.
# Yo (U+0451) and short i (U+0439) are not needed — NFD already decomposed
# them into U+0435/U+0438 + combining marks (a name with "yo" slugs with a
# plain "e"; switching to "yo" would change existing slugs).
_CYR_TO_LAT = {
    "\u0430": "a", "\u0431": "b", "\u0432": "v", "\u0433": "g", "\u0434": "d",
    "\u0435": "e", "\u0436": "zh", "\u0437": "z", "\u0438": "i", "\u043a": "k",
    "\u043b": "l", "\u043c": "m", "\u043d": "n", "\u043e": "o", "\u043f": "p",
    "\u0440": "r", "\u0441": "s", "\u0442": "t", "\u0443": "u", "\u0444": "f",
    "\u0445": "kh", "\u0446": "ts", "\u0447": "ch", "\u0448": "sh", "\u0449": "shch",
    "\u044a": "", "\u044b": "y", "\u044c": "", "\u044d": "e", "\u044e": "yu",
    "\u044f": "ya",
}  # fmt: skip
_CYR_TABLE = str.maketrans(_CYR_TO_LAT)


def make_document_id(filename: str) -> str:
    """Turn a file name into an id safe for paths and the DB.

    'ČSN EN 1991-2.pdf' -> 'csn_en_1991_2'; a Cyrillic file name is
    transliterated (e.g. -> 'chertezh_mosta').
    """
    stem = Path(filename).stem
    # Decompose diacritics: Č -> C + combining caron.
    normalized = unicodedata.normalize("NFD", stem)
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    # Transliterate Cyrillic (no-op for latin/Czech — slugs unchanged).
    transliterated = ascii_only.lower().translate(_CYR_TABLE)
    return re.sub(r"[^a-z0-9]+", "_", transliterated).strip("_")
