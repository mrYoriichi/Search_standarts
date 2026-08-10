"""Atomic JSON writes: write to a temp file, then rename.

os.replace within one directory is atomic — a reader never sees a
half-written file. This matters for the shared network `.search_index`
folder: an interrupted write leaves at most a stray *.tmp, never a
corrupted index.
"""

import json
import os
import time
import uuid
from pathlib import Path

# OneDrive/антивирус на Windows держат целевой файл открытым пару секунд —
# os.replace в этот момент кидает PermissionError (WinError 5). Файл
# отпускают быстро, поэтому несколько попыток с паузой решают проблему.
REPLACE_ATTEMPTS = 5
REPLACE_RETRY_DELAY_S = 1.0


def save_json_atomic(path: Path, data: object) -> None:
    """Write data to path via a temp file in the same directory."""
    # The tmp name is unique per writer: a shared name (`X.tmp`) let two
    # machines on a network share steal the file from under each other's
    # os.replace.
    tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            # ensure_ascii=False keeps Czech characters readable.
            json.dump(data, f, ensure_ascii=False, indent=2)
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_RETRY_DELAY_S)
    except Exception:
        tmp.unlink(missing_ok=True)  # a failed write must not pile up tmp files
        raise
