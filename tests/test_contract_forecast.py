"""Tests for the contract burn forecast module."""
import pandas as pd
import pytest
from datetime import date, timedelta


class TestContractForecast:
    def test_empty_dataframe_returns_defaults(self, mock_streamlit):
        from utils.contract_forecast import compute_burn_forecast

        result = compute_burn_forecast(pd.DataFrame())
        assert result["daily_burn_rate"] == 0.0
        assert result["days_remaining"] is None
        assert result["confidence"] == "low"

    def test_none_input_returns_defaults(self, mock_streamlit):
        from utils.contract_forecast import compute_burn_forecast

        result = compute_burn_forecast(None)
        assert result["observed_days"] == 0

    def test_computes_burn_rate_from_daily_data(self, mock_streamlit, sample_daily_credits):
        from utils.contract_forecast import compute_burn_forecast

        result = compute_burn_forecast(sample_daily_credits)
        assert result["daily_burn_rate"] > 0
        assert result["weekly_burn_rate"] == pytest.approx(result["daily_burn_rate"] * 7, rel=0.01)
        assert result["monthly_burn_rate"] == pytest.approx(result["daily_burn_rate"] * 30, rel=0.01)
        assert result["observed_days"] == 30

    def test_computes_days_remaining_with_contract(self, mock_streamlit, sample_daily_credits):
        from utils.contract_forecast import compute_burn_forecast

        result = compute_burn_forecast(
            sample_daily_credits,
            contract_remaining=50000,
            contract_total=100000,
        )
        assert result["days_remaining"] is not None
        assert result["days_remaining"] > 0
        assert result["projected_exhaustion_date"] is not None
        assert result["utilization_pct"] is not None
        assert 0 <= result["utilization_pct"] <= 100

    def test_trend_detection_accelerating(self, mock_streamlit):
        from utils.contract_forecast import compute_burn_forecast

        # Create data where recent usage is much higher
        dates = [date.today() - timedelta(days=i) for i in range(14, 0, -1)]
        credits = [50] * 7 + [100] * 7  # Doubled in recent week
        df = pd.DataFrame({"USAGE_DATE": dates, "DAILY_CREDITS": credits})

        result = compute_burn_forecast(df)
        assert result["burn_trend"] == "accelerating"
        assert result["burn_trend_pct"] > 0

    def test_trend_detection_decelerating(self, mock_streamlit):
        from utils.contract_forecast import compute_burn_forecast

        dates = [date.today() - timedelta(days=i) for i in range(14, 0, -1)]
        credits = [100] * 7 + [50] * 7  # Halved in recent week
        df = pd.DataFrame({"USAGE_DATE": dates, "DAILY_CREDITS": credits})

        result = compute_burn_forecast(df)
        assert result["burn_trend"] == "decelerating"
        assert result["burn_trend_pct"] < 0

    def test_confidence_increases_with_more_data(self, mock_streamlit):
        from utils.contract_forecast import compute_burn_forecast

        # 7 days = medium
        dates_7 = [date.today() - timedelta(days=i) for i in range(7, 0, -1)]
        df_7 = pd.DataFrame({"USAGE_DATE": dates_7, "DAILY_CREDITS": [100] * 7})
        result_7 = compute_burn_forecast(df_7)

        # 30 days = high
        dates_30 = [date.today() - timedelta(days=i) for i in range(30, 0, -1)]
        df_30 = pd.DataFrame({"USAGE_DATE": dates_30, "DAILY_CREDITS": [100] * 30})
        result_30 = compute_burn_forecast(df_30)

        assert result_7["confidence"] in ("low", "medium")
        assert result_30["confidence"] == "high"

    def test_sql_generation(self, mock_streamlit):
        from utils.contract_forecast import build_contract_burn_sql

        sql = build_contract_burn_sql(days_back=30)
        assert "METERING_HISTORY" in sql
        assert "30" in sql
        assert "daily_credits" in sql.lower()
