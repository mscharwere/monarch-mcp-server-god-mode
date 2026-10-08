"""
Tests for create_transaction_category.

The real client signature (monarchmoneycommunity >= 1.x) is:

    create_transaction_category(self, group_id, transaction_category_name,
                                rollover_start_month=..., icon=..., ...)

`group_id` is REQUIRED and the name kwarg is `transaction_category_name`.
The tool used to pass `name=` with no group, which failed on every call.
All clients here are mocks -- nothing touches a real Monarch account.
"""

import inspect
import json
from unittest.mock import AsyncMock, patch

import pytest

GROUPS = {
    "categoryGroups": [
        {"id": "grp-1", "name": "Food & Dining", "type": "expense"},
        {"id": "grp-2", "name": "Auto & Transport", "type": "expense"},
        {"id": "grp-3", "name": "Income", "type": "income"},
    ]
}


class FakeClient:
    """Mirrors the REAL create_transaction_category signature."""

    def __init__(self, groups=GROUPS):
        self.calls = []
        self._groups = groups

    async def get_transaction_category_groups(self):
        return self._groups

    async def create_transaction_category(
        self,
        group_id,
        transaction_category_name,
        rollover_start_month=None,
        icon="?",
        rollover_enabled=False,
        rollover_type="monthly",
    ):
        self.calls.append(
            {"group_id": group_id, "name": transaction_category_name, "icon": icon}
        )
        return {"createCategory": {"category": {"id": "new-cat"}, "errors": None}}


def _server():
    from monarch_mcp_server import server

    return server


def _call(fake, **kwargs):
    server = _server()
    with patch.object(server, "get_monarch_client", new=AsyncMock(return_value=fake)):
        return server.create_transaction_category(**kwargs)


def test_real_library_signature_still_matches():
    """Guard: fail loudly if the library changes the signature again."""
    from monarchmoney import MonarchMoney

    params = list(inspect.signature(MonarchMoney.create_transaction_category).parameters)
    assert params[1:3] == ["group_id", "transaction_category_name"]


def test_group_by_name_resolves_to_id():
    fake = FakeClient()
    result = _call(fake, name="Coffee", group="food & dining")
    assert "Error" not in result
    assert fake.calls == [{"group_id": "grp-1", "name": "Coffee", "icon": "?"}]
    assert json.loads(result)["createCategory"]["category"]["id"] == "new-cat"


def test_group_by_id():
    fake = FakeClient()
    _call(fake, name="Tolls", group="grp-2")
    assert fake.calls[0]["group_id"] == "grp-2"


def test_legacy_group_id_param_still_works():
    fake = FakeClient()
    _call(fake, name="Tolls", group_id="grp-2")
    assert fake.calls[0]["group_id"] == "grp-2"


def test_icon_passed_through():
    fake = FakeClient()
    _call(fake, name="Coffee", group="grp-1", icon="\u2615")
    assert fake.calls[0]["icon"] == "\u2615"


def test_unknown_group_lists_valid_groups_and_does_not_create():
    fake = FakeClient()
    result = _call(fake, name="Coffee", group="Nope")
    assert result.startswith("Error creating transaction category")
    assert "not found" in result
    for g in GROUPS["categoryGroups"]:
        assert g["name"] in result and g["id"] in result
    assert fake.calls == []


def test_missing_group_is_clear_error_without_api_call():
    fake = FakeClient()
    result = _call(fake, name="Coffee")
    assert "group is required" in result
    assert fake.calls == []


def test_empty_name_rejected():
    fake = FakeClient()
    assert "name cannot be empty" in _call(fake, name="  ", group="grp-1")
    assert fake.calls == []


def test_ambiguous_group_name_rejected():
    groups = {
        "categoryGroups": [
            {"id": "a", "name": "Dup"},
            {"id": "b", "name": "dup"},
        ]
    }
    fake = FakeClient(groups)
    result = _call(fake, name="X", group="DUP")
    assert "ambiguous" in result
    assert fake.calls == []


def test_is_pending_reads_current_field_name():
    """Library returns `pending` (not `isPending`); verbose output must follow."""
    server = _server()
    fake = AsyncMock()
    fake.get_transactions.return_value = {
        "allTransactions": {
            "results": [
                {"id": "t1", "date": "2026-01-01", "amount": -1.0, "pending": True,
                 "account": {"displayName": "A"}},
            ]
        }
    }
    with patch.object(server, "get_monarch_client", new=AsyncMock(return_value=fake)):
        out = json.loads(server.get_transactions(limit=1))
    assert out[0]["is_pending"] is True
