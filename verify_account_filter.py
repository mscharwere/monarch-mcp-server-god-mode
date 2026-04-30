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
from monarch_mcp_server.secure_session import secure_session
from monarchmoney import MonarchMoney


async def main(account_id: str):
    client = secure_session.get_authenticated_client()
    if client is None:
        print("ERROR: No authenticated session found. Run login_setup.py first.")
        sys.exit(1)

    print(f"Testing account filter for account_id: {account_id}\n")

    # Unfiltered — should return transactions for all accounts
    all_txns = await client.get_transactions(limit=200, offset=0)
    all_results = all_txns.get("allTransactions", {}).get("results", [])
    unfiltered_count = len(all_results)
    print(f"Unfiltered call  → {unfiltered_count} transactions returned")

    # Filtered — should return only transactions for the given account
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
