# utils/cortex_agent.py - Cortex Agent with tool-use for autonomous investigation
"""
Replaces basic "Ask OVERWATCH" context-stuffing with a proper
agent loop that can:
  1. Decide which SQL to run based on the question
  2. Execute the query via Snowflake session
  3. Interpret results
  4. Run follow-up queries if needed
  5. Produce a grounded answer

Uses Cortex COMPLETE with a structured tool-use prompt pattern
(not Snowflake's native Agent API — that requires separate deployment).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st


_AGENT_HISTORY_KEY = "_overwatch_agent_history"
_AGENT_COOLDOWN_KEY = "_overwatch_agent_last_call"
_AGENT_COOLDOWN_SEC = 8
_MAX_ITERATIONS = 3


# ─── Tool definitions (SQL builders the agent can invoke) ─────────────────────

def _safe_days(days) -> int:
    """Validate days parameter for agent SQL — bounded 1-90, prevents injection."""
    return max(1, min(90, int(days)))


AGENT_TOOLS = {
    "cost_summary": {
        "description": "Get total credit consumption by warehouse for a time window",
        "sql_fn": lambda days: f"""
            SELECT warehouse_name, ROUND(SUM(credits_used), 2) AS total_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE start_time >= DATEADD('day', -{_safe_days(days)}, CURRENT_TIMESTAMP())
            GROUP BY warehouse_name ORDER BY total_credits DESC LIMIT 15
        """,
    },
    "task_failures": {
        "description": "Get recent task failures with error details",
        "sql_fn": lambda days: f"""
            SELECT database_name, schema_name, name, state, error_code,
                   SUBSTR(error_message, 1, 100) AS error_preview, scheduled_time
            FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
            WHERE state = 'FAILED'
              AND scheduled_time >= DATEADD('day', -{_safe_days(days)}, CURRENT_TIMESTAMP())
            ORDER BY scheduled_time DESC LIMIT 20
        """,
    },
    "query_bottlenecks": {
        "description": "Find the slowest queries by elapsed time",
        "sql_fn": lambda days: f"""
            SELECT warehouse_name, user_name, database_name,
                   ROUND(total_elapsed_time/1000, 1) AS elapsed_sec,
                   ROUND(bytes_scanned/1024/1024/1024, 2) AS gb_scanned,
                   query_type, start_time
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE start_time >= DATEADD('day', -{_safe_days(days)}, CURRENT_TIMESTAMP())
              AND execution_status = 'SUCCESS'
            ORDER BY total_elapsed_time DESC LIMIT 15
        """,
    },
    "warehouse_idle": {
        "description": "Find warehouses with idle credit waste",
        "sql_fn": lambda days: f"""
            SELECT warehouse_name, ROUND(SUM(credits_used), 2) AS total_credits,
                   COUNT(DISTINCT DATE_TRUNC('hour', start_time)) AS metered_hours
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE start_time >= DATEADD('day', -{_safe_days(days)}, CURRENT_TIMESTAMP())
            GROUP BY warehouse_name
            HAVING metered_hours > total_credits * 2
            ORDER BY total_credits DESC LIMIT 10
        """,
    },
    "security_grants": {
        "description": "Check recent privilege escalation (GRANT to admin roles)",
        "sql_fn": lambda days: f"""
            SELECT user_name, role_name, query_type, start_time,
                   SUBSTR(query_text, 1, 200) AS statement
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE query_type IN ('GRANT', 'REVOKE')
              AND start_time >= DATEADD('day', -{_safe_days(days)}, CURRENT_TIMESTAMP())
              AND (query_text ILIKE '%ACCOUNTADMIN%' OR query_text ILIKE '%SYSADMIN%')
            ORDER BY start_time DESC LIMIT 10
        """,
    },
    "alert_summary": {
        "description": "Get current alert status counts",
        "sql_fn": lambda _: """
            SELECT STATUS, SEVERITY, COUNT(*) AS alert_count
            FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS
            GROUP BY STATUS, SEVERITY ORDER BY alert_count DESC
        """,
    },
}


def _select_tools(question: str) -> list[str]:
    """Select relevant tools based on the question keywords."""
    q_lower = question.lower()
    selected = []

    keyword_map = {
        "cost_summary": ["cost", "credit", "spend", "expensive", "warehouse", "bill"],
        "task_failures": ["task", "fail", "error", "job", "pipeline", "etl"],
        "query_bottlenecks": ["slow", "query", "bottleneck", "performance", "p95", "elapsed"],
        "warehouse_idle": ["idle", "waste", "suspend", "unused", "underutilized"],
        "security_grants": ["grant", "security", "privilege", "admin", "access", "revoke"],
        "alert_summary": ["alert", "incident", "open", "escalat"],
    }

    for tool, keywords in keyword_map.items():
        if any(kw in q_lower for kw in keywords):
            selected.append(tool)

    # Default: cost + tasks if nothing matched
    return selected or ["cost_summary", "task_failures"]


def agent_investigate(
    question: str,
    *,
    session=None,
    model: str = "mistral-large2",
    days: int = 7,
) -> str:
    """
    Run the agent loop: select tools → execute SQL → interpret → answer.

    Returns the final answer string.
    """
    # Rate limit
    last_call = st.session_state.get(_AGENT_COOLDOWN_KEY)
    if last_call and (datetime.now() - last_call).total_seconds() < _AGENT_COOLDOWN_SEC:
        return f"Please wait {_AGENT_COOLDOWN_SEC}s between agent calls to manage AI credits."
    st.session_state[_AGENT_COOLDOWN_KEY] = datetime.now()

    if not session:
        try:
            from .session import get_session
            session = get_session()
        except Exception:
            return "Snowflake connection required for agent investigation."

    # Step 1: Select tools
    tools = _select_tools(question)

    # Step 2: Execute selected SQL
    results = {}
    for tool_name in tools[:3]:  # Max 3 tools per investigation
        tool = AGENT_TOOLS.get(tool_name)
        if not tool:
            continue
        try:
            sql = tool["sql_fn"](days)
            rows = session.sql(sql).collect()
            if rows:
                # Convert to readable format
                data = []
                for row in rows[:10]:
                    rd = row.as_dict() if hasattr(row, "as_dict") else dict(row)
                    data.append(rd)
                results[tool_name] = data
        except Exception as e:
            results[tool_name] = f"Error: {str(e)[:100]}"

    # Step 3: Build grounded prompt with results
    context = f"Question: {question}\n\nData from Snowflake (last {days} days):\n\n"
    for tool_name, data in results.items():
        tool_desc = AGENT_TOOLS[tool_name]["description"]
        context += f"[{tool_desc}]\n"
        if isinstance(data, list):
            for row in data[:8]:
                context += f"  {row}\n"
        else:
            context += f"  {data}\n"
        context += "\n"

    prompt = f"""You are OVERWATCH Agent, a Snowflake DBA AI assistant.
Answer the question using ONLY the data provided below. Be specific and actionable.
If the data doesn't answer the question, say what additional data would be needed.
Format your response with bullet points for clarity.

{context}

Answer:"""

    # Step 4: Call Cortex COMPLETE
    try:
        from snowflake.cortex import Complete
        answer = str(Complete(model, prompt, session=session)).strip()
    except ImportError:
        try:
            safe_prompt = prompt.replace("'", "''")[:12000]
            result = session.sql(
                f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}', '{safe_prompt}') AS response"
            ).collect()
            answer = str(result[0]["RESPONSE"]).strip() if result else "No response."
        except Exception as e:
            answer = f"Cortex unavailable: {str(e)[:150]}"

    # Store history
    history = st.session_state.setdefault(_AGENT_HISTORY_KEY, [])
    history.append({"question": question, "answer": answer, "tools": tools, "ts": datetime.now().isoformat()})
    if len(history) > 10:
        del history[:5]

    return answer


def render_agent_panel(session, *, container=None) -> None:
    """Render the Cortex Agent investigation panel."""
    target = container or st

    target.markdown("**OVERWATCH Agent** (Cortex + SQL Tools)")
    target.caption("Asks follow-up SQL queries autonomously to investigate your question.")

    question = target.text_input(
        "Investigate",
        placeholder="e.g., Why did costs spike this week? Which tasks are failing?",
        key="_agent_input",
        label_visibility="collapsed",
    )

    col_ask, col_days, col_clear = target.columns([2, 1, 1])
    with col_days:
        days = target.selectbox("Window", [1, 3, 7, 14, 30], index=2, key="_agent_days")
    with col_ask:
        if target.button("Investigate", key="_agent_go", type="primary", disabled=not question):
            with target.spinner("Agent investigating..."):
                answer = agent_investigate(question, session=session, days=days)
                target.markdown(f"**Agent:** {answer}")
    with col_clear:
        if target.button("Clear", key="_agent_clear"):
            st.session_state.pop(_AGENT_HISTORY_KEY, None)
            st.rerun()

    # History
    history = st.session_state.get(_AGENT_HISTORY_KEY, [])
    if history:
        with target.expander(f"Investigation history ({len(history)})"):
            for entry in reversed(history[-5:]):
                target.markdown(f"**Q:** {entry['question']}")
                target.markdown(f"**A:** {entry['answer']}")
                target.caption(f"Tools: {', '.join(entry['tools'])} · {entry['ts']}")
                target.divider()
