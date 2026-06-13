"""Tests for self-healing playbook engine."""
import pytest


class TestSelfHealing:
    def test_evaluate_unknown_playbook(self, mock_streamlit):
        from utils.self_healing import evaluate_playbook

        result = evaluate_playbook("nonexistent", "WH_A")
        assert result["should_execute"] is False
        assert "Unknown" in result["reason"]

    def test_evaluate_suspend_idle_warehouse(self, mock_streamlit):
        from utils.self_healing import evaluate_playbook

        result = evaluate_playbook("suspend_idle_warehouse", "WH_ALFA_QUERY")
        assert result["should_execute"] is True
        assert "SUSPEND" in result["sql"]
        assert result["risk"] == "Low"
        assert len(result["validation_checks"]) > 0

    def test_cannot_suspend_overwatch_warehouse(self, mock_streamlit):
        from utils.self_healing import evaluate_playbook

        result = evaluate_playbook("suspend_idle_warehouse", "OVERWATCH_WH")
        assert result["should_execute"] is False
        assert "Cannot suspend" in result["reason"]

    def test_evaluate_resume_task(self, mock_streamlit):
        from utils.self_healing import evaluate_playbook

        evidence = {"database": "DB1", "schema": "PUBLIC"}
        result = evaluate_playbook("resume_failed_task", "ETL_LOAD", evidence)
        assert result["should_execute"] is True
        assert "RESUME" in result["sql"]
        assert "DB1" in result["sql"]

    def test_evaluate_fix_auto_suspend(self, mock_streamlit):
        from utils.self_healing import evaluate_playbook

        result = evaluate_playbook("fix_auto_suspend", "WH_IDLE")
        assert result["should_execute"] is True
        assert result["requires_approval"] is True
        assert "AUTO_SUSPEND" in result["sql"]
        assert "60" in result["sql"]

    def test_evaluate_resize_warehouse(self, mock_streamlit):
        from utils.self_healing import evaluate_playbook

        evidence = {"recommended_size": "Small"}
        result = evaluate_playbook("resize_oversized_warehouse", "WH_BIG", evidence)
        assert result["should_execute"] is True
        assert result["requires_approval"] is True
        assert "Small" in result["sql"]
        assert result["risk"] == "High"

    def test_sql_generation_safety(self, mock_streamlit):
        from utils.self_healing import generate_suspend_warehouse_sql

        # Should escape dangerous characters
        sql = generate_suspend_warehouse_sql("WH; DROP TABLE users--")
        assert ";" not in sql.split("SUSPEND")[0]
        assert "DROP" not in sql.upper().replace("WH DROP TABLE USERS--", "")

    def test_dry_run_does_not_execute(self, mock_streamlit):
        from utils.self_healing import evaluate_playbook, execute_playbook
        from unittest.mock import MagicMock

        playbook = evaluate_playbook("suspend_idle_warehouse", "WH_TEST")
        session = MagicMock()

        result = execute_playbook(session, playbook, dry_run=True)
        assert result["success"] is True
        assert result["executed"] is False
        assert "DRY RUN" in result["message"]
        session.sql.assert_not_called()
