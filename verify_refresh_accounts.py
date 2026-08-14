"""
Mocked unit-style verification for the refresh_accounts optional-account_ids fix.

Confirms:
1. Calling refresh_accounts() with NO arguments fetches all account IDs via
   get_accounts() and passes that full list to request_accounts_refresh().
2. Calling refresh_accounts(account_ids=[...]) skips the get_accounts() call
   and passes the given IDs straight through (targeted refresh still works).
3. An empty-account edge case (no linked accounts) raises/returns an error
   instead of silently calling the lib with an empty list.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
import json

src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from monarch_mcp_server import server  # noqa: E402


async def run():
    # --- Case 1: no account_ids -> should fetch all and refresh all ---
    mock_client = AsyncMock()
    mock_client.get_accounts.return_value = {
        "accounts": [{"id": "acct_1"}, {"id": "acct_2"}, {"id": None}]
    }
    mock_client.request_accounts_refresh.return_value = True

    with patch.object(server, "get_monarch_client", AsyncMock(return_value=mock_client)):
        result = server.refresh_accounts()
        mock_client.get_accounts.assert_awaited_once()
        mock_client.request_accounts_refresh.assert_awaited_once_with(["acct_1", "acct_2"])
        assert json.loads(result) is True
        print("PASS: no-arg call fetches all accounts and refreshes them ->", result)

    # --- Case 2: explicit account_ids -> should skip get_accounts ---
    mock_client2 = AsyncMock()
    mock_client2.request_accounts_refresh.return_value = True

    with patch.object(server, "get_monarch_client", AsyncMock(return_value=mock_client2)):
        result2 = server.refresh_accounts(account_ids=["acct_9"])
        mock_client2.get_accounts.assert_not_awaited()
        mock_client2.request_accounts_refresh.assert_awaited_once_with(["acct_9"])
        print("PASS: explicit account_ids skips get_accounts and targets only those ->", result2)

    # --- Case 3: no linked accounts at all -> should surface an error, not call lib with [] ---
    mock_client3 = AsyncMock()
    mock_client3.get_accounts.return_value = {"accounts": []}
    with patch.object(server, "get_monarch_client", AsyncMock(return_value=mock_client3)):
        result3 = server.refresh_accounts()
        mock_client3.request_accounts_refresh.assert_not_awaited()
        assert result3.startswith("Error"), result3
        print("PASS: empty account list does not call lib with [] ->", result3)


if __name__ == "__main__":
    asyncio.run(run())
    print("\nALL CHECKS PASSED")
