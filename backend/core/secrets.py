"""Encryption of stored secrets at rest (the OpenAI key).

On Windows the value is protected with DPAPI (CryptProtectData), which
ties it to the user's account: app.db copied to another machine or account
no longer reveals the key. The realistic threat this closes is a travelling
file — a backup, a roamed profile, a lost laptop. It does NOT protect
against code running as that user: such code can simply ask Windows to
decrypt, exactly like with any system password store.

Elsewhere (development on macOS) the value is stored as it is: the
distribution is Windows-only, and pretend-encryption would only create a
false sense of safety.

Both directions fail soft. Encryption that fails stores the plain value —
losing the user's key would be worse. Decryption that fails returns None,
so the app asks for the key again instead of crashing (a DB restored under
a different Windows account cannot be decrypted at all).
"""

import base64
import ctypes
import sys


# Marks a value as DPAPI ciphertext; anything else is a plain legacy value.
PREFIX = "dpapi:"


class _Blob(ctypes.Structure):
    """DATA_BLOB from wincrypt.h.

    c_uint32 instead of wintypes.DWORD on purpose: `ctypes.wintypes` does
    not import off Windows, and this module is imported everywhere.
    """

    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _available() -> bool:
    """Can this platform protect secrets at all?"""
    return sys.platform == "win32"


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    """One CryptProtectData / CryptUnprotectData call. Windows only."""
    crypt32 = ctypes.windll.crypt32
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    call = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    if not call(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)):
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def protect(value: str) -> str:
    """The value as it should be written to the DB."""
    if not value or not _available():
        return value
    try:
        blob = _dpapi(value.encode("utf-8"), encrypt=True)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[secrets] could not protect the value, storing it plain: {exc}")
        return value
    return PREFIX + base64.b64encode(blob).decode("ascii")


def unprotect(stored: str) -> str | None:
    """The usable value, or None when the stored one cannot be read."""
    if not stored.startswith(PREFIX):
        return stored  # written before this feature, or on another platform
    try:
        blob = base64.b64decode(stored[len(PREFIX) :])
        return _dpapi(blob, encrypt=False).decode("utf-8")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[secrets] could not read the protected value: {exc}")
        return None


def needs_upgrade(stored: str) -> bool:
    """Is this a plain value on a platform that could protect it?"""
    return bool(stored) and _available() and not stored.startswith(PREFIX)
