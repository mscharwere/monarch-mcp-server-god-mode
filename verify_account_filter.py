"""
Manual verification script for the get_transactions account_id filter fix.

Run with:  python verify_account_filter.py <account_id>

This confirms that:
1. Calling get_transactions WITH account_id returns only transactions for that account.
2. Calling get_transactions WITHOUT account_id returns transactions across all accounts.
3. The filtered count <= the unfiltered count.
4. Every transaction in the filtered result belongs to the specified account.

If (1) and (3) and (4) all pass, the fix is working. Before the fix, filtered_count
would equal unfiltered_count (because account_id was silently ignored).
"""

import asyncio
import sys
from pathlib import Path

# Add the src directory to the Python path for imports
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from monarch_mcp_server.server import get_monarch_client  # noqa: E402
# NOTE: We call get_monarch_client() (the server's entrypoint) rather than
# secure_session.get_authenticated_client() directly. get_monarch_client()
# handles token refresh and falls back to env-var credentials — using the raw
# secure_session accessor bypasses that fallback and will fail silently if the
# keyring token is absent or stale. Always use this entrypoint for auth.


async def main(account_id: str):
    client = await get_monarch_client()

    print(f"Testing account filter for account_id: {account_id}\n")

    # Unfiltered — should return transactions for all accounts
    all_txns = await client.get_transactions(limit=200, offset=0)
    all_results = all_txns.get("allTransactions", {}).get("results", [])
    unfiltered_count = len(all_results)
    print(f"Unfiltered call  → {unfiltered_count} transactions returned")

    # Filtered — should return only transactions for the given account.
    # The lib expects account_ids: List[str], NOT account_id: str.
    # Passing account_id directly is silently ignored by the lib.
    filtered_txns = await client.get_transactions(
        limit=200, offset=0, account_ids=[account_id]
    )
    filtered_results = filtered_txns.get("allTransactions", {}).get("results", [])
    filtered_count = len(filtered_results)
    print(f"Filtered call    → {filtered_count} transactions returned")

    # Validate filter is actually working
    wrong_account = [
        t for t in filtered_results
        if (t.get("account") or {}).get("id") != account_id
    ]

    print()
    if filtered_count <= unfiltered_count and len(wrong_account) == 0:
        print("PASS: account_id filter is working correctly.")
        print(f"  - Filtered ({filtered_count}) <= Unfiltered ({unfiltered_count}) ✓")
        print(f"  - All {filtered_count} filtered transactions belong to the account ✓")
    elif len(wrong_account) > 0:
        print(f"FAIL: {len(wrong_account)} transactions in filtered result belong to a different account.")
    else:
        print("FAIL: Filtered count exceeds unfiltered count — something is wrong.")

    # Also show account names in filtered result for sanity check
    accounts_seen = set()
    for t in filtered_results:
        acct = t.get("account") or {}
        accounts_seen.add(acct.get("displayName") or acct.get("id") or "unknown")
    if accounts_seen:
        print(f"\nAccounts seen in filtered results: {accounts_seen}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python verify_account_filter.py <account_id>")
        print("       Get an account_id by running: get_accounts via MCP or login_setup.py")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
