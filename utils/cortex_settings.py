# utils/cortex_settings.py - Cortex Code and AI settings management
"""
Manages Cortex Code and AI service configuration:
  - View account-level AI settings (CORTEX_ENABLED_CROSS_REGION, AI guardrails)
  - Check per-function privileges (who can use which Cortex functions)
  - View/manage AI spend controls
  - Cortex Code enablement status

Safety: Read operations are always allowed; write operations require admin gate.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


def build_ai_settings_sql() -> str:
    """SQL to check account-level AI/Cortex settings."""
    return """
    SELECT
        'CORTEX_ENABLED_CROSS_REGION' AS setting_name,
        SYSTEM$GET_SNOWFLAKE_PLATFORM_INFO()::VARIANT:CORTEX_ENABLED_CROSS_REGION::VARCHAR AS setting_value
    """


def load_cortex_function_grants(session) -> list[dict[str, Any]]:
    """Load grants on Cortex functions to check who has AI access."""
    try:
        rows = session.sql("""
            SELECT
                grantee_name,
                privilege,
                granted_on,
                name AS function_name,
                granted_by,
                created_on
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE granted_on = 'FUNCTION'
              AND (name ILIKE '%CORTEX%' OR name ILIKE '%COMPLETE%' OR name ILIKE '%TRANSLATE%'
                   OR name ILIKE '%SUMMARIZE%' OR name ILIKE '%SENTIMENT%')
              AND deleted_on IS NULL
            ORDER BY grantee_name, name
        """).collect()

        grants = []
        for row in rows:
            row_dict = row.as_dict() if hasattr(row, "as_dict") else dict(row)
            grants.append({
                "role": str(row_dict.get("GRANTEE_NAME", "")),
                "privilege": str(row_dict.get("PRIVILEGE", "")),
                "function": str(row_dict.get("FUNCTION_NAME", "")),
                "granted_by": str(row_dict.get("GRANTED_BY", "")),
            })
        return grants
    except Exception:
        return []


def load_cortex_usage_summary(session, days_back: int = 7) -> dict[str, Any]:
    """Load Cortex usage summary for the settings panel."""
    try:
        rows = session.sql(f"""
            SELECT
                'Cortex Code (Snowsight)' AS source,
                COUNT(*) AS request_count,
                ROUND(SUM(COALESCE(token_credits, 0)), 4) AS total_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
            WHERE usage_time >= DATEADD('day', -{int(days_back)}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT
                'Cortex Code (CLI)' AS source,
                COUNT(*) AS request_count,
                ROUND(SUM(COALESCE(token_credits, 0)), 4) AS total_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
            WHERE usage_time >= DATEADD('day', -{int(days_back)}, CURRENT_TIMESTAMP())
        """).collect()

        summary = {"sources": [], "total_credits": 0.0, "total_requests": 0}
        for row in rows:
            row_dict = row.as_dict() if hasattr(row, "as_dict") else dict(row)
            credits = float(row_dict.get("TOTAL_CREDITS", 0) or 0)
            requests = int(row_dict.get("REQUEST_COUNT", 0) or 0)
            summary["sources"].append({
                "source": str(row_dict.get("SOURCE", "")),
                "credits": credits,
                "requests": requests,
            })
            summary["total_credits"] += credits
            summary["total_requests"] += requests
        return summary
    except Exception as e:
        return {"sources": [], "total_credits": 0.0, "total_requests": 0, "error": str(e)[:200]}


def check_public_ai_access(session) -> list[dict[str, Any]]:
    """Check if PUBLIC role has Cortex/AI function access (security concern)."""
    try:
        rows = session.sql("""
            SELECT
                name AS function_name,
                privilege,
                granted_by,
                created_on
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
            WHERE grantee_name = 'PUBLIC'
              AND granted_on = 'FUNCTION'
              AND (name ILIKE '%CORTEX%' OR name ILIKE '%COMPLETE%'
                   OR name ILIKE '%TRANSLATE%' OR name ILIKE '%SUMMARIZE%')
              AND deleted_on IS NULL
        """).collect()

        findings = []
        for row in rows:
            row_dict = row.as_dict() if hasattr(row, "as_dict") else dict(row)
            findings.append({
                "function": str(row_dict.get("FUNCTION_NAME", "")),
                "privilege": str(row_dict.get("PRIVILEGE", "")),
                "granted_by": str(row_dict.get("GRANTED_BY", "")),
            })
        return findings
    except Exception:
        return []


def render_cortex_settings_panel(session, *, container=None) -> None:
    """Render the Cortex Code / AI settings control panel."""
    target = container or st

    target.markdown("**Cortex Code & AI Settings**")

    # Usage summary
    with target.spinner("Loading Cortex usage..."):
        usage = load_cortex_usage_summary(session)

    if usage.get("error"):
        target.warning(f"Cortex usage views not available: {usage['error']}")
        target.caption("This may require Enterprise Edition or the CORTEX_CODE usage history views to be enabled.")
    else:
        col1, col2, col3 = target.columns(3)
        with col1:
            target.metric("Total AI Credits (7d)", f"{usage['total_credits']:,.4f}")
        with col2:
            target.metric("Total Requests (7d)", f"{usage['total_requests']:,}")
        with col3:
            ai_price = float(st.session_state.get("ai_credit_price", 2.20))
            target.metric("Est. Cost (7d)", f"${usage['total_credits'] * ai_price:,.2f}")

        if usage["sources"]:
            for source in usage["sources"]:
                target.caption(f"  · {source['source']}: {source['requests']:,} requests, {source['credits']:,.4f} credits")

    target.divider()

    # Security check: PUBLIC AI access
    target.markdown("**AI Security Posture**")
    public_access = check_public_ai_access(session)
    if public_access:
        target.warning(f"⚠️ PUBLIC role has access to {len(public_access)} Cortex function(s) — review and restrict.")
        for finding in public_access[:5]:
            target.caption(f"  · {finding['function']} ({finding['privilege']}) granted by {finding['granted_by']}")
    else:
        target.success("✓ No PUBLIC blanket AI access detected. Cortex functions require explicit role grants.")

    # Function grants overview
    target.divider()
    target.markdown("**AI Function Grants**")
    grants = load_cortex_function_grants(session)
    if grants:
        import pandas as pd
        grants_df = pd.DataFrame(grants)
        role_counts = grants_df["role"].value_counts().head(10)
        for role, count in role_counts.items():
            target.caption(f"  · {role}: {count} Cortex function grant(s)")
        with target.expander("Full grant detail"):
            target.dataframe(grants_df, use_container_width=True)
    else:
        target.caption("No Cortex function grants found, or insufficient privileges to view GRANTS_TO_ROLES.")

    # Spend controls info
    target.divider()
    target.markdown("**AI Spend Controls**")
    target.caption(
        "Configure AI credit budgets via: Settings → Contract Capacity → AI Credit Rate. "
        "Per-user AI quotas require the Budget Governance workflow in Cost & Contract."
    )
    ai_price = float(st.session_state.get("ai_credit_price", 2.20))
    target.markdown(f"Current AI credit rate: **${ai_price:.2f}/credit**")
    if usage["total_credits"] > 0:
        projected_30d = usage["total_credits"] / 7 * 30
        target.markdown(f"Projected 30-day AI cost: **${projected_30d * ai_price:,.2f}** ({projected_30d:,.2f} credits)")
