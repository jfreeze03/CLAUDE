"""Tests for capacity planning and warehouse sizing."""
import pytest


class TestCapacityPlanning:
    def test_recommend_maintain_when_healthy(self, mock_streamlit):
        from utils.capacity_planning import recommend_warehouse_size

        utilization = {
            "avg_queue_sec": 0.2,
            "peak_queue_sec": 1.5,
            "total_remote_spill_gb": 0.0,
            "peak_hourly_credits": 4.0,
            "avg_hourly_credits": 3.5,
        }
        result = recommend_warehouse_size(utilization)
        assert result["recommendation"] == "maintain"
        assert result["confidence"] == "high"

    def test_recommend_upsize_on_queue_pressure(self, mock_streamlit):
        from utils.capacity_planning import recommend_warehouse_size

        utilization = {
            "avg_queue_sec": 8.0,
            "peak_queue_sec": 25.0,
            "total_remote_spill_gb": 3.0,
            "peak_hourly_credits": 10.0,
            "avg_hourly_credits": 8.0,
        }
        result = recommend_warehouse_size(utilization)
        assert result["recommendation"] == "upsize"
        assert len(result["evidence"]) >= 2

    def test_recommend_multi_cluster_on_concurrency(self, mock_streamlit):
        from utils.capacity_planning import recommend_warehouse_size

        utilization = {
            "avg_queue_sec": 2.0,
            "peak_queue_sec": 30.0,  # High peak queue
            "total_remote_spill_gb": 0.1,  # No spill
            "peak_hourly_credits": 8.0,
            "avg_hourly_credits": 6.0,
        }
        result = recommend_warehouse_size(utilization)
        assert result["recommendation"] == "consider_multi_cluster"

    def test_recommend_downsize_when_underutilized(self, mock_streamlit):
        from utils.capacity_planning import recommend_warehouse_size

        utilization = {
            "avg_queue_sec": 0.1,
            "peak_queue_sec": 0.3,
            "total_remote_spill_gb": 0.0,
            "peak_hourly_credits": 2.0,
            "avg_hourly_credits": 1.8,
        }
        result = recommend_warehouse_size(utilization)
        assert result["recommendation"] == "downsize"

    def test_forecast_exhaustion_growing(self, mock_streamlit):
        from utils.capacity_planning import forecast_capacity_exhaustion

        result = forecast_capacity_exhaustion(
            weekly_growth_pct=10.0,
            current_weekly_credits=500,
            warehouse_capacity_credits=1000,
        )
        assert result["weeks_until_full"] is not None
        assert result["weeks_until_full"] > 0
        assert result["action_needed"] is True

    def test_forecast_no_growth(self, mock_streamlit):
        from utils.capacity_planning import forecast_capacity_exhaustion

        result = forecast_capacity_exhaustion(
            weekly_growth_pct=0.0,
            current_weekly_credits=500,
            warehouse_capacity_credits=1000,
        )
        assert result["weeks_until_full"] is None
        assert result["action_needed"] is False

    def test_forecast_already_full(self, mock_streamlit):
        from utils.capacity_planning import forecast_capacity_exhaustion

        result = forecast_capacity_exhaustion(
            weekly_growth_pct=5.0,
            current_weekly_credits=1200,
            warehouse_capacity_credits=1000,
        )
        assert result["weeks_until_full"] == 0
        assert result["urgency"] == "immediate"

    def test_sql_generation(self, mock_streamlit):
        from utils.capacity_planning import (
            build_warehouse_utilization_sql,
            build_peak_hour_analysis_sql,
            build_growth_trend_sql,
        )

        sql = build_warehouse_utilization_sql(30)
        assert "WAREHOUSE_METERING_HISTORY" in sql
        assert "QUERY_HISTORY" in sql
        assert "remote_spill" in sql.lower()

        sql2 = build_peak_hour_analysis_sql("WH_A", 14)
        assert "WH_A" in sql2
        assert "hour_of_day" in sql2.lower()

        sql3 = build_growth_trend_sql(days_back=60)
        assert "wow_growth_pct" in sql3.lower()
