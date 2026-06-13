# sections/cost_chargeback.py - Chargeback allocation and reporting workflow
"""
Renders the chargeback/cost-allocation view within Cost & Contract.
Shows:
  - Owner-based allocation from OVERWATCH_OWNER_DIRECTORY
  - Database-based allocation as fallback
  - Weekly trend by owner
  - Unattributed credit percentage
  - Multi-rate pricing application
"""
from __future__ import annotations

import streamlit as st


def render() -> None:
    """Render the chargeback workflow."""
    from utils.chargeback import (
        build_chargeback_by_owner_sql,
        build_chargeback_by_database_sql,
        build_chargeback_trend_sql,
        format_chargeback_report,
    )
    from utils.credit_rates import get_rate_table, build_rate_summary
    from utils.session import get_session_for_action
    from utils.query import run_query
    from utils.cost import get_credit_price
    from utils.section_guidance import defer_section_note

    import pandas as pd

    st.markdown("**Cost Allocation & Chargeback**")
    st.caption(
        "Allocates warehouse credit consumption to business owners using the OVERWATCH Owner Directory. "
        "Unattributed spend indicates warehouses without ownership tags."
    )

    # Rate summary
    rates = build_rate_summary()
    if rates["is_multi_rate"]:
        st.caption(
            f"Multi-rate pricing active: Compute ${rates['compute_rate']:.2f}/cr, "
            f"AI ${rates['ai_rate']:.2f}/cr, Storage ${rates['storage_rate_per_tb']:.0f}/TB/mo"
        )
    else:
        st.caption(f"Uniform rate: ${rates['compute_rate']:.2f}/credit")

    # Controls
    col_days, col_load = st.columns([1, 1])
    with col_days:
        days_back = st.selectbox("Lookback", [7, 14, 30, 60, 90], index=2, key="chargeback_days")
    with col_load:
        st.write("")
        load_clicked = st.button("Load Chargeback", key="chargeback_load", type="primary", width="stretch")

    credit_price = get_credit_price()

    # Load data
    if load_clicked:
        session = get_session_for_action("load chargeback data", surface="Cost & Contract")
        if session is None:
            return

        with st.spinner("Loading owner-based allocation..."):
            try:
                owner_df = run_query(
                    build_chargeback_by_owner_sql(days_back),
                    ttl_key=f"chargeback_owner_{days_back}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["chargeback_owner_data"] = owner_df
            except Exception as e:
                st.warning(f"Owner allocation unavailable: {e}")
                st.session_state["chargeback_owner_data"] = pd.DataFrame()

        with st.spinner("Loading database-based allocation..."):
            try:
                db_df = run_query(
                    build_chargeback_by_database_sql(days_back),
                    ttl_key=f"chargeback_db_{days_back}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["chargeback_db_data"] = db_df
            except Exception as e:
                st.session_state["chargeback_db_data"] = pd.DataFrame()

        with st.spinner("Loading weekly trend..."):
            try:
                trend_df = run_query(
                    build_chargeback_trend_sql(days_back),
                    ttl_key=f"chargeback_trend_{days_back}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["chargeback_trend_data"] = trend_df
            except Exception:
                st.session_state["chargeback_trend_data"] = pd.DataFrame()

    # Render results
    owner_df = st.session_state.get("chargeback_owner_data")
    if isinstance(owner_df, pd.DataFrame) and not owner_df.empty:
        report = format_chargeback_report(owner_df, credit_price=credit_price)

        # Summary KPIs
        col_total, col_owners, col_unattr = st.columns(3)
        with col_total:
            st.metric("Total Credits", f"{report['total_credits']:,.0f}", f"${report['total_cost']:,.0f}")
        with col_owners:
            st.metric("Attributed Owners", str(report["owner_count"]))
        with col_unattr:
            color = "#ef4444" if report["unattributed_pct"] > 20 else "#f59e0b" if report["unattributed_pct"] > 5 else "#22c55e"
            st.metric("Unattributed", f"{report['unattributed_pct']:.1f}%")
            if report["unattributed_pct"] > 10:
                st.caption("Tag warehouses with COST_OWNER to reduce unattributed spend.")

        st.divider()

        # Owner breakdown
        st.markdown("**Allocation by Owner**")
        for owner_row in report["owners"][:10]:
            if owner_row["owner"] == "Unattributed":
                st.markdown(
                    f"⚠️ **{owner_row['owner']}** — {owner_row['credits']:,.0f} cr "
                    f"(${owner_row['cost_usd']:,.0f}) · {owner_row['pct_of_total']:.1f}%"
                )
            else:
                st.markdown(
                    f"**{owner_row['owner']}** — {owner_row['credits']:,.0f} cr "
                    f"(${owner_row['cost_usd']:,.0f}) · {owner_row['pct_of_total']:.1f}% · "
                    f"_{owner_row['tier']}_"
                )

        # Full table
        with st.expander("Full allocation table"):
            st.dataframe(owner_df, use_container_width=True)

    # Database allocation
    db_df = st.session_state.get("chargeback_db_data")
    if isinstance(db_df, pd.DataFrame) and not db_df.empty:
        with st.expander("Allocation by Database (query attribution)"):
            st.caption("Query-level credit allocation by database. Uses execution-time share of warehouse metering.")
            st.dataframe(db_df.head(20), use_container_width=True)

    # Weekly trend
    trend_df = st.session_state.get("chargeback_trend_data")
    if isinstance(trend_df, pd.DataFrame) and not trend_df.empty:
        with st.expander("Weekly Chargeback Trend"):
            try:
                import altair as alt
                chart = alt.Chart(trend_df).mark_bar().encode(
                    x=alt.X("WEEK_START:T", title="Week"),
                    y=alt.Y("WEEKLY_CREDITS:Q", title="Credits"),
                    color=alt.Color("COST_OWNER:N", title="Owner"),
                    tooltip=["COST_OWNER:N", "WEEKLY_CREDITS:Q", "WEEK_START:T"],
                ).properties(height=280)
                st.altair_chart(chart, use_container_width=True)
            except Exception:
                st.dataframe(trend_df, use_container_width=True)

    defer_section_note(
        "Chargeback accuracy depends on OVERWATCH_OWNER_DIRECTORY coverage. "
        "Run OVERWATCH_MART_SETUP.sql to deploy the owner directory and tag warehouses."
    )
