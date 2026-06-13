# utils/export_powerpoint.py - PowerPoint/slide deck generation
"""
Generates slide-ready content from OVERWATCH evidence:
  - Executive summary slides (health, cost, reliability)
  - KPI tables formatted for copy-paste into slides
  - Chart data exports for external visualization tools
  - Structured JSON for automation into Snowflake-native reports

Since python-pptx isn't available in SiS, we generate:
  1. CSV tables that paste cleanly into PowerPoint
  2. Markdown bullets for slide text
  3. JSON structures for external automation
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import streamlit as st


def build_slide_data(state: dict | None = None) -> dict[str, Any]:
    """
    Build structured slide content from loaded evidence.

    Returns:
        {
            "title": str,
            "generated_at": str,
            "slides": [
                {"title": str, "bullets": [str], "kpis": [dict], "table": [[str]]},
                ...
            ],
        }
    """
    import pandas as pd

    if state is None:
        state = dict(st.session_state)

    slides = []

    # Slide 1: Executive Summary
    health_bullets = []
    try:
        from .health_score import compute_platform_health_score
        health = compute_platform_health_score(state)
        health_bullets = [
            f"Platform Health: {health['score']:.0f}/100 (Grade {health['grade']})",
            f"Trend: {health['trend'].title()}",
            f"Cost Control: {health['components']['cost_control']['score']:.0f}/100",
            f"Reliability: {health['components']['reliability']['score']:.0f}/100",
            f"Security: {health['components']['security']['score']:.0f}/100",
            f"Operations: {health['components']['operations']['score']:.0f}/100",
        ]
    except Exception:
        health_bullets = ["Health score unavailable — load evidence first"]

    slides.append({
        "title": "Platform Health Summary",
        "bullets": health_bullets,
        "kpis": [],
        "table": None,
    })

    # Slide 2: Cost Summary
    cost_bullets = []
    cost_kpis = []
    credit_price = float(state.get("credit_price", 3.68))

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
            cost_kpis = [
                {"label": "Total Credits", "value": f"{total:,.0f}"},
                {"label": "Total Cost", "value": f"${total * credit_price:,.0f}"},
                {"label": "Credit Rate", "value": f"${credit_price:.2f}"},
            ]
            cost_bullets.append(f"Total consumption: {total:,.0f} credits (${total * credit_price:,.0f})")

    remaining = state.get("_contract_remaining_credits")
    if remaining:
        cost_kpis.append({"label": "Contract Remaining", "value": f"{int(remaining):,}"})
        cost_bullets.append(f"Contract remaining: {int(remaining):,} credits")

    if not cost_bullets:
        cost_bullets = ["Cost data not loaded"]

    slides.append({
        "title": "Cost & Contract Status",
        "bullets": cost_bullets,
        "kpis": cost_kpis,
        "table": None,
    })

    # Slide 3: Operational Status
    ops_bullets = []
    dba_data = state.get("dba_control_room_snapshot_result")
    if isinstance(dba_data, pd.DataFrame) and not dba_data.empty:
        failures = int(dba_data["FAIL_COUNT"].sum()) if "FAIL_COUNT" in dba_data.columns else 0
        queued = int(dba_data["QUEUED_COUNT"].sum()) if "QUEUED_COUNT" in dba_data.columns else 0
        ops_bullets = [
            f"Task Failures: {failures}",
            f"Queued Queries: {queued}",
            f"Status: {'Healthy' if failures < 5 else 'Needs attention'}",
        ]
    else:
        ops_bullets = ["Operational data not loaded"]

    slides.append({
        "title": "Operational Status",
        "bullets": ops_bullets,
        "kpis": [],
        "table": None,
    })

    # Slide 4: Action Items
    action_bullets = []
    alert_data = state.get("alert_center_data")
    if isinstance(alert_data, pd.DataFrame) and not alert_data.empty:
        if "STATUS" in alert_data.columns:
            open_count = len(alert_data[alert_data["STATUS"].str.upper().isin(["NEW", "OPEN", "ESCALATED"])])
            action_bullets.append(f"{open_count} open alerts require triage")

    if not action_bullets:
        action_bullets = ["No outstanding action items identified"]

    slides.append({
        "title": "Action Items & Next Steps",
        "bullets": action_bullets,
        "kpis": [],
        "table": None,
    })

    return {
        "title": "OVERWATCH Platform Report",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "company": str(state.get("active_company", "ALFA")),
        "slides": slides,
    }


def format_slides_as_markdown(slide_data: dict[str, Any]) -> str:
    """Format slide data as markdown for copy-paste into presentations."""
    lines = [
        f"# {slide_data['title']}",
        f"*Generated: {slide_data['generated_at']} | Company: {slide_data['company']}*",
        "",
    ]

    for i, slide in enumerate(slide_data["slides"], 1):
        lines.append(f"---")
        lines.append(f"## Slide {i}: {slide['title']}")
        lines.append("")

        if slide["kpis"]:
            lines.append("| KPI | Value |")
            lines.append("|-----|-------|")
            for kpi in slide["kpis"]:
                lines.append(f"| {kpi['label']} | {kpi['value']} |")
            lines.append("")

        for bullet in slide["bullets"]:
            lines.append(f"- {bullet}")
        lines.append("")

    return "\n".join(lines)


def format_slides_as_csv(slide_data: dict[str, Any]) -> str:
    """Format KPIs as CSV for direct import into PowerPoint charts."""
    rows = ["Category,Metric,Value"]
    for slide in slide_data["slides"]:
        category = slide["title"]
        for kpi in slide.get("kpis", []):
            rows.append(f"{category},{kpi['label']},{kpi['value']}")
        for bullet in slide.get("bullets", []):
            rows.append(f"{category},Note,\"{bullet}\"")
    return "\n".join(rows)


def render_export_panel(*, container=None) -> None:
    """Render the PowerPoint export panel with download buttons."""
    target = container or st

    slide_data = build_slide_data()

    target.markdown("**Slide Deck Export**")
    target.caption(f"Generated {slide_data['generated_at']} for {slide_data['company']}")

    # Preview
    for slide in slide_data["slides"]:
        with target.expander(slide["title"]):
            if slide["kpis"]:
                for kpi in slide["kpis"]:
                    target.markdown(f"**{kpi['label']}:** {kpi['value']}")
            for bullet in slide["bullets"]:
                target.markdown(f"- {bullet}")

    # Downloads
    col_md, col_csv, col_json = target.columns(3)
    with col_md:
        target.download_button(
            "Markdown",
            data=format_slides_as_markdown(slide_data),
            file_name=f"overwatch_slides_{date.today().isoformat()}.md",
            mime="text/markdown",
            key="export_slides_md",
        )
    with col_csv:
        target.download_button(
            "CSV (KPIs)",
            data=format_slides_as_csv(slide_data),
            file_name=f"overwatch_kpis_{date.today().isoformat()}.csv",
            mime="text/csv",
            key="export_slides_csv",
        )
    with col_json:
        target.download_button(
            "JSON (Full)",
            data=json.dumps(slide_data, indent=2, default=str),
            file_name=f"overwatch_slides_{date.today().isoformat()}.json",
            mime="application/json",
            key="export_slides_json",
        )
