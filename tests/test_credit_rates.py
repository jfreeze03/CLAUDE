"""Tests for multi-rate credit pricing."""
import pytest


class TestCreditRates:
    def test_get_rate_for_compute(self, mock_streamlit):
        from utils.credit_rates import get_rate_for_service

        rate = get_rate_for_service("WAREHOUSE_METERING")
        assert rate > 0
        assert rate == pytest.approx(3.68, abs=0.5)

    def test_get_rate_for_cortex(self, mock_streamlit):
        from utils.credit_rates import get_rate_for_service

        rate = get_rate_for_service("CORTEX")
        assert rate > 0
        assert rate == pytest.approx(2.20, abs=0.5)

    def test_ai_keywords_get_ai_rate(self, mock_streamlit):
        from utils.credit_rates import get_rate_for_service

        assert get_rate_for_service("CORTEX_FUNCTIONS") == get_rate_for_service("CORTEX")
        assert get_rate_for_service("AI_SERVICES") == get_rate_for_service("AI")

    def test_unknown_service_gets_compute_rate(self, mock_streamlit):
        from utils.credit_rates import get_rate_for_service

        rate = get_rate_for_service("TOTALLY_UNKNOWN_SERVICE")
        compute_rate = get_rate_for_service("COMPUTE")
        assert rate == compute_rate

    def test_service_category_classification(self, mock_streamlit):
        from utils.credit_rates import get_service_category

        assert get_service_category("WAREHOUSE_METERING") == "Compute"
        assert get_service_category("CORTEX") == "AI / Cortex"
        assert get_service_category("SNOWPIPE") == "Serverless"
        assert get_service_category("SERVERLESS_TASK") == "Serverless"

    def test_credits_to_dollars_multi_rate(self, mock_streamlit):
        from utils.credit_rates import credits_to_dollars_multi_rate

        compute_cost = credits_to_dollars_multi_rate(100, "WAREHOUSE_METERING")
        ai_cost = credits_to_dollars_multi_rate(100, "CORTEX")

        # AI should be cheaper per credit
        assert ai_cost < compute_cost
        assert compute_cost > 0
        assert ai_cost > 0

    def test_dollarize_dataframe_adds_column(self, mock_streamlit):
        import pandas as pd
        from utils.credit_rates import dollarize_dataframe

        df = pd.DataFrame({
            "WAREHOUSE_NAME": ["WH_A", "WH_B"],
            "TOTAL_CREDITS": [100.0, 200.0],
        })
        result = dollarize_dataframe(df, "TOTAL_CREDITS")
        assert "TOTAL_CREDITS_COST_USD" in result.columns
        assert result["TOTAL_CREDITS_COST_USD"].sum() > 0

    def test_dollarize_with_service_type_column(self, mock_streamlit):
        import pandas as pd
        from utils.credit_rates import dollarize_dataframe

        df = pd.DataFrame({
            "SERVICE_TYPE": ["WAREHOUSE_METERING", "CORTEX"],
            "CREDITS": [100.0, 100.0],
        })
        result = dollarize_dataframe(df, "CREDITS", "SERVICE_TYPE")
        assert "CREDITS_COST_USD" in result.columns
        # Different rates applied per row
        costs = result["CREDITS_COST_USD"].tolist()
        assert costs[0] != costs[1]

    def test_rate_summary(self, mock_streamlit):
        from utils.credit_rates import build_rate_summary

        summary = build_rate_summary()
        assert "compute_rate" in summary
        assert "ai_rate" in summary
        assert "is_multi_rate" in summary
        assert summary["compute_rate"] > 0
