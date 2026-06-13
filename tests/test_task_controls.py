"""Tests for task controls (execute, cancel, resume)."""
import pytest
from unittest.mock import MagicMock


class TestTaskControls:
    def test_execute_task_requires_admin(self, mock_streamlit):
        from utils.task_controls import execute_task

        mock_streamlit.session_state = {"_admin_actions_enabled": False}
        session = MagicMock()

        result = execute_task(session, "DB1", "PUBLIC", "MY_TASK")
        assert result["success"] is False
        assert "Admin actions" in result["message"]
        session.sql.assert_not_called()

    def test_cancel_task_requires_admin(self, mock_streamlit):
        from utils.task_controls import cancel_task

        mock_streamlit.session_state = {"_admin_actions_enabled": False}
        session = MagicMock()

        result = cancel_task(session, "DB1", "PUBLIC", "MY_TASK")
        assert result["success"] is False
        session.sql.assert_not_called()

    def test_resume_task_requires_admin(self, mock_streamlit):
        from utils.task_controls import resume_task

        mock_streamlit.session_state = {"_admin_actions_enabled": False}
        session = MagicMock()

        result = resume_task(session, "DB1", "PUBLIC", "MY_TASK")
        assert result["success"] is False
        session.sql.assert_not_called()

    def test_kill_query_requires_admin(self, mock_streamlit):
        from utils.task_controls import kill_query

        mock_streamlit.session_state = {"_admin_actions_enabled": False}
        session = MagicMock()

        result = kill_query(session, "01234567-abcd-efgh")
        assert result["success"] is False
        session.sql.assert_not_called()

    def test_live_task_sql_generation(self, mock_streamlit):
        from utils.task_controls import build_live_task_runs_sql

        sql = build_live_task_runs_sql()
        assert "INFORMATION_SCHEMA.TASK_HISTORY" in sql
        assert "state" in sql.lower()
        assert "running_sec" in sql.lower()

    def test_task_graph_sql_generation(self, mock_streamlit):
        from utils.task_controls import build_task_graph_sql

        sql = build_task_graph_sql("ROOT_TASK", "DB1", "PUBLIC")
        assert "TASK_DEPENDENTS" in sql
        assert "DB1" in sql
        assert "ROOT_TASK" in sql
