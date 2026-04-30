"""Monarch Money MCP Server - Main server implementation."""

import os
import logging
import asyncio
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, date
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from mcp.server.auth.provider import AccessTokenT
from mcp.server.fastmcp import FastMCP
import mcp.types as types
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def get_transactions(
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
) -> str:
    """
    Get transactions from Monarch Money.

    Args:
        limit: Number of transactions to retrieve (default: 100)
        offset: Number of transactions to skip (default: 0)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_id: Specific account ID to filter by
    """
    try:

        async def _get_transactions():
            client = await get_monarch_client()

            # Build filters.
            # NOTE: The underlying monarchmoney lib accepts `account_ids` (List[str]),
            # NOT `account_id` (str). Passing `account_id` as a kwarg is silently
            # ignored by the lib (no error, no filter). We translate here.
            filters = {}
            if start_date:
                filters["start_date"] = start_date
            if end_date:
                filters["end_date"] = end_date
            if account_id:
                filters["account_ids"] = [account_id]  # lib expects a list

            return await client.get_transactions(limit=limit, offset=offset, **filters)

        transactions = run_async(_get_transactions())

        # Format transactions for display
        transaction_list = []
        for txn in transactions.get("allTransactions", {}).get("results", []):
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
                "is_pending": txn.get("isPending", False),
            }
            transaction_list.append(transaction_info)

        return json.dumps(transaction_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions: {e}")
        return f"Error getting transactions: {str(e)}"


@mcp.tool()
def get_budgets() -> str:
    """Get budget information from Monarch Money."""
    try:

        async def _get_budgets():
            client = await get_monarch_client()
            return await client.get_budgets()

        budgets = run_async(_get_budgets())

        # Format budgets for display
        budget_list = []
        for budget in budgets.get("budgets", []):
            budget_info = {
                "id": budget.get("id"),
                "name": budget.get("name"),
                "amount": budget.get("amount"),
                "spent": budget.get("spent"),
                "remaining": budget.get("remaining"),
                "category": budget.get("category", {}).get("name"),
                "period": budget.get("period"),
            }
            budget_list.append(budget_info)

        return json.dumps(budget_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get budgets: {e}")
        return f"Error getting budgets: {str(e)}"


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def create_transaction(
    account_id: str,
    amount: float,
    description: str,
    date: str,
    category_id: Optional[str] = None,
    merchant_name: Optional[str] = None,
) -> str:
    """
    Create a new transaction in Monarch Money.

    Args:
        account_id: The account ID to add the transaction to
        amount: Transaction amount (positive for income, negative for expenses)
        description: Transaction description
        date: Transaction date in YYYY-MM-DD format
        category_id: Optional category ID
        merchant_name: Optional merchant name
    """
    try:

        async def _create_transaction():
            client = await get_monarch_client()

            transaction_data = {
                "account_id": account_id,
                "amount": amount,
                "description": description,
                "date": date,
            }

            if category_id:
                transaction_data["category_id"] = category_id
            if merchant_name:
                transaction_data["merchant_name"] = merchant_name

            return await client.create_transaction(**transaction_data)

        result = run_async(_create_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction: {e}")
        return f"Error creating transaction: {str(e)}"


@mcp.tool()
def update_transaction(
    transaction_id: str,
    amount: Optional[float] = None,
    description: Optional[str] = None,
    category_id: Optional[str] = None,
    date: Optional[str] = None,
) -> str:
    """
    Update an existing transaction in Monarch Money.

    Args:
        transaction_id: The ID of the transaction to update
        amount: New transaction amount
        description: New transaction description
        category_id: New category ID
        date: New transaction date in YYYY-MM-DD format
    """
    try:

        async def _update_transaction():
            client = await get_monarch_client()

            update_data = {"transaction_id": transaction_id}

            if amount is not None:
                update_data["amount"] = amount
            if description is not None:
                update_data["description"] = description
            if category_id is not None:
                update_data["category_id"] = category_id
            if date is not None:
                update_data["date"] = date

            return await client.update_transaction(**update_data)

        result = run_async(_update_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update transaction: {e}")
        return f"Error updating transaction: {str(e)}"


@mcp.tool()
def refresh_accounts() -> str:
    """Request account data refresh from financial institutions."""
    try:

        async def _refresh_accounts():
            client = await get_monarch_client()
            return await client.request_accounts_refresh()

        result = run_async(_refresh_accounts())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to refresh accounts: {e}")
        return f"Error refreshing accounts: {str(e)}"


# ============================================================================
# NEW TOOLS - Account & Institution Data
# ============================================================================


@mcp.tool()
def get_account_history(
    account_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get daily balance history for a specific account.

    Args:
        account_id: The unique identifier for the account
        start_date: Start date (YYYY-MM-DD). Defaults to 30 days ago
        end_date: End date (YYYY-MM-DD). Defaults to today
    """
    try:

        async def _get_account_history():
            client = await get_monarch_client()
            kwargs = {}
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            return await client.get_account_history(account_id, **kwargs)

        result = run_async(_get_account_history())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get account history: {e}")
        return f"Error getting account history: {str(e)}"


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def get_transaction_details(transaction_id: str) -> str:
    """
    Get comprehensive details for a single transaction including all metadata.

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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def create_transaction_category(
    name: str,
    group_id: Optional[str] = None,
    icon: Optional[str] = None,
) -> str:
    """
    Create a new custom category for transactions.

    Args:
        name: Category name (max 50 chars, must be unique)
        group_id: Optional parent category group ID
        icon: Optional icon identifier
    """
    try:

        async def _create_transaction_category():
            client = await get_monarch_client()
            kwargs = {"name": name}
            if group_id:
                kwargs["group_id"] = group_id
            if icon:
                kwargs["icon"] = icon
            return await client.create_transaction_category(**kwargs)

        result = run_async(_create_transaction_category())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction category: {e}")
        return f"Error creating transaction category: {str(e)}"


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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
            return await client.set_budget_amount(category_id, **kwargs)

        result = run_async(_set_budget_amount())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to set budget amount: {e}")
        return f"Error setting budget amount: {str(e)}"


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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
