"""Tests for data quality monitoring."""
import pandas as pd
import pytest


class TestDataQuality:
    def test_summarize_empty(self, mock_streamlit):
        from utils.data_quality import summarize_data_quality

        result = summarize_data_quality()
        assert result["overall_status"] == "unknown"
        assert result["stale_tables"] == 0

    def test_summarize_with_stale_tables(self, mock_streamlit):
        from utils.data_quality import summarize_data_quality

        freshness_df = pd.DataFrame({
            "DATABASE_NAME": ["DB1", "DB1", "DB2"],
            "TABLE_NAME": ["T1", "T2", "T3"],
            "FRESHNESS_STATUS": ["Critical", "Stale", "Fresh"],
            "HOURS_SINCE_LOAD": [72, 30, 2],
        })
        result = summarize_data_quality(freshness_df=freshness_df)
        assert result["critical_tables"] == 1
        assert result["stale_tables"] == 1
        assert result["overall_status"] == "critical"
        assert len(result["top_issues"]) > 0

    def test_summarize_with_drift(self, mock_streamlit):
        from utils.data_quality import summarize_data_quality

        drift_df = pd.DataFrame({
            "TABLE_NAME": ["T1", "T2", "T3", "T4", "T5", "T6"],
            "DRIFT_STATUS": ["Critical Shrink"] * 3 + ["Rapid Growth"] * 3,
            "PCT_CHANGE": [-60, -55, -70, 80, 120, 200],
        })
        result = summarize_data_quality(drift_df=drift_df)
        assert result["drift_alerts"] == 6
        assert result["overall_status"] == "warning"

    def test_sql_freshness(self, mock_streamlit):
        from utils.data_quality import build_load_freshness_sql

        sql = build_load_freshness_sql(days_back=7, stale_hours=24)
        assert "LOAD_HISTORY" in sql
        assert "freshness_status" in sql.lower()

    def test_sql_drift(self, mock_streamlit):
        from utils.data_quality import build_row_count_drift_sql

        sql = build_row_count_drift_sql(days_back=7)
        assert "TABLE_STORAGE_METRICS" in sql
        assert "pct_change" in sql.lower()

    def test_sql_schema_changes(self, mock_streamlit):
        from utils.data_quality import build_schema_change_sql

        sql = build_schema_change_sql(days_back=7)
        assert "QUERY_HISTORY" in sql
        assert "ALTER_TABLE" in sql
