"""Shared lock for all PDFium calls.

PDFium is not thread-safe, and we call it from several threads at once:
3 pipeline workers, the archive scan, strong-search page rendering.
Concurrent calls occasionally crash the whole process without a Python
traceback.

Docling renders through pypdfium2 under its own internal lock, and our
calls must serialize WITH it, not just among themselves. But importing
docling here would drag torch into memory on every app start (gigabytes
of RAM for an idle server — see test_light_startup). So the lock is
two-layered: our own Lock is always taken first; if docling is already
loaded (indexing has started), its internal lock is taken as well.
Before docling is imported no docling threads exist, so our Lock alone
is enough. The order is always ours -> docling's and docling never takes
ours — no deadlock. If Docling ever moves the internal module we fall
back to our own Lock (test_pdfium_lock catches the change).
"""

from __future__ import annotations

import sys
import threading

__all__ = ["PDFIUM_LOCK"]


class _SharedPdfiumLock:
    def __init__(self) -> None:
        self._own = threading.Lock()
        self._docling_held: threading.Lock | None = None

    @staticmethod
    def _docling_lock() -> threading.Lock | None:
        # sys.modules вместо import: увидеть уже загруженный docling,
        # но не загружать его самим.
        locks = sys.modules.get("docling.utils.locks")
        return getattr(locks, "pypdfium2_lock", None)

    def __enter__(self) -> "_SharedPdfiumLock":
        self._own.acquire()
        # Пишется только потоком, владеющим _own, — гонки нет.
        self._docling_held = self._docling_lock()
        if self._docling_held is not None:
            self._docling_held.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._docling_held is not None:
            self._docling_held.release()
        self._own.release()


PDFIUM_LOCK = _SharedPdfiumLock()
