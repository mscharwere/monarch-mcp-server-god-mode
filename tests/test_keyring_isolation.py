"""Guard: the suite must never reach the real OS credential store."""

import keyring

from monarch_mcp_server.secure_session import (
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    secure_session,
)
from tests.conftest import InMemoryKeyring


def test_active_backend_is_in_memory():
    backend = keyring.get_keyring()
    assert isinstance(backend, InMemoryKeyring)
    assert "WinVault" not in type(backend).__name__


def test_save_and_delete_token_stay_in_memory():
    backend = keyring.get_keyring()
    secure_session.save_token("fake-token")
    assert backend.store == {(KEYRING_SERVICE, KEYRING_USERNAME): "fake-token"}
    assert secure_session.load_token() == "fake-token"
    secure_session.delete_token()
    assert backend.store == {}
    assert secure_session.load_token() is None
    assert isinstance(keyring.get_keyring(), InMemoryKeyring)


def test_store_starts_empty_each_test():
    assert keyring.get_keyring().store == {}


def test_cwd_is_isolated(tmp_path):
    import os

    assert os.getcwd() == str(tmp_path)
