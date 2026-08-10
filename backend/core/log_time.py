"""Обёртка лог-файла: приписывает время в начало каждой строки.

app.log дописывается через все запуски приложения — без времени в
строках нельзя понять, когда что случилось.
"""

import time
from typing import TextIO


class TimestampWriter:
    def __init__(self, target: TextIO) -> None:
        self._target = target
        self._line_start = True

    def write(self, text: str) -> int:
        for line in text.splitlines(keepends=True):
            if self._line_start:
                self._target.write(time.strftime("%Y-%m-%d %H:%M:%S "))
            self._target.write(line)
            self._line_start = line.endswith("\n")
        return len(text)

    def flush(self) -> None:
        self._target.flush()

    def __getattr__(self, name: str) -> object:
        # Остальные атрибуты файла (isatty, encoding, ...) — у оригинала.
        return getattr(self._target, name)
