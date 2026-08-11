"""Кооперативная остановка индексации (кнопки ⏹, решение 2026-08-11).

Реестр слагов, для которых юзер попросил стоп. Пайплайн проверяет флаг
в безопасных точках (между стадиями, между страницами describe, между
событиями parse) и выходит через IndexingCancelled — документ
возвращается в «čeká», чекпоинты остаются, продолжение бесплатно.

Не персистится намеренно: рестарт приложения сам по себе останавливает
всё, а crash-resume должен работать как раньше.
"""

import threading

_lock = threading.Lock()
_requested: set[str] = set()
_running: set[str] = set()


class IndexingCancelled(Exception):
    """Индексация остановлена юзером — не ошибка, документ снова čeká."""


def request(slug: str) -> None:
    """⏹ нажата: попросить пайплайн документа остановиться."""
    with _lock:
        _requested.add(slug)


def requested(slug: str) -> bool:
    with _lock:
        return slug in _requested


def mark_running(slug: str) -> None:
    """Пайплайн документа реально начал работать (не просто в очереди).

    Эндпоинт стопа по этому флагу различает: очередь — вернуть в čeká
    сразу; работает — ждать, пока пайплайн дойдёт до безопасной точки.
    """
    with _lock:
        _running.add(slug)


def is_running(slug: str) -> bool:
    with _lock:
        return slug in _running


def mark_done(slug: str) -> None:
    """Пайплайн закончил (как угодно) — подчистить оба флага."""
    with _lock:
        _running.discard(slug)
        _requested.discard(slug)
