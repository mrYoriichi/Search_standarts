"""Shared lock for all PDFium calls.

PDFium is not thread-safe, and we call it from several threads at once:
3 pipeline workers, the archive scan, strong-search page rendering.
Concurrent calls occasionally crash the whole process without a Python
traceback.

The lock is borrowed from Docling: its converter renders through
pypdfium2 under its own threading.Lock, and our calls must serialize
WITH it, not just among themselves. If Docling ever moves the internal
module we fall back to our own Lock (our threads stay protected;
test_pdfium_lock catches the change).
"""

import threading

__all__ = ["PDFIUM_LOCK"]

try:
    from docling.utils.locks import pypdfium2_lock as PDFIUM_LOCK
except ImportError:
    PDFIUM_LOCK = threading.Lock()
