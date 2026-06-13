"""Tests for trend analysis utilities."""
import pytest


class TestTrendAnalysis:
    def test_compute_wow_delta_rising(self, mock_streamlit):
        from utils.trend_analysis import compute_wow_delta

        # Recent week is higher than prior
        values = [50, 50, 50, 50, 50, 50, 50, 80, 80, 80, 80, 80, 80, 80]
        result = compute_wow_delta(values)
        assert result["direction"] == "up"
        assert result["arrow"] == "↑"
        assert result["delta_pct"] > 0

    def test_compute_wow_delta_falling(self, mock_streamlit):
        from utils.trend_analysis import compute_wow_delta

        values = [80, 80, 80, 80, 80, 80, 80, 50, 50, 50, 50, 50, 50, 50]
        result = compute_wow_delta(values)
        assert result["direction"] == "down"
        assert result["arrow"] == "↓"
        assert result["delta_pct"] < 0

    def test_compute_wow_delta_flat(self, mock_streamlit):
        from utils.trend_analysis import compute_wow_delta

        values = [100] * 14
        result = compute_wow_delta(values)
        assert result["direction"] == "flat"
        assert result["delta_pct"] == 0.0

    def test_compute_wow_delta_insufficient(self, mock_streamlit):
        from utils.trend_analysis import compute_wow_delta

        result = compute_wow_delta([1, 2, 3])
        assert result["direction"] == "flat"

    def test_classify_trend_accelerating(self, mock_streamlit):
        from utils.trend_analysis import classify_trend

        values = [10, 12, 14, 16, 18, 20, 22, 24, 26]
        assert classify_trend(values) == "accelerating"

    def test_classify_trend_decelerating(self, mock_streamlit):
        from utils.trend_analysis import classify_trend

        values = [26, 24, 22, 20, 18, 16, 14, 12, 10]
        assert classify_trend(values) == "decelerating"

    def test_moving_average(self, mock_streamlit):
        from utils.trend_analysis import moving_average

        values = [1, 2, 3, 4, 5, 6, 7]
        ma = moving_average(values, window=3)
        assert len(ma) == 7
        assert ma[-1] == pytest.approx(6.0)  # (5+6+7)/3

    def test_format_delta(self, mock_streamlit):
        from utils.trend_analysis import format_delta

        assert "↑" in format_delta(15.5)
        assert "↓" in format_delta(-8.2)
        assert "flat" in format_delta(0.3)
