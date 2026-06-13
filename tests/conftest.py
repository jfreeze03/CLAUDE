"""Shared test fixtures for OVERWATCH tests."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def mock_streamlit():
    """Mock streamlit for all tests — avoids needing a real Streamlit runtime."""
    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.secrets = MagicMock()
    mock_st.secrets.get.return_value = {}

    with patch.dict(sys.modules, {"streamlit": mock_st}):
        # Also mock streamlit submodules that config.py doesn't need
        with patch.dict(sys.modules, {
            "streamlit.runtime": MagicMock(),
            "streamlit.runtime.scriptrunner": MagicMock(),
        }):
            yield mock_st


@pytest.fixture
def sample_daily_credits():
    """Sample daily credit consumption DataFrame for testing."""
    import pandas as pd
    from datetime import date, timedelta

    dates = [date.today() - timedelta(days=i) for i in range(30, 0, -1)]
    credits = [100 + (i % 7) * 10 + (i * 2) for i in range(30)]

    return pd.DataFrame({
        "USAGE_DATE": dates,
        "DAILY_CREDITS": credits,
    })


@pytest.fixture
def sample_alert_data():
    """Sample alert DataFrame."""
    import pandas as pd

    return pd.DataFrame({
        "STATUS": ["NEW", "OPEN", "ESCALATED", "RESOLVED", "RESOLVED", "NEW", "OPEN"],
        "SEVERITY": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "MEDIUM", "HIGH", "LOW"],
        "ENTITY": ["WH_A", "WH_B", "TASK_C", "WH_A", "TASK_D", "WH_B", "WH_C"],
    })


@pytest.fixture
def sample_dba_snapshot():
    """Sample DBA control room snapshot DataFrame."""
    import pandas as pd

    return pd.DataFrame({
        "FAIL_COUNT": [3, 5, 0, 2, 1, 8, 0],
        "QUEUED_COUNT": [2, 0, 4, 1, 0, 3, 2],
        "ACTIVE_COUNT": [10, 8, 12, 6, 9, 11, 7],
        "BLOCKED_COUNT": [0, 0, 1, 0, 0, 2, 0],
    })


@pytest.fixture
def sample_cost_data():
    """Sample cost cockpit DataFrame."""
    import pandas as pd
    from datetime import date, timedelta

    dates = [date.today() - timedelta(days=i) for i in range(7, 0, -1)]
    return pd.DataFrame({
        "USAGE_DATE": dates,
        "TOTAL_CREDITS": [150.5, 162.3, 148.7, 155.0, 190.2, 145.8, 160.1],
        "VARIANCE_PCT": [2.1, 8.5, -1.2, 3.8, 25.4, -3.1, 6.2],
    })
