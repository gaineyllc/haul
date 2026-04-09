"""Tests for keyring-backed credential store."""
import os
import pytest


@pytest.fixture(autouse=True)
def isolated_keyring(tmp_path, monkeypatch):
    """Use a temp keyring backend + data dir for each test."""
    monkeypatch.setenv("HAUL_DATA_DIR", str(tmp_path))
    # Use in-memory keyring for tests
    import keyring
    from keyring.backends import fail, null
    monkeypatch.setattr(keyring, "get_keyring", lambda: null.Keyring())
    # Reset module state
    from src.haul import credentials as creds
    yield
    # Cleanup index file
    idx = tmp_path / "credential_keys.json"
    if idx.exists():
        idx.unlink()


def test_set_and_get(tmp_path, monkeypatch):
    monkeypatch.setenv("HAUL_DATA_DIR", str(tmp_path))
    # Use env var fallback since keyring is null in tests
    monkeypatch.setenv("SYNOLOGY_HOST", "http://nas")
    from src.haul.credentials import get_credential
    assert get_credential("SYNOLOGY_HOST") == "http://nas"


def test_env_fallback(monkeypatch):
    monkeypatch.setenv("MY_TEST_KEY", "env_value")
    from src.haul.credentials import get_credential
    assert get_credential("MY_TEST_KEY") == "env_value"


def test_default_returned_when_missing():
    from src.haul.credentials import get_credential
    assert get_credential("NONEXISTENT_KEY_XYZ", "default") == "default"


def test_unlock_store_is_noop():
    from src.haul.credentials import unlock_store
    unlock_store()  # should not raise
    unlock_store("any passphrase")  # should not raise


def test_session_always_loaded():
    from src.haul.credentials import _Session
    assert _Session.loaded() is True
