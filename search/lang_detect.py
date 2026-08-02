"""Определение языка документов корпуса — для многоязычного расширения.

Эвристика по символам вместо ML-библиотеки: нормы и отчёты — печатный
текст, где национальные символы встречаются в каждом предложении. Этого
хватает, чтобы отличить cs/de/ru от «латиницы без диакритики» (en);
зависимостей ноль, работает детерминированно и мгновенно.
"""

# Символы, однозначно выдающие язык. Общие для cs/de буквы (á, é, ó, ú)
# намеренно не используются.
_CZECH_CHARS = set("ěščřžůťďňĚŠČŘŽŮŤĎŇ")
_GERMAN_CHARS = set("äöüßÄÖÜ")

# Сколько символов текста читаем на документ: языку хватает первых страниц,
# а хвост может содержать иноязычные цитаты/приложения.
SAMPLE_CHARS = 2000


def detect_language(text: str) -> str:
    """Язык текста: 'cs' | 'de' | 'ru' | 'en' (en — латиница без примет)."""
    sample = text[:SAMPLE_CHARS]
    if any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in sample):
        return "ru"
    if any(ch in _CZECH_CHARS for ch in sample):
        return "cs"
    if any(ch in _GERMAN_CHARS for ch in sample):
        return "de"
    return "en"


def corpus_languages(chunks: list[dict]) -> set[str]:
    """Языки документов по списку чанков (обычно уже отфильтрованному).

    На документ читается ~SAMPLE_CHARS первых чанков — begin документа
    (заголовки, преамбула) надёжнее хвоста. Стоимость на вопрос — миллисекунды
    даже на потолке дизайна (30к чанков).
    """
    samples: dict[str, str] = {}
    for chunk in chunks:
        doc = chunk["document_id"]
        current = samples.get(doc, "")
        if len(current) >= SAMPLE_CHARS:
            continue
        samples[doc] = current + " " + chunk.get("text", "")
    return {detect_language(text) for text in samples.values()}
