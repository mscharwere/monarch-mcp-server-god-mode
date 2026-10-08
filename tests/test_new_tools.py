"""
Tests for PR M2: reviewed/owner params, is_pending filter, owner in compact
output, and the new read-only tools. Mock clients only; synthetic data.
"""

import inspect
import json
from unittest.mock import AsyncMock, patch

import pytest


def _server():
    from monarch_mcp_server import server

    return server


def _patched(server, client):
    return patch.object(server, "get_monarch_client", new=AsyncMock(return_value=client))


# --------------------------------------------------------------------------
# library signature guards
# --------------------------------------------------------------------------


def test_library_supports_reviewed_and_owner_user_id():
    from monarchmoney import MonarchMoney

    params = inspect.signature(MonarchMoney.update_transaction).parameters
    assert "reviewed" in params and "owner_user_id" in params
    assert "is_pending" in inspect.signature(MonarchMoney.get_transactions).parameters
    for name in (
        "get_household_members",
        "get_transaction_rules",
        "get_aggregate_snapshots",
        "get_credit_history",
        "find_duplicate_transactions",
    ):
        assert hasattr(MonarchMoney, name)


# --------------------------------------------------------------------------
# update_transaction / bulk
# --------------------------------------------------------------------------


def test_update_transaction_passes_reviewed_and_owner():
    server = _server()
    client = AsyncMock()
    client.update_transaction.return_value = {"ok": True}
    with _patched(server, client):
        server.update_transaction("t1", reviewed=True, owner_user_id="u-1")
    client.update_transaction.assert_awaited_once_with(
        transaction_id="t1", reviewed=True, owner_user_id="u-1"
    )


def test_update_transaction_empty_owner_means_joint_and_is_forwarded():
    server = _server()
    client = AsyncMock()
    client.update_transaction.return_value = {}
    with _patched(server, client):
        server.update_transaction("t1", owner_user_id="")
    assert client.update_transaction.await_args.kwargs["owner_user_id"] == ""


def test_update_transaction_omitted_params_not_sent():
    server = _server()
    client = AsyncMock()
    client.update_transaction.return_value = {}
    with _patched(server, client):
        server.update_transaction("t1", notes="n")
    kwargs = client.update_transaction.await_args.kwargs
    assert "reviewed" not in kwargs and "owner_user_id" not in kwargs


def test_reviewed_false_is_forwarded_not_dropped():
    server = _server()
    client = AsyncMock()
    client.update_transaction.return_value = {}
    with _patched(server, client):
        server.update_transaction("t1", reviewed=False)
    assert client.update_transaction.await_args.kwargs["reviewed"] is False


def test_bulk_update_passes_reviewed_and_owner():
    server = _server()
    client = AsyncMock()
    client.update_transaction.return_value = {"ok": True}
    updates = json.dumps(
        [
            {"transaction_id": "a", "reviewed": True, "owner_user_id": "u-1"},
            {"transaction_id": "b", "owner_user_id": ""},
            {"transaction_id": "c", "category_id": "cat"},
        ]
    )
    with _patched(server, client):
        out = json.loads(server.update_transactions_bulk(updates))
    assert all(r["success"] for r in out)
    calls = {
        c.kwargs["transaction_id"]: c.kwargs
        for c in client.update_transaction.await_args_list
    }
    assert calls["a"]["reviewed"] is True and calls["a"]["owner_user_id"] == "u-1"
    assert calls["b"]["owner_user_id"] == ""
    assert "reviewed" not in calls["c"] and "owner_user_id" not in calls["c"]


# --------------------------------------------------------------------------
# is_pending filter + owner in compact output
# --------------------------------------------------------------------------

TXNS = {
    "allTransactions": {
        "results": [
            {
                "id": "t1",
                "date": "2026-01-02",
                "amount": -5.0,
                "pending": True,
                "merchant": {"name": "Cafe"},
                "category": {"name": "Coffee"},
                "ownedByUser": {"id": "u-1", "name": "Pat"},
            },
            {
                "id": "t2",
                "date": "2026-01-03",
                "amount": -9.0,
                "pending": False,
                "merchant": {"name": "Shop"},
                "category": None,
                "ownedByUser": None,
            },
        ]
    }
}


@pytest.mark.parametrize("flag", [True, False])
def test_get_transactions_is_pending_passthrough(flag):
    server = _server()
    client = AsyncMock()
    client.get_transactions.return_value = TXNS
    with _patched(server, client):
        server.get_transactions(is_pending=flag)
    assert client.get_transactions.await_args.kwargs["is_pending"] is flag


def test_get_transactions_is_pending_omitted_not_sent():
    server = _server()
    client = AsyncMock()
    client.get_transactions.return_value = TXNS
    with _patched(server, client):
        server.get_transactions()
    assert "is_pending" not in client.get_transactions.await_args.kwargs


def test_search_transactions_is_pending_passthrough():
    server = _server()
    client = AsyncMock()
    client.get_transactions.return_value = TXNS
    with _patched(server, client):
        server.search_transactions(query="x", is_pending=True)
    assert client.get_transactions.await_args.kwargs["is_pending"] is True


def test_compact_output_has_owner_and_pending():
    server = _server()
    client = AsyncMock()
    client.get_transactions.return_value = TXNS
    with _patched(server, client):
        compact = json.loads(server.get_transactions(verbose=False))
        searched = json.loads(server.search_transactions(query="x", verbose=False))
    assert compact[0]["owner"] == "Pat" and compact[0]["is_pending"] is True
    assert compact[1]["owner"] is None and compact[1]["is_pending"] is False
    assert searched["transactions"][0]["owner"] == "Pat"


def test_verbose_output_has_owner():
    server = _server()
    client = AsyncMock()
    client.get_transactions.return_value = TXNS
    with _patched(server, client):
        verbose = json.loads(server.get_transactions(verbose=True))
    assert verbose[0]["owner"] == "Pat"


# --------------------------------------------------------------------------
# get_household_members
# --------------------------------------------------------------------------


def test_get_household_members_compact():
    server = _server()
    client = AsyncMock()
    client.get_household_members.return_value = {
        "myHousehold": {
            "users": [
                {"id": "u-1", "name": "Pat Doe", "displayName": "Pat", "householdRole": "OWNER"},
                {"id": "u-2", "name": "Sam Doe", "displayName": "Sam", "householdRole": "MEMBER"},
            ]
        }
    }
    with _patched(server, client):
        out = json.loads(server.get_household_members())
    assert out == [
        {"id": "u-1", "name": "Pat Doe", "display_name": "Pat", "role": "OWNER"},
        {"id": "u-2", "name": "Sam Doe", "display_name": "Sam", "role": "MEMBER"},
    ]


def test_get_household_members_empty():
    server = _server()
    client = AsyncMock()
    client.get_household_members.return_value = {"myHousehold": None}
    with _patched(server, client):
        assert json.loads(server.get_household_members()) == []


# --------------------------------------------------------------------------
# get_transaction_rules
# --------------------------------------------------------------------------


def _rule(order, **extra):
    base = {
        "order": order,
        "id": f"r{order}",
        "merchantCriteriaUseOriginalStatement": False,
        "merchantCriteria": None,
        "originalStatementCriteria": None,
        "merchantNameCriteria": None,
        "amountCriteria": None,
        "categoryIds": None,
        "accountIds": None,
        "categories": [],
        "accounts": [],
        "criteriaOwnerIsJoint": False,
        "criteriaOwnerUserIds": None,
        "criteriaOwnerUsers": None,
        "criteriaBusinessEntities": None,
        "setMerchantAction": None,
        "setCategoryAction": None,
        "addTagsAction": [],
        "needsReviewByUserAction": None,
        "reviewStatusAction": None,
        "unassignNeedsReviewByUserAction": False,
        "sendNotificationAction": False,
        "setHideFromReportsAction": False,
        "actionSetOwnerIsJoint": False,
        "actionSetOwner": None,
        "splitTransactionsAction": None,
        "recentApplicationCount": 0,
        "lastAppliedAt": None,
    }
    base.update(extra)
    return base


def test_get_transaction_rules_sorted_and_compact():
    server = _server()
    client = AsyncMock()
    client.get_transaction_rules.return_value = {
        "transactionRules": [
            _rule(
                2,
                merchantCriteria=[{"operator": "contains", "value": "acme"}],
                amountCriteria={
                    "operator": "gt",
                    "isExpense": True,
                    "value": 50.0,
                    "valueRange": None,
                },
                setCategoryAction={"id": "c1", "name": "Shopping"},
                addTagsAction=[{"id": "tg", "name": "Review"}],
                recentApplicationCount=3,
                lastAppliedAt="2026-01-01T00:00:00",
            ),
            _rule(0, setHideFromReportsAction=True, actionSetOwnerIsJoint=True),
            _rule(
                1,
                merchantCriteriaUseOriginalStatement=True,
                merchantCriteria=[{"operator": "eq", "value": "XYZ"}],
                setMerchantAction={"id": "m", "name": "Xyz Inc"},
            ),
        ]
    }
    with _patched(server, client):
        out = json.loads(server.get_transaction_rules())
    assert out["count"] == 3
    assert [r["priority"] for r in out["rules"]] == [0, 1, 2]
    r0, r1, r2 = out["rules"]
    assert r0["then"] == {"hide_from_reports": True, "set_owner": "joint"}
    assert r0["if"] == {}
    assert r1["if"] == {"merchant_original_statement": ["eq XYZ"]}
    assert r1["then"] == {"set_merchant": "Xyz Inc"}
    assert r2["if"] == {"merchant": ["contains acme"], "amount": "expense gt 50.0"}
    assert r2["then"] == {"set_category": "Shopping", "add_tags": ["Review"]}
    assert r2["applied_recently"] == 3


# --------------------------------------------------------------------------
# get_net_worth_history
# --------------------------------------------------------------------------

SNAPS = {
    "aggregateSnapshots": [
        {"date": "2026-01-01", "balance": 100.0},
        {"date": "2026-01-31", "balance": 110.0},
        {"date": "2026-02-15", "balance": 120.0},
        {"date": "2026-02-28", "balance": 90.0},
        {"date": "2026-03-31", "balance": 99.0},
        {"date": "2026-03-10", "balance": None},
    ]
}


def test_net_worth_monthly_trend_has_deltas():
    server = _server()
    client = AsyncMock()
    client.get_aggregate_snapshots.return_value = SNAPS
    with _patched(server, client):
        out = json.loads(server.get_net_worth_history(start_date="2026-01-01"))
    assert [p["date"] for p in out["points"]] == ["2026-01-31", "2026-02-28", "2026-03-31"]
    assert [p["net_worth"] for p in out["points"]] == [110.0, 90.0, 99.0]
    assert "change" not in out["points"][0]
    assert out["points"][1]["change"] == -20.0
    assert out["points"][1]["change_pct"] == pytest.approx(-18.18)
    assert out["points"][2]["change"] == 9.0
    s = out["summary"]
    assert (s["start_net_worth"], s["end_net_worth"], s["change"]) == (100.0, 99.0, -1.0)
    assert s["high"] == 120.0 and s["low"] == 90.0 and s["points"] == 3
    assert client.get_aggregate_snapshots.await_args.kwargs["start_date"] == "2026-01-01"


def test_net_worth_daily_keeps_all_valid_points():
    server = _server()
    client = AsyncMock()
    client.get_aggregate_snapshots.return_value = SNAPS
    with _patched(server, client):
        out = json.loads(server.get_net_worth_history(interval="daily"))
    assert len(out["points"]) == 5  # None balance dropped


def test_net_worth_bad_interval_and_empty():
    server = _server()
    assert "interval must be one of" in server.get_net_worth_history(interval="yearly")
    client = AsyncMock()
    client.get_aggregate_snapshots.return_value = {"aggregateSnapshots": []}
    with _patched(server, client):
        out = json.loads(server.get_net_worth_history())
    assert out == {"summary": None, "points": []}


# --------------------------------------------------------------------------
# get_credit_history
# --------------------------------------------------------------------------


def test_credit_history_deltas_per_member():
    server = _server()
    client = AsyncMock()
    client.get_credit_history.return_value = {
        "myHousehold": {"users": [{"id": "u-1", "displayName": "Pat", "name": "Pat Doe"}]},
        "spinwheelUser": {
            "creditScoreTrackingStatus": "enabled",
            "spinwheelUserId": "secret-id",
        },
        "creditScoreSnapshots": [
            {"reportedDate": "2026-03-01", "score": 720, "user": {"id": "u-1"}},
            {"reportedDate": "2026-01-01", "score": 700, "user": {"id": "u-1"}},
            {"reportedDate": "2026-02-01", "score": 690, "user": {"id": "u-1"}},
        ],
    }
    with _patched(server, client):
        raw = server.get_credit_history()
    out = json.loads(raw)
    assert "secret-id" not in raw
    m = out["members"][0]
    assert out["tracking_status"] == "enabled" and m["user"] == "Pat"
    assert [h["score"] for h in m["history"]] == [700, 690, 720]
    assert [h.get("change") for h in m["history"]] == [None, -10, 30]
    assert m["latest_score"] == 720
    assert m["change_vs_previous"] == 30
    assert m["change_over_period"] == 20


# --------------------------------------------------------------------------
# find_duplicate_transactions
# --------------------------------------------------------------------------


def test_find_duplicates_is_report_only():
    server = _server()

    class Client:
        """No delete_* methods exist, so any attempt to delete would raise."""

        def __init__(self):
            self.kwargs = None

        async def find_duplicate_transactions(self, **kwargs):
            self.kwargs = kwargs
            return [
                {
                    "date": "2026-01-01",
                    "amount": -10.0,
                    "plaidName": "ACME 123",
                    "account_id": "a1",
                    "account_name": "Checking",
                    "transactions": [{"id": "t-old"}, {"id": "t-new"}, {"id": "t-newer"}],
                }
            ]

    client = Client()
    with _patched(server, client):
        out = json.loads(
            server.find_duplicate_transactions(start_date="2026-01-01", account_id="a1")
        )
    assert out["duplicate_groups"] == 1 and out["extra_copies"] == 2
    g = out["groups"][0]
    assert g["transaction_ids"] == ["t-old", "t-new", "t-newer"] and g["count"] == 3
    assert client.kwargs["max_pages"] == 10
    assert client.kwargs["account_ids"] == ["a1"]
    assert client.kwargs["start_date"] == "2026-01-01" and client.kwargs["end_date"]


def test_find_duplicates_limit_and_validation():
    server = _server()

    def group(i):
        return {
            "date": "d",
            "amount": 1,
            "plaidName": "p",
            "account_name": "a",
            "transactions": [{"id": f"{i}a"}, {"id": f"{i}b"}],
        }

    client = AsyncMock()
    client.find_duplicate_transactions.return_value = [group(i) for i in range(5)]
    with _patched(server, client):
        out = json.loads(server.find_duplicate_transactions(limit=2))
    assert out["duplicate_groups"] == 5 and len(out["groups"]) == 2
    assert "truncated" in out
    assert "max_pages" in server.find_duplicate_transactions(max_pages=0)


# --------------------------------------------------------------------------
# annotations
# --------------------------------------------------------------------------

NEW_READ_TOOLS = [
    "get_household_members",
    "get_transaction_rules",
    "get_net_worth_history",
    "get_credit_history",
    "find_duplicate_transactions",
]


async def test_new_tools_registered_with_read_only_annotations():
    server = _server()
    tools = {t.name: t for t in await server.mcp.list_tools()}
    for name in NEW_READ_TOOLS:
        assert name in tools, name
        assert tools[name].annotations is not None
        assert tools[name].annotations.readOnlyHint is True, name
    # no delete/reset/upload tools were added
    assert not [n for n in tools if n.startswith(("delete_", "reset_", "upload_"))]
