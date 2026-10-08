"""Compatibility tests for read tools against the real library signatures (mock clients only)."""

import json
from unittest.mock import AsyncMock, patch


def _server():
    from monarch_mcp_server import server

    return server


def test_get_account_history_trims_client_side_and_calls_lib_with_id_only():
    server = _server()
    fake = AsyncMock()
    fake.get_account_history.return_value = [
        {"date": "2026-01-01", "signedBalance": 1},
        {"date": "2026-01-15", "signedBalance": 2},
        {"date": "2026-02-01", "signedBalance": 3},
    ]
    with patch.object(server, "get_monarch_client", new=AsyncMock(return_value=fake)):
        out = json.loads(
            server.get_account_history("acc", start_date="2026-01-10", end_date="2026-01-31")
        )
    fake.get_account_history.assert_awaited_once_with("acc")
    assert [r["date"] for r in out] == ["2026-01-15"]


def test_get_account_history_no_dates_returns_all():
    server = _server()
    fake = AsyncMock()
    fake.get_account_history.return_value = [{"date": "2026-01-01"}, {"date": "2026-01-02"}]
    with patch.object(server, "get_monarch_client", new=AsyncMock(return_value=fake)):
        assert len(json.loads(server.get_account_history("acc"))) == 2


def test_search_transactions_single_date_bound_is_completed():
    """Library raises if only one of start/end is given; the tool fills the other."""
    server = _server()
    fake = AsyncMock()
    fake.get_transactions.return_value = {"allTransactions": {"results": []}}
    with patch.object(server, "get_monarch_client", new=AsyncMock(return_value=fake)):
        server.search_transactions(query="x", start_date="2026-01-01")
    kwargs = fake.get_transactions.await_args.kwargs
    assert kwargs["start_date"] == "2026-01-01"
    assert kwargs["end_date"]  # filled


def test_get_transactions_end_only_is_completed():
    server = _server()
    fake = AsyncMock()
    fake.get_transactions.return_value = {"allTransactions": {"results": []}}
    with patch.object(server, "get_monarch_client", new=AsyncMock(return_value=fake)):
        server.get_transactions(end_date="2026-01-31")
    kwargs = fake.get_transactions.await_args.kwargs
    assert kwargs["end_date"] == "2026-01-31" and kwargs["start_date"]
