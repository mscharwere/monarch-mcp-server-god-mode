"""Monarch Money MCP Server - Main server implementation."""

import os
import logging
import asyncio
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, date, timedelta
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from mcp.server.auth.provider import AccessTokenT
from mcp.server.fastmcp import FastMCP
import mcp.types as types
from mcp.types import ToolAnnotations
from monarchmoney import MonarchMoney, RequireMFAException
from pydantic import BaseModel, Field
from monarch_mcp_server.secure_session import secure_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("Monarch Money MCP Server")


def run_async(coro):
    """Run async function in a new thread with its own event loop."""

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with ThreadPoolExecutor() as executor:
        future = executor.submit(_run)
        return future.result()


class MonarchConfig(BaseModel):
    """Configuration for Monarch Money connection."""

    email: Optional[str] = Field(default=None, description="Monarch Money email")
    password: Optional[str] = Field(default=None, description="Monarch Money password")
    session_file: str = Field(
        default="monarch_session.json", description="Session file path"
    )


async def get_monarch_client() -> MonarchMoney:
    """Get or create MonarchMoney client instance using secure session storage."""
    # Try to get authenticated client from secure session
    client = secure_session.get_authenticated_client()

    if client is not None:
        logger.info("✅ Using authenticated client from secure keyring storage")
        return client

    # If no secure session, try environment credentials
    email = os.getenv("MONARCH_EMAIL")
    password = os.getenv("MONARCH_PASSWORD")

    if email and password:
        try:
            client = MonarchMoney()
            await client.login(email, password)
            logger.info(
                "Successfully logged into Monarch Money with environment credentials"
            )

            # Save the session securely
            secure_session.save_authenticated_session(client)

            return client
        except Exception as e:
            logger.error(f"Failed to login to Monarch Money: {e}")
            raise

    raise RuntimeError("🔐 Authentication needed! Run: python login_setup.py")


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def setup_authentication() -> str:
    """Get instructions for setting up secure authentication with Monarch Money."""
    return """🔐 Monarch Money - One-Time Setup

1️⃣ Open Terminal and run:
   python login_setup.py

2️⃣ Enter your Monarch Money credentials when prompted
   • Email and password
   • 2FA code if you have MFA enabled

3️⃣ Session will be saved automatically and last for weeks

4️⃣ Start using Monarch tools in Claude Desktop:
   • get_accounts - View all accounts
   • get_transactions - Recent transactions
   • get_budgets - Budget information

✅ Session persists across Claude restarts
✅ No need to re-authenticate frequently
✅ All credentials stay secure in terminal"""


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def check_auth_status() -> str:
    """Check if already authenticated with Monarch Money."""
    try:
        # Check if we have a token in the keyring
        token = secure_session.load_token()
        if token:
            status = "✅ Authentication token found in secure keyring storage\n"
        else:
            status = "❌ No authentication token found in keyring\n"

        email = os.getenv("MONARCH_EMAIL")
        if email:
            status += f"📧 Environment email: {email}\n"

        status += (
            "\n💡 Try get_accounts to test connection or run login_setup.py if needed."
        )

        return status
    except Exception as e:
        return f"Error checking auth status: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def debug_session_loading() -> str:
    """Debug keyring session loading issues."""
    try:
        # Check keyring access
        token = secure_session.load_token()
        if token:
            return f"✅ Token found in keyring (length: {len(token)})"
        else:
            return "❌ No token found in keyring. Run login_setup.py to authenticate."
    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        return f"❌ Keyring access failed:\nError: {str(e)}\nType: {type(e)}\nTraceback:\n{error_details}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_accounts() -> str:
    """Get all financial accounts from Monarch Money."""
    try:

        async def _get_accounts():
            client = await get_monarch_client()
            return await client.get_accounts()

        accounts = run_async(_get_accounts())

        # Format accounts for display
        account_list = []
        for account in accounts.get("accounts", []):
            account_info = {
                "id": account.get("id"),
                "name": account.get("displayName") or account.get("name"),
                "type": (account.get("type") or {}).get("name"),
                "balance": account.get("currentBalance"),
                "institution": (account.get("institution") or {}).get("name"),
                "is_active": account.get("isActive")
                if "isActive" in account
                else not account.get("deactivatedAt"),
            }
            account_list.append(account_info)

        return json.dumps(account_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get accounts: {e}")
        return f"Error getting accounts: {str(e)}"


LONE_END_DATE_WINDOW_DAYS = 365


def _complete_date_range(
    start_date: Optional[str], end_date: Optional[str]
) -> tuple:
    """
    The Monarch API rejects a date filter with only one bound. If just one is
    supplied, fill the other:
      - only start_date -> end_date = today
      - only end_date   -> start_date = LONE_END_DATE_WINDOW_DAYS (365) days
        before end_date (a bounded window, not an unbounded scan from 1970).
    An unparseable end_date is passed through unchanged so the API reports it.
    """
    if start_date and not end_date:
        end_date = date.today().isoformat()
    elif end_date and not start_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
            start_date = (end - timedelta(days=LONE_END_DATE_WINDOW_DAYS)).isoformat()
        except ValueError:
            start_date = "1970-01-01"
    return start_date, end_date


def _owner_name(txn: Dict[str, Any]) -> Optional[str]:
    """Owner display name of a transaction (None when shared/unassigned)."""
    owner = txn.get("ownedByUser")
    return owner.get("name") if isinstance(owner, dict) else None


def _format_transaction_compact(txn: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a compact transaction object with only eight essential fields:
    id, date, amount, merchant name, category name, notes, owner, is_pending.

    Used by get_transactions(verbose=False) and search_transactions(verbose=False)
    to reduce token cost by ~80% vs. full verbose output.
    """
    category = txn.get("category")
    compact: Dict[str, Any] = {
        "id": txn.get("id"),
        "date": txn.get("date"),
        "amount": txn.get("amount"),
        "merchant": txn.get("merchant", {}).get("name") if isinstance(txn.get("merchant"), dict) else None,
        "category": category.get("name") if isinstance(category, dict) else None,
        "notes": txn.get("notes") or None,
        # None = shared/unassigned
        "owner": _owner_name(txn),
        "is_pending": bool(txn.get("pending", txn.get("isPending", False))),
    }
    return compact


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_transactions(
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
    verbose: bool = True,
    is_pending: Optional[bool] = None,
) -> str:
    """
    Get transactions from Monarch Money.

    Args:
        limit: Number of transactions to retrieve (default: 100)
        offset: Number of transactions to skip (default: 0)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format. If given without start_date, only the
            365 days ending on end_date are searched (pass start_date to go further back).
        account_id: Specific account ID to filter by
        verbose: If True (default), return all fields. If False, return compact
                 format with only: id, date, amount, merchant, category, notes,
                 owner, is_pending.
                 Use verbose=False for bulk fetches to reduce token usage (~80% reduction).
        is_pending: True = only pending transactions, False = only posted
                    (settled) transactions, omit for both.
    """
    try:

        async def _get_transactions():
            client = await get_monarch_client()

            # Build filters.
            # NOTE: The underlying monarchmoney lib accepts `account_ids` (List[str]),
            # NOT `account_id` (str). Passing `account_id` as a kwarg is silently
            # ignored by the lib (no error, no filter). We translate here.
            filters = {}
            range_start, range_end = _complete_date_range(start_date, end_date)
            if range_start:
                filters["start_date"] = range_start
            if range_end:
                filters["end_date"] = range_end
            if account_id:
                filters["account_ids"] = [account_id]  # lib expects a list
            if is_pending is not None:
                filters["is_pending"] = is_pending

            return await client.get_transactions(limit=limit, offset=offset, **filters)

        transactions = run_async(_get_transactions())

        raw_results = transactions.get("allTransactions", {}).get("results", [])

        if not verbose:
            transaction_list = [_format_transaction_compact(txn) for txn in raw_results]
            return json.dumps(transaction_list, default=str)

        # verbose=True path — full fields, unchanged behaviour
        transaction_list = []
        for txn in raw_results:
            transaction_info = {
                "id": txn.get("id"),
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "description": txn.get("description"),
                "category": txn.get("category", {}).get("name")
                if txn.get("category")
                else None,
                "account": txn.get("account", {}).get("displayName"),
                "merchant": txn.get("merchant", {}).get("name")
                if txn.get("merchant")
                else None,
                "is_pending": bool(txn.get("pending", txn.get("isPending", False))),
                "owner": _owner_name(txn),
            }
            transaction_list.append(transaction_info)

        return json.dumps(transaction_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions: {e}")
        return f"Error getting transactions: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def search_transactions(
    query: str,
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
    category_id: Optional[str] = None,
    tag_ids: Optional[str] = None,
    has_attachments: Optional[bool] = None,
    has_notes: Optional[bool] = None,
    hidden_from_reports: Optional[bool] = None,
    is_split: Optional[bool] = None,
    is_recurring: Optional[bool] = None,
    is_pending: Optional[bool] = None,
    verbose: bool = True,
) -> str:
    """
    Search transactions by text across merchant names, descriptions, and notes.

    Accepts all the same filters as get_transactions plus a full-text query string.
    Search is executed server-side by the Monarch Money API.

    Args:
        query: Search term (e.g. "IRS", "Amazon", "Target")
        limit: Number of transactions to retrieve (default: 100)
        offset: Number of transactions to skip (default: 0)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format. If given without start_date, only the
            365 days ending on end_date are searched (pass start_date to go further back).
        account_id: Specific account ID to filter by
        category_id: Specific category ID to filter by
        tag_ids: Comma-separated tag IDs to filter by (e.g. "tag1,tag2")
        has_attachments: Filter by attachment presence
        has_notes: Filter by notes presence
        hidden_from_reports: Filter by report visibility
        is_split: Filter split transactions
        is_recurring: Filter recurring transactions
        is_pending: True = only pending transactions, False = only posted
        verbose: If True (default), return all fields. If False, return compact
                 format with only: id, date, amount, merchant, category, notes,
                 owner, is_pending.
    """
    if not query or not query.strip():
        return "Error: query parameter cannot be empty"

    try:

        async def _search_transactions():
            client = await get_monarch_client()

            filters: Dict[str, Any] = {"search": query.strip()}
            range_start, range_end = _complete_date_range(start_date, end_date)
            if range_start:
                filters["start_date"] = range_start
            if range_end:
                filters["end_date"] = range_end
            if account_id:
                filters["account_ids"] = [account_id]
            if category_id:
                filters["category_ids"] = [category_id]
            if tag_ids:
                filters["tag_ids"] = [t.strip() for t in tag_ids.split(",") if t.strip()]
            if has_attachments is not None:
                filters["has_attachments"] = has_attachments
            if has_notes is not None:
                filters["has_notes"] = has_notes
            if hidden_from_reports is not None:
                filters["hidden_from_reports"] = hidden_from_reports
            if is_split is not None:
                filters["is_split"] = is_split
            if is_recurring is not None:
                filters["is_recurring"] = is_recurring
            if is_pending is not None:
                filters["is_pending"] = is_pending

            return await client.get_transactions(limit=limit, offset=offset, **filters)

        transactions = run_async(_search_transactions())

        raw_results = transactions.get("allTransactions", {}).get("results", [])

        if not verbose:
            transaction_list = [_format_transaction_compact(txn) for txn in raw_results]
        else:
            transaction_list = []
            for txn in raw_results:
                transaction_info = {
                    "id": txn.get("id"),
                    "date": txn.get("date"),
                    "amount": txn.get("amount"),
                    "description": txn.get("description"),
                    "category": txn.get("category", {}).get("name")
                    if txn.get("category")
                    else None,
                    "account": txn.get("account", {}).get("displayName"),
                    "merchant": txn.get("merchant", {}).get("name")
                    if txn.get("merchant")
                    else None,
                    "is_pending": bool(txn.get("pending", txn.get("isPending", False))),
                    "notes": txn.get("notes"),
                    "owner": _owner_name(txn),
                }
                transaction_list.append(transaction_info)

        result = {
            "search_metadata": {
                "query": query.strip(),
                "result_count": len(transaction_list),
            },
            "transactions": transaction_list,
        }

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to search transactions: {e}")
        return f"Error searching transactions: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_budgets(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """Get budget information from Monarch Money.

    Without start_date/end_date, defaults to the CURRENT calendar month only
    (not the underlying API's own last-month-to-next-month default) — the
    unfiltered 3-month x every-category response is large enough to exceed
    typical tool-output limits (258 rows / ~50KB observed). Pass explicit
    dates to widen the window if a multi-month view is actually needed.

    :param start_date: earliest month to include, "yyyy-mm-dd" (default: first of current month)
    :param end_date: latest month to include, "yyyy-mm-dd" (default: first of next month, i.e. current month only)
    :param category: optional case-insensitive substring filter on category name (e.g. "Pets") to shrink the response further
    """
    try:
        resolved_start = start_date
        resolved_end = end_date
        if resolved_start is None or resolved_end is None:
            today = date.today()
            current_month_start = today.replace(day=1)
            next_month_start = (current_month_start + timedelta(days=32)).replace(day=1)
            resolved_start = resolved_start or current_month_start.isoformat()
            resolved_end = resolved_end or next_month_start.isoformat()

        async def _get_budgets():
            client = await get_monarch_client()
            return await client.get_budgets(start_date=resolved_start, end_date=resolved_end)

        budgets = run_async(_get_budgets())
        budget_list = _parse_budgets_response(budgets)

        if category:
            needle = category.lower()
            budget_list = [b for b in budget_list if needle in (b.get("category") or "").lower()]

        return json.dumps(budget_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get budgets: {e}")
        return f"Error getting budgets: {str(e)}"


def _parse_budgets_response(budgets: dict) -> list:
    """
    Flatten the real `MonarchMoney.get_budgets()` GraphQL response into a
    list of per-category, per-month budget entries.

    The response has NO top-level "budgets" key (a wrong assumption that
    previously made this tool always return []). The actual shape is:

        {
          "budgetData": {
            "monthlyAmountsByCategory": [
              {
                "category": {"id": "..."},
                "monthlyAmounts": [
                  {
                    "month": "2026-08-01",
                    "plannedCashFlowAmount": 290.0,
                    "actualAmount": 123.45,
                    "remainingAmount": 166.55,
                    ...
                  },
                  ...
                ],
              },
              ...
            ],
            ...
          },
          "categoryGroups": [
            {"id": "...", "name": "...", "categories": [{"id": "...", "name": "..."}, ...]},
            ...
          ],
          ...
        }

    `categoryGroups[].categories` (present in the same response) is used to
    resolve category ids to human-readable names, since
    `monthlyAmountsByCategory` only carries category ids.
    """
    category_names: dict = {}
    for group in budgets.get("categoryGroups", []) or []:
        for category in group.get("categories", []) or []:
            category_id = category.get("id")
            if category_id is not None:
                category_names[category_id] = category.get("name")

    budget_data = budgets.get("budgetData", {}) or {}

    budget_list = []
    for entry in budget_data.get("monthlyAmountsByCategory", []) or []:
        category = entry.get("category", {}) or {}
        category_id = category.get("id")
        for monthly_amount in entry.get("monthlyAmounts", []) or []:
            budget_list.append(
                {
                    "category_id": category_id,
                    "category": category_names.get(category_id),
                    "month": monthly_amount.get("month"),
                    "amount": monthly_amount.get("plannedCashFlowAmount"),
                    "spent": monthly_amount.get("actualAmount"),
                    "remaining": monthly_amount.get("remainingAmount"),
                }
            )

    return budget_list


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_cashflow(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> str:
    """
    Get cashflow analysis from Monarch Money.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    try:

        async def _get_cashflow():
            client = await get_monarch_client()

            filters = {}
            if start_date:
                filters["start_date"] = start_date
            if end_date:
                filters["end_date"] = end_date

            return await client.get_cashflow(**filters)

        cashflow = run_async(_get_cashflow())

        return json.dumps(cashflow, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get cashflow: {e}")
        return f"Error getting cashflow: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_account_holdings(account_id: str) -> str:
    """
    Get investment holdings for a specific account.

    Args:
        account_id: The ID of the investment account
    """
    try:

        async def _get_holdings():
            client = await get_monarch_client()
            return await client.get_account_holdings(account_id)

        holdings = run_async(_get_holdings())

        return json.dumps(holdings, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get account holdings: {e}")
        return f"Error getting account holdings: {str(e)}"


def _resolve_by_id_or_name(
    items: List[Dict[str, Any]],
    ref: str,
    kind: str,
    name_keys: tuple,
    describe,
) -> str:
    """
    Resolve a reference (id or name) against a list of dicts with an "id".

    Exact id first, then case-insensitive name (any of `name_keys`). Raises
    ValueError on no match or an ambiguous name, listing the options.
    """
    ref_s = str(ref).strip()
    for it in items:
        if str(it.get("id")) == ref_s:
            return str(it["id"])

    def names(it):
        return [
            (it.get(k) or "").strip().lower() for k in name_keys if it.get(k)
        ]

    matches = [it for it in items if ref_s.lower() in names(it)]
    if len(matches) == 1:
        return str(matches[0]["id"])
    if len(matches) > 1:
        raise ValueError(
            f"{kind} name '{ref}' is ambiguous; use the id. Matches: "
            + "; ".join(f"{describe(m)} (id {m.get('id')})" for m in matches)
        )
    valid = ", ".join(sorted({describe(it) for it in items})) or "none found"
    raise ValueError(f"{kind} '{ref}' not found. Valid {kind.lower()}s: {valid}")


def _account_is_open(account: Dict[str, Any]) -> bool:
    """True if an account is open (not closed/deactivated) and not hidden.

    Fields come from the Monarch AccountFields fragment: `deactivatedAt`
    (set when an account is closed) and `isHidden` (hidden by the user).
    `hideFromList` is only a summary-display preference and does not make an
    account unusable.
    """
    return not account.get("deactivatedAt") and not account.get("isHidden")


def _resolve_account(accounts_response: Dict[str, Any], ref: str) -> str:
    """Resolve an account id or (display) name to an account id.

    Names are matched only against open, non-hidden accounts, and the "valid
    accounts" list in errors shows only those. An explicit id may be any
    account, but if it is closed or hidden a clear error is raised rather than
    silently writing to it.
    """
    accounts = (accounts_response or {}).get("accounts", []) or []
    ref_s = str(ref).strip()
    for a in accounts:
        if str(a.get("id")) == ref_s and not _account_is_open(a):
            label = a.get("displayName") or a.get("name") or ref_s
            state = "closed" if a.get("deactivatedAt") else "hidden"
            raise ValueError(
                f"Account '{label}' (id {ref_s}) is {state}; refusing to create a "
                "transaction on it. Use an open account."
            )
    return _resolve_by_id_or_name(
        [a for a in accounts if _account_is_open(a)],
        ref,
        "Account",
        ("displayName", "name"),
        lambda a: a.get("displayName") or a.get("name") or str(a.get("id")),
    )


def _resolve_category(categories_response: Dict[str, Any], ref: str) -> str:
    """Resolve a transaction category id or name to a category id."""
    categories = (categories_response or {}).get("categories", []) or []
    return _resolve_by_id_or_name(
        categories,
        ref,
        "Category",
        ("name",),
        lambda c: c.get("name") or str(c.get("id")),
    )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def create_transaction(
    amount: float,
    date: str,
    merchant_name: str,
    account: Optional[str] = None,
    category: Optional[str] = None,
    notes: Optional[str] = None,
    update_balance: bool = False,
    account_id: Optional[str] = None,
    category_id: Optional[str] = None,
) -> str:
    """
    Create a new transaction in Monarch Money.

    The Monarch API requires a merchant name and a category. Account and
    category can each be given by NAME or ID (names are matched
    case-insensitively; ambiguous or unknown names return an error listing the
    options, and nothing is created).

    Args:
        amount: Transaction amount (positive for income, negative for expenses)
        date: Transaction date in YYYY-MM-DD format
        merchant_name: Merchant name (required)
        account: Account name or ID (required; see get_accounts)
        category: Category name or ID (required; see get_transaction_categories)
        notes: Optional notes
        update_balance: Also adjust the account balance (default False)
        account_id: Legacy alias for `account`
        category_id: Legacy alias for `category`
    """
    account_ref = account or account_id
    category_ref = category or category_id

    if not merchant_name or not str(merchant_name).strip():
        return "Error creating transaction: merchant_name is required"
    if not account_ref or not str(account_ref).strip():
        return "Error creating transaction: account (name or id) is required"
    if not category_ref or not str(category_ref).strip():
        return "Error creating transaction: category (name or id) is required"
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return "Error creating transaction: date must be in YYYY-MM-DD format"
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount != amount:
        return "Error creating transaction: amount must be a number"

    try:

        async def _create_transaction():
            client = await get_monarch_client()
            resolved_account = _resolve_account(
                await client.get_accounts(), account_ref
            )
            resolved_category = _resolve_category(
                await client.get_transaction_categories(), category_ref
            )
            return await client.create_transaction(
                date=date,
                account_id=resolved_account,
                amount=amount,
                merchant_name=str(merchant_name).strip(),
                category_id=resolved_category,
                notes=notes or "",
                update_balance=bool(update_balance),
            )

        result = run_async(_create_transaction())

        payload = (result or {}).get("createTransaction") or {}
        errors = payload.get("errors")
        if errors:
            return f"Error creating transaction: {json.dumps(errors, default=str)}"

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction: {e}")
        return f"Error creating transaction: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def update_transaction(
    transaction_id: str,
    amount: Optional[float] = None,
    notes: Optional[str] = None,
    merchant_name: Optional[str] = None,
    category_id: Optional[str] = None,
    date: Optional[str] = None,
    hide_from_reports: Optional[bool] = None,
    needs_review: Optional[bool] = None,
    goal_id: Optional[str] = None,
    reviewed: Optional[bool] = None,
    owner_user_id: Optional[str] = None,
) -> str:
    """
    Update an existing transaction in Monarch Money.

    Args:
        transaction_id: The ID of the transaction to update
        amount: New transaction amount
        notes: Notes to attach to the transaction (Monarch's notes field)
        merchant_name: Override the merchant name displayed for the transaction
        category_id: New category ID
        date: New transaction date in YYYY-MM-DD format
        hide_from_reports: Exclude this transaction from reports/cashflow views
        needs_review: Flag the transaction as needing review (True) or clear the flag (False)
        goal_id: Associate with a goal ID; pass empty string "" to clear existing goal
        notes: Notes/memo for the transaction; pass empty string "" to clear existing notes
        reviewed: True to mark the transaction as reviewed. (To remove reviewed
                  status, use needs_review=True.)
        owner_user_id: Household member ID to assign as owner (see
                       get_household_members); empty string "" sets the
                       transaction to Shared/joint. Omit to leave ownership unchanged.
    """
    try:

        async def _update_transaction():
            client = await get_monarch_client()

            update_data: Dict[str, Any] = {"transaction_id": transaction_id}

            if amount is not None:
                update_data["amount"] = amount
            if notes is not None:
                update_data["notes"] = notes
            if merchant_name is not None:
                update_data["merchant_name"] = merchant_name
            if category_id is not None:
                update_data["category_id"] = category_id
            if date is not None:
                update_data["date"] = date
            if hide_from_reports is not None:
                update_data["hide_from_reports"] = hide_from_reports
            if needs_review is not None:
                update_data["needs_review"] = needs_review
            if goal_id is not None:
                update_data["goal_id"] = goal_id
            if notes is not None:
                update_data["notes"] = notes
            if reviewed is not None:
                update_data["reviewed"] = reviewed
            if owner_user_id is not None:
                update_data["owner_user_id"] = owner_user_id

            return await client.update_transaction(**update_data)

        result = run_async(_update_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update transaction: {e}")
        return f"Error updating transaction: {str(e)}"


# Concurrency cap for bulk updates — prevents hammering the Monarch API with
# hundreds of parallel requests. Groups of 10 are processed sequentially;
# requests within each group are fired in parallel.
_BULK_UPDATE_BATCH_SIZE = 10


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def update_transactions_bulk(updates: str) -> str:
    """
    Update multiple transactions in a single call.

    There is no native bulk-update endpoint in the Monarch API; this tool
    wraps update_transaction in controlled batches of 10 concurrent requests
    to avoid overwhelming the API. Each transaction is attempted independently
    — a failure on one does NOT abort the rest.

    Args:
        updates: JSON array of update objects. Each object must have:
                 - transaction_id (string, required): The transaction to update
                 - amount (number, optional): New amount
                 - description (string, optional): New merchant/description name
                 - category_id (string, optional): New category ID
                 - date (string, optional): New date in YYYY-MM-DD format
                 - hide_from_reports (boolean, optional): Exclude from reports
                 - needs_review (boolean, optional): Flag for review
                 - goal_id (string, optional): Associate with goal; "" clears it
                 - notes (string, optional): Notes/memo; "" clears existing
                 - reviewed (boolean, optional): True marks as reviewed
                 - owner_user_id (string, optional): Household member id (see
                   get_household_members) to set as owner; "" = Shared/joint

    Returns:
        JSON array of per-transaction results:
        [{"transaction_id": "...", "success": true, "result": {...}}, ...]
        or
        [{"transaction_id": "...", "success": false, "error": "..."}, ...]

    Example:
        '[{"transaction_id": "123", "category_id": "abc", "needs_review": false},
          {"transaction_id": "456", "hide_from_reports": true}]'
    """
    try:
        update_list = json.loads(updates)
    except json.JSONDecodeError as e:
        return f"Error parsing updates JSON: {str(e)}. Please provide a valid JSON array."

    if not isinstance(update_list, list):
        return "Error: updates must be a JSON array of update objects."

    async def _update_one(client: MonarchMoney, item: Dict[str, Any]) -> Dict[str, Any]:
        """Attempt a single transaction update; return success/failure envelope."""
        if not isinstance(item, dict):
            return {
                "transaction_id": None,
                "success": False,
                "error": f"item must be a dict, got {type(item).__name__}",
            }
        txn_id = item.get("transaction_id")
        if not txn_id:
            return {"transaction_id": None, "success": False, "error": "missing transaction_id"}
        try:
            update_data: Dict[str, Any] = {"transaction_id": txn_id}
            if "amount" in item and item["amount"] is not None:
                update_data["amount"] = item["amount"]
            if "description" in item and item["description"] is not None:
                update_data["merchant_name"] = item["description"]
            if "category_id" in item and item["category_id"] is not None:
                update_data["category_id"] = item["category_id"]
            if "date" in item and item["date"] is not None:
                update_data["date"] = item["date"]
            if "hide_from_reports" in item and item["hide_from_reports"] is not None:
                update_data["hide_from_reports"] = item["hide_from_reports"]
            if "needs_review" in item and item["needs_review"] is not None:
                update_data["needs_review"] = item["needs_review"]
            if "goal_id" in item and item["goal_id"] is not None:
                update_data["goal_id"] = item["goal_id"]
            if "notes" in item and item["notes"] is not None:
                update_data["notes"] = item["notes"]
            if "reviewed" in item and item["reviewed"] is not None:
                update_data["reviewed"] = item["reviewed"]
            if "owner_user_id" in item and item["owner_user_id"] is not None:
                update_data["owner_user_id"] = item["owner_user_id"]
            result = await client.update_transaction(**update_data)
            return {"transaction_id": txn_id, "success": True, "result": result}
        except Exception as exc:
            return {"transaction_id": txn_id, "success": False, "error": str(exc)}

    async def _run_bulk():
        client = await get_monarch_client()
        all_results: List[Dict[str, Any]] = []
        # Process in batches to cap concurrency
        for batch_start in range(0, len(update_list), _BULK_UPDATE_BATCH_SIZE):
            batch = update_list[batch_start : batch_start + _BULK_UPDATE_BATCH_SIZE]
            # return_exceptions=True is required: without it, BaseException subclasses
            # (e.g. asyncio.CancelledError on Python 3.12+, which is no longer a
            # subclass of Exception) escape _update_one's inner except clause, propagate
            # to gather, and kill the whole batch — silently discarding successful results.
            results = await asyncio.gather(
                *[_update_one(client, item) for item in batch],
                return_exceptions=True,
            )
            # Convert any raw BaseException instances to the standard envelope shape
            # so callers always see dicts, never bare exception objects.
            for idx, result in enumerate(results):
                if isinstance(result, BaseException):
                    src_item = batch[idx]
                    tx_id = src_item.get("transaction_id") if isinstance(src_item, dict) else None
                    results[idx] = {
                        "transaction_id": tx_id,
                        "success": False,
                        "error": f"unexpected exception: {type(result).__name__}: {str(result)}",
                    }
            all_results.extend(results)
        return all_results

    try:
        results = run_async(_run_bulk())
        success_count = sum(1 for r in results if r.get("success"))
        fail_count = len(results) - success_count
        logger.info(f"Bulk update complete: {success_count} succeeded, {fail_count} failed out of {len(results)}")
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to run bulk update: {e}")
        return f"Error running bulk update: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def refresh_accounts(account_ids: Optional[List[str]] = None) -> str:
    """
    Request account data refresh from financial institutions.

    Args:
        account_ids: Specific account IDs to refresh. If omitted (default),
                     ALL linked accounts are refreshed. The underlying
                     monarchmoney lib requires an explicit account_ids list
                     (there is no server-side "refresh everything" mode), so
                     when this is omitted we first fetch the full account
                     list and pass all of its IDs.
    """
    try:

        async def _refresh_accounts():
            client = await get_monarch_client()
            ids = account_ids
            if not ids:
                accounts = await client.get_accounts()
                ids = [
                    account["id"]
                    for account in accounts.get("accounts", [])
                    if account.get("id")
                ]
                if not ids:
                    raise ValueError("No linked accounts found to refresh")
            return await client.request_accounts_refresh(ids)

        result = run_async(_refresh_accounts())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to refresh accounts: {e}")
        return f"Error refreshing accounts: {str(e)}"


# ============================================================================
# NEW TOOLS - Account & Institution Data
# ============================================================================


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_account_history(
    account_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get daily balance history for a specific account.

    The Monarch API returns the account's full history; start_date/end_date
    (inclusive) are applied client-side to trim it. Omit both for everything.

    Args:
        account_id: The unique identifier for the account
        start_date: Optional first date to include (YYYY-MM-DD)
        end_date: Optional last date to include (YYYY-MM-DD)
    """
    try:

        async def _get_account_history():
            client = await get_monarch_client()
            # The library's get_account_history() takes only account_id.
            return await client.get_account_history(account_id)

        result = run_async(_get_account_history())

        if isinstance(result, list) and (start_date or end_date):
            result = [
                row
                for row in result
                if isinstance(row, dict)
                and (not start_date or str(row.get("date") or "") >= start_date)
                and (not end_date or str(row.get("date") or "") <= end_date)
            ]

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get account history: {e}")
        return f"Error getting account history: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_account_type_options() -> str:
    """
    Get all available account types and subtypes in Monarch Money.
    Useful for account creation and understanding account categorization.
    """
    try:

        async def _get_account_type_options():
            client = await get_monarch_client()
            return await client.get_account_type_options()

        result = run_async(_get_account_type_options())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get account type options: {e}")
        return f"Error getting account type options: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_institutions() -> str:
    """
    Get all financial institutions linked to your Monarch Money account.
    Returns institution details including connection status and last sync time.
    """
    try:

        async def _get_institutions():
            client = await get_monarch_client()
            return await client.get_institutions()

        result = run_async(_get_institutions())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get institutions: {e}")
        return f"Error getting institutions: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_subscription_details() -> str:
    """
    Get Monarch Money subscription status including plan type and expiration.
    """
    try:

        async def _get_subscription_details():
            client = await get_monarch_client()
            return await client.get_subscription_details()

        result = run_async(_get_subscription_details())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get subscription details: {e}")
        return f"Error getting subscription details: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def is_accounts_refresh_complete() -> str:
    """
    Check if a running account refresh operation is complete.
    Use this after calling refresh_accounts to poll for completion status.
    """
    try:

        async def _is_accounts_refresh_complete():
            client = await get_monarch_client()
            return await client.is_accounts_refresh_complete()

        result = run_async(_is_accounts_refresh_complete())

        return json.dumps({"refresh_complete": result}, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to check refresh status: {e}")
        return f"Error checking refresh status: {str(e)}"


# ============================================================================
# NEW TOOLS - Transaction Management
# ============================================================================


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_transaction_details(transaction_id: str) -> str:
    """
    Get comprehensive details for a single transaction including all metadata.
    Output includes: hideFromReports, needsReview, goal (id), and all other transaction fields.

    Args:
        transaction_id: The unique identifier for the transaction
    """
    try:

        async def _get_transaction_details():
            client = await get_monarch_client()
            return await client.get_transaction_details(transaction_id)

        result = run_async(_get_transaction_details())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction details: {e}")
        return f"Error getting transaction details: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_transaction_splits(transaction_id: str) -> str:
    """
    Get split information for a transaction divided across multiple categories.

    Args:
        transaction_id: The unique identifier for the transaction
    """
    try:

        async def _get_transaction_splits():
            client = await get_monarch_client()
            return await client.get_transaction_splits(transaction_id)

        result = run_async(_get_transaction_splits())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction splits: {e}")
        return f"Error getting transaction splits: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def update_transaction_splits(transaction_id: str, splits: str) -> str:
    """
    Split a transaction across multiple categories or modify existing splits.

    Args:
        transaction_id: The transaction to split
        splits: JSON array of split objects. Each object should have:
                - category_id (string): Category ID for this split
                - amount (number): Amount for this split (positive value)
                - merchant_name (string, optional): Merchant name
                - notes (string, optional): Notes for this split

    Example splits: '[{"category_id": "cat123", "amount": 50.00}, {"category_id": "cat456", "amount": 25.00}]'

    Note: Sum of split amounts must equal the original transaction amount.
    """
    try:
        # Parse the splits JSON
        split_data = json.loads(splits)

        async def _update_transaction_splits():
            client = await get_monarch_client()
            return await client.update_transaction_splits(transaction_id, split_data)

        result = run_async(_update_transaction_splits())

        return json.dumps(result, indent=2, default=str)
    except json.JSONDecodeError as e:
        return f"Error parsing splits JSON: {str(e)}. Please provide valid JSON array."
    except Exception as e:
        logger.error(f"Failed to update transaction splits: {e}")
        return f"Error updating transaction splits: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_transactions_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get aggregated transaction summary data (totals by category, merchant, etc.).

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    """
    try:

        async def _get_transactions_summary():
            client = await get_monarch_client()
            kwargs = {}
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            return await client.get_transactions_summary(**kwargs)

        result = run_async(_get_transactions_summary())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions summary: {e}")
        return f"Error getting transactions summary: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_recurring_transactions() -> str:
    """
    Get all recurring/scheduled transactions with frequency, next occurrence, and merchant details.
    Useful for tracking subscriptions and upcoming bills.
    """
    try:

        async def _get_recurring_transactions():
            client = await get_monarch_client()
            return await client.get_recurring_transactions()

        result = run_async(_get_recurring_transactions())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get recurring transactions: {e}")
        return f"Error getting recurring transactions: {str(e)}"


# ============================================================================
# NEW TOOLS - Categories & Tags
# ============================================================================


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_transaction_categories() -> str:
    """
    Get all transaction categories configured in the account.
    Returns category IDs, names, icons, and whether they are system or custom categories.
    """
    try:

        async def _get_transaction_categories():
            client = await get_monarch_client()
            return await client.get_transaction_categories()

        result = run_async(_get_transaction_categories())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction categories: {e}")
        return f"Error getting transaction categories: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_transaction_category_groups() -> str:
    """
    Get all category groups (parent groupings for categories).
    Returns group IDs, names, and associated category information.
    """
    try:

        async def _get_transaction_category_groups():
            client = await get_monarch_client()
            return await client.get_transaction_category_groups()

        result = run_async(_get_transaction_category_groups())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction category groups: {e}")
        return f"Error getting transaction category groups: {str(e)}"


def _resolve_category_group(groups_response: Dict[str, Any], group_ref: str) -> str:
    """
    Resolve a category group reference (ID or name) to a group ID.

    Matches an exact ID first, then a case-insensitive name. Raises ValueError
    listing the valid groups when nothing matches (or the name is ambiguous).
    """
    groups = (groups_response or {}).get("categoryGroups", []) or []
    ref = str(group_ref).strip()

    for g in groups:
        if str(g.get("id")) == ref:
            return str(g["id"])

    matches = [
        g for g in groups if (g.get("name") or "").strip().lower() == ref.lower()
    ]
    if len(matches) == 1:
        return str(matches[0]["id"])
    if len(matches) > 1:
        raise ValueError(
            f"Category group name '{group_ref}' is ambiguous; use the group id. "
            f"Matching group ids: {', '.join(str(g.get('id')) for g in matches)}"
        )

    valid = (
        ", ".join(f"{g.get('name')} (id {g.get('id')})" for g in groups) or "none found"
    )
    raise ValueError(f"Category group '{group_ref}' not found. Valid groups: {valid}")


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def create_transaction_category(
    name: str,
    group: Optional[str] = None,
    group_id: Optional[str] = None,
    icon: Optional[str] = None,
) -> str:
    """
    Create a new custom category for transactions.

    A parent category group is REQUIRED. Pass it as `group` (group NAME or ID,
    e.g. "Food & Dining") -- use get_transaction_category_groups to list them.
    `group_id` is accepted as a legacy alias for `group` (ID or name).

    Args:
        name: Category name (max 50 chars, must be unique)
        group: Parent category group name or ID (required unless group_id is given)
        group_id: Legacy alias for `group`
        icon: Optional emoji/icon for the category
    """
    group_ref = group or group_id
    if not name or not name.strip():
        return "Error creating transaction category: name cannot be empty"
    if not group_ref or not str(group_ref).strip():
        return (
            "Error creating transaction category: a parent category group is "
            "required. Pass `group` (name or id); use "
            "get_transaction_category_groups to list them."
        )

    try:

        async def _create_transaction_category():
            client = await get_monarch_client()
            resolved_group_id = _resolve_category_group(
                await client.get_transaction_category_groups(), group_ref
            )
            kwargs: Dict[str, Any] = {
                "group_id": resolved_group_id,
                "transaction_category_name": name.strip(),
            }
            if icon:
                kwargs["icon"] = icon
            return await client.create_transaction_category(**kwargs)

        result = run_async(_create_transaction_category())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction category: {e}")
        return f"Error creating transaction category: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_transaction_tags() -> str:
    """
    Get all tags configured in the account.
    Tags are user-defined labels that can be applied to any transaction.
    """
    try:

        async def _get_transaction_tags():
            client = await get_monarch_client()
            return await client.get_transaction_tags()

        result = run_async(_get_transaction_tags())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction tags: {e}")
        return f"Error getting transaction tags: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def create_transaction_tag(
    name: str,
    color: Optional[str] = None,
) -> str:
    """
    Create a new tag for transactions.

    Args:
        name: Tag name (max 30 chars)
        color: Optional hex color code
    """
    try:

        async def _create_transaction_tag():
            client = await get_monarch_client()
            kwargs = {"name": name}
            if color:
                kwargs["color"] = color
            return await client.create_transaction_tag(**kwargs)

        result = run_async(_create_transaction_tag())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction tag: {e}")
        return f"Error creating transaction tag: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def set_transaction_tags(transaction_id: str, tag_ids: str) -> str:
    """
    Apply one or more tags to a transaction.

    Args:
        transaction_id: The transaction to tag
        tag_ids: JSON array of tag IDs to apply. Example: '["tag123", "tag456"]'

    Note: This replaces existing tags (not additive). Empty array removes all tags.
    """
    try:
        # Parse the tag_ids JSON
        tag_id_list = json.loads(tag_ids)

        async def _set_transaction_tags():
            client = await get_monarch_client()
            return await client.set_transaction_tags(transaction_id, tag_id_list)

        result = run_async(_set_transaction_tags())

        return json.dumps(result, indent=2, default=str)
    except json.JSONDecodeError as e:
        return f"Error parsing tag_ids JSON: {str(e)}. Please provide valid JSON array."
    except Exception as e:
        logger.error(f"Failed to set transaction tags: {e}")
        return f"Error setting transaction tags: {str(e)}"


# ============================================================================
# NEW TOOLS - Budgets
# ============================================================================


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def set_budget_amount(
    category_id: str,
    amount: float,
    month: Optional[str] = None,
    apply_to_future: Optional[bool] = None,
) -> str:
    """
    Set or update a budget amount for a specific category and month.

    Args:
        category_id: The category to budget
        amount: Budget amount (0 to clear/unset the budget)
        month: Month in YYYY-MM format. Defaults to current month
        apply_to_future: If true, apply to this and all future months
    """
    try:

        async def _set_budget_amount():
            client = await get_monarch_client()
            kwargs = {
                "amount": amount,
            }
            if month:
                # Convert YYYY-MM to start_date format expected by API
                kwargs["start_date"] = f"{month}-01"
            if apply_to_future is not None:
                kwargs["apply_to_future"] = apply_to_future
            # NOTE: category_id MUST be passed as a keyword argument here.
            # MonarchMoney.set_budget_amount()'s real signature is
            # (self, amount, category_id=None, category_group_id=None, ...) —
            # `amount` is positional arg 0, not `category_id`. Passing
            # category_id positionally while kwargs also contains "amount"
            # causes "got multiple values for argument 'amount'". This exact
            # regression happened twice (see test_set_budget_amount.py).
            return await client.set_budget_amount(category_id=category_id, **kwargs)

        result = run_async(_set_budget_amount())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to set budget amount: {e}")
        return f"Error setting budget amount: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_cashflow_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get high-level cashflow metrics (income, expenses, savings, savings rate).

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    """
    try:

        async def _get_cashflow_summary():
            client = await get_monarch_client()
            kwargs = {}
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            return await client.get_cashflow_summary(**kwargs)

        result = run_async(_get_cashflow_summary())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get cashflow summary: {e}")
        return f"Error getting cashflow summary: {str(e)}"


# ============================================================================
# NEW TOOLS - Account Management
# ============================================================================


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def create_manual_account(
    name: str,
    account_type: str,
    balance: float,
    account_subtype: Optional[str] = None,
    include_in_net_worth: bool = True,
) -> str:
    """
    Create a new manual (non-linked) account for tracking assets or liabilities.

    Args:
        name: Account name
        account_type: Type from get_account_type_options (e.g., "depository", "investment", "loan")
        balance: Starting balance
        account_subtype: Subtype (e.g., "checking", "savings", "brokerage")
        include_in_net_worth: Include in net worth calculations (default: true)
    """
    try:

        async def _create_manual_account():
            client = await get_monarch_client()
            kwargs = {
                "account_name": name,
                "account_type": account_type,
                "account_balance": balance,
                "include_in_net_worth": include_in_net_worth,
            }
            if account_subtype:
                kwargs["account_subtype"] = account_subtype
            return await client.create_manual_account(**kwargs)

        result = run_async(_create_manual_account())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create manual account: {e}")
        return f"Error creating manual account: {str(e)}"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def update_account(
    account_id: str,
    name: Optional[str] = None,
    balance: Optional[float] = None,
    include_in_net_worth: Optional[bool] = None,
    hide_from_overview: Optional[bool] = None,
) -> str:
    """
    Update an existing account's settings or balance.

    Args:
        account_id: The account to update
        name: New account name
        balance: New balance (manual accounts only)
        include_in_net_worth: Update net worth inclusion
        hide_from_overview: Hide from main dashboard
    """
    try:

        async def _update_account():
            client = await get_monarch_client()
            kwargs = {}
            if name is not None:
                kwargs["name"] = name
            if balance is not None:
                kwargs["balance"] = balance
            if include_in_net_worth is not None:
                kwargs["include_in_net_worth"] = include_in_net_worth
            if hide_from_overview is not None:
                kwargs["hide_from_overview"] = hide_from_overview
            return await client.update_account(account_id, **kwargs)

        result = run_async(_update_account())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update account: {e}")
        return f"Error updating account: {str(e)}"


# ---------------------------------------------------------------------------
# Read-only reporting tools (household, rules, net worth, credit, duplicates)
# ---------------------------------------------------------------------------


def _format_household_members(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten myHousehold.users into compact member dicts."""
    users = ((response or {}).get("myHousehold") or {}).get("users") or []
    return [
        {
            "id": u.get("id"),
            "name": u.get("name"),
            "display_name": u.get("displayName"),
            "role": u.get("householdRole"),
        }
        for u in users
    ]


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_household_members() -> str:
    """
    List household members (ids, names, roles).

    Use a member `id` as `owner_user_id` in update_transaction /
    update_transactions_bulk to assign a transaction owner.
    """
    try:

        async def _get_household_members():
            client = await get_monarch_client()
            return await client.get_household_members()

        response = run_async(_get_household_members())
        return json.dumps(_format_household_members(response), indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get household members: {e}")
        return f"Error getting household members: {str(e)}"


def _criteria_list(criteria: Any) -> Optional[List[str]]:
    """[{operator, value}, ...] -> ["operator value", ...] (None if empty)."""
    if not criteria:
        return None
    out = [
        f"{c.get('operator')} {c.get('value')}".strip()
        for c in criteria
        if isinstance(c, dict)
    ]
    return out or None


def _format_amount_criteria(amount: Any) -> Optional[str]:
    if not isinstance(amount, dict):
        return None
    kind = "expense" if amount.get("isExpense") else "income"
    value_range = amount.get("valueRange")
    if isinstance(value_range, dict) and (
        value_range.get("lower") is not None or value_range.get("upper") is not None
    ):
        return f"{kind} {amount.get('operator')} {value_range.get('lower')}..{value_range.get('upper')}"
    return f"{kind} {amount.get('operator')} {amount.get('value')}"


def _names(items: Any, key: str = "name") -> Optional[List[str]]:
    if not items:
        return None
    out = [i.get(key) or i.get("displayName") or i.get("id") for i in items if isinstance(i, dict)]
    return out or None


def _format_transaction_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compact view of one transaction rule: only the criteria ("if") and
    actions ("then") that are actually set, plus usage stats.
    """
    cond: Dict[str, Any] = {}
    merchant_key = (
        "merchant_original_statement"
        if rule.get("merchantCriteriaUseOriginalStatement")
        else "merchant"
    )
    for key, value in (
        (merchant_key, _criteria_list(rule.get("merchantCriteria"))),
        ("original_statement", _criteria_list(rule.get("originalStatementCriteria"))),
        ("merchant_name", _criteria_list(rule.get("merchantNameCriteria"))),
        ("amount", _format_amount_criteria(rule.get("amountCriteria"))),
        ("categories", _names(rule.get("categories")) or rule.get("categoryIds") or None),
        ("accounts", _names(rule.get("accounts"), "displayName") or rule.get("accountIds") or None),
        ("owners", _names(rule.get("criteriaOwnerUsers"), "displayName")
         or rule.get("criteriaOwnerUserIds") or None),
        ("business_entities", _names(rule.get("criteriaBusinessEntities"))),
    ):
        if value:
            cond[key] = value
    if rule.get("criteriaOwnerIsJoint"):
        cond["owner_is_joint"] = True

    then: Dict[str, Any] = {}
    set_merchant = rule.get("setMerchantAction")
    if isinstance(set_merchant, dict) and set_merchant.get("name"):
        then["set_merchant"] = set_merchant["name"]
    set_category = rule.get("setCategoryAction")
    if isinstance(set_category, dict) and set_category.get("name"):
        then["set_category"] = set_category["name"]
    if rule.get("addTagsAction"):
        then["add_tags"] = _names(rule["addTagsAction"])
    for key, field in (("link_goal", "linkGoalAction"), ("link_savings_goal", "linkSavingsGoalAction")):
        if isinstance(rule.get(field), dict) and rule[field].get("name"):
            then[key] = rule[field]["name"]
    review_user = rule.get("needsReviewByUserAction")
    if isinstance(review_user, dict):
        then["needs_review_by"] = review_user.get("displayName") or review_user.get("name") or review_user.get("id")
    if rule.get("reviewStatusAction"):
        then["review_status"] = rule["reviewStatusAction"]
    for key, field in (
        ("unassign_needs_review", "unassignNeedsReviewByUserAction"),
        ("send_notification", "sendNotificationAction"),
        ("hide_from_reports", "setHideFromReportsAction"),
        ("link_to_paydown_budget", "setLinkToPaydownBudgetAction"),
    ):
        if rule.get(field):
            then[key] = True
    if rule.get("actionSetOwnerIsJoint"):
        then["set_owner"] = "joint"
    elif isinstance(rule.get("actionSetOwner"), dict):
        owner = rule["actionSetOwner"]
        then["set_owner"] = owner.get("displayName") or owner.get("id")
    entity = rule.get("actionSetBusinessEntity")
    if isinstance(entity, dict) and entity.get("name"):
        then["set_business_entity"] = entity["name"]
    if rule.get("splitTransactionsAction"):
        then["split_transaction"] = True

    return {
        "priority": rule.get("order"),
        "id": rule.get("id"),
        "if": cond,
        "then": then,
        "applied_recently": rule.get("recentApplicationCount"),
        "last_applied": rule.get("lastAppliedAt"),
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_transaction_rules() -> str:
    """
    List transaction auto-categorization rules (read-only), in priority order
    (priority 0 runs first). Output is compact: for each rule only the
    criteria ("if") and actions ("then") that are set, plus how often the
    rule applied recently.
    """
    try:

        async def _get_transaction_rules():
            client = await get_monarch_client()
            return await client.get_transaction_rules()

        response = run_async(_get_transaction_rules())
        rules = (response or {}).get("transactionRules") or []
        formatted = [
            _format_transaction_rule(r)
            for r in sorted(rules, key=lambda r: (r.get("order") is None, r.get("order") or 0))
        ]
        return json.dumps({"count": len(formatted), "rules": formatted}, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction rules: {e}")
        return f"Error getting transaction rules: {str(e)}"


_NET_WORTH_INTERVALS = ("daily", "weekly", "monthly")


def _period_key(day: date, interval: str) -> str:
    if interval == "monthly":
        return day.strftime("%Y-%m")
    if interval == "weekly":
        iso = day.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return day.isoformat()


def _build_net_worth_trend(snapshots: List[Dict[str, Any]], interval: str) -> Dict[str, Any]:
    """
    Turn raw daily {date, balance} snapshots into a trend: one point per
    period (the LAST snapshot of each period), each with the change vs the
    previous point, plus an overall summary.
    """
    rows = []
    for snap in snapshots or []:
        try:
            day = date.fromisoformat(str(snap.get("date"))[:10])
        except ValueError:
            continue
        if snap.get("balance") is None:
            continue
        rows.append((day, float(snap["balance"])))
    rows.sort(key=lambda r: r[0])
    if not rows:
        return {"summary": None, "points": []}

    by_period: Dict[str, tuple] = {}
    for day, balance in rows:
        by_period[_period_key(day, interval)] = (day, balance)  # last one wins
    selected = list(by_period.values())

    points = []
    previous: Optional[float] = None
    for day, balance in selected:
        point: Dict[str, Any] = {"date": day.isoformat(), "net_worth": round(balance, 2)}
        if previous is not None:
            change = balance - previous
            point["change"] = round(change, 2)
            point["change_pct"] = round(change / abs(previous) * 100, 2) if previous else None
        points.append(point)
        previous = balance

    first_balance, last_balance = rows[0][1], rows[-1][1]
    total_change = last_balance - first_balance
    summary = {
        "interval": interval,
        "from": rows[0][0].isoformat(),
        "to": rows[-1][0].isoformat(),
        "start_net_worth": round(first_balance, 2),
        "end_net_worth": round(last_balance, 2),
        "change": round(total_change, 2),
        "change_pct": round(total_change / abs(first_balance) * 100, 2) if first_balance else None,
        "high": round(max(b for _, b in rows), 2),
        "low": round(min(b for _, b in rows), 2),
        "points": len(points),
    }
    return {"summary": summary, "points": points}


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_net_worth_history(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    interval: str = "monthly",
) -> str:
    """
    Net worth trend over time with period-over-period deltas (read-only).

    Wraps Monarch's aggregate daily snapshots and downsamples to one point per
    period (the last snapshot in the period), each with its change vs the
    previous point, plus an overall summary (start/end, change, % change,
    high/low).

    Args:
        start_date: First date to include (YYYY-MM-DD). Default: 365 days ago.
        end_date: Last date to include (YYYY-MM-DD). Default: today.
        interval: "daily", "weekly" or "monthly" (default "monthly")
    """
    interval = (interval or "monthly").lower()
    if interval not in _NET_WORTH_INTERVALS:
        return f"Error: interval must be one of {', '.join(_NET_WORTH_INTERVALS)}"

    resolved_start = start_date or (date.today() - timedelta(days=365)).isoformat()
    try:

        async def _get_net_worth_history():
            client = await get_monarch_client()
            kwargs: Dict[str, Any] = {"start_date": resolved_start}
            if end_date:
                kwargs["end_date"] = end_date
            return await client.get_aggregate_snapshots(**kwargs)

        response = run_async(_get_net_worth_history())
        snapshots = (response or {}).get("aggregateSnapshots") or []
        return json.dumps(_build_net_worth_trend(snapshots, interval), indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get net worth history: {e}")
        return f"Error getting net worth history: {str(e)}"


def _build_credit_history(response: Dict[str, Any]) -> Dict[str, Any]:
    """Group credit score snapshots per household member with deltas."""
    response = response or {}
    names = {
        u.get("id"): u.get("displayName") or u.get("name")
        for u in ((response.get("myHousehold") or {}).get("users") or [])
    }
    per_user: Dict[str, List[Dict[str, Any]]] = {}
    for snap in response.get("creditScoreSnapshots") or []:
        if snap.get("score") is None:
            continue
        uid = (snap.get("user") or {}).get("id")
        per_user.setdefault(uid, []).append(
            {"date": snap.get("reportedDate"), "score": snap["score"]}
        )

    tracking = (response.get("spinwheelUser") or {}).get("creditScoreTrackingStatus")
    members = []
    for uid, history in per_user.items():
        history.sort(key=lambda h: str(h["date"]))
        previous = None
        for h in history:
            if previous is not None:
                h["change"] = h["score"] - previous
            previous = h["score"]
        latest, first = history[-1], history[0]
        members.append(
            {
                "user": names.get(uid) or uid,
                "latest_score": latest["score"],
                "latest_date": latest["date"],
                "change_vs_previous": latest.get("change"),
                "change_over_period": latest["score"] - first["score"],
                "period_from": first["date"],
                "history": history,
            }
        )
    return {"tracking_status": tracking, "members": members}


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def get_credit_history() -> str:
    """
    Credit score history per household member (read-only): latest score, change
    vs the previous reading, change over the whole period, and each reading
    with its delta.
    """
    try:

        async def _get_credit_history():
            client = await get_monarch_client()
            return await client.get_credit_history()

        response = run_async(_get_credit_history())
        return json.dumps(_build_credit_history(response), indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get credit history: {e}")
        return f"Error getting credit history: {str(e)}"


def _format_duplicate_group(group: Dict[str, Any]) -> Dict[str, Any]:
    txns = group.get("transactions") or []
    return {
        "date": group.get("date"),
        "amount": group.get("amount"),
        "account": group.get("account_name"),
        "statement": group.get("plaidName"),
        "count": len(txns),
        # oldest first: the first id is the likely original
        "transaction_ids": [t.get("id") for t in txns],
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    )
)
def find_duplicate_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
    max_pages: int = 10,
    limit: int = 50,
) -> str:
    """
    Report groups of likely duplicate transactions (READ-ONLY; this tool never
    deletes or changes anything).

    Transactions are grouped when they share the same date, amount, bank
    statement text (plaidName) and account -- i.e. the same upstream event
    written twice (e.g. after an account re-link). Legitimate repeat charges
    carry distinct statement references and are not grouped.

    Args:
        start_date: Earliest date to scan (YYYY-MM-DD)
        end_date: Latest date to scan (YYYY-MM-DD)
        account_id: Restrict the scan to one account
        max_pages: Pages of 500 transactions to scan (default 10 = 5,000
                   transactions, newest first). Duplicates are only found
                   within the scanned transactions.
        limit: Max duplicate groups to return (default 50)
    """
    if max_pages < 1:
        return "Error: max_pages must be at least 1"
    range_start, range_end = _complete_date_range(start_date, end_date)
    try:

        async def _find_duplicates():
            client = await get_monarch_client()
            kwargs: Dict[str, Any] = {"max_pages": max_pages}
            if range_start:
                kwargs["start_date"] = range_start
            if range_end:
                kwargs["end_date"] = range_end
            if account_id:
                kwargs["account_ids"] = [account_id]
            return await client.find_duplicate_transactions(**kwargs)

        groups = run_async(_find_duplicates()) or []
        formatted = [_format_duplicate_group(g) for g in groups]
        result = {
            "duplicate_groups": len(formatted),
            "extra_copies": sum(g["count"] - 1 for g in formatted),
            "scan": {"max_pages": max_pages, "page_size": 500},
            "groups": formatted[: max(limit, 0)],
        }
        if len(formatted) > limit:
            result["truncated"] = f"showing {limit} of {len(formatted)} groups"
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to find duplicate transactions: {e}")
        return f"Error finding duplicate transactions: {str(e)}"


def main():
    """Main entry point for the server."""
    logger.info("Starting Monarch Money MCP Server...")
    try:
        mcp.run()
    except Exception as e:
        logger.error(f"Failed to run server: {str(e)}")
        raise


# Export for mcp run
app = mcp

if __name__ == "__main__":
    main()
