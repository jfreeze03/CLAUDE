"""Tests for multi-account organization support."""
import pandas as pd
import pytest


class TestMultiAccount:
    def test_sql_org_credits(self, mock_streamlit):
        from utils.multi_account import build_org_credit_summary_sql

        sql = build_org_credit_summary_sql(30)
        assert "ORGANIZATION_USAGE" in sql
        assert "account_name" in sql.lower()
        assert "credits_used" in sql.lower()

    def test_sql_contract_status(self, mock_streamlit):
        from utils.multi_account import build_org_contract_status_sql

        sql = build_org_contract_status_sql()
        assert "REMAINING_BALANCE_DAILY" in sql

    def test_sql_cross_account(self, mock_streamlit):
        from utils.multi_account import build_cross_account_comparison_sql

        sql = build_cross_account_comparison_sql(30)
        assert "pct_of_org" in sql.lower()

    def test_summarize_org_costs_empty(self, mock_streamlit):
        from utils.multi_account import summarize_org_costs

        result = summarize_org_costs(pd.DataFrame())
        assert result["total_credits"] == 0
        assert result["accounts"] == []

    def test_summarize_org_costs_with_data(self, mock_streamlit):
        from utils.multi_account import summarize_org_costs

        df = pd.DataFrame({
            "ACCOUNT_NAME": ["ACCT_A", "ACCT_A", "ACCT_B"],
            "CREDITS_USED": [100.0, 200.0, 150.0],
            "SERVICE_TYPE": ["WAREHOUSE_METERING", "WAREHOUSE_METERING", "CORTEX"],
        })
        result = summarize_org_costs(df)
        assert result["total_credits"] == 450.0
        assert len(result["accounts"]) == 2
        assert result["accounts"][0]["account"] == "ACCT_A"
        assert result["accounts"][0]["credits"] == 300.0
