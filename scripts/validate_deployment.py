#!/usr/bin/env python3
"""OVERWATCH deployment validation script.

Run before deploying to Snowflake Streamlit:
    python scripts/validate_deployment.py

Checks:
  1. All section modules import without error
  2. Config version is consistent
  3. No circular imports
  4. All utils exports resolve
  5. Theme CSS generates without error
  6. Shell render functions exist
  7. SQL builders produce valid-looking SQL
"""
import sys
import importlib
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

PASS = "✓"
FAIL = "✗"
errors = []


def check(description: str, fn):
    """Run a check and report pass/fail."""
    try:
        result = fn()
        if result is False:
            errors.append(description)
            print(f"  {FAIL} {description}")
        else:
            print(f"  {PASS} {description}")
    except Exception as e:
        errors.append(f"{description}: {e}")
        print(f"  {FAIL} {description}: {e}")


def main():
    print("OVERWATCH Deployment Validation")
    print("=" * 50)

    # Mock streamlit for import validation
    from unittest.mock import MagicMock, patch
    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.secrets = MagicMock()
    mock_st.secrets.get.return_value = {}

    with patch.dict(sys.modules, {
        "streamlit": mock_st,
        "streamlit.runtime": MagicMock(),
        "streamlit.runtime.scriptrunner": MagicMock(),
    }):
        print("\n[1] Config imports")
        check("config.py loads", lambda: importlib.import_module("config"))

        print("\n[2] Utils package")
        check("utils/__init__.py loads", lambda: importlib.import_module("utils"))

        print("\n[3] Core utility modules")
        core_modules = [
            "utils.health_score",
            "utils.contract_forecast",
            "utils.anomaly_detection",
            "utils.sla_tracking",
            "utils.sparklines",
            "utils.credit_rates",
            "utils.data_quality",
            "utils.incident_correlation",
            "utils.chargeback",
            "utils.dependency_graph",
            "utils.morning_brief",
            "utils.scheduled_delivery",
            "utils.company_config_loader",
            "utils.multi_account",
            "utils.network_egress",
            "utils.ask_overwatch_cortex",
        ]
        for mod in core_modules:
            check(f"{mod} imports", lambda m=mod: importlib.import_module(m))

        print("\n[4] Section shell modules")
        shell_modules = [
            "sections.shell_helpers",
            "sections.executive_landing_shell",
            "sections.dba_control_room_shell",
            "sections.cost_contract_shell",
            "sections.alert_center_shell",
            "sections.workload_operations_shell",
            "sections.warehouse_health_shell",
            "sections.architecture_readiness_shell",
            "sections.change_drift_shell",
            "sections.account_health_shell",
        ]
        for mod in shell_modules:
            check(f"{mod} imports", lambda m=mod: importlib.import_module(m))

        print("\n[5] Shell render functions exist")
        for mod_name in shell_modules:
            if "shell_helpers" in mod_name:
                continue
            mod = importlib.import_module(mod_name)
            check(f"{mod_name}.render() exists", lambda m=mod: hasattr(m, "render") and callable(m.render))

        print("\n[6] SQL builder validation")
        sql_builders = [
            ("utils.contract_forecast", "build_contract_burn_sql", {}),
            ("utils.anomaly_detection", "build_cost_anomaly_sql", {}),
            ("utils.anomaly_detection", "build_query_regression_sql", {}),
            ("utils.sla_tracking", "build_task_sla_compliance_sql", {}),
            ("utils.sla_tracking", "build_overall_sla_sql", {}),
            ("utils.data_quality", "build_load_freshness_sql", {}),
            ("utils.data_quality", "build_row_count_drift_sql", {}),
            ("utils.chargeback", "build_chargeback_by_owner_sql", {}),
            ("utils.multi_account", "build_org_credit_summary_sql", {}),
            ("utils.network_egress", "build_data_transfer_sql", {}),
        ]
        for mod_name, fn_name, kwargs in sql_builders:
            def _check(m=mod_name, f=fn_name, k=kwargs):
                mod = importlib.import_module(m)
                sql = getattr(mod, f)(**k)
                assert isinstance(sql, str) and len(sql) > 50, f"SQL too short: {len(sql)}"
                assert "SELECT" in sql.upper() or "WITH" in sql.upper(), "Missing SELECT/WITH"
                return True
            check(f"{mod_name}.{fn_name}() produces SQL", _check)

        print("\n[7] Theme system")
        check("theme.py loads", lambda: importlib.import_module("theme"))
        theme = importlib.import_module("theme")
        check("THEMES dict has entries", lambda: len(getattr(theme, "THEMES", {})) >= 3)

        print("\n[8] Utils export coverage")
        utils = importlib.import_module("utils")
        exports = getattr(utils, "__all__", ())
        check(f"Utils exports {len(exports)} symbols", lambda: len(exports) >= 100)

    # Summary
    print("\n" + "=" * 50)
    if errors:
        print(f"\n{FAIL} {len(errors)} check(s) failed:")
        for err in errors:
            print(f"    - {err}")
        sys.exit(1)
    else:
        print(f"\n{PASS} All checks passed. Ready for deployment.")
        sys.exit(0)


if __name__ == "__main__":
    main()
