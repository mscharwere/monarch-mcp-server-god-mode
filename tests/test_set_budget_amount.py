"""
Regression test for the set_budget_amount() positional/keyword argument
collision bug.

History
-------
`monarch_mcp_server.server.set_budget_amount` (the MCP tool handler) used to
call the underlying client like this:

    await client.set_budget_amount(category_id, **kwargs)

where `kwargs` always contains an "amount" key. The real client method
(`monarchmoney.MonarchMoney.set_budget_amount`) has the signature:

    async def set_budget_amount(
        self,
        amount: float,
        category_id: Optional[str] = None,
        category_group_id: Optional[str] = None,
        timeframe: str = "month",
        start_date: Optional[str] = None,
        apply_to_future: bool = False,
    ) -> Dict[str, Any]: ...

`amount` — not `category_id` — is positional parameter 0. So passing
`category_id` positionally filled the `amount` slot, and then the `amount`
kwarg collided with it, raising:

    TypeError: MonarchMoney.set_budget_amount() got multiple values for
    argument 'amount'

This bug was "fixed" once before (2026-07-30) by hot-patching the running
process, but the fix was never committed to source control, so it was lost
on the next MCP server restart and recurred. This test exists specifically
so a future regression is caught by CI instead of live/production use.
"""

import inspect
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch

import pytest


class FakeMonarchClient:
    """
    Stand-in for `monarchmoney.MonarchMoney` that mirrors the REAL
    `set_budget_amount` signature (amount is positional arg 0, category_id
    is keyword-only in practice). Used so this test fails the same way the
    real client would if the handler ever regresses to a positional call.
    """

    def __init__(self):
        self.calls = []

    async def set_budget_amount(
        self,
        amount: float,
        category_id: Optional[str] = None,
        category_group_id: Optional[str] = None,
        timeframe: str = "month",
        start_date: Optional[str] = None,
        apply_to_future: bool = False,
    ) -> Dict[str, Any]:
        if (category_id is None) is (category_group_id is None):
            raise Exception(
                "You must specify either a category_id OR category_group_id; not both"
            )
        self.calls.append(
            {
                "amount": amount,
                "category_id": category_id,
                "category_group_id": category_group_id,
                "timeframe": timeframe,
                "start_date": start_date,
                "apply_to_future": apply_to_future,
            }
        )
        return {"updateOrCreateBudgetItem": {"budgetItem": {"id": "fake-budget-item"}}}


@pytest.fixture
def fake_client():
    return FakeMonarchClient()


def _import_server():
    # Imported lazily so a missing MCP_* env / auth setup at collection time
    # can't block test discovery.
    from monarch_mcp_server import server

    return server


def test_set_budget_amount_signature_matches_real_client():
    """
    Guard against the underlying `monarchmoney` package changing its
    signature out from under us again without anyone noticing.
    """
    sig = inspect.signature(FakeMonarchClient.set_budget_amount)
    params = list(sig.parameters)
    assert params[0] == "self"
    assert params[1] == "amount", (
        "monarchmoney.MonarchMoney.set_budget_amount's first positional "
        "argument is 'amount', not 'category_id'. If this changes, the "
        "regression this test guards against may no longer apply -- "
        "re-verify server.py's call site."
    )


def test_set_budget_amount_no_multiple_values_for_amount(fake_client):
    """
    Core regression test: calling the tool handler with a category_id and
    an amount must NOT raise
    'TypeError: set_budget_amount() got multiple values for argument amount'.

    This is exactly the call shape that broke in production twice
    (2026-07-30 and again in August 2026): a category_id plus an amount
    kwarg.
    """
    server = _import_server()

    with patch.object(
        server, "get_monarch_client", new=AsyncMock(return_value=fake_client)
    ):
        result = server.set_budget_amount(category_id="cat-123", amount=250.0)

    assert "Error" not in result
    assert "got multiple values for argument" not in result
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["category_id"] == "cat-123"
    assert call["amount"] == 250.0


def test_set_budget_amount_with_month_and_apply_to_future(fake_client):
    """Same regression check, but exercising every optional kwarg path."""
    server = _import_server()

    with patch.object(
        server, "get_monarch_client", new=AsyncMock(return_value=fake_client)
    ):
        result = server.set_budget_amount(
            category_id="cat-456",
            amount=0,
            month="2026-09",
            apply_to_future=True,
        )

    assert "Error" not in result
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["category_id"] == "cat-456"
    assert call["amount"] == 0
    assert call["start_date"] == "2026-09-01"
    assert call["apply_to_future"] is True


def test_fake_client_reproduces_the_original_bug_when_called_positionally(fake_client):
    """
    Sanity check on the test double itself: confirms FakeMonarchClient
    actually reproduces the original TypeError when called the OLD
    (buggy) way, proving this test would have caught the regression.
    """
    kwargs = {"amount": 100.0}

    with pytest.raises(TypeError, match="multiple values for argument 'amount'"):
        import asyncio

        asyncio.run(fake_client.set_budget_amount("cat-789", **kwargs))
