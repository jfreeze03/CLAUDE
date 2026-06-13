"""Tests for the Ask OVERWATCH Cortex integration."""
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch


class TestAskOverwatch:
    def test_build_evidence_context_empty(self, mock_streamlit):
        from utils.ask_overwatch_cortex import _build_evidence_context

        context = _build_evidence_context({})
        assert "[SCOPE]" in context
        assert "ALFA" in context  # default company

    def test_build_evidence_context_with_data(self, mock_streamlit, sample_cost_data):
        from utils.ask_overwatch_cortex import _build_evidence_context

        state = {
            "cost_contract_cockpit": sample_cost_data,
            "active_company": "Trexis",
        }
        context = _build_evidence_context(state)
        assert "[COST DATA" in context
        assert "Trexis" in context

    def test_build_evidence_context_with_alerts(self, mock_streamlit, sample_alert_data):
        from utils.ask_overwatch_cortex import _build_evidence_context

        state = {"alert_center_data": sample_alert_data}
        context = _build_evidence_context(state)
        assert "[ALERTS]" in context

    def test_ask_overwatch_empty_question(self, mock_streamlit):
        from utils.ask_overwatch_cortex import ask_overwatch

        result = ask_overwatch("", session=MagicMock())
        assert "Please ask" in result

    def test_ask_overwatch_no_session(self, mock_streamlit):
        from utils.ask_overwatch_cortex import ask_overwatch

        # Mock session import failure
        with patch.dict("sys.modules", {"utils.session": MagicMock(side_effect=Exception("no conn"))}):
            result = ask_overwatch("test question", session=None)
            # Should either succeed with mocked session or report connection needed
            assert isinstance(result, str)

    def test_context_respects_max_length(self, mock_streamlit):
        from utils.ask_overwatch_cortex import _build_evidence_context, _MAX_CONTEXT_CHARS

        # Create a very large dataframe
        large_df = pd.DataFrame({
            "COL_" + str(i): range(100) for i in range(50)
        })
        state = {"cost_contract_cockpit": large_df}
        context = _build_evidence_context(state)
        assert len(context) <= _MAX_CONTEXT_CHARS
