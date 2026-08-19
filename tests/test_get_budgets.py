"""
Regression test for the get_budgets() wrong-response-key bug.

History
-------
`monarch_mcp_server.server.get_budgets` (the MCP tool handler) used to parse
the client response like this:

    for budget in budgets.get("budgets", []):
        ...

but the real client method (`monarchmoney.MonarchMoney.get_budgets`, a
GraphQL call named `GetJointPlanningData`) never returns a top-level
"budgets" key. Its actual shape (see
`.venv/Lib/site-packages/monarchmoney/monarchmoney.py` around line 1161) is:

    {
      "budgetData": {
        "monthlyAmountsByCategory": [
          {
            "category": {"id": ...},
            "monthlyAmounts": [
              {
                "month": ...,
                "plannedCashFlowAmount": ...,
                "actualAmount": ...,
                "remainingAmount": ...,
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
        {"id": ..., "name": ..., "categories": [{"id": ..., "name": ...}, ...]},
        ...
      ],
      ...
    }

`.get("budgets", [])` on this dict always returns `[]`, so `get_budgets()`
was silently broken -- it returned an empty budget list regardless of what
budgets were actually set in Monarch. This was caught in production on
2026-08-19: 27 budget lines had just been written successfully via
`set_budget_amount`, but `get_budgets()` still reported [].

This test pins the parsing logic to the REAL client response shape (not an
invented one) so a future regression is caught by CI instead of live use.
"""

from monarch_mcp_server.server import _parse_budgets_response

# A response shaped exactly like the real
# `monarchmoney.MonarchMoney.get_budgets()` GraphQL payload, trimmed to the
# fields the handler actually consumes.
REAL_SHAPE_RESPONSE = {
    "budgetData": {
        "monthlyAmountsByCategory": [
            {
                "category": {"id": "cat-gas-electric", "__typename": "Category"},
                "monthlyAmounts": [
                    {
                        "month": "2026-08-01",
                        "plannedCashFlowAmount": 290.0,
                        "plannedSetAsideAmount": 0.0,
                        "actualAmount": 143.22,
                        "remainingAmount": 146.78,
                        "previousMonthRolloverAmount": 0.0,
                        "rolloverType": None,
                        "__typename": "MonthlyAmount",
                    }
                ],
                "__typename": "CategoryMonthlyAmounts",
            },
            {
                "category": {"id": "cat-groceries", "__typename": "Category"},
                "monthlyAmounts": [
                    {
                        "month": "2026-08-01",
                        "plannedCashFlowAmount": 1250.0,
                        "plannedSetAsideAmount": 0.0,
                        "actualAmount": 612.50,
                        "remainingAmount": 637.50,
                        "previousMonthRolloverAmount": 0.0,
                        "rolloverType": None,
                        "__typename": "MonthlyAmount",
                    }
                ],
                "__typename": "CategoryMonthlyAmounts",
            },
        ],
        "monthlyAmountsByCategoryGroup": [],
        "monthlyAmountsForFlexExpense": [],
        "totalsByMonth": [],
        "__typename": "BudgetData",
    },
    "categoryGroups": [
        {
            "id": "grp-utilities",
            "name": "Utilities",
            "order": 1,
            "groupLevelBudgetingEnabled": False,
            "budgetVariability": None,
            "rolloverPeriod": None,
            "categories": [
                {"id": "cat-gas-electric", "name": "Gas & Electric", "order": 1},
            ],
            "type": "expense",
            "__typename": "CategoryGroup",
        },
        {
            "id": "grp-food",
            "name": "Food & Dining",
            "order": 2,
            "groupLevelBudgetingEnabled": False,
            "budgetVariability": None,
            "rolloverPeriod": None,
            "categories": [
                {"id": "cat-groceries", "name": "Groceries", "order": 1},
            ],
            "type": "expense",
            "__typename": "CategoryGroup",
        },
    ],
    "goalsV2": [],
    "budgetSystem": "categoryBudgetSystem",
}


def test_get_budgets_old_key_is_absent_in_real_response():
    """
    Sanity check on the fixture itself: proves the old (buggy) assumption
    -- a top-level "budgets" key -- is genuinely absent from the real
    response shape, so this fixture would have caught the original bug.
    """
    assert "budgets" not in REAL_SHAPE_RESPONSE


def test_parse_budgets_response_extracts_amounts_from_real_shape():
    """
    Core regression test: the parser must pull amounts out of
    budgetData.monthlyAmountsByCategory[].monthlyAmounts[], not a
    nonexistent top-level "budgets" list.
    """
    result = _parse_budgets_response(REAL_SHAPE_RESPONSE)

    assert len(result) == 2

    gas = next(r for r in result if r["category_id"] == "cat-gas-electric")
    assert gas["category"] == "Gas & Electric"
    assert gas["amount"] == 290.0
    assert gas["spent"] == 143.22
    assert gas["remaining"] == 146.78
    assert gas["month"] == "2026-08-01"

    groceries = next(r for r in result if r["category_id"] == "cat-groceries")
    assert groceries["category"] == "Groceries"
    assert groceries["amount"] == 1250.0
    assert groceries["spent"] == 612.50
    assert groceries["remaining"] == 637.50


def test_parse_budgets_response_handles_missing_category_name():
    """
    If a category id in monthlyAmountsByCategory has no matching entry in
    categoryGroups (e.g. an archived category), the parser should degrade
    gracefully to None rather than raising.
    """
    response = {
        "budgetData": {
            "monthlyAmountsByCategory": [
                {
                    "category": {"id": "cat-unknown"},
                    "monthlyAmounts": [
                        {
                            "month": "2026-08-01",
                            "plannedCashFlowAmount": 50.0,
                            "actualAmount": 10.0,
                            "remainingAmount": 40.0,
                        }
                    ],
                }
            ]
        },
        "categoryGroups": [],
    }

    result = _parse_budgets_response(response)

    assert len(result) == 1
    assert result[0]["category_id"] == "cat-unknown"
    assert result[0]["category"] is None
    assert result[0]["amount"] == 50.0


def test_parse_budgets_response_empty_when_no_budget_data():
    assert _parse_budgets_response({}) == []
    assert _parse_budgets_response({"budgetData": {}}) == []
