"""Холостой старт бэкенда не должен грузить ML-библиотеки.

Docling/torch/transformers занимают гигабайты RAM и грузятся десятки
секунд — они нужны только при индексации PDF, а не при запуске сервера
(на рабочем компе приложение без индексации держало ~4 ГБ).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Импорт в отдельном процессе: sys.modules текущего процесса уже засорён
# другими тестами, чистую картину даёт только свежий интерпретатор.
_CHECK = (
    "import sys; import backend.app; "
    "heavy = [m for m in ('docling', 'torch', 'transformers') if m in sys.modules]; "
    "sys.exit('ML loaded at startup: ' + ', '.join(heavy) if heavy else 0)"
)


def test_backend_import_does_not_load_ml_stack() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _CHECK],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr.strip()
