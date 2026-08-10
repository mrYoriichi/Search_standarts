"""Холостой старт бэкенда не должен грузить ML-библиотеки.

Docling/torch/transformers занимают гигабайты RAM и грузятся десятки
секунд — они нужны только при индексации PDF, а не при запуске сервера
(на рабочем компе приложение без индексации держало ~4 ГБ).
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Импорт в отдельном процессе: sys.modules текущего процесса уже засорён
# другими тестами, чистую картину даёт только свежий интерпретатор.
_CHECK = (
    "import sys; import {module}; "
    "heavy = [m for m in ('docling', 'torch', 'transformers') if m in sys.modules]; "
    "sys.exit('ML loaded: ' + ', '.join(heavy) if heavy else 0)"
)


def _assert_light_import(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _CHECK.format(module=module)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"{module}: {result.stderr.strip()}"


def test_backend_import_does_not_load_ml_stack() -> None:
    _assert_light_import("backend.app")


# Эти стадии выполняются в ОСНОВНОМ процессе (docling нужен только
# parse, а он живёт в дочернем воркере) — импорт describe/chunk/embed
# не должен затащить ML-стек обратно в родителя. pipeline.parse тоже
# лёгкий: путь резюма (готовый document.json) рендерит скриншоты
# pdfium'ом, docling грузится только при полном парсе.
@pytest.mark.parametrize(
    "module",
    ["pipeline.parse", "pipeline.describe", "pipeline.chunk", "pipeline.embed"],
)
def test_parent_stages_do_not_load_ml_stack(module: str) -> None:
    _assert_light_import(module)
