"""
Haul PQC credential store.
Uses ML-KEM-768 (CRYSTALS-Kyber, NIST FIPS 203) via kyber-py >= 1.2.

Storage: ~/.haul/credentials.enc
Keys:    ~/.haul/credentials.key  (encapsulation key only — never the private key)

Hybrid encryption pattern:
  Setup:   PBKDF2(passphrase) → seed → ML_KEM_768.keygen() → (ek, dk)
           Store ek on disk. dk is re-derived from passphrase each session.
  Encrypt: ML_KEM_768.encaps(ek) → (K, ct); AES-256-GCM(K) encrypts data
  Decrypt: ML_KEM_768.decaps(dk, ct) → K; AES-256-GCM(K) decrypts data

Performance: keypair is cached in memory after first unlock — no repeated keygen.
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from kyber_py.ml_kem import ML_KEM_768


# ── Config ─────────────────────────────────────────────────────────────────────

# Iterations for PBKDF2 — override with env var for testing
_PBKDF2_ITERATIONS = int(os.getenv("HAUL_PBKDF2_ITERATIONS", "200000"))


# ── Paths ──────────────────────────────────────────────────────────────────────

def _dir() -> Path:
    d = Path(os.getenv("HAUL_DATA_DIR", str(Path.home() / ".haul")))
    d.mkdir(parents=True, exist_ok=True)
    return d

def _cred_file() -> Path: return _dir() / "credentials.enc"
def _key_file()  -> Path: return _dir() / "credentials.key"


# ── Key helpers ────────────────────────────────────────────────────────────────

def _hkdf(length: int, ikm: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length,
                salt=None, info=info).derive(ikm)


def _derive_seed(passphrase: str, salt: bytes) -> bytes:
    """PBKDF2 passphrase → 48-byte seed for ML-KEM DRBG."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=48,
                     salt=salt, iterations=_PBKDF2_ITERATIONS)
    return kdf.derive(passphrase.encode())


def _keygen_from_seed(seed: bytes) -> tuple[bytes, bytes]:
    """Deterministic ML-KEM-768 keygen from a 48-byte seed."""
    ML_KEM_768.set_drbg_seed(seed)
    return ML_KEM_768.keygen()


# ── Session-level keypair cache ────────────────────────────────────────────────

class _Session:
    """Holds the decrypted keypair for the lifetime of this process."""
    ek: bytes | None = None
    dk: bytes | None = None
    cache: dict | None = None

    @classmethod
    def loaded(cls) -> bool:
        return cls.dk is not None

    @classmethod
    def load(cls, passphrase: str | None = None) -> None:
        """Derive keypair from passphrase and cache it."""
        kf = _key_file()
        if not kf.exists():
            raise RuntimeError("Credential store not initialized. Run: haul setup")

        data = json.loads(kf.read_text())
        ek_stored = base64.b64decode(data["ek"])
        salt      = base64.b64decode(data["salt"])

        pp = passphrase or getpass.getpass("Haul passphrase: ")
        seed = _derive_seed(pp, salt)
        ek_derived, dk = _keygen_from_seed(seed)

        if ek_derived != ek_stored:
            raise ValueError("Wrong passphrase — derived key doesn't match stored key.")

        cls.ek = ek_stored
        cls.dk = dk
        cls.cache = None  # will be loaded on first access

    @classmethod
    def reset(cls) -> None:
        cls.ek = cls.dk = cls.cache = None


# ── Core encrypt/decrypt ───────────────────────────────────────────────────────

def _encrypt_data(data: dict, ek: bytes) -> None:
    """Encrypt credential dict and write to disk using cached ek."""
    K, ct_kem = ML_KEM_768.encaps(ek)
    aes_key = _hkdf(32, K, b"haul-aes-256-gcm")
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(aes_key).encrypt(nonce, json.dumps(data).encode(), None)
    packed = len(ct_kem).to_bytes(4, "big") + ct_kem + nonce + ciphertext
    _cred_file().write_bytes(base64.b64encode(packed))
    _cred_file().chmod(0o600)


def _decrypt_data(dk: bytes) -> dict:
    """Decrypt credential file using cached dk."""
    if not _cred_file().exists():
        return {}
    packed  = base64.b64decode(_cred_file().read_bytes())
    kl      = int.from_bytes(packed[:4], "big")
    ct_kem  = packed[4:4 + kl]
    nonce   = packed[4 + kl: 4 + kl + 12]
    ct_aes  = packed[4 + kl + 12:]
    K       = ML_KEM_768.decaps(dk, ct_kem)
    aes_key = _hkdf(32, K, b"haul-aes-256-gcm")
    return json.loads(AESGCM(aes_key).decrypt(nonce, ct_aes, None))


def _get_cache() -> dict:
    """Return credential cache, loading from disk if needed."""
    if _Session.cache is None:
        if not _Session.loaded():
            raise RuntimeError("Store not unlocked. Call unlock_store() first.")
        _Session.cache = _decrypt_data(_Session.dk)
    return _Session.cache


def _save_cache() -> None:
    """Persist in-memory cache to disk."""
    if _Session.ek is None:
        raise RuntimeError("Store not unlocked.")
    _encrypt_data(_Session.cache or {}, _Session.ek)


# ── Public API ─────────────────────────────────────────────────────────────────

def initialized() -> bool:
    return _key_file().exists()


def init_store(passphrase: str | None = None) -> None:
    """Create a new credential store. Fails if already initialized."""
    if initialized():
        raise RuntimeError("Store already initialized. Delete ~/.haul/credentials.* to reset.")

    pp = passphrase or getpass.getpass("Choose haul passphrase: ")
    if not passphrase:
        pp2 = getpass.getpass("Confirm: ")
        if pp != pp2:
            raise ValueError("Passphrases don't match")

    salt = secrets.token_bytes(32)
    seed = _derive_seed(pp, salt)
    ek, dk = _keygen_from_seed(seed)

    # Store encapsulation key (public) + salt
    _key_file().write_text(json.dumps({
        "ek":        base64.b64encode(ek).decode(),
        "salt":      base64.b64encode(salt).decode(),
        "algorithm": "ML-KEM-768",
        "kdf":       "PBKDF2-SHA256",
    }))
    _key_file().chmod(0o600)

    # Cache session state
    _Session.ek    = ek
    _Session.dk    = dk
    _Session.cache = {}

    # Write empty encrypted store
    _encrypt_data({}, ek)


def unlock_store(passphrase: str | None = None) -> None:
    """Unlock the store for this session. Must be called before get/set."""
    _Session.load(passphrase)


def get_credential(key: str, default: str | None = None) -> str | None:
    """Get a credential. Falls back to environment variable."""
    if _Session.loaded():
        cache = _get_cache()
        v = cache.get(key)
        if v:
            return v
    return os.getenv(key, default)


def set_credential(key: str, value: str) -> None:
    """Set a credential and immediately persist."""
    cache = _get_cache()
    cache[key] = value
    _save_cache()


def delete_credential(key: str) -> None:
    cache = _get_cache()
    cache.pop(key, None)
    _save_cache()


def list_credentials() -> list[str]:
    return sorted(_get_cache().keys())


class _Store:
    """Legacy-compat shim used by setup.py."""
    _cache: dict | None = None
    _pp: str | None = None

    @classmethod
    def unlock(cls, pp: str | None = None) -> None:
        unlock_store(pp)
        cls._cache = _Session.cache

    @classmethod
    def get(cls, key: str, default: str | None = None) -> str | None:
        return get_credential(key, default)

    @classmethod
    def set(cls, key: str, value: str, pp: str | None = None) -> None:
        set_credential(key, value)

    @classmethod
    def initialized(cls) -> bool:
        return initialized()

    @classmethod
    def list_keys(cls) -> list[str]:
        return list_credentials()
