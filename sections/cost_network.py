# sections/cost_network.py - Network and data transfer cost workflow
"""
Surfaces the 10-20% of spend that's invisible in warehouse-only views:
  - Data transfer credits
  - PrivateLink consumption
  - Replication costs
  - External function egress
"""
from __future__ import annotations

import streamlit as st


def render() -> None:
    """Render the network/egress cost workflow."""
    from utils.network_egress import (
        build_data_transfer_sql,
        build_replication_cost_sql,
        build_network_summary_sql,
    )
    from utils.session import get_session_for_action
    from utils.query import run_query
    from utils.cost import get_credit_price
    from utils.section_guidance import defer_section_note

    import pandas as pd

    st.markdown("**Network & Transfer Costs**")
    st.caption(
        "Data transfer, PrivateLink, replication, and external function costs are often 10-20% of total spend "
        "but invisible in warehouse-only views. This surface makes them visible."
    )

    col_days, col_load = st.columns([1, 1])
    with col_days:
        days_back = st.selectbox("Lookback", [7, 14, 30, 60], index=2, key="network_cost_days")
    with col_load:
        st.write("")
        load_clicked = st.button("Load Network Costs", key="network_cost_load", type="primary", width="stretch")

    credit_price = get_credit_price()

    if load_clicked:
        session = get_session_for_action("load network costs", surface="Cost & Contract")
        if session is None:
            return

        with st.spinner("Loading network cost data..."):
            try:
                summary_df = run_query(
                    build_network_summary_sql(days_back),
                    ttl_key=f"network_summary_{days_back}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["network_cost_summary"] = summary_df
            except Exception as e:
                st.warning(f"Network cost data unavailable: {e}")
                st.session_state["network_cost_summary"] = pd.DataFrame()

            try:
                detail_df = run_query(
                    build_data_transfer_sql(days_back),
                    ttl_key=f"network_detail_{days_back}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["network_cost_detail"] = detail_df
            except Exception:
                st.session_state["network_cost_detail"] = pd.DataFrame()

            try:
                replication_df = run_query(
                    build_replication_cost_sql(days_back),
                    ttl_key=f"replication_cost_{days_back}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["network_replication_cost"] = replication_df
            except Exception:
                st.session_state["network_replication_cost"] = pd.DataFrame()

    # Render results
    summary_df = st.session_state.get("network_cost_summary")
    if isinstance(summary_df, pd.DataFrame) and not summary_df.empty:
        st.markdown("**Network Cost Summary**")

        total_credits = 0
        for _, row in summary_df.iterrows():
            category = str(row.get("NETWORK_CATEGORY", "Unknown"))
            credits = float(row.get("CREDITS", 0) or 0)
            active_days = int(row.get("ACTIVE_DAYS", 0) or 0)
            daily_avg = float(row.get("AVG_DAILY_CREDITS", 0) or 0)
            cost_usd = credits * credit_price
            total_credits += credits

            st.markdown(
                f"**{category}** — {credits:,.2f} credits (${cost_usd:,.0f}) "
                f"over {active_days} days · avg {daily_avg:,.2f}/day"
            )

        if total_credits > 0:
            total_cost = total_credits * credit_price
            st.divider()
            col_total, col_pct = st.columns(2)
            with col_total:
                st.metric("Total Network Credits", f"{total_credits:,.2f}", f"${total_cost:,.0f}")
            with col_pct:
                # Compare to total spend if available
                cockpit = st.session_state.get("cost_contract_cockpit")
                if isinstance(cockpit, pd.DataFrame) and not cockpit.empty:
                    credit_col = next(
                        (c for c in cockpit.columns if "CREDIT" in c.upper() and "TOTAL" in c.upper()),
                        None,
                    )
                    if credit_col:
                        total_all = float(cockpit[credit_col].sum())
                        if total_all > 0:
                            pct = total_credits / total_all * 100
                            st.metric("% of Total Spend", f"{pct:.1f}%",
                                      "Normal" if pct < 15 else "Review")
    elif isinstance(summary_df, pd.DataFrame) and summary_df.empty:
        st.info("No network/transfer costs found in this window. This is normal for single-region deployments.")

    # Detail tables
    detail_df = st.session_state.get("network_cost_detail")
    if isinstance(detail_df, pd.DataFrame) and not detail_df.empty:
        with st.expander("Transfer Cost Detail"):
            st.dataframe(detail_df.head(30), use_container_width=True)

    replication_df = st.session_state.get("network_replication_cost")
    if isinstance(replication_df, pd.DataFrame) and not replication_df.empty:
        with st.expander("Replication Cost Detail"):
            st.dataframe(replication_df.head(20), use_container_width=True)

    defer_section_note(
        "Network costs come from METERING_HISTORY service types containing DATA_TRANSFER, "
        "PRIVATELINK, REPLICATION, or EXTERNAL_FUNCTION. Zero results is expected for single-region accounts."
    )
