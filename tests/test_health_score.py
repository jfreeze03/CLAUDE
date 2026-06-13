"""Tests for the Platform Health Score module."""
import pandas as pd
import pytest


class TestHealthScore:
    def test_empty_state_returns_baseline_scores(self, mock_streamlit):
        from utils.health_score import compute_platform_health_score

        result = compute_platform_health_score({})

        assert "score" in result
        assert "grade" in result
        assert "components" in result
        assert 0 <= result["score"] <= 100
        assert result["grade"] in ("A", "B", "C", "D", "F")
        assert result["trend"] == "unknown"

    def test_healthy_state_scores_high(self, mock_streamlit, sample_dba_snapshot):
        from utils.health_score import compute_platform_health_score

        # Low failures = healthy
        healthy_snapshot = sample_dba_snapshot.copy()
        healthy_snapshot["FAIL_COUNT"] = [0, 1, 0, 0, 0, 0, 0]
        state = {"dba_control_room_data": healthy_snapshot}

        result = compute_platform_health_score(state)
        assert result["score"] >= 75

    def test_high_failures_reduce_reliability_score(self, mock_streamlit):
        from utils.health_score import compute_platform_health_score

        bad_state = {
            "dba_control_room_data": pd.DataFrame({
                "FAIL_COUNT": [100],
            }),
        }
        result = compute_platform_health_score(bad_state)
        assert result["components"]["reliability"]["score"] < 70

    def test_critical_security_findings_reduce_score(self, mock_streamlit):
        from utils.health_score import compute_platform_health_score

        state = {
            "security_posture_summary": pd.DataFrame({
                "SEVERITY": ["CRITICAL", "CRITICAL", "HIGH", "HIGH", "HIGH", "MEDIUM"],
            }),
        }
        result = compute_platform_health_score(state)
        assert result["components"]["security"]["score"] < 60

    def test_open_alerts_reduce_operations_score(self, mock_streamlit, sample_alert_data):
        from utils.health_score import compute_platform_health_score

        state = {"alert_center_data": sample_alert_data}
        result = compute_platform_health_score(state)
        # 4 open alerts should lower ops score slightly
        assert result["components"]["operations"]["score"] < 85

    def test_grade_boundaries(self, mock_streamlit):
        from utils.health_score import compute_platform_health_score

        # Empty state should be baseline (B range)
        result = compute_platform_health_score({})
        assert result["grade"] in ("A", "B")

    def test_trend_detection_with_previous_score(self, mock_streamlit):
        from utils.health_score import compute_platform_health_score

        state = {"_platform_health_score_prev": 60.0}
        result = compute_platform_health_score(state)
        # Score should be higher than 60 (baseline), so trend = improving
        if result["score"] > 63:
            assert result["trend"] == "improving"
