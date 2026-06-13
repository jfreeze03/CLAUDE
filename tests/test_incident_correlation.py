"""Tests for incident correlation engine."""
import pandas as pd
import pytest


class TestIncidentCorrelation:
    def test_correlate_empty_inputs(self, mock_streamlit):
        from utils.incident_correlation import correlate_incident

        result = correlate_incident("cost_spike", "2026-06-01", "WH_A")
        assert result["anomaly"]["type"] == "cost_spike"
        assert result["anomaly"]["date"] == "2026-06-01"
        assert len(result["probable_causes"]) == 0
        assert "No correlated events" in result["recommendation"]

    def test_correlate_with_ddl_changes(self, mock_streamlit):
        from utils.incident_correlation import correlate_incident

        ddl_df = pd.DataFrame({
            "QUERY_TYPE": ["ALTER_WAREHOUSE", "CREATE_TABLE"],
            "USER_NAME": ["ADMIN_USER", "DEV_USER"],
            "DATABASE_NAME": ["DB1", "DB1"],
            "SCHEMA_NAME": ["PUBLIC", "STAGING"],
            "START_TIME": ["2026-06-01 08:00:00", "2026-06-01 09:00:00"],
            "QUERY_PREVIEW": ["ALTER WAREHOUSE WH_A SET SIZE = '2X-LARGE'", "CREATE TABLE foo (id INT)"],
        })

        result = correlate_incident(
            "cost_spike", "2026-06-01", "WH_A",
            ddl_changes_df=ddl_df,
        )
        assert len(result["probable_causes"]) > 0
        assert any("warehouse" in c["cause"].lower() for c in result["probable_causes"])
        assert len(result["timeline"]) > 0

    def test_correlate_with_new_workloads(self, mock_streamlit):
        from utils.incident_correlation import correlate_incident

        workload_df = pd.DataFrame({
            "USER_NAME": ["NEW_SERVICE_ACCT"],
            "WAREHOUSE_NAME": ["WH_A"],
            "QUERY_COUNT": [500],
            "TOTAL_SEC": [3600.0],
            "FIRST_SEEN": ["2026-06-01 07:00:00"],
            "USER_STATUS": ["New"],
        })

        result = correlate_incident(
            "cost_spike", "2026-06-01", "WH_A",
            new_workloads_df=workload_df,
        )
        assert len(result["probable_causes"]) > 0
        assert "new workload" in result["probable_causes"][0]["cause"].lower()

    def test_correlate_with_warehouse_changes(self, mock_streamlit):
        from utils.incident_correlation import correlate_incident

        wh_df = pd.DataFrame({
            "USER_NAME": ["DBA_USER"],
            "ROLE_NAME": ["SYSADMIN"],
            "WAREHOUSE_NAME": ["WH_A"],
            "START_TIME": ["2026-06-01 06:00:00"],
            "QUERY_TYPE": ["ALTER_WAREHOUSE"],
            "QUERY_PREVIEW": ["ALTER WAREHOUSE WH_A SET WAREHOUSE_SIZE = '4X-LARGE'"],
        })

        result = correlate_incident(
            "cost_spike", "2026-06-01", "WH_A",
            warehouse_changes_df=wh_df,
        )
        assert len(result["probable_causes"]) > 0
        assert "config change" in result["probable_causes"][0]["cause"].lower()

    def test_sql_generation(self, mock_streamlit):
        from utils.incident_correlation import (
            build_ddl_changes_sql,
            build_new_workload_sql,
            build_warehouse_change_sql,
            build_volume_change_sql,
        )

        assert "QUERY_HISTORY" in build_ddl_changes_sql("2026-06-01")
        assert "baseline_users" in build_new_workload_sql("2026-06-01").lower()
        assert "ALTER_WAREHOUSE" in build_warehouse_change_sql("2026-06-01")
        assert "pct_change" in build_volume_change_sql("2026-06-01").lower()
