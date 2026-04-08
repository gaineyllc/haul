"""Tests for PQC credential store."""
import os
import tempfile
import pytest


@pytest.fixture
def tmp_haul_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HAUL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HAUL_PBKDF2_ITERATIONS", "1000")  # fast for tests
    # Reset module-level cache
    from src.haul import credentials
    credentials._Store._cache = None
    credentials._Store._pp = None
    yield tmp_path
    credentials._Store._cache = None
    credentials._Store._pp = None


def test_init_and_roundtrip(tmp_haul_dir):
    from src.haul.credentials import init_store, set_credential, get_credential, unlock_store, _Store

    init_store("testpass")
    set_credential("SYNOLOGY_HOST", "http://192.168.1.1:5000")
    set_credential("IPTORRENTS_USER", "neil")

    # Simulate new session
    _Store._cache = None
    unlock_store("testpass")

    assert get_credential("SYNOLOGY_HOST") == "http://192.168.1.1:5000"
    assert get_credential("IPTORRENTS_USER") == "neil"


def test_wrong_passphrase_raises(tmp_haul_dir):
    from src.haul.credentials import init_store, unlock_store, _Session

    init_store("correctpass")
    _Session.reset()

    with pytest.raises(ValueError, match="Wrong passphrase"):
        unlock_store("wrongpass")


def test_env_fallback(tmp_haul_dir, monkeypatch):
    from src.haul.credentials import get_credential, _Store
    _Store._cache = {}
    monkeypatch.setenv("MY_SECRET", "from_env")
    assert get_credential("MY_SECRET") == "from_env"


def test_list_keys(tmp_haul_dir):
    from src.haul.credentials import init_store, set_credential, _Store, unlock_store

    init_store("testpass")
    set_credential("KEY_A", "val_a")
    set_credential("KEY_B", "val_b")

    _Store._cache = None
    unlock_store("testpass")

    keys = _Store.list_keys()
    assert "KEY_A" in keys
    assert "KEY_B" in keys
