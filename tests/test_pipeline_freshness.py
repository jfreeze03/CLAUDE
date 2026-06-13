"""Tests for pipeline freshness monitoring."""
import pandas as pd
import pytest


class TestPipelineFreshness:
    def test_summarize_empty(self, mock_streamlit):
        from utils.pipeline_freshness import summarize_pipeline_health

        result = summarize_pipeline_health(pd.DataFrame())
        assert result["status"] == "unknown"
        assert result["total_pipelines"] == 0

    def test_summarize_all_fresh(self, mock_streamlit):
        from utils.pipeline_freshness import summarize_pipeline_health

        df = pd.DataFrame({
            "PIPELINE_NAME": ["pipe_a", "pipe_b", "pipe_c"],
            "FRESHNESS_STATUS": ["Fresh", "Fresh", "Fresh"],
            "MINUTES_SINCE_LAST": [10, 30, 45],
        })
        result = summarize_pipeline_health(df)
        assert result["status"] == "healthy"
        assert result["freshness_pct"] == 100.0
        assert result["fresh"] == 3

    def test_summarize_with_failures(self, mock_streamlit):
        from utils.pipeline_freshness import summarize_pipeline_health

        df = pd.DataFrame({
            "PIPELINE_NAME": ["pipe_a", "pipe_b", "pipe_c"],
            "PIPELINE_TYPE": ["TASK", "TASK", "SNOWPIPE"],
            "FRESHNESS_STATUS": ["Failed", "Fresh", "Critical"],
            "MINUTES_SINCE_LAST": [120, 30, 1500],
        })
        result = summarize_pipeline_health(df)
        assert result["status"] == "critical"
        assert result["failed"] == 1
        assert result["critical"] == 1
        assert len(result["top_issues"]) > 0

    def test_summarize_stale(self, mock_streamlit):
        from utils.pipeline_freshness import summarize_pipeline_health

        df = pd.DataFrame({
            "PIPELINE_NAME": [f"pipe_{i}" for i in range(5)],
            "FRESHNESS_STATUS": ["Stale", "Stale", "Stale", "Stale", "Fresh"],
            "MINUTES_SINCE_LAST": [400, 500, 380, 420, 20],
        })
        result = summarize_pipeline_health(df)
        assert result["status"] == "warning"
        assert result["stale"] == 4

    def test_sql_generation(self, mock_streamlit):
        from utils.pipeline_freshness import build_pipeline_status_sql, build_snowpipe_health_sql

        sql = build_pipeline_status_sql(3)
        assert "TASK_HISTORY" in sql
        assert "freshness_status" in sql.lower()

        sql2 = build_snowpipe_health_sql(7)
        assert "PIPE_USAGE_HISTORY" in sql2
