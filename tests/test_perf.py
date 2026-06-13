"""Tests for the performance optimization utilities."""
import pandas as pd
import pytest


class TestPerf:
    def test_lazy_import_caches(self, mock_streamlit):
        from utils.perf import lazy_import, _LAZY_MODULES

        # Clear cache for test
        _LAZY_MODULES.pop("json", None)
        mod1 = lazy_import("json")
        mod2 = lazy_import("json")
        assert mod1 is mod2

    def test_precompute_shell_metrics_dba(self, mock_streamlit, sample_dba_snapshot):
        from utils.perf import precompute_shell_metrics

        metrics = precompute_shell_metrics("dba_control_room_snapshot_result", sample_dba_snapshot)
        assert "FAIL_COUNT" in metrics
        assert metrics["FAIL_COUNT"] == int(sample_dba_snapshot["FAIL_COUNT"].sum())
        assert "QUEUED_COUNT" in metrics
        assert "ACTIVE_COUNT" in metrics

    def test_precompute_shell_metrics_cost(self, mock_streamlit, sample_cost_data):
        from utils.perf import precompute_shell_metrics

        metrics = precompute_shell_metrics("cost_contract_cockpit", sample_cost_data)
        assert "total_credits" in metrics
        assert metrics["total_credits"] == sample_cost_data["TOTAL_CREDITS"].sum()
        assert "max_variance" in metrics
        assert "unique_dates" in metrics

    def test_precompute_shell_metrics_alerts(self, mock_streamlit, sample_alert_data):
        from utils.perf import precompute_shell_metrics

        metrics = precompute_shell_metrics("alert_center_data", sample_alert_data)
        assert "open_count" in metrics
        assert metrics["open_count"] == 4  # NEW + OPEN + ESCALATED + NEW
        assert metrics["total_count"] == 7

    def test_precompute_caches_result(self, mock_streamlit, sample_dba_snapshot):
        from utils.perf import precompute_shell_metrics, get_cached_metrics

        mock_streamlit.session_state = {}
        precompute_shell_metrics("dba_control_room_snapshot_result", sample_dba_snapshot)

        # Should return cached without re-computing
        cached = get_cached_metrics("dba_control_room_snapshot_result")
        assert cached.get("FAIL_COUNT") == int(sample_dba_snapshot["FAIL_COUNT"].sum())

    def test_html_batch(self, mock_streamlit):
        from utils.perf import HtmlBatch

        batch = HtmlBatch()
        assert not batch
        batch.add("<div>A</div>")
        batch.add("<div>B</div>")
        assert batch
        # Can't test render without real streamlit, but can test accumulation
        assert len(batch._parts) == 2

    def test_store_pruned(self, mock_streamlit, sample_dba_snapshot):
        from utils.perf import store_pruned, get_shell_df

        mock_streamlit.session_state = {}
        store_pruned("dba_control_room_snapshot_result", sample_dba_snapshot)

        # Full DataFrame stored
        assert "dba_control_room_snapshot_result" in mock_streamlit.session_state
        # Shell copy stored with fewer columns
        shell = get_shell_df("dba_control_room_snapshot_result")
        assert shell is not None
        assert len(shell.columns) <= len(sample_dba_snapshot.columns)

    def test_get_row_limit(self, mock_streamlit):
        from utils.perf import get_row_limit

        assert get_row_limit("shell_kpi") == 50
        assert get_row_limit("shell_sparkline") == 30
        assert get_row_limit("workspace_detail") == 2000
        assert get_row_limit("unknown") == 5000

    def test_dedup_key(self, mock_streamlit):
        from utils.perf import deduplicate_query_key

        key1 = deduplicate_query_key("SELECT 1", "scope_a")
        key2 = deduplicate_query_key("SELECT 1", "scope_a")
        key3 = deduplicate_query_key("SELECT 2", "scope_a")

        assert key1 == key2
        assert key1 != key3
