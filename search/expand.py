"""
Расширение поискового запроса через LLM.

Короткие запросы и ломаный чешский без диакритики бьют по поиску: вектор уходит
в шум, BM25 не находит словоформы. Здесь один дешёвый вызов mini переписывает
запрос пользователя в выразительный чешский поисковый запрос — с диакритикой,
терминами и синонимами. Этим запросом потом ищем (вектор + BM25); оригинальный
вопрос остаётся для генерации ответа.
"""

from openai import OpenAI

EXPAND_MODEL = "gpt-5.4-mini"

SYSTEM_PROMPT = """Jsi pomocník pro vyhledávání v českých stavebních normách
(ČSN, TP, VL, MVL) — mosty, propustky, odvodnění, dokumentace staveb.

Uživatel zadá dotaz, často krátký, zkratkovitý nebo bez diakritiky. Přepiš ho na
jeden výstižný český vyhledávací dotaz:
- doplň českou diakritiku (např. "odlazdeni propustku" → "odláždění propustku"),
- rozviň krátké fráze do srozumitelné věty,
- přidej odborné synonyma a související termíny z oboru, pokud pomohou
  (např. ocelové svodidlo ≈ svodidlo svodnicového typu; odláždění ≈ kamenná
  dlažba, opevnění koryta),
- zachovej PŮVODNÍ záměr dotazu, nic nového si nevymýšlej.

Vrať POUZE přepsaný dotaz jako jednu větu v češtině, bez uvozovek a bez
vysvětlení."""


def expand_query(question: str) -> str:
    """
    Переписывает вопрос пользователя в выразительный чешский поисковый запрос.

    Возвращает одну строку. При любой ошибке/пустом ответе возвращает исходный
    вопрос — расширение не должно ломать поиск.
    """
    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model=EXPAND_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        )
        expanded = (response.choices[0].message.content or "").strip()
        return expanded or question
    except Exception:
        return question
