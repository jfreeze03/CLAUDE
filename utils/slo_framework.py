# utils/slo_framework.py - SLO/SLI framework with burn-rate alerting
"""
Define Service Level Objectives, measure Indicators, and alert on burn rate:
  - Define SLOs: "p95 query latency < 5s", "cost < $500/day", "task success > 99%"
  - Measure SLIs from Snowflake data
  - Compute error budget burn rate
  - Alert when burn rate exceeds threshold

Integration points: PagerDuty, ServiceNow, email via webhook/notification.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st


# ─── SLO definitions ─────────────────────────────────────────────────────────

DEFAULT_SLOS: list[dict[str, Any]] = [
    {
        "id": "task_success_rate",
        "name": "Task Success Rate",
        "target": 99.0,
        "unit": "%",
        "window_days": 7,
        "category": "reliability",
        "sql_fn": "build_task_sli_sql",
    },
    {
        "id": "query_p95_latency",
        "name": "Query P95 Latency",
        "target": 10.0,
        "unit": "seconds",
        "window_days": 7,
        "category": "performance",
        "sql_fn": "build_query_latency_sli_sql",
    },
    {
        "id": "daily_cost_limit",
        "name": "Daily Cost Limit",
        "target": 500.0,
        "unit": "$/day",
        "window_days": 7,
        "category": "cost",
        "sql_fn": "build_cost_sli_sql",
    },
    {
        "id": "alert_resolution_24h",
        "name": "Alert Resolution within 24h",
        "target": 90.0,
        "unit": "%",
        "window_days": 30,
        "category": "operations",
        "sql_fn": "build_alert_resolution_sli_sql",
    },
]


def build_task_sli_sql(days: int = 7) -> str:
    return f"""
    SELECT
        COUNT_IF(state = 'SUCCEEDED') * 100.0 / NULLIF(COUNT(*), 0) AS sli_value
    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
    WHERE scheduled_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
      AND state IN ('SUCCEEDED', 'FAILED')
    """


def build_query_latency_sli_sql(days: int = 7) -> str:
    return f"""
    SELECT
        ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_elapsed_time / 1000.0), 2) AS sli_value
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
      AND execution_status = 'SUCCESS'
      AND warehouse_name IS NOT NULL
    """


def build_cost_sli_sql(days: int = 7) -> str:
    return f"""
    SELECT
        ROUND(AVG(daily_cost), 2) AS sli_value
    FROM (
        SELECT DATE(start_time) AS usage_date,
               SUM(credits_used) * 3.68 AS daily_cost
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        GROUP BY usage_date
    )
    """


def build_alert_resolution_sli_sql(days: int = 30) -> str:
    return f"""
    SELECT
        COUNT_IF(DATEDIFF('hour', CREATED_AT, COALESCE(RESOLVED_AT, CURRENT_TIMESTAMP())) <= 24)
        * 100.0 / NULLIF(COUNT(*), 0) AS sli_value
    FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS
    WHERE CREATED_AT >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
    """


_SLI_BUILDERS = {
    "build_task_sli_sql": build_task_sli_sql,
    "build_query_latency_sli_sql": build_query_latency_sli_sql,
    "build_cost_sli_sql": build_cost_sli_sql,
    "build_alert_resolution_sli_sql": build_alert_resolution_sli_sql,
}


def measure_sli(session, slo: dict[str, Any]) -> float | None:
    """Measure an SLI by executing its SQL against Snowflake."""
    builder_name = slo.get("sql_fn", "")
    builder = _SLI_BUILDERS.get(builder_name)
    if not builder:
        return None

    try:
        sql = builder(slo.get("window_days", 7))
        rows = session.sql(sql).collect()
        if rows:
            rd = rows[0].as_dict() if hasattr(rows[0], "as_dict") else dict(rows[0])
            return float(rd.get("SLI_VALUE", 0) or 0)
    except Exception:
        return None


def compute_error_budget(sli_value: float, target: float, *, higher_is_better: bool = True) -> dict[str, Any]:
    """
    Compute error budget status.

    Returns:
        {
            "budget_remaining_pct": float (0-100, negative = breached),
            "burn_rate": float (1.0 = normal, >1 = burning fast),
            "status": "healthy" | "warning" | "critical" | "breached",
        }
    """
    if higher_is_better:
        # e.g., success rate: target=99%, sli=98% → budget = 1% allowed, used 1%
        allowed_error = 100.0 - target
        actual_error = 100.0 - sli_value
    else:
        # e.g., latency: target=5s, sli=4s → budget = 5s allowed, used 4s
        allowed_error = target
        actual_error = sli_value

    if allowed_error <= 0:
        return {"budget_remaining_pct": 0, "burn_rate": 99.0, "status": "breached"}

    budget_used_pct = (actual_error / allowed_error) * 100
    budget_remaining_pct = 100.0 - budget_used_pct
    burn_rate = budget_used_pct / 100.0  # 1.0 = exactly at budget

    if budget_remaining_pct <= 0:
        status = "breached"
    elif burn_rate > 2.0:
        status = "critical"
    elif burn_rate > 1.0:
        status = "warning"
    else:
        status = "healthy"

    return {
        "budget_remaining_pct": round(budget_remaining_pct, 1),
        "burn_rate": round(burn_rate, 2),
        "status": status,
    }


def evaluate_all_slos(session) -> list[dict[str, Any]]:
    """Evaluate all defined SLOs and return results."""
    results = []
    for slo in DEFAULT_SLOS:
        sli = measure_sli(session, slo)
        if sli is None:
            results.append({**slo, "sli_value": None, "budget": None, "status": "unmeasured"})
            continue

        higher_is_better = slo["id"] != "query_p95_latency" and slo["id"] != "daily_cost_limit"
        budget = compute_error_budget(sli, slo["target"], higher_is_better=higher_is_better)
        results.append({**slo, "sli_value": round(sli, 2), "budget": budget, "status": budget["status"]})

    return results


def build_pagerduty_webhook_payload(slo_result: dict[str, Any]) -> dict[str, Any]:
    """Build a PagerDuty Events API v2 payload for SLO breach."""
    severity_map = {"breached": "critical", "critical": "error", "warning": "warning"}
    return {
        "routing_key": "<PAGERDUTY_ROUTING_KEY>",
        "event_action": "trigger",
        "payload": {
            "summary": f"OVERWATCH SLO Breach: {slo_result['name']} "
                       f"(current: {slo_result.get('sli_value', '?')}, target: {slo_result['target']}{slo_result['unit']})",
            "severity": severity_map.get(slo_result["status"], "warning"),
            "source": "OVERWATCH",
            "component": slo_result["category"],
            "custom_details": {
                "slo_id": slo_result["id"],
                "target": slo_result["target"],
                "current_value": slo_result.get("sli_value"),
                "budget_remaining": slo_result.get("budget", {}).get("budget_remaining_pct"),
                "burn_rate": slo_result.get("budget", {}).get("burn_rate"),
            },
        },
    }


def render_slo_dashboard(session, *, container=None) -> None:
    """Render the SLO/SLI dashboard."""
    target = container or st

    target.markdown("**Service Level Objectives**")
    results = evaluate_all_slos(session)

    for result in results:
        status_icons = {"healthy": "🟢", "warning": "🟡", "critical": "🟠", "breached": "🔴", "unmeasured": "⚪"}
        icon = status_icons.get(result["status"], "⚪")

        if result.get("sli_value") is not None:
            budget = result.get("budget", {})
            target.markdown(
                f"{icon} **{result['name']}** — "
                f"Current: {result['sli_value']}{result['unit']} | "
                f"Target: {result['target']}{result['unit']} | "
                f"Budget: {budget.get('budget_remaining_pct', '?')}% remaining | "
                f"Burn: {budget.get('burn_rate', '?')}x"
            )
        else:
            target.markdown(f"{icon} **{result['name']}** — Not measured (query failed or no data)")
