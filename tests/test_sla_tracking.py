"""Tests for SLA compliance tracking."""
import pandas as pd
import pytest


class TestSLATracking:
    def test_compute_sla_summary_empty(self, mock_streamlit):
        from utils.sla_tracking import compute_sla_summary

        result = compute_sla_summary(pd.DataFrame())
        assert result["overall_sla_pct"] is None
        assert result["status"] == "No Data"

    def test_compute_sla_summary_excellent(self, mock_streamlit):
        from utils.sla_tracking import compute_sla_summary

        df = pd.DataFrame({
            "OVERALL_SLA_PCT": [99.5],
            "TOTAL_RUNS": [1000],
            "WITHIN_SLA": [995],
            "MISSED_SLA": [5],
            "TRACKED_TASKS": [50],
            "TASKS_WITH_MISSES": [3],
        })
        result = compute_sla_summary(df)
        assert result["status"] == "Excellent"
        assert result["status_color"] == "#22c55e"
        assert result["overall_sla_pct"] == 99.5

    def test_compute_sla_summary_critical(self, mock_streamlit):
        from utils.sla_tracking import compute_sla_summary

        df = pd.DataFrame({
            "OVERALL_SLA_PCT": [65.0],
            "TOTAL_RUNS": [100],
            "WITHIN_SLA": [65],
            "MISSED_SLA": [35],
            "TRACKED_TASKS": [20],
            "TASKS_WITH_MISSES": [15],
        })
        result = compute_sla_summary(df)
        assert result["status"] == "Critical"
        assert result["status_color"] == "#ef4444"

    def test_sql_generation_task_sla(self, mock_streamlit):
        from utils.sla_tracking import build_task_sla_compliance_sql

        sql = build_task_sla_compliance_sql(days_back=7, sla_multiplier=1.5)
        assert "TASK_HISTORY" in sql
        assert "sla_compliance_pct" in sql.lower()
        assert "1.5" in sql

    def test_sql_generation_overall_sla(self, mock_streamlit):
        from utils.sla_tracking import build_overall_sla_sql

        sql = build_overall_sla_sql(days_back=14)
        assert "TASK_HISTORY" in sql
        assert "overall_sla_pct" in sql.lower()
