"""
Haul PQC credential store — same ML-KEM-768 pattern as archon.
Stored at ~/.haul/credentials.enc
"""
from __future__ import annotations
import base64, getpass, json, os, secrets, sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

try:
    from kyber import Kyber768
    _KYBER = True
except ImportError:
    _KYBER = False


def _dir() -> Path:
    d = Path(os.getenv("HAUL_DATA_DIR", str(Path.home() / ".haul")))
    d.mkdir(parents=True, exist_ok=True)
    return d

def _cred_file() -> Path: return _dir() / "credentials.enc"
def _key_file()  -> Path: return _dir() / "credentials.key"


def _hkdf(length: int, ikm: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length,
                salt=None, info=info).derive(ikm)


def _load_keypair(passphrase: str | None = None) -> tuple[bytes, bytes]:
    if not _KYBER:
        raise RuntimeError("kyber-py not installed")
    kf = _key_file()
    if kf.exists():
        data = json.loads(kf.read_text())
        pub  = base64.b64decode(data["public_key"])
        salt = base64.b64decode(data["salt"])
        pp   = passphrase or getpass.getpass("Haul passphrase: ")
        seed = HKDF(algorithm=hashes.SHA256(), length=64,
                    salt=salt, info=b"haul-kyber").derive(pp.encode())
        _, priv = Kyber768.keygen(seed[:32])
        return pub, priv
    # First time
    pp = passphrase or getpass.getpass("Choose haul passphrase: ")
    pp2 = getpass.getpass("Confirm: ")
    if pp != pp2: raise ValueError("Passphrases don't match")
    salt = secrets.token_bytes(32)
    seed = HKDF(algorithm=hashes.SHA256(), length=64,
                salt=salt, info=b"haul-kyber").derive(pp.encode())
    pub, priv = Kyber768.keygen(seed[:32])
    kf.write_text(json.dumps({
        "public_key": base64.b64encode(pub).decode(),
        "salt": base64.b64encode(salt).decode(),
        "algorithm": "ML-KEM-768",
    }))
    kf.chmod(0o600)
    return pub, priv


def _encrypt(data: dict, passphrase: str | None = None) -> None:
    pub, _ = _load_keypair(passphrase)
    ct_kem, ss = Kyber768.enc(pub)
    aes_key = _hkdf(32, ss, b"haul-aes")
    nonce = secrets.token_bytes(12)
    cipher = AESGCM(aes_key).encrypt(nonce, json.dumps(data).encode(), None)
    payload = len(ct_kem).to_bytes(4,"big") + ct_kem + nonce + cipher
    _cred_file().write_bytes(base64.b64encode(payload))
    _cred_file().chmod(0o600)


def _decrypt(passphrase: str | None = None) -> dict:
    if not _cred_file().exists(): return {}
    _, priv = _load_keypair(passphrase)
    payload = base64.b64decode(_cred_file().read_bytes())
    kl = int.from_bytes(payload[:4], "big")
    ct_kem = payload[4:4+kl]
    nonce  = payload[4+kl:4+kl+12]
    cipher = payload[4+kl+12:]
    ss = Kyber768.dec(priv, ct_kem)
    aes_key = _hkdf(32, ss, b"haul-aes")
    return json.loads(AESGCM(aes_key).decrypt(nonce, cipher, None))


class _Store:
    _cache: dict | None = None
    _pp: str | None = None

    @classmethod
    def unlock(cls, pp: str | None = None) -> None:
        cls._pp = pp; cls._cache = _decrypt(pp)

    @classmethod
    def get(cls, key: str, default: str | None = None) -> str | None:
        if cls._cache is not None:
            v = cls._cache.get(key)
            if v: return v
        return os.getenv(key, default)

    @classmethod
    def set(cls, key: str, value: str, pp: str | None = None) -> None:
        if cls._cache is None: cls._cache = _decrypt(pp or cls._pp)
        cls._cache[key] = value
        _encrypt(cls._cache, pp or cls._pp)

    @classmethod
    def initialized(cls) -> bool: return _key_file().exists()


def get_credential(key: str, default: str | None = None) -> str | None:
    return _Store.get(key, default)


def init_store(passphrase: str | None = None) -> None:
    _load_keypair(passphrase)
    _Store._cache = {}
    _encrypt({}, passphrase)


def set_credential(key: str, value: str) -> None:
    _Store.set(key, value)


def unlock_store(passphrase: str | None = None) -> None:
    _Store.unlock(passphrase)
