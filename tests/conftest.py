"""Test-suite-wide safety net: no test may ever touch the real OS credential store.

Incident 2026-10-08: tests/test_login_setup_exceptions.py ran login_setup.main(),
whose first step is secure_session.delete_token() -> keyring.delete_password(...)
against the REAL Windows Credential Manager, wiping the live Monarch login on every
test run.

Defense in depth:
  1. The keyring backend is swapped for an in-memory one at import time (before any
     test module is collected/imported) and re-asserted + emptied for every test.
  2. Every test runs in a fresh temp cwd, because secure_session cleans up relative
     paths (.mm/, monarch_session.json) and monarchmoney writes .mm/ relative to cwd.
"""

import keyring
import keyring.backend
import keyring.errors
import pytest


class InMemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1000  # type: ignore[assignment]

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        try:
            del self.store[(service, username)]
        except KeyError:
            raise keyring.errors.PasswordDeleteError("not found")


_MEMORY_KEYRING = InMemoryKeyring()
# Installed at import time so even module-level code in tests is covered.
keyring.set_keyring(_MEMORY_KEYRING)


@pytest.fixture(autouse=True)
def _isolate_credentials_and_cwd(tmp_path, monkeypatch):
    _MEMORY_KEYRING.store.clear()
    keyring.set_keyring(_MEMORY_KEYRING)  # undo anything a test swapped
    monkeypatch.chdir(tmp_path)
    yield
    assert keyring.get_keyring() is _MEMORY_KEYRING, "a test replaced the isolated keyring"
