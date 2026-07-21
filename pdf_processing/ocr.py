"""OCR картинки через RapidOCR — локально, без затрат на API.

Нужен для ветки «чертёж»: у опубликованных чертежей текст сплющён в кривые
или отсутствует (скан), OCR — единственный источник текста.

RapidOCR тяжёлый (движок onnxruntime грузит модели) — импортируем и создаём
движок ЛЕНИВО, один раз на процесс. В сборку .exe движок входит через
build.spec; в dev-venv: `pip install onnxruntime`.
"""

import threading

import numpy as np
from PIL import Image

_engine = None
# Документы индексируются в несколько потоков; без лока они создавали движок
# параллельно, и на Windows одновременное чтение .onnx падало с "error 13".
_engine_lock = threading.Lock()


def _get_engine():
    """Ленивый синглтон движка RapidOCR (модели грузятся один раз)."""
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr import RapidOCR

            _engine = RapidOCR()
    return _engine


def _extract_text(result) -> str:
    """Достаёт текст из ответа RapidOCR, сшивая фрагменты через пробел.

    Поддерживает оба формата API: новый объект с полем `.txts` и старый
    кортеж `([[box, text, score], ...], elapse)`. Пусто → пустая строка.
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
    """Распознаёт текст на картинке → одна строка (фрагменты через пробел)."""
    arr = np.array(image.convert("RGB"))
    return _extract_text(_get_engine()(arr))
