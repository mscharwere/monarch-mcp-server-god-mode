"""
Regression test for get_budgets() defaulting to a huge, unfiltered response.

History
-------
`monarch_mcp_server.server.get_budgets` used to call the underlying client
with no arguments at all:

    await client.get_budgets()

`monarchmoney.MonarchMoney.get_budgets()` defaults `start_date`/`end_date` to
"last month" through "next month" when neither is given, and returns EVERY
budgeted category for EACH of those months. In production this was 258 rows
(86 categories x 3 months) / ~50KB of JSON -- large enough to exceed the
tool-output size limit and force the caller to a file-based fallback instead
of a normal response, confirmed live 2026-09-18.

The fix: the tool now resolves an explicit start_date/end_date (defaulting to
the CURRENT calendar month only, not the client library's own wider default)
and passes them through, plus an optional client-side `category` substring
filter to narrow further. This test pins that behavior so a future edit
can't silently widen the default window again.
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest


class FakeMonarchClient:
    """Stand-in for `monarchmoney.MonarchMoney` that records call args."""

    def __init__(self, response):
        self.calls = []
        self._response = response

    async def get_budgets(self, start_date=None, end_date=None, **kwargs):
        self.calls.append({"start_date": start_date, "end_date": end_date})
        return self._response


REAL_SHAPE_RESPONSE = {
    "budgetData": {
        "monthlyAmountsByCategory": [
            {
                "category": {"id": "cat-pets"},
                "monthlyAmounts": [
                    {
                        "month": "2026-09-01",
                        "plannedCashFlowAmount": 55.0,
                        "actualAmount": 839.09,
                        "remainingAmount": -784.09,
                    }
                ],
            },
            {
                "category": {"id": "cat-groceries"},
                "monthlyAmounts": [
                    {
                        "month": "2026-09-01",
                        "plannedCashFlowAmount": 1250.0,
                        "actualAmount": 612.50,
                        "remainingAmount": 637.50,
                    }
                ],
            },
        ]
    },
    "categoryGroups": [
        {"id": "grp-1", "name": "g1", "categories": [{"id": "cat-pets", "name": "Pets"}]},
        {"id": "grp-2", "name": "g2", "categories": [{"id": "cat-groceries", "name": "Groceries"}]},
    ],
}


def _import_server():
    # Imported lazily so a missing MCP_*/auth env at collection time can't
    # block test discovery, matching this repo's established convention.
    from monarch_mcp_server import server

    return server


@pytest.fixture
def fake_client():
    return FakeMonarchClient(REAL_SHAPE_RESPONSE)


def test_get_budgets_defaults_to_current_month_only(fake_client):
    """
    With no arguments, the tool must request the CURRENT month only --
    not the underlying client's own last-month-to-next-month default.
    """
    server = _import_server()

    with patch.object(
        server, "get_monarch_client", new=AsyncMock(return_value=fake_client)
    ):
        server.get_budgets()

    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]

    today = date.today()
    expected_start = today.replace(day=1).isoformat()
    expected_end_month = today.month + 1 if today.month < 12 else 1
    expected_end_year = today.year if today.month < 12 else today.year + 1
    expected_end = date(expected_end_year, expected_end_month, 1).isoformat()

    assert call["start_date"] == expected_start, (
        "get_budgets() must default start_date to the first of the CURRENT "
        "month, not the client library's own wider default."
    )
    assert call["end_date"] == expected_end, (
        "get_budgets() must default end_date to the first of NEXT month "
        "(i.e. current month only), not a multi-month window."
    )


def test_get_budgets_explicit_dates_pass_through_unmodified(fake_client):
    """An explicitly-requested wider window must still work, unmodified."""
    server = _import_server()

    with patch.object(
        server, "get_monarch_client", new=AsyncMock(return_value=fake_client)
    ):
        server.get_budgets(start_date="2026-01-01", end_date="2026-12-01")

    assert len(fake_client.calls) == 1
    assert fake_client.calls[0] == {"start_date": "2026-01-01", "end_date": "2026-12-01"}


def test_get_budgets_category_filter_narrows_response(fake_client):
    """The optional `category` param is a case-insensitive substring filter."""
    server = _import_server()
    import json

    with patch.object(
        server, "get_monarch_client", new=AsyncMock(return_value=fake_client)
    ):
        result = json.loads(server.get_budgets(category="pets"))

    assert len(result) == 1
    assert result[0]["category"] == "Pets"


def test_get_budgets_no_category_filter_returns_everything_in_range(fake_client):
    server = _import_server()
    import json

    with patch.object(
        server, "get_monarch_client", new=AsyncMock(return_value=fake_client)
    ):
        result = json.loads(server.get_budgets())

    assert len(result) == 2
