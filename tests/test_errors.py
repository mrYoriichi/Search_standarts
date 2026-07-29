"""Тесты классификатора ошибок пайплайна."""

from backend.core.errors import classify_pipeline_error


class AuthenticationError(Exception):
    pass


class RateLimitError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class PdfiumError(Exception):
    pass


def test_invalid_api_key():
    msg = classify_pipeline_error(AuthenticationError("Error code: 401"))
    assert "klíč" in msg


def test_out_of_credit():
    exc = RateLimitError("Error code: 429 - insufficient_quota")
    assert "kredit" in classify_pipeline_error(exc)


def test_rate_limit_without_quota_is_not_credit():
    exc = RateLimitError("Error code: 429 - requests per minute")
    msg = classify_pipeline_error(exc)
    assert "kredit" not in msg
    assert "limit" in msg.lower()


def test_no_connection():
    assert "internet" in classify_pipeline_error(APIConnectionError("boom"))


def test_password_protected_pdf():
    exc = PdfiumError("Failed to load document (PDFium: Incorrect password error).")
    assert "heslem" in classify_pipeline_error(exc)


class ConversionError(Exception):
    pass


def test_docling_invalid_pdf():
    exc = ConversionError("Input document test_broken.pdf is not valid.")
    assert "poškozený" in classify_pipeline_error(exc)


def test_unknown_error_keeps_details():
    msg = classify_pipeline_error(ValueError("something odd"))
    assert "ValueError" in msg
    assert "something odd" in msg


class OpenAIError(Exception):
    pass


def test_missing_api_key():
    exc = OpenAIError("The api_key client option must be set")
    assert "Chybí OpenAI API klíč" in classify_pipeline_error(exc)


class VisionEmptyResponseError(Exception):
    pass


def test_vision_empty_response():
    exc = VisionEmptyResponseError("stránka 3")
    assert "indexovat znovu" in classify_pipeline_error(exc)


def test_permission_error_neutral_with_path():
    # Классификатор общий для библиотеки, архива и поиска — текст не должен
    # сваливать всё на «папку библиотеки», а путь из исключения должен
    # остаться виден (Windows: PDF залочен Acrobat'ом/антивирусом).
    exc = PermissionError("[Errno 13] Permission denied: 'projects_data/x.json'")
    msg = classify_pipeline_error(exc)
    assert "oprávnění" in msg
    assert "projects_data/x.json" in msg
    assert "Neočekávaná" not in msg
