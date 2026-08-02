"""Background-processing progress per document — shown in the UI.

Ephemeral in-process state: {slug: "describing images: page 12/47"}.
Deliberately not persisted: progress lives as long as the pipeline;
after a restart processing resumes and progress reappears.

Pipelines write from ThreadPoolExecutor threads, the API reads from its
own — hence the lock.
"""

import threading

_lock = threading.Lock()
_progress: dict[str, str] = {}


def set_progress(slug: str, text: str) -> None:
    with _lock:
        _progress[slug] = text


def get_progress(slug: str) -> str | None:
    with _lock:
        return _progress.get(slug)


def clear_progress(slug: str) -> None:
    with _lock:
        _progress.pop(slug, None)
