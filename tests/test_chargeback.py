"""Tests for chargeback/cost allocation."""
import pandas as pd
import pytest


class TestChargeback:
    def test_format_chargeback_report_empty(self, mock_streamlit):
        from utils.chargeback import format_chargeback_report

        result = format_chargeback_report(pd.DataFrame())
        assert result["total_credits"] == 0
        assert result["owners"] == []

    def test_format_chargeback_report_with_data(self, mock_streamlit):
        from utils.chargeback import format_chargeback_report

        df = pd.DataFrame({
            "COST_OWNER": ["DBA / FinOps", "ALFA Development", "Unattributed"],
            "OWNER_EMAIL": ["dba@co.com", "dev@co.com", ""],
            "SERVICE_TIER": ["Tier 1", "Tier 2", "Unclassified"],
            "TOTAL_CREDITS": [500.0, 300.0, 50.0],
            "ATTRIBUTION_SOURCE": ["Owner Directory", "Owner Directory", "Unattributed"],
            "WAREHOUSES": ["WH_A, WH_B", "WH_C", "WH_D"],
        })

        result = format_chargeback_report(df, credit_price=3.68)
        assert result["total_credits"] == 850.0
        assert result["total_cost"] == pytest.approx(850.0 * 3.68, rel=0.01)
        assert len(result["owners"]) == 3
        assert result["owner_count"] == 2  # Excludes "Unattributed"
        assert result["unattributed_pct"] > 0

        # Check individual owner
        dba_owner = next(o for o in result["owners"] if o["owner"] == "DBA / FinOps")
        assert dba_owner["credits"] == 500.0
        assert dba_owner["pct_of_total"] > 50

    def test_sql_generation_by_owner(self, mock_streamlit):
        from utils.chargeback import build_chargeback_by_owner_sql

        sql = build_chargeback_by_owner_sql(days_back=30)
        assert "WAREHOUSE_METERING_HISTORY" in sql
        assert "OVERWATCH_OWNER_DIRECTORY" in sql
        assert "cost_owner" in sql.lower()

    def test_sql_generation_by_database(self, mock_streamlit):
        from utils.chargeback import build_chargeback_by_database_sql

        sql = build_chargeback_by_database_sql(days_back=30)
        assert "QUERY_HISTORY" in sql
        assert "database_name" in sql.lower()
        assert "allocated_credits" in sql.lower()

    def test_sql_generation_trend(self, mock_streamlit):
        from utils.chargeback import build_chargeback_trend_sql

        sql = build_chargeback_trend_sql(days_back=30)
        assert "week_start" in sql.lower()
        assert "weekly_credits" in sql.lower()
