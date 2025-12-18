[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/robcerda-monarch-mcp-server-badge.png)](https://mseep.ai/app/robcerda-monarch-mcp-server)

# Monarch Money MCP Server

A comprehensive Model Context Protocol (MCP) server for integrating with the Monarch Money personal finance platform. This server provides seamless access to your financial accounts, transactions, budgets, categories, tags, and analytics through Claude Desktop.

My MonarchMoney referral: https://www.monarchmoney.com/referral/ufmn0r83yf?r_source=share

**Built with the [MonarchMoney Python library](https://github.com/hammem/monarchmoney) by [@hammem](https://github.com/hammem)** - A fantastic unofficial API for Monarch Money with full MFA support.

<a href="https://glama.ai/mcp/servers/@robcerda/monarch-mcp-server">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@robcerda/monarch-mcp-server/badge" alt="monarch-mcp-server MCP server" />
</a>

## Quick Start

### 1. Installation

1. **Clone this repository**:
   ```bash
   git clone https://github.com/robcerda/monarch-mcp-server.git
   cd monarch-mcp-server
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

3. **Configure Claude Desktop**:
   Add this to your Claude Desktop configuration file:

   **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

   **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

   ```json
   {
     "mcpServers": {
       "Monarch Money": {
         "command": "/opt/homebrew/bin/uv",
         "args": [
           "run",
           "--with",
           "mcp[cli]",
           "--with-editable",
           "/path/to/your/monarch-mcp-server",
           "mcp",
           "run",
           "/path/to/your/monarch-mcp-server/src/monarch_mcp_server/server.py"
         ]
       }
     }
   }
   ```

   **Important**: Replace `/path/to/your/monarch-mcp-server` with your actual path!

4. **Restart Claude Desktop**

### 2. One-Time Authentication Setup

**Important**: For security and MFA support, authentication is done outside of Claude Desktop.

Open Terminal and run:
```bash
cd /path/to/your/monarch-mcp-server
python login_setup.py
```

Follow the prompts:
- Enter your Monarch Money email and password
- Provide 2FA code if you have MFA enabled
- Session will be saved automatically

### 3. Start Using in Claude Desktop

Once authenticated, you have access to 31 powerful tools for managing your finances.

---

## Features

### Account Management
- **Get Accounts**: View all linked financial accounts with balances and institution info
- **Get Account Holdings**: See securities and investments in investment accounts
- **Get Account History**: View daily balance history for trend analysis
- **Create Manual Account**: Add manual accounts for assets/liabilities not linked via Plaid
- **Update Account**: Modify account settings, balance, or visibility
- **Refresh Accounts**: Request real-time data updates from financial institutions
- **Check Refresh Status**: Poll for account refresh completion

### Transaction Management
- **Get Transactions**: Fetch transactions with filtering by date, account, and pagination
- **Get Transaction Details**: Comprehensive details for a single transaction
- **Create Transaction**: Add new transactions to accounts
- **Update Transaction**: Modify existing transactions
- **Get Transaction Splits**: View how a transaction is divided across categories
- **Update Transaction Splits**: Split transactions across multiple categories
- **Get Recurring Transactions**: View subscriptions and scheduled transactions
- **Get Transactions Summary**: Aggregated spending data by category/merchant

### Categories & Tags
- **Get Categories**: List all transaction categories
- **Get Category Groups**: View category hierarchy and groupings
- **Create Category**: Add custom categories for transaction organization
- **Get Tags**: List all user-defined tags
- **Create Tag**: Add new tags for transaction labeling
- **Set Transaction Tags**: Apply tags to transactions

### Budgets & Cashflow
- **Get Budgets**: Access budget information with spent/remaining amounts
- **Set Budget Amount**: Create or update budget amounts by category
- **Get Cashflow**: Detailed income/expense analysis over date ranges
- **Get Cashflow Summary**: High-level metrics (income, expenses, savings rate)

### Institutions & Account Info
- **Get Institutions**: View all linked financial institutions with sync status
- **Get Account Type Options**: Available account types for manual account creation
- **Get Subscription Details**: Monarch Money subscription status

### Security & Authentication
- **Setup Authentication**: Get instructions for secure auth setup
- **Check Auth Status**: Verify authentication state
- **Debug Session Loading**: Troubleshoot keyring issues

---

## Available Tools

### Authentication & Setup

| Tool | Description | Parameters |
|------|-------------|------------|
| `setup_authentication` | Get setup instructions | None |
| `check_auth_status` | Check authentication status | None |
| `debug_session_loading` | Debug keyring session issues | None |

### Accounts

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_accounts` | Get all financial accounts | None |
| `get_account_holdings` | Get investment holdings | `account_id` |
| `get_account_history` | Get daily balance history | `account_id`, `start_date`?, `end_date`? |
| `get_account_type_options` | Get available account types | None |
| `get_institutions` | Get linked institutions | None |
| `get_subscription_details` | Get subscription status | None |
| `create_manual_account` | Create manual account | `name`, `account_type`, `balance`, `account_subtype`?, `include_in_net_worth`? |
| `update_account` | Update account settings | `account_id`, `name`?, `balance`?, `include_in_net_worth`?, `hide_from_overview`? |
| `refresh_accounts` | Request account data refresh | None |
| `is_accounts_refresh_complete` | Check refresh completion | None |

### Transactions

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_transactions` | Get transactions with filtering | `limit`?, `offset`?, `start_date`?, `end_date`?, `account_id`? |
| `get_transaction_details` | Get full transaction details | `transaction_id` |
| `get_transaction_splits` | Get transaction splits | `transaction_id` |
| `get_transactions_summary` | Get aggregated summary | `start_date`?, `end_date`? |
| `get_recurring_transactions` | Get recurring/scheduled transactions | None |
| `create_transaction` | Create new transaction | `account_id`, `amount`, `description`, `date`, `category_id`?, `merchant_name`? |
| `update_transaction` | Update existing transaction | `transaction_id`, `amount`?, `description`?, `category_id`?, `date`? |
| `update_transaction_splits` | Split transaction across categories | `transaction_id`, `splits` (JSON array) |

### Categories & Tags

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_transaction_categories` | Get all categories | None |
| `get_transaction_category_groups` | Get category groups | None |
| `create_transaction_category` | Create custom category | `name`, `group_id`?, `icon`? |
| `get_transaction_tags` | Get all tags | None |
| `create_transaction_tag` | Create new tag | `name`, `color`? |
| `set_transaction_tags` | Apply tags to transaction | `transaction_id`, `tag_ids` (JSON array) |

### Budgets & Cashflow

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_budgets` | Get budget information | None |
| `set_budget_amount` | Set/update budget amount | `category_id`, `amount`, `month`?, `apply_to_future`? |
| `get_cashflow` | Get cashflow analysis | `start_date`?, `end_date`? |
| `get_cashflow_summary` | Get high-level cashflow metrics | `start_date`?, `end_date`? |

---

## Usage Examples

### View Your Accounts
```
Show me all my financial accounts with their current balances
```

### Get Recent Transactions
```
Show me my last 50 transactions from this month
```

### Analyze Spending by Category
```
Get a summary of my spending for November 2024 broken down by category
```

### Check Budget Status
```
Show my current budget status - what have I spent vs budgeted?
```

### Track Subscriptions
```
What recurring transactions and subscriptions do I have?
```

### View Account History
```
Show me how my savings account balance has changed over the last 6 months
```

### Split a Transaction
```
Split my $150 Costco transaction: $100 for groceries and $50 for household items
```

### Create a Custom Category
```
Create a new category called "Side Hustle Income" for tracking my freelance earnings
```

### Tag Transactions
```
Tag my recent business dinner as "Tax Deductible" and "Client Entertainment"
```

### Set a Budget
```
Set my dining out budget to $500 for this month and apply it to future months
```

### Create Manual Account
```
Create a manual account for my car valued at $25,000
```

### Check Institution Status
```
Which of my bank connections are working? When did they last sync?
```

---

## Date Formats

- All dates should be in `YYYY-MM-DD` format (e.g., "2024-01-15")
- Month format for budgets: `YYYY-MM` (e.g., "2024-12")
- Transaction amounts: **positive** for income, **negative** for expenses

---

## Troubleshooting

### Authentication Issues
If you see "Authentication needed" errors:
1. Run the setup command: `cd /path/to/your/monarch-mcp-server && python login_setup.py`
2. Restart Claude Desktop
3. Try using a tool like `get_accounts`

### Session Expired
Sessions last for weeks, but if expired:
1. Run the same setup command again
2. Enter your credentials and 2FA code
3. Session will be refreshed automatically

### Common Error Messages

| Error | Solution |
|-------|----------|
| "No valid session found" | Run `login_setup.py` |
| "Invalid account ID" | Use `get_accounts` to see valid account IDs |
| "Invalid category ID" | Use `get_transaction_categories` to see valid IDs |
| "Invalid transaction ID" | Verify transaction exists with `get_transactions` |
| "Date format error" | Use YYYY-MM-DD format for dates |
| "Split amounts don't sum" | Ensure split amounts equal original transaction total |

---

## Technical Details

### Project Structure
```
monarch-mcp-server/
├── src/monarch_mcp_server/
│   ├── __init__.py
│   ├── server.py              # Main server implementation (31 tools)
│   └── secure_session.py      # Secure session management
├── login_setup.py             # Authentication setup script
├── pyproject.toml             # Project configuration
├── requirements.txt           # Dependencies
├── PRD.md                     # Product Requirements Document
└── README.md                  # This documentation
```

### Session Management
- Sessions are stored securely using system keyring
- Automatic session discovery and loading
- Sessions persist across Claude Desktop restarts
- No need for frequent re-authentication

### Security Features
- Credentials never transmitted through Claude Desktop
- MFA/2FA fully supported
- Session tokens stored in system keyring
- Authentication handled in secure terminal environment

---

## Acknowledgments

This MCP server is built on top of the excellent [MonarchMoney Python library](https://github.com/hammem/monarchmoney) created by [@hammem](https://github.com/hammem). Their library provides the robust foundation that makes this integration possible, including:

- Secure authentication with MFA support
- Comprehensive API coverage for Monarch Money
- Session management and persistence
- Well-documented and maintained codebase

Thank you to [@hammem](https://github.com/hammem) for creating and maintaining this essential library!

---

## License

MIT License

---

## Support

For issues:
1. Check authentication with `check_auth_status`
2. Run the setup command again: `cd /path/to/your/monarch-mcp-server && python login_setup.py`
3. Check error logs for detailed messages
4. Ensure Monarch Money service is accessible
5. Open an issue on GitHub with error details

---

## Updates

To update the server:
1. Pull latest changes from repository
2. Restart Claude Desktop
3. Re-run authentication if needed: `python login_setup.py`
