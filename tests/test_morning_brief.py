"""Tests for the morning brief generator."""
import pandas as pd
import pytest


class TestMorningBrief:
    def test_build_brief_empty_state(self, mock_streamlit):
        from utils.morning_brief import build_morning_brief

        brief = build_morning_brief({})
        assert "generated_at" in brief
        assert "sections" in brief
        assert len(brief["sections"]) == 4
        assert "action_items" in brief

    def test_build_brief_with_cost_data(self, mock_streamlit, sample_cost_data):
        from utils.morning_brief import build_morning_brief

        state = {"cost_contract_cockpit": sample_cost_data}
        brief = build_morning_brief(state)
        cost_section = next(s for s in brief["sections"] if "Cost" in s["title"])
        assert cost_section["status"] != "unknown"

    def test_build_brief_with_alerts(self, mock_streamlit, sample_alert_data):
        from utils.morning_brief import build_morning_brief

        state = {"alert_center_data": sample_alert_data}
        brief = build_morning_brief(state)
        alert_section = next(s for s in brief["sections"] if "Alert" in s["title"])
        assert alert_section["status"] != "unknown"
        assert "open" in alert_section["summary"].lower()

    def test_build_brief_with_failures_creates_actions(self, mock_streamlit):
        from utils.morning_brief import build_morning_brief

        state = {
            "dba_control_room_data": pd.DataFrame({"FAIL_COUNT": [50]}),
        }
        brief = build_morning_brief(state)
        reliability = next(s for s in brief["sections"] if "Reliability" in s["title"])
        assert reliability["status"] == "red"
        assert reliability["action_required"] is True
        assert len(brief["action_items"]) > 0

    def test_format_as_text(self, mock_streamlit):
        from utils.morning_brief import build_morning_brief, format_brief_as_text

        brief = build_morning_brief({})
        text = format_brief_as_text(brief)
        assert "OVERWATCH MORNING BRIEF" in text
        assert "Cost" in text
        assert "Reliability" in text
        assert "End of brief" in text

    def test_format_as_html(self, mock_streamlit):
        from utils.morning_brief import build_morning_brief, format_brief_as_html

        brief = build_morning_brief({})
        html = format_brief_as_html(brief)
        assert "<div" in html
        assert "OVERWATCH" in html
        assert "Morning Brief" in html

    def test_scope_captured_from_state(self, mock_streamlit):
        from utils.morning_brief import build_morning_brief

        state = {
            "active_company": "Trexis",
            "global_environment": "PROD",
        }
        brief = build_morning_brief(state)
        assert brief["scope"]["company"] == "Trexis"
        assert brief["scope"]["environment"] == "PROD"
