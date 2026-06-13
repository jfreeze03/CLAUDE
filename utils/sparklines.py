# utils/sparklines.py - Inline SVG sparklines for shell snapshot metrics
"""
Generates lightweight inline SVG sparklines for embedding in shell
snapshot cards. Zero-dependency (no Altair/matplotlib needed for shells).

Shows 7-day micro-trends next to key metrics so returning users
get immediate visual context without opening a workspace.
"""
from __future__ import annotations

import html
from typing import Sequence


def svg_sparkline(
    values: Sequence[float],
    *,
    width: int = 64,
    height: int = 20,
    color: str = "var(--accent, #29B5E8)",
    fill_opacity: float = 0.15,
    stroke_width: float = 1.5,
) -> str:
    """
    Generate an inline SVG sparkline from a sequence of numeric values.

    Args:
        values: Sequence of numbers (at least 2 points needed)
        width: SVG width in pixels
        height: SVG height in pixels
        color: Stroke color (supports CSS variables)
        fill_opacity: Area fill opacity (0 = no fill)
        stroke_width: Line width

    Returns:
        HTML string with inline SVG, or empty string if insufficient data.
    """
    clean_values = []
    for v in values:
        try:
            f = float(v) if v is not None else 0.0
            if f != f:  # NaN check
                f = 0.0
            clean_values.append(f)
        except (TypeError, ValueError):
            clean_values.append(0.0)

    if len(clean_values) < 2:
        return ""

    min_val = min(clean_values)
    max_val = max(clean_values)
    val_range = max_val - min_val
    if val_range == 0:
        val_range = 1.0  # Flat line

    padding = 2
    draw_w = width - padding * 2
    draw_h = height - padding * 2

    # Build polyline points
    points = []
    n = len(clean_values)
    for i, v in enumerate(clean_values):
        x = padding + (i / (n - 1)) * draw_w
        y = padding + draw_h - ((v - min_val) / val_range) * draw_h
        points.append(f"{x:.1f},{y:.1f}")

    polyline_str = " ".join(points)

    # Build filled area polygon
    fill_path = ""
    if fill_opacity > 0:
        area_points = [f"{padding:.1f},{height - padding:.1f}"]
        area_points.extend(points)
        area_points.append(f"{width - padding:.1f},{height - padding:.1f}")
        fill_path = (
            f'<polygon points="{" ".join(area_points)}" '
            f'fill="{html.escape(color)}" fill-opacity="{fill_opacity}" stroke="none"/>'
        )

    # Trend indicator dot on last point
    last_x = padding + draw_w
    last_y = padding + draw_h - ((clean_values[-1] - min_val) / val_range) * draw_h
    dot = f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2" fill="{html.escape(color)}"/>'

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="display:inline-block;vertical-align:middle;" xmlns="http://www.w3.org/2000/svg">'
        f'{fill_path}'
        f'<polyline points="{polyline_str}" fill="none" '
        f'stroke="{html.escape(color)}" stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round"/>'
        f'{dot}'
        f'</svg>'
    )


def sparkline_with_trend(
    values: Sequence[float],
    *,
    width: int = 64,
    height: int = 20,
) -> str:
    """Generate a sparkline with adaptive color based on trend direction."""
    clean = [float(v) for v in values if v is not None]
    if len(clean) < 2:
        return ""

    # Determine trend: compare last value to mean of first half
    midpoint = len(clean) // 2
    first_half_avg = sum(clean[:midpoint]) / max(midpoint, 1)
    last_val = clean[-1]

    if first_half_avg > 0:
        change_pct = (last_val - first_half_avg) / first_half_avg * 100
    else:
        change_pct = 0

    # Color: green if decreasing (cost going down is good), red if increasing
    if change_pct > 10:
        color = "#ef4444"  # Rising — bad for costs
    elif change_pct < -10:
        color = "#22c55e"  # Falling — good for costs
    else:
        color = "var(--accent, #29B5E8)"  # Stable

    return svg_sparkline(values, width=width, height=height, color=color)


def sparkline_card(
    label: str,
    value: str,
    values: Sequence[float],
    *,
    invert_color: bool = False,
) -> str:
    """
    Generate a complete sparkline metric card as HTML.

    Args:
        label: Metric label
        value: Current formatted value
        values: Historical values for sparkline
        invert_color: If True, rising = green (e.g., for reliability)
    """
    clean = [float(v) for v in values if v is not None]
    if len(clean) < 2:
        spark_html = ""
    else:
        midpoint = len(clean) // 2
        first_half_avg = sum(clean[:midpoint]) / max(midpoint, 1)
        last_val = clean[-1]
        change_pct = ((last_val - first_half_avg) / first_half_avg * 100) if first_half_avg > 0 else 0

        if invert_color:
            # Rising is good (reliability, SLA compliance)
            color = "#22c55e" if change_pct > 5 else "#ef4444" if change_pct < -5 else "var(--accent, #29B5E8)"
        else:
            # Rising is bad (costs, failures)
            color = "#ef4444" if change_pct > 10 else "#22c55e" if change_pct < -10 else "var(--accent, #29B5E8)"

        spark_html = svg_sparkline(clean, color=color)

    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))

    return (
        f'<div class="ow-shell-snapshot-card" style="display:flex;flex-direction:column;gap:2px;">'
        f'<span style="font-size:0.66rem;color:var(--text-muted,#94a3b8);text-transform:uppercase;letter-spacing:0.04em;">{safe_label}</span>'
        f'<div style="display:flex;align-items:center;gap:6px;">'
        f'<strong style="font-size:0.9rem;color:var(--text-primary,#eef8fb);">{safe_value}</strong>'
        f'{spark_html}'
        f'</div>'
        f'</div>'
    )


def render_sparkline_snapshot(
    metrics: Sequence[tuple[str, str, Sequence[float]]],
    *,
    invert_colors: Sequence[bool] | None = None,
) -> str:
    """
    Render a complete snapshot grid with sparklines.

    Args:
        metrics: Sequence of (label, formatted_value, historical_values)
        invert_colors: Per-metric color inversion flags

    Returns:
        HTML string for st.markdown(unsafe_allow_html=True)
    """
    if not metrics:
        return ""

    cards = []
    for i, (label, value, values) in enumerate(metrics):
        invert = (invert_colors[i] if invert_colors and i < len(invert_colors) else False)
        cards.append(sparkline_card(label, value, values, invert_color=invert))

    col_count = max(1, min(4, len(cards)))
    return (
        f'<div class="ow-shell-snapshot-grid" '
        f'style="display:grid;grid-template-columns:repeat({col_count}, minmax(0, 1fr));gap:0.6rem;">'
        f'{"".join(cards)}</div>'
    )
