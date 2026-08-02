"""Translate pipeline exceptions into user-readable causes.

Classification is by type name and message text, not isinstance, so the
module has no openai/pypdfium2 dependency and tests easily. The full
traceback always stays in the log — only the UI message is built here,
in the current app language (backend/core/ui_messages.py).
"""

from backend.core.ui_messages import msg


def classify_pipeline_error(exc: Exception) -> str:
    """Return a human-readable cause for the UI."""
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

    # Fresh install: no key yet, the OpenAI client fails at creation.
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

    # Typical Windows case: the file is held by Acrobat/antivirus/OneDrive,
    # so the path from the exception stays visible. The specific read-only
    # library-folder text comes from scan_library itself.
    if name == "PermissionError":
        return msg("err.locked_or_no_write", exc=exc)

    return msg("err.unexpected", name=name, exc=exc)
