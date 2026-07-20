"""Общий замок всех вызовов PDFium.

PDFium не потокобезопасна, а мы зовём её из нескольких потоков сразу:
3 воркера пайплайна, скан архива, рендер страниц сильного поиска.
Параллельные вызовы изредка роняют весь процесс без Python-traceback.

Замок берём у Docling: его конвертер рендерит через pypdfium2 под своим
threading.Lock, и наши вызовы должны сериализоваться С НИМ, а не только
между собой. Если Docling переложит внутренний модуль — откат на свой
Lock (защита наших потоков останется, тест test_pdfium_lock это поймает).
"""

import threading

__all__ = ["PDFIUM_LOCK"]

try:
    from docling.utils.locks import pypdfium2_lock as PDFIUM_LOCK
except ImportError:
    PDFIUM_LOCK = threading.Lock()
