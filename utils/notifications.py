# utils/notifications.py - In-app notification center
"""
Surfaces the most important signals without navigation:
  - Unread alerts since last visit
  - Recent action queue changes
  - Anomaly detections
  - Self-healing suggestions

Renders as a compact badge in the app header and an
expandable panel with notification details.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st


_NOTIFICATIONS_KEY = "_overwatch_notifications"
_LAST_SEEN_KEY = "_overwatch_notifications_last_seen"


def _get_notifications() -> list[dict[str, Any]]:
    """Collect current notifications from session state evidence."""
    notifications = []

    # Unread alerts
    import pandas as pd
    alert_data = st.session_state.get("alert_center_data")
    if isinstance(alert_data, pd.DataFrame) and not alert_data.empty:
        if "STATUS" in alert_data.columns:
            open_count = int(alert_data["STATUS"].str.upper().isin(["NEW", "OPEN", "ESCALATED"]).sum())
            if open_count > 0:
                notifications.append({
                    "type": "alert",
                    "severity": "high" if open_count > 5 else "medium",
                    "message": f"{open_count} open alert(s) need triage",
                    "route": "Alert Center",
                })

    # Cost anomalies
    from utils.perf import get_cached_metrics
    cost_metrics = get_cached_metrics("cost_contract_cockpit")
    if cost_metrics.get("max_variance", 0) > 25:
        notifications.append({
            "type": "cost",
            "severity": "high",
            "message": f"Cost spike: {cost_metrics['max_variance']:.0f}% above baseline",
            "route": "Cost & Contract",
        })

    # Task failures
    dba_metrics = get_cached_metrics("dba_control_room_snapshot_result")
    if dba_metrics.get("FAIL_COUNT", 0) > 10:
        notifications.append({
            "type": "reliability",
            "severity": "high",
            "message": f"{dba_metrics['FAIL_COUNT']} task failures detected",
            "route": "DBA Control Room",
        })
    elif dba_metrics.get("FAIL_COUNT", 0) > 3:
        notifications.append({
            "type": "reliability",
            "severity": "medium",
            "message": f"{dba_metrics['FAIL_COUNT']} task failures",
            "route": "DBA Control Room",
        })

    # Security findings
    sec_data = st.session_state.get("security_posture_summary")
    if isinstance(sec_data, pd.DataFrame) and not sec_data.empty:
        if "SEVERITY" in sec_data.columns:
            critical = int(sec_data["SEVERITY"].str.upper().isin(["CRITICAL"]).sum())
            if critical > 0:
                notifications.append({
                    "type": "security",
                    "severity": "critical",
                    "message": f"{critical} critical security finding(s)",
                    "route": "Security Posture",
                })

    return notifications


def get_notification_count() -> int:
    """Get current notification count for badge display."""
    return len(_get_notifications())


def render_notification_badge(*, container=None) -> None:
    """Render the notification bell badge in the header."""
    target = container or st

    count = get_notification_count()
    if count == 0:
        return

    # Badge color
    notifications = _get_notifications()
    has_critical = any(n["severity"] == "critical" for n in notifications)
    has_high = any(n["severity"] == "high" for n in notifications)
    color = "#ef4444" if has_critical else "#f97316" if has_high else "#f59e0b"

    target.markdown(
        f'<div style="display:inline-flex;align-items:center;gap:4px;padding:3px 8px;'
        f'border-radius:12px;background:{color}20;border:1px solid {color}40;'
        f'font-size:0.7rem;font-weight:700;color:{color};">'
        f'🔔 {count}'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_notification_panel(*, container=None) -> None:
    """Render the full notification panel with details."""
    target = container or st

    notifications = _get_notifications()

    if not notifications:
        target.caption("✓ No notifications. All systems operating normally.")
        return

    severity_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}

    for notif in notifications:
        icon = severity_icons.get(notif["severity"], "⚪")
        target.markdown(
            f"{icon} **{notif['message']}**"
        )
        target.caption(f"  → Navigate to {notif['route']}")
