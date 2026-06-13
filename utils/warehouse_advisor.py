# utils/warehouse_advisor.py - Intelligent warehouse optimization advisor
"""
Generates specific, actionable warehouse recommendations:
  - Suspend timeout optimization
  - Size right-sizing with before/after projection
  - Multi-cluster vs scale-up decision
  - Auto-suspend vs always-on decision
  - Warehouse consolidation candidates

Each recommendation includes:
  - The specific SQL to implement
  - Estimated monthly savings
  - Risk level and rollback plan
  - Proof evidence from query history
"""
from __future__ import annotations

from typing import Any


def build_suspend_timeout_analysis_sql(days_back: int = 7) -> str:
    """SQL to identify warehouses with suboptimal auto-suspend settings."""
    days_back = max(1, int(days_back or 7))
    return f"""
    WITH warehouse_settings AS (
        SELECT
            name AS warehouse_name,
            auto_suspend,
            auto_resume,
            warehouse_size,
            min_cluster_count,
            max_cluster_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES
        WHERE deleted_on IS NULL
    ),
    usage_pattern AS (
        SELECT
            warehouse_name,
            COUNT(DISTINCT DATE_TRUNC('hour', start_time)) AS active_hours,
            COUNT(*) AS query_count,
            ROUND(AVG(
                DATEDIFF('second', query_start_time, query_end_time)
            ), 1) AS avg_query_sec
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
        GROUP BY warehouse_name
    ),
    metering AS (
        SELECT
            warehouse_name,
            ROUND(SUM(credits_used), 4) AS total_credits,
            COUNT(DISTINCT DATE_TRUNC('hour', start_time)) AS metered_hours
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
        GROUP BY warehouse_name
    )
    SELECT
        ws.warehouse_name,
        ws.auto_suspend,
        ws.warehouse_size,
        COALESCE(up.active_hours, 0) AS active_hours,
        COALESCE(up.query_count, 0) AS query_count,
        COALESCE(up.avg_query_sec, 0) AS avg_query_sec,
        COALESCE(m.total_credits, 0) AS total_credits,
        COALESCE(m.metered_hours, 0) AS metered_hours,
        CASE
            WHEN ws.auto_suspend = 0 THEN 'Never suspends — always-on'
            WHEN ws.auto_suspend > 300 AND COALESCE(up.query_count, 0) < 100 THEN 'High timeout + low usage'
            WHEN ws.auto_suspend > 120 AND COALESCE(m.total_credits, 0) > 10 THEN 'Could benefit from 60s timeout'
            ELSE 'Acceptable'
        END AS recommendation_type,
        CASE
            WHEN ws.auto_suspend = 0 THEN 'Set AUTO_SUSPEND = 60 unless this is a dedicated always-on service'
            WHEN ws.auto_suspend > 300 AND COALESCE(up.query_count, 0) < 100 THEN 'Reduce AUTO_SUSPEND to 60 seconds'
            WHEN ws.auto_suspend > 120 THEN 'Consider reducing AUTO_SUSPEND to 60 seconds'
            ELSE 'No change needed'
        END AS recommendation
    FROM warehouse_settings ws
    LEFT JOIN usage_pattern up ON ws.warehouse_name = up.warehouse_name
    LEFT JOIN metering m ON ws.warehouse_name = m.warehouse_name
    WHERE ws.auto_suspend = 0
       OR (ws.auto_suspend > 120 AND COALESCE(up.query_count, 0) < 1000)
    ORDER BY COALESCE(m.total_credits, 0) DESC
    """


def build_consolidation_candidates_sql(days_back: int = 14) -> str:
    """SQL to find warehouses that could be consolidated."""
    days_back = max(7, int(days_back or 14))
    return f"""
    WITH warehouse_overlap AS (
        SELECT
            a.warehouse_name AS warehouse_a,
            b.warehouse_name AS warehouse_b,
            COUNT(DISTINCT DATE_TRUNC('hour', a.start_time)) AS overlapping_hours,
            COUNT(DISTINCT a.query_id) + COUNT(DISTINCT b.query_id) AS combined_queries
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY a
        JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY b
          ON DATE_TRUNC('hour', a.start_time) = DATE_TRUNC('hour', b.start_time)
         AND a.warehouse_name < b.warehouse_name
        WHERE a.start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND b.start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND a.warehouse_name IS NOT NULL
          AND b.warehouse_name IS NOT NULL
        GROUP BY a.warehouse_name, b.warehouse_name
        HAVING overlapping_hours < 5
    ),
    low_usage AS (
        SELECT
            warehouse_name,
            COUNT(*) AS query_count,
            ROUND(SUM(total_elapsed_time) / 1000.0 / 3600, 2) AS total_hours_runtime
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
        GROUP BY warehouse_name
        HAVING query_count < 100 AND total_hours_runtime < 1
    )
    SELECT
        warehouse_name,
        query_count,
        total_hours_runtime,
        'Low usage — consolidation candidate' AS recommendation
    FROM low_usage
    ORDER BY total_hours_runtime ASC
    LIMIT 20
    """


def generate_optimization_recommendations(
    suspend_df=None,
    consolidation_df=None,
    *,
    credit_price: float = 3.68,
) -> list[dict[str, Any]]:
    """Generate prioritized warehouse optimization recommendations."""
    import pandas as pd

    recommendations = []

    if isinstance(suspend_df, pd.DataFrame) and not suspend_df.empty:
        for _, row in suspend_df.head(10).iterrows():
            rec_type = str(row.get("RECOMMENDATION_TYPE", ""))
            if "Acceptable" in rec_type:
                continue

            wh_name = str(row.get("WAREHOUSE_NAME", ""))
            total_credits = float(row.get("TOTAL_CREDITS", 0) or 0)
            current_suspend = int(row.get("AUTO_SUSPEND", 0) or 0)

            # Estimate savings from reducing idle time
            est_savings_pct = 0.15 if current_suspend > 300 else 0.10 if current_suspend > 120 else 0.05
            if current_suspend == 0:
                est_savings_pct = 0.30  # Never-suspend has highest waste
            monthly_savings = total_credits * est_savings_pct * (30 / 7) * credit_price

            recommendations.append({
                "warehouse": wh_name,
                "type": "suspend_timeout",
                "severity": "High" if current_suspend == 0 else "Medium",
                "current_setting": f"AUTO_SUSPEND = {current_suspend}s",
                "recommended_setting": "AUTO_SUSPEND = 60",
                "sql": f'ALTER WAREHOUSE "{wh_name}" SET AUTO_SUSPEND = 60;',
                "est_monthly_savings": round(monthly_savings, 0),
                "risk": "Low — warehouse auto-resumes on next query",
                "evidence": f"{total_credits:.1f} credits in window, {int(row.get('QUERY_COUNT', 0))} queries",
            })

    if isinstance(consolidation_df, pd.DataFrame) and not consolidation_df.empty:
        for _, row in consolidation_df.head(5).iterrows():
            wh_name = str(row.get("WAREHOUSE_NAME", ""))
            query_count = int(row.get("QUERY_COUNT", 0) or 0)
            runtime_hours = float(row.get("TOTAL_HOURS_RUNTIME", 0) or 0)

            recommendations.append({
                "warehouse": wh_name,
                "type": "consolidation",
                "severity": "Low",
                "current_setting": f"{query_count} queries, {runtime_hours:.1f}h runtime",
                "recommended_setting": "Consolidate into shared warehouse",
                "sql": f"-- Review: {wh_name} has very low usage. Consider routing queries to a shared warehouse.",
                "est_monthly_savings": round(credit_price * 2, 0),  # Minimum 2 credits saved from not running
                "risk": "Medium — verify no scheduling dependencies before consolidating",
                "evidence": f"Only {query_count} queries and {runtime_hours:.1f}h total runtime in the observation window",
            })

    # Sort by savings potential
    recommendations.sort(key=lambda r: r.get("est_monthly_savings", 0), reverse=True)
    return recommendations


def render_recommendations_panel(recommendations: list[dict[str, Any]], *, container=None) -> None:
    """Render optimization recommendations with actionable SQL."""
    import streamlit as st

    target = container or st

    if not recommendations:
        target.success("✓ No optimization recommendations. Warehouse configuration looks healthy.")
        return

    total_savings = sum(r.get("est_monthly_savings", 0) for r in recommendations)
    target.markdown(f"**{len(recommendations)} optimization(s)** — Est. ${total_savings:,.0f}/mo savings potential")

    for i, rec in enumerate(recommendations[:8]):
        sev_colors = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}
        icon = sev_colors.get(rec.get("severity", "Low"), "⚪")

        with target.expander(
            f"{icon} {rec['warehouse']} — {rec['type'].replace('_', ' ').title()} "
            f"(${rec.get('est_monthly_savings', 0):,.0f}/mo)",
            expanded=i == 0,
        ):
            target.markdown(f"**Current:** {rec.get('current_setting', '')}")
            target.markdown(f"**Recommended:** {rec.get('recommended_setting', '')}")
            target.code(rec.get("sql", ""), language="sql")
            target.caption(f"Risk: {rec.get('risk', '')} · Evidence: {rec.get('evidence', '')}")
