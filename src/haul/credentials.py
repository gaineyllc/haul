"""
Haul credential store — backed by OS keychain.

Uses the `keyring` library which routes to:
  Windows  → Windows Credential Manager
  macOS    → Keychain
  Linux    → SecretService (GNOME Keyring / KWallet)

No passphrase. No encryption to manage. No salt. No mismatch.
Credentials are stored and retrieved by name. OS handles security.

Usage:
  set_credential("IPTORRENTS_USER", "myuser")
  get_credential("IPTORRENTS_USER")  → "myuser"
  list_credentials()                 → ["IPTORRENTS_USER", ...]
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import keyring

# Keyring service name — all haul credentials stored under this
_SERVICE = "haul"

# Track which keys exist (keyring has no list API)
def _index_path() -> Path:
    d = Path(os.getenv("HAUL_DATA_DIR", str(Path.home() / ".haul")))
    d.mkdir(parents=True, exist_ok=True)
    return d / "credential_keys.json"


def _load_index() -> list[str]:
    p = _index_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _save_index(keys: list[str]) -> None:
    _index_path().write_text(json.dumps(sorted(set(keys))))


def get_credential(key: str, default: str | None = None) -> str | None:
    """Get a credential from the OS keychain, falling back to environment."""
    try:
        val = keyring.get_password(_SERVICE, key)
        if val:
            return val
    except Exception:
        pass
    return os.getenv(key, default)


def set_credential(key: str, value: str) -> None:
    """Store a credential in the OS keychain."""
    keyring.set_password(_SERVICE, key, value)
    idx = _load_index()
    if key not in idx:
        idx.append(key)
        _save_index(idx)


def delete_credential(key: str) -> None:
    """Remove a credential from the OS keychain."""
    try:
        keyring.delete_password(_SERVICE, key)
    except Exception:
        pass
    idx = _load_index()
    if key in idx:
        idx.remove(key)
        _save_index(idx)


def list_credentials() -> list[str]:
    """List all stored credential key names."""
    return _load_index()


def initialized() -> bool:
    """True if any credentials have been stored."""
    return bool(_load_index())


def unlock_store(passphrase: str | None = None) -> None:
    """No-op — keyring handles auth at the OS level. Kept for API compat."""
    pass


def save_passphrase_to_wincred(passphrase: str) -> None:
    """No-op — not needed with keyring backend. Kept for API compat."""
    pass


def load_passphrase_from_wincred() -> str | None:
    """No-op — not needed with keyring backend. Kept for API compat."""
    return "not-needed"  # truthy so auto-unlock code paths don't prompt


# Legacy compat shim
class _Session:
    @staticmethod
    def loaded() -> bool:
        return True  # always "unlocked" with keyring

    @staticmethod
    def reset() -> None:
        pass  # nothing to reset


class _Store:
    _cache = None
    _pp = None

    @classmethod
    def unlock(cls, pp=None): pass

    @classmethod
    def get(cls, key, default=None): return get_credential(key, default)

    @classmethod
    def set(cls, key, value, pp=None): set_credential(key, value)

    @classmethod
    def initialized(cls): return initialized()

    @classmethod
    def list_keys(cls): return list_credentials()
