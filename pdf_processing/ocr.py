"""Image OCR via RapidOCR — local, no API cost.

Needed for the drawing branch: published drawings have their text
flattened into curves or none at all (scans), so OCR is the only text
source.

RapidOCR is heavy (the onnxruntime engine loads models) — imported and
created LAZILY, once per process. The .exe bundles the engine via
build.spec; in a dev venv: `pip install onnxruntime`.
"""

import threading

import numpy as np
from PIL import Image

_engine = None
# Documents index on several threads; without the lock they created the
# engine concurrently, and parallel reads of the same .onnx files failed
# on Windows with "error 13".
_engine_lock = threading.Lock()


def _get_engine():
    """Lazy RapidOCR engine singleton (models load once)."""
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr import RapidOCR

            _engine = RapidOCR()
    return _engine


def _extract_text(result) -> str:
    """Pull text out of a RapidOCR result, joining fragments with spaces.

    Supports both API shapes: the new object with `.txts` and the old
    `([[box, text, score], ...], elapse)` tuple. Empty → empty string.
    """
    if result is None:
        return ""
    txts = getattr(result, "txts", None)
    if txts:
        return " ".join(txts)
    if isinstance(result, tuple) and result[0]:
        return " ".join(row[1] for row in result[0])
    return ""


def ocr_image(image: Image.Image) -> str:
    """Recognize text in an image → one line (fragments space-joined)."""
    arr = np.array(image.convert("RGB"))
    return _extract_text(_get_engine()(arr))
