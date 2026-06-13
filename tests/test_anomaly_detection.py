"""Tests for the anomaly detection module."""
import pandas as pd
import pytest


class TestAnomalyDetection:
    def test_classify_anomalies_empty_inputs(self, mock_streamlit):
        from utils.anomaly_detection import classify_anomalies

        result = classify_anomalies()
        assert result["total_anomalies"] == 0
        assert result["critical"] == 0
        assert result["top_findings"] == []
        assert result["recommendations"] == []

    def test_classify_cost_anomalies(self, mock_streamlit):
        from utils.anomaly_detection import classify_anomalies

        df = pd.DataFrame({
            "USAGE_DATE": ["2026-06-01", "2026-06-02"],
            "WAREHOUSE_NAME": ["WH_A", "WH_B"],
            "DAILY_CREDITS": [500, 300],
            "Z_SCORE": [3.5, 2.8],
            "PCT_ABOVE_BASELINE": [85, 55],
            "ANOMALY_SEVERITY": ["Critical", "High"],
        })

        result = classify_anomalies(cost_anomalies_df=df)
        assert result["total_anomalies"] == 2
        assert result["critical"] == 1
        assert result["high"] == 1
        assert len(result["affected_warehouses"]) == 2
        assert any("cost spike" in r.lower() or "warehouse" in r.lower()
                   for r in result["recommendations"])

    def test_classify_query_regressions(self, mock_streamlit):
        from utils.anomaly_detection import classify_anomalies

        df = pd.DataFrame({
            "QUERY_HASH": ["abc123"],
            "WAREHOUSE_NAME": ["WH_A"],
            "DATABASE_NAME": ["DB1"],
            "USER_NAME": ["USER_A"],
            "BASELINE_P95_SEC": [2.0],
            "RECENT_P95_SEC": [8.5],
            "REGRESSION_FACTOR": [4.25],
            "SEVERITY": ["High"],
        })

        result = classify_anomalies(query_regressions_df=df)
        assert result["total_anomalies"] == 1
        assert result["high"] == 1
        assert any("regression" in f["signal"].lower() for f in result["top_findings"])

    def test_classify_task_bursts(self, mock_streamlit):
        from utils.anomaly_detection import classify_anomalies

        df = pd.DataFrame({
            "FAILURE_DATE": ["2026-06-01"],
            "DATABASE_NAME": ["DB1"],
            "SCHEMA_NAME": ["PUBLIC"],
            "TASK_NAME": ["ETL_LOAD"],
            "FAILURE_COUNT": [15],
            "ERROR_CODES": ["100132"],
            "SEVERITY": ["Critical"],
        })

        result = classify_anomalies(task_bursts_df=df)
        assert result["total_anomalies"] == 1
        assert result["critical"] == 1
        assert len(result["affected_tasks"]) == 1

    def test_sql_generation_cost_anomaly(self, mock_streamlit):
        from utils.anomaly_detection import build_cost_anomaly_sql

        sql = build_cost_anomaly_sql(days_back=30, sensitivity=2.0)
        assert "WAREHOUSE_METERING_HISTORY" in sql
        assert "z_score" in sql.lower() or "Z_SCORE" in sql
        assert "rolling" in sql.lower()

    def test_sql_generation_query_regression(self, mock_streamlit):
        from utils.anomaly_detection import build_query_regression_sql

        sql = build_query_regression_sql(days_back=14)
        assert "QUERY_HISTORY" in sql
        assert "PERCENTILE_CONT" in sql
        assert "BASELINE" in sql

    def test_sql_generation_task_burst(self, mock_streamlit):
        from utils.anomaly_detection import build_task_failure_burst_sql

        sql = build_task_failure_burst_sql(days_back=7, burst_threshold=3)
        assert "TASK_HISTORY" in sql
        assert "FAILED" in sql
