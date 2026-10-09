"""
Tests for create_transaction.

monarchmoneycommunity 1.6.0 signature:

    create_transaction(self, date, account_id, amount, merchant_name,
                       category_id, notes="", update_balance=False)

The tool used to pass `description=` and no merchant/category, so every call
raised TypeError. The mock below mirrors the real signature (and a test pins
it against the installed library). Nothing touches a real Monarch account.
"""

import inspect
import json
from unittest.mock import AsyncMock, patch

import pytest

ACCOUNTS = {
    "accounts": [
        {"id": "acc-1", "displayName": "Test Checking"},
        {"id": "acc-2", "displayName": "Test Savings"},
        {"id": "acc-3", "displayName": "Dup"},
        {"id": "acc-4", "displayName": "dup"},
        {"id": "acc-closed", "displayName": "Old Closed", "deactivatedAt": "2025-01-01"},
        {"id": "acc-hidden", "displayName": "Secret Hidden", "isHidden": True},
        # A closed account sharing a name with an open one must not cause ambiguity.
        {"id": "acc-closed2", "displayName": "Test Checking", "deactivatedAt": "2024-05-05"},
        {"id": "acc-open-flags", "displayName": "Open Flags", "isHidden": False, "deactivatedAt": None},
    ]
}
CATEGORIES = {
    "categories": [
        {"id": "cat-1", "name": "Groceries", "group": {"id": "g1", "name": "Food"}},
        {"id": "cat-2", "name": "Gas", "group": {"id": "g2", "name": "Auto"}},
        {"id": "cat-3", "name": "Gas", "group": {"id": "g3", "name": "Utilities"}},
    ]
}


class FakeClient:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {
            "createTransaction": {"errors": None, "transaction": {"id": "txn-1"}}
        }

    async def get_accounts(self):
        return ACCOUNTS

    async def get_transaction_categories(self):
        return CATEGORIES

    # Mirrors the REAL 1.6.0 signature: missing/extra kwargs raise TypeError.
    async def create_transaction(
        self,
        date,
        account_id,
        amount,
        merchant_name,
        category_id,
        notes="",
        update_balance=False,
    ):
        self.calls.append(
            dict(
                date=date,
                account_id=account_id,
                amount=amount,
                merchant_name=merchant_name,
                category_id=category_id,
                notes=notes,
                update_balance=update_balance,
            )
        )
        return self.result


def _server():
    from monarch_mcp_server import server

    return server


def _call(fake, **kwargs):
    server = _server()
    with patch.object(server, "get_monarch_client", new=AsyncMock(return_value=fake)):
        return server.create_transaction(**kwargs)


def test_fake_matches_installed_library_signature():
    from monarchmoney import MonarchMoney

    real = inspect.signature(MonarchMoney.create_transaction)
    fake = inspect.signature(FakeClient.create_transaction)
    assert list(real.parameters) == list(fake.parameters)
    for name, p in real.parameters.items():
        assert fake.parameters[name].default == p.default


def test_create_by_names_resolves_ids_and_uses_real_signature():
    fake = FakeClient()
    out = _call(
        fake,
        amount=-12.5,
        date="2026-10-08",
        merchant_name="  Test Merchant ",
        account="test checking",
        category="GROCERIES",
        notes="unit test",
    )
    assert json.loads(out)["createTransaction"]["transaction"]["id"] == "txn-1"
    assert fake.calls == [
        {
            "date": "2026-10-08",
            "account_id": "acc-1",
            "amount": -12.5,
            "merchant_name": "Test Merchant",
            "category_id": "cat-1",
            "notes": "unit test",
            "update_balance": False,
        }
    ]


def test_create_by_ids_and_legacy_aliases_notes_default_empty():
    fake = FakeClient()
    _call(
        fake,
        amount=5,
        date="2026-10-08",
        merchant_name="M",
        account_id="acc-2",
        category_id="cat-2",
    )
    c = fake.calls[0]
    assert c["account_id"] == "acc-2" and c["category_id"] == "cat-2"
    assert c["notes"] == "" and c["update_balance"] is False


def test_update_balance_passed_through():
    fake = FakeClient()
    _call(
        fake, amount=1, date="2026-10-08", merchant_name="M",
        account="acc-1", category="cat-1", update_balance=True,
    )
    assert fake.calls[0]["update_balance"] is True


@pytest.mark.parametrize(
    "kwargs,needle",
    [
        (dict(merchant_name="", account="acc-1", category="cat-1"), "merchant_name"),
        (dict(merchant_name="M", category="cat-1"), "account"),
        (dict(merchant_name="M", account="acc-1"), "category"),
        (dict(merchant_name="M", account="acc-1", category="cat-1", date="10/08/2026"), "YYYY-MM-DD"),
    ],
)
def test_missing_or_bad_inputs_error_without_calling_client(kwargs, needle):
    fake = FakeClient()
    base = dict(amount=1, date="2026-10-08")
    base.update(kwargs)
    out = _call(fake, **base)
    assert out.startswith("Error creating transaction") and needle in out
    assert fake.calls == []


@pytest.mark.parametrize(
    "kwargs,needle",
    [
        (dict(account="Nope", category="cat-1"), "Account 'Nope' not found"),
        (dict(account="acc-1", category="Nope"), "Category 'Nope' not found"),
        (dict(account="dup", category="cat-1"), "ambiguous"),
        (dict(account="acc-1", category="gas"), "ambiguous"),
    ],
)
def test_unknown_or_ambiguous_refs_error_and_create_nothing(kwargs, needle):
    fake = FakeClient()
    out = _call(fake, amount=1, date="2026-10-08", merchant_name="M", **kwargs)
    assert out.startswith("Error creating transaction") and needle in out
    assert fake.calls == []


def test_unknown_account_lists_valid_options():
    out = _call(
        FakeClient(), amount=1, date="2026-10-08", merchant_name="M",
        account="Nope", category="cat-1",
    )
    assert "Test Checking" in out and "Test Savings" in out


def test_api_payload_errors_are_surfaced():
    fake = FakeClient(
        result={"createTransaction": {"errors": {"message": "bad"}, "transaction": None}}
    )
    out = _call(
        fake, amount=1, date="2026-10-08", merchant_name="M",
        account="acc-1", category="cat-1",
    )
    assert out.startswith("Error creating transaction") and "bad" in out


def test_name_never_resolves_to_closed_or_hidden_account():
    for name in ("Old Closed", "secret hidden"):
        fake = FakeClient()
        out = _call(
            fake, amount=1, date="2026-10-08", merchant_name="M",
            account=name, category="cat-1",
        )
        assert out.startswith("Error creating transaction") and "not found" in out
        assert fake.calls == []


def test_closed_duplicate_name_does_not_make_open_account_ambiguous():
    fake = FakeClient()
    _call(
        fake, amount=1, date="2026-10-08", merchant_name="M",
        account="Test Checking", category="cat-1",
    )
    assert fake.calls[0]["account_id"] == "acc-1"


def test_valid_account_list_excludes_closed_and_hidden():
    out = _call(
        FakeClient(), amount=1, date="2026-10-08", merchant_name="M",
        account="Nope", category="cat-1",
    )
    assert "Test Checking" in out and "Open Flags" in out
    assert "Old Closed" not in out and "Secret Hidden" not in out


@pytest.mark.parametrize(
    "acc_id,state", [("acc-closed", "closed"), ("acc-hidden", "hidden")]
)
def test_explicit_id_of_closed_or_hidden_account_errors(acc_id, state):
    fake = FakeClient()
    out = _call(
        fake, amount=1, date="2026-10-08", merchant_name="M",
        account_id=acc_id, category="cat-1",
    )
    assert out.startswith("Error creating transaction") and f"is {state}" in out
    assert fake.calls == []


def test_explicit_id_of_open_account_with_false_flags_works():
    fake = FakeClient()
    _call(
        fake, amount=1, date="2026-10-08", merchant_name="M",
        account_id="acc-open-flags", category="cat-1",
    )
    assert fake.calls[0]["account_id"] == "acc-open-flags"
