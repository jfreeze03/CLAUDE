# utils/breadcrumb.py - Navigation breadcrumb component
"""
Shows: Domain > Section > Current View
Helps users understand where they are in the navigation hierarchy.
"""
from __future__ import annotations

import html

import streamlit as st

from config import SECTION_DEFINITIONS


# Build reverse lookup: section label → group
_SECTION_TO_GROUP: dict[str, str] = {}
for _sec in SECTION_DEFINITIONS:
    _SECTION_TO_GROUP[_sec.label] = _sec.group


def get_breadcrumb_parts() -> list[str]:
    """Get the current navigation breadcrumb parts."""
    section = str(st.session_state.get("nav_section", "Executive Landing"))
    group = _SECTION_TO_GROUP.get(section, "OVERWATCH")

    parts = ["OVERWATCH", group, section]

    # Add sub-view if present
    for key_suffix in ("_view", "_pane", "_workflow"):
        for state_key in st.session_state:
            if state_key.endswith(key_suffix) and section.lower().replace(" ", "_") in state_key.lower():
                sub_view = str(st.session_state[state_key])
                if sub_view and sub_view != section:
                    parts.append(sub_view)
                    break

    return parts


def render_breadcrumb(*, container=None) -> None:
    """Render the navigation breadcrumb."""
    target = container or st

    parts = get_breadcrumb_parts()
    crumbs = []
    for i, part in enumerate(parts):
        safe_part = html.escape(str(part))
        if i < len(parts) - 1:
            crumbs.append(f'<span style="color:var(--text-muted,#94a3b8);">{safe_part}</span>')
        else:
            crumbs.append(f'<span style="color:var(--text-primary,#eef8fb);font-weight:700;">{safe_part}</span>')

    separator = ' <span style="color:var(--text-muted,#64748b);margin:0 4px;">›</span> '
    target.markdown(
        f'<div style="font-size:0.68rem;margin-bottom:4px;">{separator.join(crumbs)}</div>',
        unsafe_allow_html=True,
    )
