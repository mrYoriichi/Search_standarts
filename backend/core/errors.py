"""Translate pipeline exceptions into user-readable causes.

Classification is by type name and message text, not isinstance, so the
module has no openai/pypdfium2 dependency and tests easily. The full
traceback always stays in the log — only the UI message is built here,
in the current app language (backend/core/ui_messages.py).
"""

from backend.core.ui_messages import msg


def classify_pipeline_error(exc: Exception) -> str:
    """Return a human-readable cause for the UI."""
    # Parse now runs in a worker process; the spawner already built the
    # final UI text from the worker's raw (type, text) report.
    if type(exc).__name__ == "ParseFailedError":
        return str(exc)
    return classify_by_name(type(exc).__name__, str(exc))


def classify_by_name(name: str, raw_text: str) -> str:
    """Classify by exception type name and message text.

    Split from classify_pipeline_error so the parse worker can report an
    error as raw strings across the process boundary — the parent builds
    the UI text here, in its own current language.
    """
    text = raw_text.lower()

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
        return msg("err.locked_or_no_write", exc=raw_text)

    return msg("err.unexpected", name=name, exc=raw_text)
