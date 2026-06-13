# sections/cost_anomalies.py - Cost anomaly detection workflow
"""
Renders the anomaly detection and root cause investigation view
within Cost & Contract. Surfaces Z-score based cost spikes with
automated incident correlation.
"""
from __future__ import annotations

import streamlit as st


def render() -> None:
    """Render the cost anomaly detection workflow."""
    from utils.anomaly_detection import (
        build_cost_anomaly_sql,
        classify_anomalies,
        render_anomaly_summary,
    )
    from utils.incident_correlation import (
        build_ddl_changes_sql,
        build_new_workload_sql,
        correlate_incident,
    )
    from utils.session import get_session_for_action
    from utils.query import run_query
    from utils.section_guidance import defer_section_note

    import pandas as pd

    st.markdown("**Cost Anomaly Detection**")
    st.caption(
        "Statistical anomaly detection using Z-scores from rolling 14-day baselines. "
        "Flags days where warehouse consumption exceeds the normal pattern by 2+ standard deviations."
    )

    # Controls
    col_days, col_sens, col_load = st.columns([1, 1, 1])
    with col_days:
        days_back = st.selectbox("Lookback", [14, 30, 60, 90], index=1, key="cost_anomaly_days")
    with col_sens:
        sensitivity = st.selectbox("Sensitivity", [1.5, 2.0, 2.5, 3.0], index=1, key="cost_anomaly_sensitivity",
                                   format_func=lambda x: f"{x}σ")
    with col_load:
        st.write("")
        load_clicked = st.button("Detect Anomalies", key="cost_anomaly_load", type="primary", width="stretch")

    if load_clicked:
        session = get_session_for_action("detect cost anomalies", surface="Cost & Contract")
        if session is None:
            return

        with st.spinner("Scanning for cost anomalies..."):
            try:
                anomaly_df = run_query(
                    build_cost_anomaly_sql(days_back, sensitivity),
                    ttl_key=f"cost_anomalies_{days_back}_{sensitivity}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["cost_anomaly_results"] = anomaly_df
            except Exception as e:
                st.warning(f"Anomaly detection unavailable: {e}")
                st.session_state["cost_anomaly_results"] = pd.DataFrame()

    # Render results
    anomaly_df = st.session_state.get("cost_anomaly_results")
    if isinstance(anomaly_df, pd.DataFrame) and not anomaly_df.empty:
        summary = classify_anomalies(cost_anomalies_df=anomaly_df)
        render_anomaly_summary(summary)

        st.divider()

        # Detailed anomaly table
        st.markdown("**Anomaly Detail**")
        display_cols = [c for c in ["USAGE_DATE", "WAREHOUSE_NAME", "DAILY_CREDITS", "BASELINE_MEAN",
                                     "Z_SCORE", "PCT_ABOVE_BASELINE", "ANOMALY_SEVERITY"]
                       if c in anomaly_df.columns]
        if display_cols:
            styled = anomaly_df[display_cols].head(20)
            st.dataframe(styled, use_container_width=True)

        # Incident correlation for top anomaly
        if len(anomaly_df) > 0:
            top_anomaly = anomaly_df.iloc[0]
            anomaly_date = str(top_anomaly.get("USAGE_DATE", ""))
            anomaly_wh = str(top_anomaly.get("WAREHOUSE_NAME", ""))

            with st.expander(f"Investigate: {anomaly_wh} on {anomaly_date}", expanded=False):
                if st.button("Run Correlation", key="cost_anomaly_correlate"):
                    session = get_session_for_action("correlate incident", surface="Cost & Contract")
                    if session:
                        with st.spinner("Correlating..."):
                            try:
                                ddl_df = run_query(
                                    build_ddl_changes_sql(anomaly_date),
                                    ttl_key=f"anomaly_ddl_{anomaly_date}",
                                    tier="recent",
                                    section="Cost & Contract",
                                )
                            except Exception:
                                ddl_df = pd.DataFrame()

                            try:
                                workload_df = run_query(
                                    build_new_workload_sql(anomaly_date),
                                    ttl_key=f"anomaly_workload_{anomaly_date}",
                                    tier="recent",
                                    section="Cost & Contract",
                                )
                            except Exception:
                                workload_df = pd.DataFrame()

                            result = correlate_incident(
                                "cost_spike", anomaly_date, anomaly_wh,
                                ddl_changes_df=ddl_df,
                                new_workloads_df=workload_df,
                            )

                            if result["probable_causes"]:
                                st.markdown("**Probable Causes:**")
                                for cause in result["probable_causes"]:
                                    st.markdown(
                                        f"- **{cause['confidence']}**: {cause['cause']}"
                                    )
                                    if cause.get("evidence"):
                                        st.caption(f"  Evidence: {cause['evidence']}")
                            else:
                                st.caption("No correlated events found in the DDL or workload history.")

                            st.markdown(f"**Recommendation:** {result['recommendation']}")

    elif isinstance(anomaly_df, pd.DataFrame) and anomaly_df.empty:
        st.success("✓ No cost anomalies detected in the selected window. Spend is within normal patterns.")

    defer_section_note(
        "Anomaly detection uses rolling 14-day statistical baselines per warehouse. "
        "Sensitivity controls the Z-score threshold for flagging."
    )
