# utils/ask_overwatch_cortex.py - Natural language "Ask OVERWATCH" via Cortex COMPLETE
"""
Wires Snowflake Cortex COMPLETE to answer free-text questions
grounded in loaded OVERWATCH evidence.

Examples:
  "Why did costs spike on Tuesday?"
  "Which warehouse is most expensive this week?"
  "Summarize task failures in the last 24 hours"

The LLM response is grounded in actual session state data,
not hallucinated from training knowledge.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st


_ASK_OVERWATCH_HISTORY_KEY = "_ask_overwatch_conversation"
_ASK_OVERWATCH_LAST_CALL_KEY = "_ask_overwatch_last_call_ts"
_ASK_OVERWATCH_COOLDOWN_SEC = 10  # Minimum seconds between Cortex calls
_MAX_CONTEXT_CHARS = 8000
_MAX_HISTORY = 10


def _check_rate_limit() -> bool:
    """Return True if the rate limit has been exceeded (should block)."""
    last_call = st.session_state.get(_ASK_OVERWATCH_LAST_CALL_KEY)
    if last_call is None:
        return False
    elapsed = (datetime.now() - last_call).total_seconds()
    return elapsed < _ASK_OVERWATCH_COOLDOWN_SEC


def _record_call() -> None:
    """Record that a Cortex call was made for rate limiting."""
    st.session_state[_ASK_OVERWATCH_LAST_CALL_KEY] = datetime.now()


def _build_evidence_context(state: dict | None = None) -> str:
    """Extract relevant evidence from session state as grounding context."""
    import pandas as pd

    if state is None:
        state = dict(st.session_state)

    context_parts = []

    # Cost data
    for key in ("cost_contract_cockpit", "cost_contract_splash"):
        df = state.get(key)
        if isinstance(df, pd.DataFrame) and not df.empty:
            summary = df.describe().to_string()[:1500]
            context_parts.append(f"[COST DATA - {key}]\n{summary}")
            break

    # DBA snapshot
    dba = state.get("dba_control_room_snapshot_result")
    if isinstance(dba, pd.DataFrame) and not dba.empty:
        context_parts.append(f"[DBA SNAPSHOT]\n{dba.to_string(max_rows=10)[:1500]}")

    # Alert data
    alerts = state.get("alert_center_data")
    if isinstance(alerts, pd.DataFrame) and not alerts.empty:
        if "STATUS" in alerts.columns:
            status_counts = alerts["STATUS"].value_counts().to_string()
            context_parts.append(f"[ALERTS]\n{status_counts}")

    # Health score
    try:
        from .health_score import compute_platform_health_score
        health = compute_platform_health_score(state)
        context_parts.append(
            f"[HEALTH SCORE] {health['score']:.0f}/100, Grade {health['grade']}, "
            f"Trend: {health['trend']}. "
            f"Components: Cost={health['components']['cost_control']['score']:.0f}, "
            f"Reliability={health['components']['reliability']['score']:.0f}, "
            f"Security={health['components']['security']['score']:.0f}, "
            f"Operations={health['components']['operations']['score']:.0f}"
        )
    except Exception:
        pass

    # Contract info
    remaining = state.get("_contract_remaining_credits")
    total = state.get("_contract_total_credits")
    if remaining or total:
        context_parts.append(
            f"[CONTRACT] Remaining: {remaining or '?'} credits, Total: {total or '?'} credits"
        )

    # Scope
    company = state.get("active_company", "ALFA")
    env = state.get("global_environment", "ALL")
    context_parts.append(f"[SCOPE] Company: {company}, Environment: {env}")

    full_context = "\n\n".join(context_parts)
    return full_context[:_MAX_CONTEXT_CHARS]


def _build_system_prompt() -> str:
    return """You are OVERWATCH AI, an expert Snowflake DBA assistant embedded in the OVERWATCH monitoring dashboard.

Rules:
- Answer questions based ONLY on the provided evidence context.
- If the evidence doesn't contain the answer, say "I don't have that data loaded. Open the relevant workspace to load evidence."
- Be concise and actionable. Prefer bullet points for lists.
- When discussing costs, always mention the credit price and total USD.
- When identifying issues, suggest a specific next action.
- Never guess or hallucinate data. Only reference what's in the context.
- Format responses for a DBA audience. Be direct."""


def ask_overwatch(
    question: str,
    *,
    session=None,
    model: str = "mistral-large2",
    state: dict | None = None,
) -> str:
    """
    Answer a natural language question using Cortex COMPLETE grounded in evidence.

    Args:
        question: The user's free-text question
        session: Snowflake session (required for Cortex call)
        model: Cortex model to use
        state: Session state dict (defaults to st.session_state)

    Returns:
        The LLM response text, or an error message.
    """
    if not question or not question.strip():
        return "Please ask a question about your Snowflake environment."

    # Rate limiting — prevent credit burn from rapid calls
    if _check_rate_limit():
        return f"Please wait {_ASK_OVERWATCH_COOLDOWN_SEC} seconds between questions to manage AI credit consumption."
    _record_call()

    if session is None:
        try:
            from .session import get_session
            session = get_session()
        except Exception:
            return "Snowflake connection required for Ask OVERWATCH. Connect and try again."

    evidence = _build_evidence_context(state)
    system_prompt = _build_system_prompt()

    # Build the full prompt
    full_prompt = f"""{system_prompt}

--- EVIDENCE CONTEXT ---
{evidence}
--- END CONTEXT ---

User question: {question}

Answer:"""

    try:
        # Call Cortex COMPLETE
        from snowflake.cortex import Complete
        response = Complete(model, full_prompt, session=session)
        answer = str(response).strip()
    except ImportError:
        # Fallback for environments without snowflake.cortex
        try:
            safe_prompt = full_prompt.replace("'", "''")[:12000]
            result = session.sql(
                f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}', '{safe_prompt}') AS response"
            ).collect()
            answer = str(result[0]["RESPONSE"]).strip() if result else "No response from Cortex."
        except Exception as e:
            return f"Cortex unavailable: {str(e)[:200]}. Ensure snowflake-ml-python is installed and Cortex is enabled."

    # Store in conversation history
    history = st.session_state.setdefault(_ASK_OVERWATCH_HISTORY_KEY, [])
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    if len(history) > _MAX_HISTORY * 2:
        del history[:2]

    return answer


def render_ask_overwatch_panel(*, container=None) -> None:
    """Render the Ask OVERWATCH chat interface."""
    target = container or st

    target.markdown("**Ask OVERWATCH**")
    target.caption("Ask natural language questions about your Snowflake environment. Answers are grounded in loaded evidence.")

    # Show conversation history
    history = st.session_state.get(_ASK_OVERWATCH_HISTORY_KEY, [])
    if history:
        for msg in history[-6:]:  # Show last 3 exchanges
            if msg["role"] == "user":
                target.markdown(f"**You:** {msg['content']}")
            else:
                target.markdown(f"**OVERWATCH:** {msg['content']}")
        target.divider()

    # Input
    question = target.text_input(
        "Ask a question",
        placeholder="e.g., Why did costs spike this week?",
        key="_ask_overwatch_input",
        label_visibility="collapsed",
    )

    col_ask, col_clear = target.columns([3, 1])
    with col_ask:
        if target.button("Ask", key="_ask_overwatch_submit", type="primary", disabled=not question):
            if question:
                with target.spinner("Thinking..."):
                    answer = ask_overwatch(question.strip())
                    target.markdown(f"**OVERWATCH:** {answer}")
    with col_clear:
        if target.button("Clear", key="_ask_overwatch_clear"):
            st.session_state.pop(_ASK_OVERWATCH_HISTORY_KEY, None)
            st.rerun()

    # Suggested questions
    if not history:
        target.caption("Try asking:")
        suggestions = [
            "What's our current health score?",
            "Which warehouses consumed the most credits?",
            "Are there any open critical alerts?",
            "Summarize task failures today",
        ]
        for suggestion in suggestions:
            if target.button(suggestion, key=f"_ask_suggest_{suggestion[:20]}"):
                st.session_state["_ask_overwatch_input"] = suggestion
                st.rerun()
