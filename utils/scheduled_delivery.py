# utils/scheduled_delivery.py - Scheduled morning brief delivery via Snowflake
"""
Uses Snowflake notification integrations to deliver the morning brief
on a schedule without requiring the dashboard to be open.

Deployment:
  1. Create a Snowflake notification integration (EMAIL or WEBHOOK)
  2. Create a Snowflake Task that calls SP_OVERWATCH_DELIVER_MORNING_BRIEF
  3. The procedure builds the brief from mart tables and sends via integration

This is the "push" complement to the "pull" dashboard experience.
"""
from __future__ import annotations

from typing import Any


def build_delivery_procedure_sql(
    notification_integration: str = "OVERWATCH_EMAIL_INT",
    recipients: str = "dba-alerts@yourcompany.com",
) -> str:
    """Generate the stored procedure SQL for scheduled brief delivery."""
    safe_integration = str(notification_integration).replace("'", "''")
    safe_recipients = str(recipients).replace("'", "''")

    return f"""
CREATE OR REPLACE PROCEDURE DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_DELIVER_MORNING_BRIEF()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    brief_body VARCHAR;
    subject_line VARCHAR;
    health_score NUMBER;
    total_failures NUMBER;
    open_alerts NUMBER;
    daily_credits NUMBER;
BEGIN
    -- Gather key metrics from Dynamic Tables / mart views
    SELECT COALESCE(SUM(total_credits), 0)
    INTO :daily_credits
    FROM DBA_MAINT_DB.OVERWATCH.V_OVERWATCH_DAILY_CREDITS
    WHERE usage_date = CURRENT_DATE() - 1;

    SELECT COALESCE(SUM(failure_count), 0)
    INTO :total_failures
    FROM DBA_MAINT_DB.OVERWATCH.V_OVERWATCH_TASK_FAILURES
    WHERE failure_date = CURRENT_DATE() - 1
      AND state = 'FAILED';

    SELECT COUNT(*)
    INTO :open_alerts
    FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS
    WHERE UPPER(COALESCE(STATUS, 'NEW')) IN ('NEW', 'OPEN', 'ESCALATED');

    -- Simple health score (0-100)
    LET failure_penalty NUMBER := LEAST(30, :total_failures * 2);
    LET alert_penalty NUMBER := LEAST(20, :open_alerts * 2);
    SET health_score = GREATEST(0, 100 - :failure_penalty - :alert_penalty);

    -- Build subject
    SET subject_line = 'OVERWATCH Brief: Health ' || :health_score::VARCHAR || '/100 | '
        || :daily_credits::VARCHAR || ' credits | '
        || :total_failures::VARCHAR || ' failures | '
        || :open_alerts::VARCHAR || ' open alerts';

    -- Build body
    SET brief_body = '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\\n'
        || 'OVERWATCH MORNING BRIEF - ' || CURRENT_DATE()::VARCHAR || '\\n'
        || '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\\n\\n'
        || 'Platform Health Score: ' || :health_score::VARCHAR || '/100\\n\\n'
        || '▸ Yesterday Credits: ' || ROUND(:daily_credits, 1)::VARCHAR || '\\n'
        || '▸ Task Failures: ' || :total_failures::VARCHAR || '\\n'
        || '▸ Open Alerts: ' || :open_alerts::VARCHAR || '\\n\\n'
        || '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\\n'
        || 'Open OVERWATCH for full evidence and drill-down.\\n';

    -- Send via notification integration
    CALL SYSTEM$SEND_EMAIL(
        '{safe_integration}',
        '{safe_recipients}',
        :subject_line,
        :brief_body,
        'text/plain'
    );

    RETURN 'Brief delivered: ' || :subject_line;
END;
$$;
"""


def build_delivery_task_sql(
    schedule: str = "USING CRON 0 7 * * * America/Chicago",
    warehouse: str = "OVERWATCH_WH",
) -> str:
    """Generate the Snowflake Task SQL for scheduled delivery."""
    return f"""
CREATE OR REPLACE TASK DBA_MAINT_DB.OVERWATCH.OVERWATCH_MORNING_BRIEF_DELIVERY
  WAREHOUSE = {warehouse}
  SCHEDULE = '{schedule}'
  COMMENT = 'Delivers OVERWATCH morning brief via email at 7am daily.'
AS
  CALL DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_DELIVER_MORNING_BRIEF();

-- Enable the task (requires ACCOUNTADMIN or task owner):
-- ALTER TASK DBA_MAINT_DB.OVERWATCH.OVERWATCH_MORNING_BRIEF_DELIVERY RESUME;
"""


def build_teams_webhook_procedure_sql(webhook_url: str = "https://your-org.webhook.office.com/...") -> str:
    """Generate a procedure for Teams/Slack webhook delivery."""
    safe_url = str(webhook_url).replace("'", "''")
    return f"""
CREATE OR REPLACE PROCEDURE DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_DELIVER_TEAMS_BRIEF()
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('requests', 'snowflake-snowpark-python')
HANDLER = 'deliver_brief'
EXECUTE AS OWNER
AS
$$
import requests
import json
from snowflake.snowpark import Session

def deliver_brief(session: Session) -> str:
    # Gather metrics
    credits_row = session.sql(\"\"\"
        SELECT COALESCE(SUM(total_credits), 0) AS credits
        FROM DBA_MAINT_DB.OVERWATCH.V_OVERWATCH_DAILY_CREDITS
        WHERE usage_date = CURRENT_DATE() - 1
    \"\"\").collect()
    daily_credits = float(credits_row[0]['CREDITS']) if credits_row else 0

    failures_row = session.sql(\"\"\"
        SELECT COALESCE(SUM(failure_count), 0) AS failures
        FROM DBA_MAINT_DB.OVERWATCH.V_OVERWATCH_TASK_FAILURES
        WHERE failure_date = CURRENT_DATE() - 1 AND state = 'FAILED'
    \"\"\").collect()
    total_failures = int(failures_row[0]['FAILURES']) if failures_row else 0

    alerts_row = session.sql(\"\"\"
        SELECT COUNT(*) AS alerts
        FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS
        WHERE UPPER(COALESCE(STATUS, 'NEW')) IN ('NEW', 'OPEN', 'ESCALATED')
    \"\"\").collect()
    open_alerts = int(alerts_row[0]['ALERTS']) if alerts_row else 0

    health = max(0, 100 - min(30, total_failures * 2) - min(20, open_alerts * 2))

    # Build Teams Adaptive Card
    card = {{
        "type": "message",
        "attachments": [{{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {{
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {{"type": "TextBlock", "text": "OVERWATCH Morning Brief", "weight": "Bolder", "size": "Large"}},
                    {{"type": "FactSet", "facts": [
                        {{"title": "Health Score", "value": f"{{health}}/100"}},
                        {{"title": "Yesterday Credits", "value": f"{{daily_credits:.1f}}"}},
                        {{"title": "Task Failures", "value": str(total_failures)}},
                        {{"title": "Open Alerts", "value": str(open_alerts)}},
                    ]}},
                    {{"type": "TextBlock", "text": "Open OVERWATCH for full evidence.", "isSubtle": True, "size": "Small"}},
                ]
            }}
        }}]
    }}

    webhook_url = '{safe_url}'
    response = requests.post(webhook_url, json=card, timeout=10)

    if response.status_code in (200, 202):
        return f"Teams brief delivered: Health {{health}}/100"
    else:
        return f"Teams delivery failed: {{response.status_code}} {{response.text[:200]}}"
$$;
"""


def render_delivery_setup_guide(*, container=None) -> None:
    """Render setup instructions for scheduled delivery."""
    import streamlit as st

    target = container or st

    target.markdown("**Scheduled Morning Brief Delivery**")
    target.caption(
        "Deploy the procedure and task below to receive the OVERWATCH morning brief "
        "at 7am daily without opening the dashboard."
    )

    with target.expander("Email Delivery (Snowflake Notification Integration)"):
        target.code(build_delivery_procedure_sql(), language="sql")
        target.code(build_delivery_task_sql(), language="sql")
        target.caption(
            "Prerequisites: Create an email notification integration "
            "(OVERWATCH_EMAIL_INT) and grant usage to the procedure owner."
        )

    with target.expander("Teams/Slack Webhook Delivery"):
        target.code(build_teams_webhook_procedure_sql(), language="sql")
        target.caption(
            "Prerequisites: Create an External Access Integration for the webhook URL "
            "and grant usage to the procedure."
        )
