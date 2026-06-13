"""Tests for the sparkline rendering module."""
import pytest


class TestSparklines:
    def test_svg_sparkline_basic(self, mock_streamlit):
        from utils.sparklines import svg_sparkline

        result = svg_sparkline([1, 2, 3, 4, 5])
        assert "<svg" in result
        assert "polyline" in result
        assert "circle" in result

    def test_svg_sparkline_insufficient_data(self, mock_streamlit):
        from utils.sparklines import svg_sparkline

        assert svg_sparkline([]) == ""
        assert svg_sparkline([5]) == ""

    def test_svg_sparkline_handles_none_values(self, mock_streamlit):
        from utils.sparklines import svg_sparkline

        result = svg_sparkline([1, None, 3, None, 5])
        assert "<svg" in result

    def test_svg_sparkline_handles_nan(self, mock_streamlit):
        from utils.sparklines import svg_sparkline

        result = svg_sparkline([1, float("nan"), 3, 4])
        assert "<svg" in result

    def test_svg_sparkline_flat_line(self, mock_streamlit):
        from utils.sparklines import svg_sparkline

        result = svg_sparkline([5, 5, 5, 5])
        assert "<svg" in result

    def test_sparkline_with_trend_rising_is_red(self, mock_streamlit):
        from utils.sparklines import sparkline_with_trend

        # Rising values → red (bad for costs)
        result = sparkline_with_trend([10, 20, 30, 40, 50, 60, 70])
        assert "#ef4444" in result  # red

    def test_sparkline_with_trend_falling_is_green(self, mock_streamlit):
        from utils.sparklines import sparkline_with_trend

        # Falling values → green (good for costs)
        result = sparkline_with_trend([70, 60, 50, 40, 30, 20, 10])
        assert "#22c55e" in result  # green

    def test_sparkline_card_generates_html(self, mock_streamlit):
        from utils.sparklines import sparkline_card

        result = sparkline_card("Credits", "1,234", [100, 110, 95, 120, 105])
        assert "Credits" in result
        assert "1,234" in result
        assert "<svg" in result

    def test_render_sparkline_snapshot_generates_grid(self, mock_streamlit):
        from utils.sparklines import render_sparkline_snapshot

        metrics = [
            ("Failures", "19", [3, 5, 0, 2, 1, 8, 0]),
            ("Queued", "12", [2, 0, 4, 1, 0, 3, 2]),
        ]
        result = render_sparkline_snapshot(metrics)
        assert "ow-shell-snapshot-grid" in result
        assert "Failures" in result
        assert "Queued" in result

    def test_render_sparkline_snapshot_empty(self, mock_streamlit):
        from utils.sparklines import render_sparkline_snapshot

        assert render_sparkline_snapshot([]) == ""
