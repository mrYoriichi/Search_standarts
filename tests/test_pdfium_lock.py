"""The PDFium lock must serialize with Docling's internal lock.

Docling renders via pypdfium2 under its own lock; while our PDFIUM_LOCK
is held, that internal lock must be held too — otherwise our renders
race with Docling's. The test will fail when Docling moves the internal
module and the fallback (our Lock only) kicks in.
"""


def test_with_block_holds_docling_lock():
    import docling.utils.locks as docling_locks

    from pdf_processing.pdfium_lock import PDFIUM_LOCK

    with PDFIUM_LOCK:
        assert docling_locks.pypdfium2_lock.locked()
    assert not docling_locks.pypdfium2_lock.locked()
