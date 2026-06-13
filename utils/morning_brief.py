# utils/morning_brief.py - Automated DBA morning briefing generator
"""
Generates a structured morning brief from loaded OVERWATCH evidence.
Designed for delivery via:
  - Email (via Snowflake notification integration)
  - Teams webhook
  - Slack webhook
  - PDF export

The brief answers the 7am question: "What happened overnight and what do I need to act on?"
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Any

import streamlit as st


MORNING_BRIEF_VERSION = "2026-06-10-v1"


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        if value is None or value != value:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def build_morning_brief(state: dict | None = None) -> dict[str, Any]:
    """
    Build a structured morning brief from current session state evidence.

    Returns:
        {
            "generated_at": str (ISO timestamp),
            "scope": {"company": str, "environment": str, "window": str},
            "health_score": float | None,
            "sections": [
                {
                    "title": str,
                    "status": "green" | "yellow" | "red" | "unknown",
                    "summary": str,
                    "items": [str, ...],
                    "action_required": bool,
                },
                ...
            ],
            "action_items": [str, ...],
            "metrics": {"key": value, ...},
        }
    """
    import pandas as pd
    from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT

    if state is None:
        state = dict(st.session_state)

    company = str(state.get("active_company", DEFAULT_COMPANY))
    environment = str(state.get("global_environment", DEFAULT_ENVIRONMENT))
    start_date = state.get("global_start_date")
    end_date = state.get("global_end_date")
    window = "7d"
    if isinstance(start_date, date) and isinstance(end_date, date):
        window = f"{max(1, (end_date - start_date).days + 1)}d"

    brief = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scope": {"company": company, "environment": environment, "window": window},
        "health_score": None,
        "sections": [],
        "action_items": [],
        "metrics": {},
    }

    # Health score
    try:
        from .health_score import compute_platform_health_score
        health = compute_platform_health_score(state)
        brief["health_score"] = health.get("score")
        brief["metrics"]["health_grade"] = health.get("grade")
        brief["metrics"]["health_trend"] = health.get("trend")
    except Exception:
        pass

    # Cost section
    brief["sections"].append(_build_cost_section(state))

    # Reliability section
    brief["sections"].append(_build_reliability_section(state))

    # Security section
    brief["sections"].append(_build_security_section(state))

    # Alerts section
    brief["sections"].append(_build_alerts_section(state))

    # Collect action items from all sections
    for section in brief["sections"]:
        if section.get("action_required"):
            for item in section.get("items", []):
                if item and not item.startswith("✓"):
                    brief["action_items"].append(f"[{section['title']}] {item}")

    return brief


def _build_cost_section(state: dict) -> dict[str, Any]:
    """Summarize cost status from loaded evidence."""
    import pandas as pd

    section = {
        "title": "Cost & Spend",
        "status": "unknown",
        "summary": "No cost evidence loaded.",
        "items": [],
        "action_required": False,
    }

    cockpit = state.get("cost_contract_cockpit")
    if isinstance(cockpit, pd.DataFrame) and not cockpit.empty:
        credit_col = next(
            (c for c in cockpit.columns if "CREDIT" in c.upper() and "TOTAL" in c.upper()),
            next((c for c in cockpit.columns if "CREDIT" in c.upper()), None),
        )
        if credit_col:
            total = cockpit[credit_col].sum()
            section["metrics_total_credits"] = round(float(total), 1)
            section["summary"] = f"Total credits consumed: {total:,.1f}"
            section["status"] = "green"

        # Check for variance
        if "VARIANCE_PCT" in cockpit.columns:
            max_var = _safe_float(cockpit["VARIANCE_PCT"].max())
            if max_var > 30:
                section["status"] = "red"
                section["action_required"] = True
                section["items"].append(f"Cost spike detected: {max_var:.0f}% above baseline")
            elif max_var > 15:
                section["status"] = "yellow"
                section["items"].append(f"Elevated spend: {max_var:.0f}% above normal")
    else:
        section["items"].append("Load Cost & Contract workspace for bill evidence")

    return section


def _build_reliability_section(state: dict) -> dict[str, Any]:
    """Summarize reliability from DBA control room and workload data."""
    import pandas as pd

    section = {
        "title": "Reliability & Jobs",
        "status": "unknown",
        "summary": "No workload evidence loaded.",
        "items": [],
        "action_required": False,
    }

    dba_data = state.get("dba_control_room_data")
    if isinstance(dba_data, pd.DataFrame) and not dba_data.empty:
        failures = 0
        if "FAIL_COUNT" in dba_data.columns:
            failures = _safe_int(dba_data["FAIL_COUNT"].sum())

        queued = 0
        if "QUEUED_COUNT" in dba_data.columns:
            queued = _safe_int(dba_data["QUEUED_COUNT"].sum())

        section["summary"] = f"Failures: {failures}, Queued: {queued}"
        if failures > 20:
            section["status"] = "red"
            section["action_required"] = True
            section["items"].append(f"{failures} failures detected — investigate immediately")
        elif failures > 5:
            section["status"] = "yellow"
            section["items"].append(f"{failures} failures — review task graphs")
        else:
            section["status"] = "green"
            section["items"].append(f"✓ {failures} failures within normal range")

        if queued > 10:
            section["items"].append(f"Queue pressure: {queued} queries waiting")
            if section["status"] == "green":
                section["status"] = "yellow"
    else:
        section["items"].append("Load DBA Control Room for workload status")

    return section


def _build_security_section(state: dict) -> dict[str, Any]:
    """Summarize security posture from loaded evidence."""
    import pandas as pd

    section = {
        "title": "Security Posture",
        "status": "unknown",
        "summary": "No security evidence loaded.",
        "items": [],
        "action_required": False,
    }

    security_data = state.get("security_posture_summary")
    if isinstance(security_data, pd.DataFrame) and not security_data.empty:
        if "SEVERITY" in security_data.columns:
            critical = len(security_data[
                security_data["SEVERITY"].str.upper().isin(["CRITICAL", "HIGH"])
            ])
            if critical > 0:
                section["status"] = "red"
                section["action_required"] = True
                section["items"].append(f"{critical} critical/high security findings")
                section["summary"] = f"{critical} findings require attention"
            else:
                section["status"] = "green"
                section["summary"] = "No critical security findings"
                section["items"].append("✓ Security posture clean")
        else:
            section["status"] = "green"
            section["summary"] = "Security evidence loaded, no severity column"
    else:
        section["items"].append("Load Security Posture for grant and access evidence")

    return section


def _build_alerts_section(state: dict) -> dict[str, Any]:
    """Summarize alert status from loaded evidence."""
    import pandas as pd

    section = {
        "title": "Alerts & Actions",
        "status": "unknown",
        "summary": "No alert evidence loaded.",
        "items": [],
        "action_required": False,
    }

    alert_data = state.get("alert_center_data")
    if isinstance(alert_data, pd.DataFrame) and not alert_data.empty:
        if "STATUS" in alert_data.columns:
            open_alerts = len(alert_data[
                alert_data["STATUS"].str.upper().isin(["NEW", "OPEN", "ESCALATED"])
            ])
            total = len(alert_data)
            section["summary"] = f"{open_alerts} open of {total} total alerts"

            if open_alerts > 10:
                section["status"] = "red"
                section["action_required"] = True
                section["items"].append(f"{open_alerts} unresolved alerts — triage needed")
            elif open_alerts > 3:
                section["status"] = "yellow"
                section["items"].append(f"{open_alerts} open alerts in queue")
            else:
                section["status"] = "green"
                section["items"].append(f"✓ {open_alerts} open alerts — manageable")
        else:
            section["status"] = "yellow"
            section["summary"] = f"{len(alert_data)} alert rows loaded"
    else:
        section["items"].append("Load Alert Center for alert inbox status")

    return section


def format_brief_as_text(brief: dict[str, Any]) -> str:
    """Format the morning brief as plain text for email/chat delivery."""
    lines = []
    lines.append("=" * 60)
    lines.append("OVERWATCH MORNING BRIEF")
    lines.append(f"Generated: {brief.get('generated_at', 'Unknown')}")
    scope = brief.get("scope", {})
    lines.append(f"Scope: {scope.get('company', '?')} / {scope.get('environment', '?')} / {scope.get('window', '?')}")

    health = brief.get("health_score")
    if health is not None:
        grade = brief.get("metrics", {}).get("health_grade", "?")
        trend = brief.get("metrics", {}).get("health_trend", "unknown")
        lines.append(f"Platform Health: {health:.0f}/100 (Grade {grade}, {trend})")

    lines.append("=" * 60)
    lines.append("")

    for section in brief.get("sections", []):
        status_icons = {"green": "✓", "yellow": "⚠", "red": "✗", "unknown": "?"}
        icon = status_icons.get(section.get("status", "unknown"), "?")
        lines.append(f"[{icon}] {section['title']}")
        lines.append(f"    {section.get('summary', 'No data')}")
        for item in section.get("items", []):
            lines.append(f"    • {item}")
        lines.append("")

    action_items = brief.get("action_items", [])
    if action_items:
        lines.append("-" * 40)
        lines.append("ACTION REQUIRED:")
        for i, item in enumerate(action_items, 1):
            lines.append(f"  {i}. {item}")
        lines.append("")

    lines.append("-" * 40)
    lines.append("End of brief. Open OVERWATCH for full evidence.")
    return "\n".join(lines)


def format_brief_as_html(brief: dict[str, Any]) -> str:
    """Format the morning brief as HTML for rich email delivery."""
    import html as html_mod

    scope = brief.get("scope", {})
    health = brief.get("health_score")
    grade = brief.get("metrics", {}).get("health_grade", "?")

    health_color = "#22c55e" if (health or 0) >= 80 else "#f59e0b" if (health or 0) >= 60 else "#ef4444"

    sections_html = ""
    for section in brief.get("sections", []):
        status_colors = {"green": "#22c55e", "yellow": "#f59e0b", "red": "#ef4444", "unknown": "#64748b"}
        color = status_colors.get(section.get("status", "unknown"), "#64748b")
        items_html = "".join(
            f"<li style='margin:2px 0;'>{html_mod.escape(item)}</li>"
            for item in section.get("items", [])
        )
        sections_html += f"""
        <div style="margin:12px 0;padding:10px 14px;border-left:3px solid {color};background:#f8fafc;">
            <strong style="color:{color};">{html_mod.escape(section['title'])}</strong>
            <div style="font-size:13px;color:#475569;margin-top:4px;">{html_mod.escape(section.get('summary', ''))}</div>
            <ul style="margin:6px 0;padding-left:18px;font-size:12px;color:#334155;">{items_html}</ul>
        </div>
        """

    action_items = brief.get("action_items", [])
    actions_html = ""
    if action_items:
        items = "".join(f"<li style='margin:3px 0;'>{html_mod.escape(item)}</li>" for item in action_items)
        actions_html = f"""
        <div style="margin:16px 0;padding:12px;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;">
            <strong style="color:#dc2626;">Action Required</strong>
            <ol style="margin:6px 0;padding-left:20px;font-size:13px;color:#7f1d1d;">{items}</ol>
        </div>
        """

    return f"""
    <div style="font-family:Inter,system-ui,sans-serif;max-width:640px;margin:0 auto;padding:20px;">
        <div style="border-bottom:2px solid #e2e8f0;padding-bottom:12px;margin-bottom:16px;">
            <h2 style="margin:0;color:#0f172a;">OVERWATCH Morning Brief</h2>
            <div style="font-size:12px;color:#64748b;margin-top:4px;">
                {html_mod.escape(scope.get('company', '?'))} / {html_mod.escape(scope.get('environment', '?'))} / {html_mod.escape(scope.get('window', '?'))}
                &nbsp;·&nbsp; {html_mod.escape(brief.get('generated_at', ''))}
            </div>
            {'<div style="margin-top:8px;"><span style="font-size:24px;font-weight:800;color:' + health_color + ';">' + f"{health:.0f}" + '</span><span style="font-size:12px;color:#64748b;"> /100 Platform Health (Grade ' + html_mod.escape(grade) + ')</span></div>' if health else ''}
        </div>
        {sections_html}
        {actions_html}
        <div style="margin-top:20px;padding-top:12px;border-top:1px solid #e2e8f0;font-size:11px;color:#94a3b8;">
            Open OVERWATCH for full evidence and drill-down.
        </div>
    </div>
    """


def render_morning_brief_preview(brief: dict[str, Any], *, container=None) -> None:
    """Render an in-app preview of the morning brief."""
    target = container or st

    target.markdown("**Morning Brief Preview**")
    scope = brief.get("scope", {})
    target.caption(
        f"{scope.get('company', '?')} / {scope.get('environment', '?')} / "
        f"{scope.get('window', '?')} · Generated {brief.get('generated_at', 'now')}"
    )

    health = brief.get("health_score")
    if health is not None:
        grade = brief.get("metrics", {}).get("health_grade", "?")
        target.metric("Platform Health", f"{health:.0f}/100", delta=f"Grade {grade}")

    for section in brief.get("sections", []):
        status_icons = {"green": "🟢", "yellow": "🟡", "red": "🔴", "unknown": "⚪"}
        icon = status_icons.get(section.get("status", "unknown"), "⚪")
        target.markdown(f"{icon} **{section['title']}** — {section.get('summary', 'No data')}")
        for item in section.get("items", []):
            target.caption(f"  • {item}")

    action_items = brief.get("action_items", [])
    if action_items:
        target.warning(f"**{len(action_items)} action(s) required**")
        for item in action_items:
            target.caption(f"→ {item}")
