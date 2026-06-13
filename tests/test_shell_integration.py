"""Integration tests — verify shell render functions work with mock data.

These test the full render path: mock data → precompute metrics → shell render.
They verify that shells don't crash and produce the expected KPI structure.
"""
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, timedelta


@pytest.fixture
def populated_session_state(mock_streamlit, sample_dba_snapshot, sample_alert_data, sample_cost_data):
    """Session state with data loaded for all sections."""
    mock_streamlit.session_state = {
        "active_company": "ALFA",
        "global_environment": "ALL",
        "global_start_date": date.today() - timedelta(days=7),
        "global_end_date": date.today(),
        "credit_price": 3.68,
        "ai_credit_price": 2.20,
        # DBA Control Room
        "dba_control_room_snapshot_result": sample_dba_snapshot,
        # Alert Center
        "alert_center_data": sample_alert_data,
        # Cost & Contract
        "cost_contract_cockpit": sample_cost_data,
        # Account Health
        "health_data": {
            "failures": 3,
            "long_queries": 2,
            "queued": 5,
            "credits_24h": 150.0,
        },
        # Security
        "security_posture_summary": pd.DataFrame({
            "SEVERITY": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "MEDIUM"],
        }),
    }
    return mock_streamlit


class TestShellIntegration:
    def test_perf_precompute_dba(self, populated_session_state):
        """Verify DBA metrics are correctly precomputed."""
        from utils.perf import precompute_shell_metrics, get_cached_metrics

        df = populated_session_state.session_state["dba_control_room_snapshot_result"]
        metrics = precompute_shell_metrics("dba_control_room_snapshot_result", df)

        assert metrics["FAIL_COUNT"] == int(df["FAIL_COUNT"].sum())
        assert metrics["QUEUED_COUNT"] == int(df["QUEUED_COUNT"].sum())
        assert metrics["ACTIVE_COUNT"] == int(df["ACTIVE_COUNT"].sum())

    def test_perf_precompute_cost(self, populated_session_state):
        """Verify cost metrics are correctly precomputed."""
        from utils.perf import precompute_shell_metrics

        df = populated_session_state.session_state["cost_contract_cockpit"]
        metrics = precompute_shell_metrics("cost_contract_cockpit", df)

        assert "total_credits" in metrics
        assert metrics["total_credits"] == df["TOTAL_CREDITS"].sum()
        assert "max_variance" in metrics
        assert "unique_dates" in metrics

    def test_perf_precompute_alerts(self, populated_session_state):
        """Verify alert metrics are correctly precomputed."""
        from utils.perf import precompute_shell_metrics

        df = populated_session_state.session_state["alert_center_data"]
        metrics = precompute_shell_metrics("alert_center_data", df)

        assert metrics["open_count"] == 4  # NEW, OPEN, ESCALATED, NEW
        assert metrics["total_count"] == 7
        assert metrics["critical_count"] == 2  # CRITICAL + HIGH

    def test_shell_metrics_mttr_empty(self, mock_streamlit):
        """MTTR returns None for empty input."""
        from utils.shell_metrics import compute_mttr

        assert compute_mttr(None) is None
        assert compute_mttr(pd.DataFrame()) is None

    def test_shell_metrics_mttr_with_data(self, mock_streamlit):
        """MTTR computes correctly from timestamps."""
        from utils.shell_metrics import compute_mttr

        df = pd.DataFrame({
            "CREATED_AT": pd.to_datetime(["2026-06-01 08:00", "2026-06-02 10:00"]),
            "FIXED_AT": pd.to_datetime(["2026-06-01 12:00", "2026-06-02 14:00"]),
            "STATUS": ["Fixed", "Fixed"],
        })
        mttr = compute_mttr(df)
        assert mttr == 4.0  # 4 hours average

    def test_shell_metrics_alert_age(self, mock_streamlit):
        """Alert age computes correctly."""
        from utils.shell_metrics import compute_alert_age

        now = pd.Timestamp.now()
        df = pd.DataFrame({
            "STATUS": ["OPEN", "OPEN", "RESOLVED"],
            "CREATED_AT": [now - pd.Timedelta(hours=48), now - pd.Timedelta(hours=12), now - pd.Timedelta(hours=24)],
            "FIXED_AT": [pd.NaT, pd.NaT, now - pd.Timedelta(hours=2)],
        })
        result = compute_alert_age(df)
        assert result["total_open"] == 2
        assert result["oldest_hours"] > 40

    def test_kpi_with_trend_flat(self, mock_streamlit):
        """KPI with flat trend shows flat indicator."""
        from utils.shell_metrics import kpi_with_trend

        label, value, delta = kpi_with_trend("Test", 100, [100] * 14)
        assert "100" in value
        assert delta is not None
        assert "flat" in delta

    def test_kpi_with_trend_rising(self, mock_streamlit):
        """KPI with rising trend shows up arrow."""
        from utils.shell_metrics import kpi_with_trend

        values = [50] * 7 + [80] * 7
        label, value, delta = kpi_with_trend("Test", 80, values)
        assert delta is not None
        assert "↑" in delta

    def test_confidence_badge(self, mock_streamlit):
        """Confidence badges are valid characters."""
        from utils.shell_metrics import confidence_badge

        assert confidence_badge("exact") == "●"
        assert confidence_badge("allocated") == "◐"
        assert confidence_badge("live") == "◉"
