# Product Requirements Document

## Monarch Money MCP Server v2.0

**Document Version:** 1.0  
**Date:** December 18, 2025  
**Author:** Joe (Customer Solutions Architect)  
**Status:** Draft

---

## Executive Summary

This PRD outlines the expansion of the Monarch Money MCP Server from its current 10 tools to a comprehensive 30+ tool suite. The existing implementation covers approximately 30% of the underlying `monarchmoney` Python library's functionality. This update will bring near-complete API parity while maintaining appropriate safety guardrails for AI-assisted financial management.

### Current State

- 10 MCP tools implemented
- Basic read operations (accounts, transactions, budgets, cashflow)
- Limited write operations (create/update transactions, refresh accounts)

### Target State

- 30 MCP tools (up from 10)
- Complete read operation coverage
- Comprehensive write operations with safety controls
- Enhanced error handling and validation
- No destructive delete operations (safety-first design)

---

## Goals & Non-Goals

### Goals

1. **API Parity**: Expose all safe, useful methods from the `monarchmoney` library
2. **Power User Enablement**: Support advanced workflows (recurring transactions, splits, tags, categories)
3. **Budget Management**: Enable full budget CRUD operations
4. **Account Management**: Support manual account creation and updates
5. **Safety First**: Implement confirmation patterns for destructive operations

### Non-Goals

1. Bulk destructive operations (mass category deletion)
2. Account deletion (too risky for AI-assisted operations)
3. File upload operations (complexity vs. value tradeoff)
4. Blocking/synchronous refresh operations (timeout risk)

---

## Methods Excluded (With Rationale)

| Method                                 | Risk Level  | Rationale                                                                                                                                                                               |
| -------------------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `delete_account`                       | 🔴 Critical | Permanently removes all transaction history. Irreversible. One misunderstood prompt could destroy years of financial data. Users should perform this action directly in the Monarch UI. |
| `delete_transaction`                   | 🟠 High     | Risk of accidental data loss. AI misinterpreting "delete" vs "update" could remove important transaction records. Users should delete transactions directly in Monarch UI.             |
| `delete_transaction_category`          | 🟠 High     | Could orphan transactions assigned to the deleted category. Users should manage category deletion directly in Monarch UI with proper transaction reassignment.                          |
| `delete_transaction_categories` (bulk) | 🟠 High     | Mass deletion of categories could orphan hundreds of transactions. Even more dangerous than single deletion.                                                                             |
| `upload_account_balance_history`       | 🟡 Medium   | Requires file handling that adds complexity. Edge case functionality that most users won't need via AI assistant.                                                                       |
| `request_accounts_refresh_and_wait`    | 🟡 Medium   | Blocking call that could timeout in MCP context. The async `refresh_accounts` + `is_accounts_refresh_complete` pattern is safer and more responsive.                                    |

---

## New Tools Specification

### Category 1: Account & Institution Data

#### 1.1 `get_account_history`

**Purpose**: Retrieve daily balance history for a specific account. Essential for net worth tracking, trend analysis, and financial planning.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `account_id` | string | Yes | The unique identifier for the account |
| `start_date` | string | No | Start date (YYYY-MM-DD). Defaults to 30 days ago |
| `end_date` | string | No | End date (YYYY-MM-DD). Defaults to today |

**Returns**: Array of daily balance snapshots with date and balance fields

**Example Use Cases**:

- "Show me how my savings account balance has changed over the last 6 months"
- "Graph my investment account performance this year"
- "When did my checking account balance dip below $1000?"

**Implementation Notes**:

- Maps to `mm.get_account_history(account_id)`
- Consider caching for frequently accessed accounts
- Large date ranges may return significant data; consider pagination

---

#### 1.2 `get_account_type_options`

**Purpose**: Retrieve all available account types and subtypes in Monarch Money. Useful for account creation and categorization.

**Parameters**: None

**Returns**: Hierarchical structure of account types (e.g., Banking → Checking, Savings; Investment → Brokerage, 401k, IRA)

**Example Use Cases**:

- "What types of accounts can I create in Monarch?"
- "What's the difference between account subtypes?"

**Implementation Notes**:

- Maps to `mm.get_account_type_options()`
- Static data; could be cached aggressively
- Useful prerequisite call before `create_manual_account`

---

#### 1.3 `get_institutions`

**Purpose**: Retrieve all financial institutions linked to the Monarch Money account.

**Parameters**: None

**Returns**: Array of institution objects with id, name, logo, connection status, last sync time

**Example Use Cases**:

- "Which banks do I have connected?"
- "Is my Chase connection working?"
- "When was the last time my accounts synced?"

**Implementation Notes**:

- Maps to `mm.get_institutions()`
- Useful for debugging sync issues
- Can help users identify which institution is causing problems

---

#### 1.4 `get_subscription_details`

**Purpose**: Retrieve Monarch Money subscription status (paid, trial, expiration).

**Parameters**: None

**Returns**: Subscription object with status, plan type, expiration date, features

**Example Use Cases**:

- "Is my Monarch subscription active?"
- "When does my trial end?"

**Implementation Notes**:

- Maps to `mm.get_subscription_details()`
- Low-frequency call; no caching needed

---

#### 1.5 `is_accounts_refresh_complete`

**Purpose**: Check the status of a running account refresh operation. Companion to the existing `refresh_accounts` tool.

**Parameters**: None

**Returns**: Boolean indicating if refresh is complete, plus any error states

**Example Use Cases**:

- "Is the account sync still running?"
- "Did the refresh complete successfully?"

**Implementation Notes**:

- Maps to `mm.is_accounts_refresh_complete()`
- Should be called after `refresh_accounts` to poll status
- Consider implementing a polling helper that calls this automatically

---

### Category 2: Transaction Management

#### 2.1 `get_transaction_details`

**Purpose**: Retrieve comprehensive details for a single transaction, including all metadata, attachments, and related data.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `transaction_id` | string | Yes | The unique identifier for the transaction |

**Returns**: Complete transaction object with all fields (amount, date, merchant, category, tags, notes, attachments, split info, etc.)

**Example Use Cases**:

- "Tell me everything about transaction ID abc123"
- "What category is this transaction in?"
- "Does this transaction have any attachments?"

**Implementation Notes**:

- Maps to `mm.get_transaction_details(transaction_id)`
- More comprehensive than the transaction objects returned by `get_transactions`

---

#### 2.2 `get_transaction_splits`

**Purpose**: Retrieve split information for a transaction that has been divided across multiple categories.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `transaction_id` | string | Yes | The unique identifier for the transaction |

**Returns**: Array of split objects, each with category_id, amount, and optional notes

**Example Use Cases**:

- "How is this Costco transaction split?"
- "Show me the breakdown of my Amazon order"

**Implementation Notes**:

- Maps to `mm.get_transaction_splits(transaction_id)`
- Returns empty array if transaction is not split

---

#### 2.3 `update_transaction_splits`

**Purpose**: Split a transaction across multiple categories or modify existing splits.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `transaction_id` | string | Yes | The transaction to split |
| `splits` | array | Yes | Array of split objects |

**Split Object Structure**:

```json
{
  "category_id": "string",
  "amount": "number (positive)",
  "merchant_name": "string (optional)",
  "notes": "string (optional)"
}
```

**Validation Rules**:

- Sum of split amounts must equal original transaction amount
- At least 2 splits required (otherwise just update the category)
- All category_ids must be valid

**Example Use Cases**:

- "Split this $150 Costco trip: $100 groceries, $50 household"
- "Divide my Amazon order between office supplies and electronics"

**Implementation Notes**:

- Maps to `mm.update_transaction_splits(transaction_id, split_data)`
- Should validate split amounts sum to transaction total before submitting
- Provide helpful error if amounts don't balance

---

#### 2.4 `get_transactions_summary`

**Purpose**: Retrieve aggregated transaction summary data (totals by category, merchant, etc.).

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` | string | No | Start date (YYYY-MM-DD) |
| `end_date` | string | No | End date (YYYY-MM-DD) |

**Returns**: Summary object with totals, counts, and breakdowns

**Example Use Cases**:

- "Give me a summary of my spending this month"
- "How many transactions did I have in Q3?"

**Implementation Notes**:

- Maps to `mm.get_transactions_summary()`
- Useful for high-level reporting without fetching all transactions

---

#### 2.5 `get_recurring_transactions`

**Purpose**: Retrieve all recurring/scheduled transactions with their frequency, next occurrence, and merchant details.

**Parameters**: None (or optional filters)

**Returns**: Array of recurring transaction objects with:

- Transaction details (amount, merchant, category)
- Recurrence pattern (weekly, monthly, etc.)
- Next expected date
- Account information
- Historical accuracy metrics

**Example Use Cases**:

- "What bills do I have coming up?"
- "Show me all my subscriptions"
- "Which recurring transactions are from my Chase card?"
- "What's my total monthly recurring expenses?"

**Implementation Notes**:

- Maps to `mm.get_recurring_transactions()`
- Critical for cash flow forecasting
- Consider grouping by frequency or due date

---

### Category 3: Categories & Tags

#### 3.1 `get_transaction_categories`

**Purpose**: Retrieve all transaction categories configured in the account.

**Parameters**: None

**Returns**: Array of category objects with id, name, icon, group_id, and whether it's a system or custom category

**Example Use Cases**:

- "What categories do I have set up?"
- "What's the category ID for 'Groceries'?"
- "Show me all my custom categories"

**Implementation Notes**:

- Maps to `mm.get_transaction_categories()`
- Essential prerequisite for many other operations (splits, transaction updates)
- Consider caching with TTL

---

#### 3.2 `get_transaction_category_groups`

**Purpose**: Retrieve all category groups (parent groupings for categories).

**Parameters**: None

**Returns**: Array of category group objects with id, name, and associated category IDs

**Example Use Cases**:

- "What are my category groups?"
- "Which categories are in the 'Housing' group?"

**Implementation Notes**:

- Maps to `mm.get_transaction_category_groups()`
- Useful for understanding category hierarchy

---

#### 3.3 `create_transaction_category`

**Purpose**: Create a new custom category for transactions.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Category name (max 50 chars) |
| `group_id` | string | No | Parent category group ID |
| `icon` | string | No | Icon identifier |

**Validation Rules**:

- Name must be unique (case-insensitive)
- Name cannot match system category names

**Returns**: Newly created category object with ID

**Example Use Cases**:

- "Create a new category called 'Side Hustle Income'"
- "Add a 'Pet Supplies' category under the Shopping group"

**Implementation Notes**:

- Maps to `mm.create_transaction_category(name)`
- Should check for existing category with same name first
- Return the new category ID for immediate use

---

#### 3.4 `get_transaction_tags`

**Purpose**: Retrieve all tags configured in the account.

**Parameters**: None

**Returns**: Array of tag objects with id, name, and color

**Example Use Cases**:

- "What tags do I have?"
- "What's the tag ID for 'Tax Deductible'?"

**Implementation Notes**:

- Maps to `mm.get_transaction_tags()`
- Tags are user-defined labels that can be applied to any transaction
- Different from categories (transactions have one category, but can have multiple tags)

---

#### 3.5 `create_transaction_tag`

**Purpose**: Create a new tag for transactions.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Tag name (max 30 chars) |
| `color` | string | No | Hex color code |

**Returns**: Newly created tag object with ID

**Example Use Cases**:

- "Create a tag called 'Reimbursable'"
- "Add a 'Trip to Japan' tag"

**Implementation Notes**:

- Maps to `mm.create_transaction_tag(name)`
- Should check for existing tag with same name

---

#### 3.6 `set_transaction_tags`

**Purpose**: Apply one or more tags to a transaction.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `transaction_id` | string | Yes | The transaction to tag |
| `tag_ids` | array | Yes | Array of tag IDs to apply |

**Returns**: Updated transaction with tags

**Example Use Cases**:

- "Tag this transaction as 'Tax Deductible' and 'Business Expense'"
- "Add the 'Vacation' tag to all my Hawaii transactions"

**Implementation Notes**:

- Maps to `mm.set_transaction_tags(transaction_id, tag_ids)`
- Replaces existing tags (not additive) - document this clearly
- Empty array removes all tags

---

### Category 4: Budgets

#### 4.1 `set_budget_amount`

**Purpose**: Set or update a budget amount for a specific category and month.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `category_id` | string | Yes | The category to budget |
| `amount` | number | Yes | Budget amount (0 to clear) |
| `month` | string | No | Month (YYYY-MM). Defaults to current month |
| `apply_to_future` | boolean | No | Apply to this and all future months |

**Validation Rules**:

- Amount must be non-negative
- Amount of 0 clears/unsets the budget
- Month must be current or future

**Returns**: Updated budget object

**Example Use Cases**:

- "Set my dining out budget to $500 for this month"
- "Increase my grocery budget to $800 starting next month"
- "Clear my entertainment budget"

**Implementation Notes**:

- Maps to `mm.set_budget_amount(category_id, amount, start_date)`
- Consider showing current budget before updating
- Useful to show the delta (was $X, now $Y)

---

#### 4.2 `get_cashflow_summary`

**Purpose**: Retrieve high-level cashflow metrics (income, expenses, savings, savings rate).

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` | string | No | Start date (YYYY-MM-DD) |
| `end_date` | string | No | End date (YYYY-MM-DD) |

**Returns**: Summary object with:

- Total income
- Total expenses
- Net savings (income - expenses)
- Savings rate percentage

**Example Use Cases**:

- "What's my savings rate this month?"
- "How much did I save in Q4?"
- "Compare my income vs expenses for the year"

**Implementation Notes**:

- Maps to `mm.get_cashflow_summary(start_date, end_date)`
- Complement to existing `get_cashflow` which has more detail
- Good for quick financial health checks

---

### Category 5: Account Management

#### 5.1 `create_manual_account`

**Purpose**: Create a new manual (non-linked) account for tracking assets or liabilities not connected via Plaid.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Account name |
| `account_type` | string | Yes | Type from `get_account_type_options` |
| `account_subtype` | string | No | Subtype (e.g., "checking", "savings") |
| `balance` | number | Yes | Starting balance |
| `include_in_net_worth` | boolean | No | Include in net worth calculations (default: true) |

**Returns**: Newly created account object with ID

**Example Use Cases**:

- "Create a manual account for my car worth $25,000"
- "Add my HSA account with a $5,000 balance"
- "Track my home equity as a manual asset"

**Implementation Notes**:

- Maps to `mm.create_manual_account(...)`
- Should call `get_account_type_options` first to validate type
- Consider prompting for all required fields interactively

---

#### 5.2 `update_account`

**Purpose**: Update an existing account's settings or balance.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `account_id` | string | Yes | The account to update |
| `name` | string | No | New account name |
| `balance` | number | No | New balance (manual accounts only) |
| `include_in_net_worth` | boolean | No | Update net worth inclusion |
| `hide_from_overview` | boolean | No | Hide from main dashboard |

**Returns**: Updated account object

**Example Use Cases**:

- "Update my car's value to $22,000"
- "Rename my 'Old Savings' account to 'Emergency Fund'"
- "Exclude my HSA from net worth calculations"

**Implementation Notes**:

- Maps to `mm.update_account(account_id, ...)`
- Balance updates only work for manual accounts
- Linked account balances are controlled by institution sync

---

---

## Error Handling Specifications

### Standard Error Response Format

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": {},
    "suggestion": "Suggested action to resolve"
  }
}
```

### Error Codes

| Code                     | Description                          | User Action                          |
| ------------------------ | ------------------------------------ | ------------------------------------ |
| `AUTH_REQUIRED`          | Session expired or not authenticated | Run `login_setup.py`                 |
| `AUTH_INVALID`           | Invalid credentials                  | Check email/password                 |
| `INVALID_ACCOUNT_ID`     | Account ID not found                 | Use `get_accounts` to find valid IDs |
| `INVALID_CATEGORY_ID`    | Category ID not found                | Use `get_transaction_categories`     |
| `INVALID_TRANSACTION_ID` | Transaction ID not found             | Verify transaction exists            |
| `INVALID_DATE_FORMAT`    | Date not in YYYY-MM-DD format        | Correct date format                  |
| `VALIDATION_ERROR`       | Input validation failed              | Check parameter requirements         |
| `SPLIT_AMOUNT_MISMATCH`  | Split amounts don't sum to total     | Adjust split amounts                 |
| `RATE_LIMIT`             | Too many requests                    | Wait and retry                       |
| `MONARCH_API_ERROR`      | Upstream API error                   | Check Monarch status, retry later    |

---

## Security Considerations

### Destructive Operation Safeguards

For operations that modify or delete data, implement a two-phase approach:

**Phase 1 - Preview**: Return details of what will be affected

```
User: "Delete transaction abc123"
Claude: "This will delete:
  - Transaction: Starbucks Coffee
  - Amount: -$5.75
  - Date: 2025-12-15
  - Account: Chase Checking

  Please confirm by saying 'Yes, delete this transaction'"
```

**Phase 2 - Execute**: Perform the operation after confirmation

### Data Validation

- All IDs should be validated before operations
- Amounts should be validated as numbers
- Dates should be parsed and validated
- String inputs should be sanitized and length-checked

### Rate Limiting

- Implement client-side rate limiting to prevent API abuse
- Suggested: Max 60 requests per minute
- Exponential backoff on rate limit errors

---

## Implementation Priority

### Phase 1: Essential Reads (Week 1)

High-value, low-risk additions that unlock common workflows.

| Tool                           | Priority | Effort |
| ------------------------------ | -------- | ------ |
| `get_transaction_categories`   | P0       | Low    |
| `get_transaction_tags`         | P0       | Low    |
| `get_recurring_transactions`   | P0       | Low    |
| `is_accounts_refresh_complete` | P0       | Low    |
| `get_cashflow_summary`         | P1       | Low    |

### Phase 2: Transaction Power Features (Week 2)

Enable full transaction management.

| Tool                        | Priority | Effort |
| --------------------------- | -------- | ------ |
| `get_transaction_details`   | P0       | Low    |
| `get_transaction_splits`    | P1       | Low    |
| `update_transaction_splits` | P1       | Medium |
| `set_transaction_tags`      | P1       | Low    |

### Phase 3: Categories & Budgets (Week 3)

Category and budget management (create operations only - no deletes for safety).

| Tool                          | Priority | Effort |
| ----------------------------- | -------- | ------ |
| `create_transaction_category` | P1       | Low    |
| `create_transaction_tag`      | P1       | Low    |
| `set_budget_amount`           | P0       | Medium |

### Phase 4: Account Management (Week 4)

Account lifecycle management.

| Tool                              | Priority | Effort |
| --------------------------------- | -------- | ------ |
| `get_account_history`             | P1       | Low    |
| `get_institutions`                | P2       | Low    |
| `create_manual_account`           | P1       | Medium |
| `update_account`                  | P2       | Medium |
| `get_account_type_options`        | P2       | Low    |
| `get_subscription_details`        | P3       | Low    |
| `get_transactions_summary`        | P2       | Low    |
| `get_transaction_category_groups` | P3       | Low    |

---

## Testing Requirements

### Unit Tests

Each new tool should have tests covering:

- Happy path with valid inputs
- All parameter combinations
- Error cases (invalid IDs, bad dates, etc.)
- Edge cases (empty results, large datasets)

### Integration Tests

- Full workflow tests (e.g., create category → use in transaction → delete category)
- Authentication session handling
- Rate limit behavior

### Manual Testing Checklist

- [ ] Test each tool in Claude Desktop
- [ ] Verify error messages are helpful
- [ ] Confirm destructive operations show warnings
- [ ] Test with real Monarch Money account data
- [ ] Verify date handling across timezones

---

## Documentation Updates

### README.md Changes

1. Update feature list with new tools
2. Add examples for new common workflows
3. Document new parameters in tools table
4. Add troubleshooting for new error codes

### New Documentation Sections

- **Workflow Guide**: Common multi-tool workflows (e.g., "Splitting a transaction")
- **Category & Tag Management**: How to organize transactions
- **Budget Planning**: Using budget tools effectively
- **Account Tracking**: Manual account best practices

---

## Success Metrics

### Adoption Metrics

- Tool usage frequency (which new tools get used most)
- Error rate by tool (identify usability issues)
- User feedback/issues on GitHub

### Quality Metrics

- < 1% error rate for valid requests
- < 500ms average response time
- 100% test coverage for new tools

### User Value Metrics

- Reduced steps for common workflows
- Support for previously impossible workflows
- User satisfaction (GitHub stars, feedback)

---

## Appendix A: Complete Tool List (v2.0)

### Existing Tools (10)

1. `setup_authentication`
2. `check_auth_status`
3. `get_accounts`
4. `get_transactions`
5. `get_budgets`
6. `get_cashflow`
7. `get_account_holdings`
8. `create_transaction`
9. `update_transaction`
10. `refresh_accounts`

### New Tools (20)

11. `get_account_history`
12. `get_account_type_options`
13. `get_institutions`
14. `get_subscription_details`
15. `is_accounts_refresh_complete`
16. `get_transaction_details`
17. `get_transaction_splits`
18. `update_transaction_splits`
19. `get_transactions_summary`
20. `get_recurring_transactions`
21. `get_transaction_categories`
22. `get_transaction_category_groups`
23. `create_transaction_category`
24. `get_transaction_tags`
25. `create_transaction_tag`
26. `set_transaction_tags`
27. `set_budget_amount`
28. `get_cashflow_summary`
29. `create_manual_account`
30. `update_account`

**Total: 30 tools**

> **Note**: Delete operations (`delete_transaction`, `delete_transaction_category`) are intentionally excluded for safety. Users should perform deletions directly in the Monarch Money UI.

---

## Appendix B: Library Method Mapping

| MCP Tool                          | Library Method                                             |
| --------------------------------- | ---------------------------------------------------------- |
| `get_account_history`             | `mm.get_account_history(account_id)`                       |
| `get_account_type_options`        | `mm.get_account_type_options()`                            |
| `get_institutions`                | `mm.get_institutions()`                                    |
| `get_subscription_details`        | `mm.get_subscription_details()`                            |
| `is_accounts_refresh_complete`    | `mm.is_accounts_refresh_complete()`                        |
| `get_transaction_details`         | `mm.get_transaction_details(transaction_id)`               |
| `get_transaction_splits`          | `mm.get_transaction_splits(transaction_id)`                |
| `update_transaction_splits`       | `mm.update_transaction_splits(transaction_id, split_data)` |
| `get_transactions_summary`        | `mm.get_transactions_summary()`                            |
| `get_recurring_transactions`      | `mm.get_recurring_transactions()`                          |
| `get_transaction_categories`      | `mm.get_transaction_categories()`                          |
| `get_transaction_category_groups` | `mm.get_transaction_category_groups()`                     |
| `create_transaction_category`     | `mm.create_transaction_category(name)`                     |
| `get_transaction_tags`            | `mm.get_transaction_tags()`                                |
| `create_transaction_tag`          | `mm.create_transaction_tag(name)`                          |
| `set_transaction_tags`            | `mm.set_transaction_tags(transaction_id, tag_ids)`         |
| `set_budget_amount`               | `mm.set_budget_amount(category_id, amount, start_date)`    |
| `get_cashflow_summary`            | `mm.get_cashflow_summary(start_date, end_date)`            |
| `create_manual_account`           | `mm.create_manual_account(...)`                            |
| `update_account`                  | `mm.update_account(account_id, ...)`                       |

---

## Revision History

| Version | Date       | Author | Changes                                                    |
| ------- | ---------- | ------ | ---------------------------------------------------------- |
| 1.0     | 2025-12-18 | Joe    | Initial draft                                              |
| 1.1     | 2025-12-18 | Joe    | Removed delete operations for safety; finalized 30 tools   |
