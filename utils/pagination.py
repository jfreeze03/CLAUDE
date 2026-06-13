# utils/pagination.py - Standardized DataFrame pagination for all sections
"""
Replaces raw st.dataframe(df) with a top-N preview + expandable full view:
  - Shows top 20 rows by default
  - "Show all" expander with full data + download button
  - Consistent height and column formatting
  - Sort controls

Usage:
    from utils.pagination import render_paginated_table
    render_paginated_table(df, title="Warehouse Credits", sort_by="TOTAL_CREDITS")
"""
from __future__ import annotations

from typing import Sequence

import streamlit as st


def render_paginated_table(
    df,
    *,
    title: str = "",
    key: str = "",
    preview_rows: int = 20,
    sort_by: str | Sequence[str] | None = None,
    ascending: bool = False,
    height: int = 400,
    show_download: bool = True,
    priority_columns: Sequence[str] | None = None,
) -> None:
    """
    Render a DataFrame with preview + expandable full view.

    Args:
        df: DataFrame to display
        title: Optional title above the table
        key: Unique key for Streamlit widgets
        preview_rows: Number of rows in the preview
        sort_by: Column(s) to sort by
        ascending: Sort direction
        height: Pixel height for the dataframe widget
        show_download: Whether to show a CSV download button
        priority_columns: Columns to show first (reorder)
    """
    import pandas as pd

    if not isinstance(df, pd.DataFrame) or df.empty:
        if title:
            st.markdown(f"**{title}**")
        st.caption("No data available.")
        return

    # Sort if requested
    display_df = df.copy()
    if sort_by:
        sort_cols = [sort_by] if isinstance(sort_by, str) else list(sort_by)
        existing_sort = [c for c in sort_cols if c in display_df.columns]
        if existing_sort:
            display_df = display_df.sort_values(existing_sort, ascending=ascending)

    # Reorder columns if priority specified
    if priority_columns:
        leading = [c for c in priority_columns if c in display_df.columns]
        remaining = [c for c in display_df.columns if c not in leading]
        display_df = display_df[leading + remaining]

    total_rows = len(display_df)
    safe_key = key or title.replace(" ", "_").lower()[:30]

    if title:
        st.markdown(f"**{title}** ({total_rows:,} rows)")

    # Preview
    preview = display_df.head(preview_rows)
    st.dataframe(preview, use_container_width=True, height=min(height, 35 * len(preview) + 50))

    # Full data expander (only if there are more rows than preview)
    if total_rows > preview_rows:
        with st.expander(f"Show all {total_rows:,} rows"):
            st.dataframe(display_df, use_container_width=True, height=height)

    # Download
    if show_download and total_rows > 0:
        csv = display_df.to_csv(index=False)
        st.download_button(
            f"📥 Download CSV ({total_rows:,} rows)",
            data=csv,
            file_name=f"{safe_key or 'data'}.csv",
            mime="text/csv",
            key=f"dl_{safe_key}_{total_rows}",
        )


def render_summary_with_detail(
    df,
    *,
    summary_fn,
    title: str = "",
    key: str = "",
    detail_label: str = "Show detail",
) -> None:
    """
    Render a summary view with optional detail expansion.

    Args:
        df: Full DataFrame
        summary_fn: Function that takes df and renders a summary (metrics/chart)
        title: Title text
        key: Unique key
        detail_label: Label for the expander
    """
    import pandas as pd

    if not isinstance(df, pd.DataFrame) or df.empty:
        if title:
            st.markdown(f"**{title}**")
        st.caption("No data available.")
        return

    if title:
        st.markdown(f"**{title}**")

    summary_fn(df)

    with st.expander(detail_label):
        render_paginated_table(df, key=key or title[:20])
