"""Перевод исключений пайплайна в понятные пользователю причины (чешский).

Классифицируем по имени типа и тексту, а не по isinstance, чтобы модуль
не зависел от openai/pypdfium2 и легко тестировался. Полный traceback
всегда остаётся в логе — здесь только сообщение для UI.
"""


def classify_pipeline_error(exc: Exception) -> str:
    """Возвращает человекочитаемую причину ошибки для показа в UI."""
    name = type(exc).__name__
    text = str(exc).lower()

    if name == "AuthenticationError":
        return "Neplatný OpenAI API klíč — zkontrolujte ho v Nastavení."

    if name == "RateLimitError":
        if "insufficient_quota" in text:
            return "Na OpenAI klíči došel kredit — dobijte na platform.openai.com."
        return "Překročen limit požadavků OpenAI — zkuste to za chvíli znovu."

    if name in ("APIConnectionError", "APITimeoutError"):
        return "Nepodařilo se připojit k OpenAI — zkontrolujte internet."

    # Свежая установка: ключ ещё не введён, клиент OpenAI падает при создании.
    if name == "OpenAIError" and "api_key" in text:
        return "Chybí OpenAI API klíč — nastavte ho v Nastavení."

    if name == "VisionEmptyResponseError":
        return "Vision nevrátil popis stránky — zkuste dokument indexovat znovu."

    if name == "PdfiumError":
        if "password" in text:
            return "PDF je chráněno heslem — odemkněte ho a naskenujte znovu."
        return "Soubor se nepodařilo otevřít jako PDF."

    if name == "ConversionError":
        return "Soubor se nepodařilo přečíst jako PDF — je poškozený nebo to není PDF."

    if name == "PermissionError":
        return (
            "Do složky knihovny nelze zapisovat — index (.search_index) "
            "nelze uložit. Povolte zápis do složky."
        )

    return f"Neočekávaná chyba ({name}): {exc}"
