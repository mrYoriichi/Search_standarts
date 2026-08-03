"""The PDFium lock must be shared with Docling.

Docling renders via pypdfium2 under its own lock; if our lock is a
different object, our renders keep racing with its renders. The test will
fail when Docling moves the internal module and the fallback kicks in.
"""


def test_lock_is_docling_lock():
    from docling.utils.locks import pypdfium2_lock

    from pdf_processing.pdfium_lock import PDFIUM_LOCK

    assert PDFIUM_LOCK is pypdfium2_lock
