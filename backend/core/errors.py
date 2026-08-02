"""Перевод исключений пайплайна в понятные пользователю причины.

Классифицируем по имени типа и тексту, а не по isinstance, чтобы модуль
не зависел от openai/pypdfium2 и легко тестировался. Полный traceback
всегда остаётся в логе — здесь только сообщение для UI. Язык сообщения —
текущий язык приложения (backend/core/ui_messages.py).
"""

from backend.core.ui_messages import msg


def classify_pipeline_error(exc: Exception) -> str:
    """Возвращает человекочитаемую причину ошибки для показа в UI."""
    name = type(exc).__name__
    text = str(exc).lower()

    if name == "AuthenticationError":
        return msg("err.bad_api_key")

    if name == "RateLimitError":
        if "insufficient_quota" in text:
            return msg("err.no_credit")
        return msg("err.rate_limit")

    if name in ("APIConnectionError", "APITimeoutError"):
        return msg("err.no_connection")

    # Свежая установка: ключ ещё не введён, клиент OpenAI падает при создании.
    if name == "OpenAIError" and "api_key" in text:
        return msg("err.missing_api_key")

    if name == "VisionEmptyResponseError":
        return msg("err.vision_empty")

    if name == "PdfiumError":
        if "password" in text:
            return msg("err.pdf_password")
        return msg("err.pdf_open")

    if name == "ConversionError":
        return msg("err.pdf_read")

    # Типовой Windows-кейс — файл держит Acrobat/антивирус/OneDrive, поэтому
    # путь из исключения оставляем видимым. Специфичный текст про read-only
    # папку библиотеки даёт сам scan_library.
    if name == "PermissionError":
        return msg("err.locked_or_no_write", exc=exc)

    return msg("err.unexpected", name=name, exc=exc)
