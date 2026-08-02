"""
Расширение поискового запроса через LLM.

Короткие запросы и ломаный чешский без диакритики бьют по поиску: вектор
уходит в шум, BM25 не находит словоформы. Один дешёвый вызов mini
переписывает вопрос в выразительный поисковый запрос: диакритика, термины,
синонимы.

Многоязычный корпус (2026-08-02): BM25 находит документ только словами его
языка, поэтому запрос содержит термины НА ВСЕХ языках корпуса (языки
определяет search/lang_detect по текстам документов). Оригинальный вопрос
остаётся для генерации ответа.
"""

from openai import OpenAI

EXPAND_MODEL = "gpt-5.4-mini"

# Код языка → имя в промпте. Неизвестные коды пропускаются.
LANGUAGE_NAMES = {"cs": "Czech", "en": "English", "de": "German", "ru": "Russian"}

# Промпт по-английски (нейтрализует языковой bias); {languages} подставляет
# build_expand_prompt.
PROMPT_TEMPLATE = """You are a search-query rewriter for a library of construction-engineering documents: norms (ČSN, TP, VL, MVL, Eurocode) and bridge project documentation (technical reports, structural calculations, drawings).

The library contains documents in: {languages}.

The user's question may be short, abbreviated or missing diacritics. Rewrite it into ONE search line that:
- restores proper diacritics and expands shorthand,
- contains the key technical terms of the question in EACH library language listed above (translate the terms; keep standard codes like "ČSN 73 6201" as-is),
- adds professional synonyms and closely related terms where they help,
- preserves the ORIGINAL intent of the question; do not invent new topics.

Return ONLY the search line, without quotes and without explanations."""


def build_expand_prompt(languages: set[str] | None) -> str:
    """Системный промпт расширения под языки корпуса.

    None/пусто или сплошь неизвестные коды → чешский (историческое
    поведение: пилотный корпус чешский).
    """
    codes = sorted(languages or set())
    names = [LANGUAGE_NAMES[c] for c in codes if c in LANGUAGE_NAMES]
    if not names:
        names = [LANGUAGE_NAMES["cs"]]
    return PROMPT_TEMPLATE.format(languages=", ".join(names))


def expand_query(question: str, languages: set[str] | None = None) -> str:
    """
    Переписывает вопрос пользователя в поисковый запрос с терминами на всех
    языках корпуса (languages; None → чешский).

    Возвращает одну строку. При любой ошибке/пустом ответе возвращает исходный
    вопрос — расширение не должно ломать поиск.
    """
    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model=EXPAND_MODEL,
            messages=[
                {"role": "system", "content": build_expand_prompt(languages)},
                {"role": "user", "content": question},
            ],
        )
        expanded = (response.choices[0].message.content or "").strip()
        return expanded or question
    except Exception:
        return question
