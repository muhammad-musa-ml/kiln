"""Credential storage for provider API keys.

Keys are encrypted at rest with Windows DPAPI, scoped to this user account on
this machine - a copied file is useless elsewhere, and another user on the
same box cannot decrypt it. Where DPAPI is unavailable the store falls back
to an obfuscated file and says so loudly, because a silent downgrade to
plaintext is worse than no encryption at all.

Nothing here is ever exported. The publisher whitelists fields by name, so a
credential cannot reach the public site even if this module changes shape.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from . import config

STORE = config.DATA / "secrets.json"

_DPAPI_OK: bool | None = None


def _dpapi():
    """ctypes binding to CryptProtectData/CryptUnprotectData."""
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    def _blob(data: bytes) -> BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _bytes(blob: BLOB) -> bytes:
        out = ctypes.string_at(blob.pbData, blob.cbData)
        kernel32.LocalFree(blob.pbData)
        return out

    def protect(raw: bytes) -> bytes:
        out = BLOB()
        if not crypt32.CryptProtectData(ctypes.byref(_blob(raw)), None, None,
                                        None, None, 0, ctypes.byref(out)):
            raise OSError("CryptProtectData failed")
        return _bytes(out)

    def unprotect(enc: bytes) -> bytes:
        out = BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(_blob(enc)), None, None,
                                          None, None, 0, ctypes.byref(out)):
            raise OSError("CryptUnprotectData failed")
        return _bytes(out)

    return protect, unprotect


def available() -> bool:
    global _DPAPI_OK
    if _DPAPI_OK is None:
        try:
            p, u = _dpapi()
            _DPAPI_OK = u(p(b"kiln-probe")) == b"kiln-probe"
        except Exception:
            _DPAPI_OK = False
    return _DPAPI_OK


def _load_raw() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"mode": "dpapi" if available() else "obfuscated", "keys": {}}


def _save_raw(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, indent=2), encoding="utf-8")
    try:  # best-effort: owner-only on POSIX, no-op on Windows
        os.chmod(STORE, 0o600)
    except Exception:
        pass


def set_key(ref: str, value: str) -> None:
    """Store a credential under a short reference name."""
    d = _load_raw()
    if available():
        protect, _ = _dpapi()
        d["mode"] = "dpapi"
        d.setdefault("keys", {})[ref] = base64.b64encode(
            protect(value.encode("utf-8"))).decode()
    else:
        d["mode"] = "obfuscated"
        d.setdefault("keys", {})[ref] = base64.b64encode(
            value.encode("utf-8")).decode()
    _save_raw(d)


def get_key(ref: str) -> str:
    """Return a credential, or '' if absent.

    Environment variables win over the store, so a CI or shell-exported key
    overrides whatever was saved from the UI.
    """
    env_name = {"gemini": "GEMINI_API_KEY"}.get(ref, f"KILN_KEY_{ref.upper()}")
    if os.environ.get(env_name):
        return os.environ[env_name]
    if os.environ.get(f"KILN_KEY_{ref.upper()}"):
        return os.environ[f"KILN_KEY_{ref.upper()}"]

    d = _load_raw()
    enc = (d.get("keys") or {}).get(ref)
    if not enc:
        return ""
    raw = base64.b64decode(enc)
    if d.get("mode") == "dpapi":
        try:
            _, unprotect = _dpapi()
            return unprotect(raw).decode("utf-8")
        except Exception:
            return ""
    return raw.decode("utf-8")


def delete_key(ref: str) -> None:
    d = _load_raw()
    (d.get("keys") or {}).pop(ref, None)
    _save_raw(d)


def known_refs() -> list[str]:
    return sorted((_load_raw().get("keys") or {}).keys())


def mask(value: str) -> str:
    """What the UI is allowed to display. Never the key itself."""
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]} ({len(value)} chars)"


def status() -> dict:
    d = _load_raw()
    return {
        "encrypted": available(),
        "mode": d.get("mode", "none"),
        "stored_refs": known_refs(),
        "warning": "" if available() else
                   "DPAPI unavailable - keys are only obfuscated on this machine.",
    }
