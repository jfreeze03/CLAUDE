"""Tests for warehouse settings controls."""
import pytest
from unittest.mock import MagicMock


class TestWarehouseControls:
    def test_alter_size_requires_admin(self, mock_streamlit):
        from utils.warehouse_controls import alter_warehouse_size

        mock_streamlit.session_state = {"_admin_actions_enabled": False}
        session = MagicMock()

        result = alter_warehouse_size(session, "WH_A", "Large")
        assert result["success"] is False
        assert "Admin" in result["message"]
        session.sql.assert_not_called()

    def test_alter_size_validates_input(self, mock_streamlit):
        from utils.warehouse_controls import alter_warehouse_size

        mock_streamlit.session_state = {"_admin_actions_enabled": True}
        session = MagicMock()

        result = alter_warehouse_size(session, "WH_A", "Invalid-Size")
        assert result["success"] is False
        assert "Invalid" in result["message"]

    def test_suspend_requires_admin(self, mock_streamlit):
        from utils.warehouse_controls import suspend_warehouse

        mock_streamlit.session_state = {"_admin_actions_enabled": False}
        session = MagicMock()

        result = suspend_warehouse(session, "WH_A")
        assert result["success"] is False

    def test_resume_requires_admin(self, mock_streamlit):
        from utils.warehouse_controls import resume_warehouse

        mock_streamlit.session_state = {"_admin_actions_enabled": False}
        session = MagicMock()

        result = resume_warehouse(session, "WH_A")
        assert result["success"] is False

    def test_alter_suspend_timeout_requires_admin(self, mock_streamlit):
        from utils.warehouse_controls import alter_warehouse_suspend

        mock_streamlit.session_state = {"_admin_actions_enabled": False}
        session = MagicMock()

        result = alter_warehouse_suspend(session, "WH_A", 60)
        assert result["success"] is False

    def test_settings_sql(self, mock_streamlit):
        from utils.warehouse_controls import build_warehouse_settings_sql

        sql = build_warehouse_settings_sql("WH_TEST")
        assert "SHOW WAREHOUSES" in sql
        assert "WH_TEST" in sql

        sql_all = build_warehouse_settings_sql()
        assert "SHOW WAREHOUSES" in sql_all
