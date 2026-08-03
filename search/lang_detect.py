"""Corpus language detection — for multilingual query expansion.

A character heuristic instead of an ML library: norms and reports are
printed text where national characters appear in every sentence. That is
enough to tell cs/de/ru apart from "latin without diacritics" (en) —
zero dependencies, deterministic, instant.
"""

# Characters that identify a language unambiguously. Letters shared by
# cs/de (á, é, ó, ú) are deliberately not used.
_CZECH_CHARS = set("ěščřžůťďňĚŠČŘŽŮŤĎŇ")
_GERMAN_CHARS = set("äöüßÄÖÜ")

# How much text to read per document: the first pages settle the language,
# while the tail may contain foreign-language quotes/appendices.
SAMPLE_CHARS = 2000


def detect_language(text: str) -> str:
    """Language of the text: 'cs' | 'de' | 'ru' | 'en' (en = plain latin)."""
    sample = text[:SAMPLE_CHARS]
    # U+0430..U+044F = Cyrillic a..ya, U+0451 = yo (escapes keep the source
    # free of Cyrillic characters).
    if any(
        "\u0430" <= ch.lower() <= "\u044f" or ch.lower() == "\u0451" for ch in sample
    ):
        return "ru"
    if any(ch in _CZECH_CHARS for ch in sample):
        return "cs"
    if any(ch in _GERMAN_CHARS for ch in sample):
        return "de"
    return "en"


def corpus_languages(chunks: list[dict]) -> set[str]:
    """Document languages for a chunk list (usually already filtered).

    Reads ~SAMPLE_CHARS of each document's first chunks — the beginning
    (headings, preamble) is more reliable than the tail. Costs
    milliseconds per question even at the design ceiling (30k chunks).
    """
    samples: dict[str, str] = {}
    for chunk in chunks:
        doc = chunk["document_id"]
        current = samples.get(doc, "")
        if len(current) >= SAMPLE_CHARS:
            continue
        samples[doc] = current + " " + chunk.get("text", "")
    return {detect_language(text) for text in samples.values()}
