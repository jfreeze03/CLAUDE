"""Tests for end-of-month cost prediction."""
import pytest
from datetime import date


class TestCostPrediction:
    def test_predict_insufficient_data(self, mock_streamlit):
        from utils.cost_prediction import predict_end_of_month_cost

        result = predict_end_of_month_cost([100, 200])
        assert result["confidence"] == "insufficient_data"

    def test_predict_flat_scenario(self, mock_streamlit):
        from utils.cost_prediction import predict_end_of_month_cost

        # 10 days of 100 credits each
        daily = [100.0] * 10
        result = predict_end_of_month_cost(daily, credit_price=3.68, target_date=date(2026, 6, 10))
        assert result["confidence"] in ("low", "medium")
        assert result["flat_projection_credits"] > sum(daily)
        assert result["days_remaining"] > 0
        assert result["daily_avg_recent"] == pytest.approx(100.0)

    def test_predict_growing_trend(self, mock_streamlit):
        from utils.cost_prediction import predict_end_of_month_cost

        # Growing pattern: 100 -> 200 over 10 days
        daily = [100 + i * 10 for i in range(10)]
        result = predict_end_of_month_cost(daily, credit_price=3.68, target_date=date(2026, 6, 15))
        # Trend projection should be higher than flat
        assert result["trend_projection_credits"] >= result["flat_projection_credits"]
        assert result["growth_rate_daily"] > 0

    def test_predict_declining_trend(self, mock_streamlit):
        from utils.cost_prediction import predict_end_of_month_cost

        daily = [200 - i * 10 for i in range(10)]
        result = predict_end_of_month_cost(daily, credit_price=3.68, target_date=date(2026, 6, 15))
        assert result["growth_rate_daily"] < 0

    def test_high_confidence_with_20_days(self, mock_streamlit):
        from utils.cost_prediction import predict_end_of_month_cost

        daily = [100.0] * 20
        result = predict_end_of_month_cost(daily, target_date=date(2026, 6, 25))
        assert result["confidence"] == "high"

    def test_sql_generation(self, mock_streamlit):
        from utils.cost_prediction import build_monthly_prediction_sql

        sql = build_monthly_prediction_sql(0)
        assert "METERING_HISTORY" in sql
        assert "daily_credits" in sql.lower()

        sql_prev = build_monthly_prediction_sql(-1)
        assert "-1" in sql_prev
