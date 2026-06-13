# utils/autonomous_optimizer.py - Autonomous Cost Optimizer
"""
Nightly autonomous evaluation of all warehouses with:
  - Automatic Low-risk actions (suspend idle warehouses)
  - Queued High-risk actions (resize, consolidation) for approval
  - Scheduled task-based execution
  - Full audit trail in OVERWATCH_ADMIN_ACTION_AUDIT
  - Approval workflow tied to OVERWATCH_ACTION_QUEUE

Architecture:
  1. Snowflake Task runs SP_OVERWATCH_AUTONOMOUS_OPTIMIZER nightly
  2. Procedure evaluates all warehouses against playbook rules
  3. Low-risk actions auto-execute (suspend idle, fix timeout)
  4. Medium/High-risk actions insert into ACTION_QUEUE for DBA approval
  5. Approved actions execute on next scheduled run
  6. All actions logged to ADMIN_ACTION_AUDIT
"""
from __future__ import annotations

from typing import Any

import streamlit as st


def build_autonomous_optimizer_procedure_sql() -> str:
    """Generate the stored procedure for autonomous cost optimization."""
    return """
CREATE OR REPLACE PROCEDURE DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_AUTONOMOUS_OPTIMIZER()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    actions_taken NUMBER DEFAULT 0;
    actions_queued NUMBER DEFAULT 0;
    errors_encountered NUMBER DEFAULT 0;
BEGIN
    -- Phase 1: Auto-execute LOW-RISK actions
    -- Suspend warehouses idle > 2 hours with AUTO_SUSPEND > 300s
    FOR wh IN (
        SELECT
            w.name AS warehouse_name,
            w.auto_suspend,
            COALESCE(m.last_query_time, w.created_on) AS last_activity
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES w
        LEFT JOIN (
            SELECT warehouse_name, MAX(end_time) AS last_query_time
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE start_time >= DATEADD('hour', -4, CURRENT_TIMESTAMP())
            GROUP BY warehouse_name
        ) m ON w.name = m.warehouse_name
        WHERE w.deleted_on IS NULL
          AND w.state = 'STARTED'
          AND w.name NOT IN ('OVERWATCH_WH', 'COMPUTE_WH')
          AND (m.last_query_time IS NULL OR m.last_query_time < DATEADD('hour', -2, CURRENT_TIMESTAMP()))
          AND w.auto_suspend > 300
    ) DO
        BEGIN
            EXECUTE IMMEDIATE 'ALTER WAREHOUSE "' || :wh.warehouse_name || '" SUSPEND';
            INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_ADMIN_ACTION_AUDIT
                (ACTION_TYPE, TARGET_OBJECT, SQL_TEXT, RESULT_STATUS, RESULT_MESSAGE)
            VALUES ('AUTO_SUSPEND_IDLE', :wh.warehouse_name,
                    'ALTER WAREHOUSE "' || :wh.warehouse_name || '" SUSPEND',
                    'SUCCESS', 'Autonomous optimizer: idle > 2h with auto_suspend=' || :wh.auto_suspend::VARCHAR);
            actions_taken := actions_taken + 1;
        EXCEPTION WHEN OTHER THEN
            errors_encountered := errors_encountered + 1;
        END;
    END FOR;

    -- Phase 2: Fix AUTO_SUSPEND = 0 (never-suspend) warehouses
    FOR wh IN (
        SELECT name AS warehouse_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES
        WHERE deleted_on IS NULL
          AND auto_suspend = 0
          AND name NOT IN ('OVERWATCH_WH', 'COMPUTE_WH')
    ) DO
        BEGIN
            EXECUTE IMMEDIATE 'ALTER WAREHOUSE "' || :wh.warehouse_name || '" SET AUTO_SUSPEND = 60';
            INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_ADMIN_ACTION_AUDIT
                (ACTION_TYPE, TARGET_OBJECT, SQL_TEXT, RESULT_STATUS, RESULT_MESSAGE)
            VALUES ('AUTO_FIX_SUSPEND', :wh.warehouse_name,
                    'ALTER WAREHOUSE "' || :wh.warehouse_name || '" SET AUTO_SUSPEND = 60',
                    'SUCCESS', 'Autonomous optimizer: fixed never-suspend warehouse');
            actions_taken := actions_taken + 1;
        EXCEPTION WHEN OTHER THEN
            errors_encountered := errors_encountered + 1;
        END;
    END FOR;

    -- Phase 3: Queue HIGH-RISK resize candidates for approval
    INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_ACTION_QUEUE
        (ACTION_ID, SOURCE, CATEGORY, SEVERITY, ENTITY_TYPE, ENTITY_NAME,
         OWNER, STATUS, FINDING, RECOMMENDED_ACTION, EST_MONTHLY_SAVINGS)
    SELECT
        'OPT-' || warehouse_name || '-' || TO_CHAR(CURRENT_DATE(), 'YYYYMMDD'),
        'Autonomous Optimizer',
        'COST',
        'Medium',
        'WAREHOUSE',
        warehouse_name,
        'DBA / FinOps',
        'New',
        'Warehouse consistently underutilized: avg ' || ROUND(avg_utilization, 1)::VARCHAR || '% capacity used',
        'Consider downsizing from ' || current_size || ' to next smaller size',
        estimated_monthly_savings
    FROM (
        SELECT
            m.warehouse_name,
            w.size AS current_size,
            AVG(m.credits_used) / NULLIF(
                CASE w.size
                    WHEN 'X-Small' THEN 1 WHEN 'Small' THEN 2 WHEN 'Medium' THEN 4
                    WHEN 'Large' THEN 8 WHEN 'X-Large' THEN 16 WHEN '2X-Large' THEN 32
                    ELSE 1
                END, 0
            ) * 100 AS avg_utilization,
            SUM(m.credits_used) * 0.15 * 4.3 * 3.68 AS estimated_monthly_savings
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
        JOIN SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES w ON m.warehouse_name = w.name
        WHERE m.start_time >= DATEADD('day', -14, CURRENT_TIMESTAMP())
          AND w.deleted_on IS NULL
          AND w.name NOT IN ('OVERWATCH_WH', 'COMPUTE_WH')
        GROUP BY m.warehouse_name, w.size
        HAVING avg_utilization < 20 AND SUM(m.credits_used) > 5
    ) candidates
    WHERE NOT EXISTS (
        SELECT 1 FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_ACTION_QUEUE
        WHERE ENTITY_NAME = candidates.warehouse_name
          AND SOURCE = 'Autonomous Optimizer'
          AND STATUS NOT IN ('Fixed', 'Ignored')
    );

    GET DIAGNOSTICS actions_queued = ROW_COUNT;

    -- Phase 4: Execute approved actions from prior runs
    FOR action IN (
        SELECT ACTION_ID, ENTITY_NAME, RECOMMENDED_ACTION, GENERATED_SQL_FIX
        FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_ACTION_QUEUE
        WHERE SOURCE = 'Autonomous Optimizer'
          AND STATUS = 'Approved'
          AND GENERATED_SQL_FIX IS NOT NULL
          AND LENGTH(GENERATED_SQL_FIX) > 5
    ) DO
        BEGIN
            EXECUTE IMMEDIATE :action.GENERATED_SQL_FIX;
            UPDATE DBA_MAINT_DB.OVERWATCH.OVERWATCH_ACTION_QUEUE
            SET STATUS = 'Fixed', FIXED_AT = CURRENT_TIMESTAMP(), FIXED_BY = 'AUTONOMOUS_OPTIMIZER'
            WHERE ACTION_ID = :action.ACTION_ID;
            INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_ADMIN_ACTION_AUDIT
                (ACTION_TYPE, TARGET_OBJECT, SQL_TEXT, RESULT_STATUS, RESULT_MESSAGE)
            VALUES ('AUTO_EXECUTE_APPROVED', :action.ENTITY_NAME, :action.GENERATED_SQL_FIX,
                    'SUCCESS', 'Executed approved action: ' || :action.ACTION_ID);
            actions_taken := actions_taken + 1;
        EXCEPTION WHEN OTHER THEN
            errors_encountered := errors_encountered + 1;
            UPDATE DBA_MAINT_DB.OVERWATCH.OVERWATCH_ACTION_QUEUE
            SET VERIFICATION_NOTES = 'Execution failed: ' || SQLERRM
            WHERE ACTION_ID = :action.ACTION_ID;
        END;
    END FOR;

    RETURN 'Autonomous Optimizer complete: ' || actions_taken || ' actions taken, '
        || actions_queued || ' queued for approval, ' || errors_encountered || ' errors.';
END;
$$;
"""


def build_optimizer_task_sql(
    schedule: str = "USING CRON 0 2 * * * America/Chicago",
    warehouse: str = "OVERWATCH_WH",
) -> str:
    """Generate the Snowflake Task for nightly optimizer runs."""
    return f"""
CREATE OR REPLACE TASK DBA_MAINT_DB.OVERWATCH.OVERWATCH_AUTONOMOUS_OPTIMIZER
  WAREHOUSE = {warehouse}
  SCHEDULE = '{schedule}'
  COMMENT = 'Nightly autonomous cost optimizer: suspends idle, fixes timeouts, queues resize candidates.'
AS
  CALL DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_AUTONOMOUS_OPTIMIZER();

-- Enable: ALTER TASK DBA_MAINT_DB.OVERWATCH.OVERWATCH_AUTONOMOUS_OPTIMIZER RESUME;
"""


def render_optimizer_status(session, *, container=None) -> None:
    """Render the autonomous optimizer status and recent actions."""
    target = container or st

    target.markdown("**Autonomous Cost Optimizer**")

    # Recent actions
    try:
        rows = session.sql("""
            SELECT ACTION_TYPE, TARGET_OBJECT, RESULT_STATUS, RESULT_MESSAGE, ACTION_TS
            FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_ADMIN_ACTION_AUDIT
            WHERE ACTION_TYPE LIKE 'AUTO_%'
              AND ACTION_TS >= DATEADD('day', -7, CURRENT_TIMESTAMP())
            ORDER BY ACTION_TS DESC
            LIMIT 20
        """).collect()

        if rows:
            target.caption(f"{len(rows)} automated actions in the last 7 days")
            import pandas as pd
            df = pd.DataFrame([r.as_dict() if hasattr(r, "as_dict") else dict(r) for r in rows])
            target.dataframe(df, use_container_width=True)
        else:
            target.info("No autonomous actions recorded yet. Deploy the optimizer task to enable.")
    except Exception as e:
        target.caption(f"Optimizer audit unavailable: {e}")

    # Pending approvals
    try:
        pending = session.sql("""
            SELECT ACTION_ID, ENTITY_NAME, FINDING, EST_MONTHLY_SAVINGS
            FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_ACTION_QUEUE
            WHERE SOURCE = 'Autonomous Optimizer'
              AND STATUS = 'New'
            ORDER BY EST_MONTHLY_SAVINGS DESC
            LIMIT 10
        """).collect()

        if pending:
            target.markdown(f"**{len(pending)} pending approval(s)**")
            for row in pending:
                rd = row.as_dict() if hasattr(row, "as_dict") else dict(row)
                savings = float(rd.get("EST_MONTHLY_SAVINGS", 0) or 0)
                target.markdown(f"- `{rd.get('ENTITY_NAME', '')}` — {rd.get('FINDING', '')[:100]} (${savings:,.0f}/mo)")
    except Exception:
        pass

    # Deploy SQL
    with target.expander("Deploy Autonomous Optimizer"):
        target.code(build_autonomous_optimizer_procedure_sql(), language="sql")
        target.code(build_optimizer_task_sql(), language="sql")
