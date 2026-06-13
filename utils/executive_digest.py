# utils/executive_digest.py - AI-powered executive email digest via Snowflake notifications
"""
Generates and delivers an AI-summarized executive digest:
  1. Collects overnight metrics from Dynamic Tables
  2. Calls Cortex COMPLETE to generate a 3-paragraph narrative
  3. Delivers via Snowflake notification integration (email)
  4. Logs delivery to OVERWATCH_ADMIN_ACTION_AUDIT

Deployed as a Snowflake Task running at 7am daily.
"""
from __future__ import annotations

from typing import Any


def build_digest_procedure_sql(
    notification_integration: str = "OVERWATCH_EMAIL_INT",
    recipients: str = "dba-alerts@yourcompany.com",
    model: str = "mistral-large2",
) -> str:
    """Generate the AI-powered executive digest delivery procedure."""
    safe_int = str(notification_integration).replace("'", "''")
    safe_recipients = str(recipients).replace("'", "''")
    return f"""
CREATE OR REPLACE PROCEDURE DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_EXECUTIVE_DIGEST()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    digest_body VARCHAR;
    subject_line VARCHAR;
    metrics_context VARCHAR;
    ai_summary VARCHAR;
    health_score NUMBER;
    daily_credits NUMBER;
    total_failures NUMBER;
    open_alerts NUMBER;
    cost_delta_pct NUMBER;
BEGIN
    -- Gather metrics
    SELECT COALESCE(SUM(total_credits), 0)
    INTO :daily_credits
    FROM DBA_MAINT_DB.OVERWATCH.V_OVERWATCH_DAILY_CREDITS
    WHERE usage_date = CURRENT_DATE() - 1;

    SELECT COALESCE(SUM(failure_count), 0)
    INTO :total_failures
    FROM DBA_MAINT_DB.OVERWATCH.V_OVERWATCH_TASK_FAILURES
    WHERE failure_date = CURRENT_DATE() - 1 AND state = 'FAILED';

    SELECT COUNT(*)
    INTO :open_alerts
    FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS
    WHERE UPPER(COALESCE(STATUS, 'NEW')) IN ('NEW', 'OPEN', 'ESCALATED');

    -- Cost delta vs prior day
    SELECT ROUND((curr.credits - prev.credits) / NULLIF(prev.credits, 0) * 100, 1)
    INTO :cost_delta_pct
    FROM (
        SELECT SUM(total_credits) AS credits
        FROM DBA_MAINT_DB.OVERWATCH.V_OVERWATCH_DAILY_CREDITS
        WHERE usage_date = CURRENT_DATE() - 1
    ) curr,
    (
        SELECT SUM(total_credits) AS credits
        FROM DBA_MAINT_DB.OVERWATCH.V_OVERWATCH_DAILY_CREDITS
        WHERE usage_date = CURRENT_DATE() - 2
    ) prev;

    -- Health score
    LET failure_penalty NUMBER := LEAST(30, :total_failures * 2);
    LET alert_penalty NUMBER := LEAST(20, :open_alerts * 2);
    SET health_score = GREATEST(0, 100 - :failure_penalty - :alert_penalty);

    -- Build context for AI summary
    SET metrics_context =
        'Yesterday metrics for executive briefing:\\n'
        || 'Credits consumed: ' || :daily_credits::VARCHAR || '\\n'
        || 'Cost change vs prior day: ' || COALESCE(:cost_delta_pct::VARCHAR, 'N/A') || '%\\n'
        || 'Task failures: ' || :total_failures::VARCHAR || '\\n'
        || 'Open alerts: ' || :open_alerts::VARCHAR || '\\n'
        || 'Health score: ' || :health_score::VARCHAR || '/100\\n';

    -- Generate AI narrative
    SET ai_summary = SNOWFLAKE.CORTEX.COMPLETE(
        '{model}',
        'You are a Snowflake DBA writing a brief executive summary email. '
        || 'Write exactly 3 short paragraphs: (1) overall health status, '
        || '(2) key cost observation, (3) recommended action if any. '
        || 'Be concise and professional. Use the following data:\\n\\n'
        || :metrics_context
    );

    -- Build email
    SET subject_line = 'OVERWATCH Daily: Health ' || :health_score::VARCHAR
        || '/100 | ' || :daily_credits::VARCHAR || ' credits | '
        || :total_failures::VARCHAR || ' failures';

    SET digest_body =
        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\\n'
        || 'OVERWATCH EXECUTIVE DIGEST - ' || CURRENT_DATE()::VARCHAR || '\\n'
        || '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\\n\\n'
        || 'PLATFORM HEALTH: ' || :health_score::VARCHAR || '/100\\n\\n'
        || '── AI SUMMARY ──\\n'
        || :ai_summary || '\\n\\n'
        || '── RAW METRICS ──\\n'
        || '▸ Yesterday Credits: ' || ROUND(:daily_credits, 1)::VARCHAR || '\\n'
        || '▸ Cost Delta: ' || COALESCE(:cost_delta_pct::VARCHAR, 'N/A') || '%\\n'
        || '▸ Task Failures: ' || :total_failures::VARCHAR || '\\n'
        || '▸ Open Alerts: ' || :open_alerts::VARCHAR || '\\n\\n'
        || '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\\n'
        || 'Open OVERWATCH for full evidence.\\n';

    -- Send
    CALL SYSTEM$SEND_EMAIL(
        '{safe_int}',
        '{safe_recipients}',
        :subject_line,
        :digest_body,
        'text/plain'
    );

    -- Audit
    INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_ADMIN_ACTION_AUDIT
        (ACTION_TYPE, TARGET_OBJECT, SQL_TEXT, RESULT_STATUS, RESULT_MESSAGE)
    VALUES ('EXECUTIVE_DIGEST_DELIVERY', 'EMAIL', :subject_line, 'SUCCESS', 'AI digest delivered');

    RETURN 'Digest delivered: ' || :subject_line;
END;
$$;
"""


def build_digest_task_sql(
    schedule: str = "USING CRON 0 7 * * * America/Chicago",
    warehouse: str = "OVERWATCH_WH",
) -> str:
    """Generate the daily digest delivery task."""
    return f"""
CREATE OR REPLACE TASK DBA_MAINT_DB.OVERWATCH.OVERWATCH_EXECUTIVE_DIGEST
  WAREHOUSE = {warehouse}
  SCHEDULE = '{schedule}'
  COMMENT = 'Daily AI-powered executive digest via email at 7am.'
AS
  CALL DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_EXECUTIVE_DIGEST();

-- Enable: ALTER TASK DBA_MAINT_DB.OVERWATCH.OVERWATCH_EXECUTIVE_DIGEST RESUME;
"""


def render_digest_setup(*, container=None) -> None:
    """Render digest deployment instructions."""
    import streamlit as st
    target = container or st

    target.markdown("**Executive AI Digest Delivery**")
    target.caption(
        "Deploys a daily 7am email with Cortex COMPLETE-generated executive summary. "
        "Requires a Snowflake email notification integration."
    )
    with target.expander("Deployment SQL"):
        target.code(build_digest_procedure_sql(), language="sql")
        target.code(build_digest_task_sql(), language="sql")
