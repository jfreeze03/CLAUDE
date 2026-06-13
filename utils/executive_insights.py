# utils/executive_insights.py - Auto-generated executive narrative insights
"""
Transforms raw metrics into human-readable narrative bullets suitable
for board presentations, weekly status emails, and leadership 1:1s.

Instead of showing "Credits: 4,521" alone, generates:
"Credit consumption increased 12% week-over-week, driven primarily by
WH_ALFA_TRANSFORM (+340 credits from a new ETL pipeline)."

This is the bridge between DBA evidence and executive communication.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


def generate_cost_narrative(state: dict | None = None) -> list[str]:
    """Generate executive cost narrative bullets from loaded evidence."""
    import pandas as pd

    if state is None:
        state = dict(st.session_state)

    bullets = []

    # Cost data
    cockpit = state.get("cost_contract_cockpit")
    splash = state.get("cost_contract_splash")
    cost_df = cockpit if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else splash

    if isinstance(cost_df, pd.DataFrame) and not cost_df.empty:
        credit_col = next(
            (c for c in cost_df.columns if "CREDIT" in c.upper() and "TOTAL" in c.upper()),
            next((c for c in cost_df.columns if "CREDIT" in c.upper()), None),
        )
        if credit_col:
            total = float(cost_df[credit_col].sum())
            credit_price = float(state.get("credit_price", 3.68))
            cost_usd = total * credit_price
            bullets.append(
                f"Total spend in the selected window: {total:,.0f} credits (${cost_usd:,.0f})."
            )

            # Variance analysis
            if "VARIANCE_PCT" in cost_df.columns:
                max_var = float(cost_df["VARIANCE_PCT"].max())
                if max_var > 20:
                    bullets.append(
                        f"Peak variance reached {max_var:.0f}% above baseline — investigate for runaway workloads."
                    )
                elif max_var > 10:
                    bullets.append(
                        f"Moderate cost variance ({max_var:.0f}% above baseline) — within acceptable bounds but trending up."
                    )
                else:
                    bullets.append("Cost variance is within normal bounds. No intervention needed.")

    # Contract info
    remaining = state.get("_contract_remaining_credits")
    total_contract = state.get("_contract_total_credits")
    if remaining and total_contract:
        utilization = ((total_contract - remaining) / total_contract) * 100
        bullets.append(
            f"Contract utilization: {utilization:.0f}% consumed, {int(remaining):,} credits remaining."
        )
        if utilization > 80:
            bullets.append("⚠️ Contract is over 80% consumed. Schedule a capacity review.")

    if not bullets:
        bullets.append("Cost evidence is not yet loaded. Open Cost & Contract to generate spend narrative.")

    return bullets


def generate_reliability_narrative(state: dict | None = None) -> list[str]:
    """Generate executive reliability narrative from loaded evidence."""
    import pandas as pd

    if state is None:
        state = dict(st.session_state)

    bullets = []

    dba_data = state.get("dba_control_room_snapshot_result")
    if isinstance(dba_data, pd.DataFrame) and not dba_data.empty:
        failures = int(dba_data["FAIL_COUNT"].sum()) if "FAIL_COUNT" in dba_data.columns else 0
        queued = int(dba_data["QUEUED_COUNT"].sum()) if "QUEUED_COUNT" in dba_data.columns else 0

        if failures == 0:
            bullets.append("Zero task failures in the observation window. All scheduled jobs completed successfully.")
        elif failures <= 5:
            bullets.append(f"{failures} minor task failures detected — within acceptable noise floor.")
        else:
            bullets.append(f"{failures} task failures require DBA investigation. Escalation may be needed.")

        if queued > 10:
            bullets.append(f"Queue pressure detected: {queued} queries waiting. Consider capacity review.")
    else:
        bullets.append("Reliability evidence is not yet loaded. Open DBA Control Room for operational status.")

    return bullets


def generate_security_narrative(state: dict | None = None) -> list[str]:
    """Generate executive security narrative from loaded evidence."""
    import pandas as pd

    if state is None:
        state = dict(st.session_state)

    bullets = []

    security_data = state.get("security_posture_summary")
    if isinstance(security_data, pd.DataFrame) and not security_data.empty:
        if "SEVERITY" in security_data.columns:
            critical = len(security_data[security_data["SEVERITY"].str.upper().isin(["CRITICAL", "HIGH"])])
            total = len(security_data)
            if critical == 0:
                bullets.append("Security posture is clean. No critical or high-severity findings.")
            else:
                bullets.append(f"{critical} critical/high security finding(s) of {total} total require remediation.")
        else:
            bullets.append(f"Security evidence loaded ({len(security_data)} rows). Review for access anomalies.")
    else:
        bullets.append("Security evidence is not yet loaded. Open Security Posture for access review.")

    return bullets


def generate_full_executive_narrative(state: dict | None = None) -> dict[str, list[str]]:
    """Generate the complete executive narrative package."""
    if state is None:
        state = dict(st.session_state)

    # Health score context
    health_bullets = []
    try:
        from .health_score import compute_platform_health_score
        health = compute_platform_health_score(state)
        score = health["score"]
        grade = health["grade"]
        trend = health["trend"]
        health_bullets.append(f"Platform Health Score: {score:.0f}/100 (Grade {grade}, {trend}).")
        if score >= 85:
            health_bullets.append("The platform is operating within healthy parameters.")
        elif score >= 70:
            health_bullets.append("Minor attention areas identified but no critical risks.")
        else:
            health_bullets.append("Health score indicates multiple areas needing immediate attention.")
    except Exception:
        health_bullets.append("Health score unavailable — load evidence to generate.")

    return {
        "health": health_bullets,
        "cost": generate_cost_narrative(state),
        "reliability": generate_reliability_narrative(state),
        "security": generate_security_narrative(state),
    }


def render_executive_narrative(*, container=None) -> None:
    """Render the executive narrative as formatted bullets."""
    target = container or st

    narrative = generate_full_executive_narrative()

    target.markdown("**Executive Summary**")

    for section_title, bullets in [
        ("Platform Health", narrative["health"]),
        ("Cost & Spend", narrative["cost"]),
        ("Reliability", narrative["reliability"]),
        ("Security", narrative["security"]),
    ]:
        target.markdown(f"**{section_title}**")
        for bullet in bullets:
            target.markdown(f"- {bullet}")

    target.caption("Generated from loaded OVERWATCH evidence. Refresh sections for latest data.")


def format_narrative_for_email(narrative: dict[str, list[str]]) -> str:
    """Format the narrative as plain text for email delivery."""
    lines = ["OVERWATCH Executive Summary", "=" * 40, ""]

    for section, bullets in [
        ("Platform Health", narrative.get("health", [])),
        ("Cost & Spend", narrative.get("cost", [])),
        ("Reliability", narrative.get("reliability", [])),
        ("Security", narrative.get("security", [])),
    ]:
        lines.append(f"[{section}]")
        for bullet in bullets:
            lines.append(f"  • {bullet}")
        lines.append("")

    lines.append("-" * 40)
    lines.append("Generated by OVERWATCH. Open dashboard for full evidence.")
    return "\n".join(lines)
