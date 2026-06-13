# utils/dependency_graph.py - Object dependency and task DAG visualization
"""
Builds dependency graphs for:
  - Task DAGs (parent → child task relationships)
  - Object dependencies (table → view → procedure chains)
  - Impact analysis (when X fails, what downstream is affected?)

Renders as text-based DAG or structured data for Altair/Streamlit display.
"""
from __future__ import annotations

from typing import Any


def build_task_dag_sql(database: str = None, schema: str = None) -> str:
    """SQL to extract task dependency relationships."""
    filters = []
    if database:
        filters.append(f"AND database_name = '{database}'")
    if schema:
        filters.append(f"AND schema_name = '{schema}'")
    filter_clause = " ".join(filters)

    return f"""
    WITH task_inventory AS (
        SELECT
            database_name,
            schema_name,
            name AS task_name,
            state,
            schedule,
            predecessors,
            warehouse,
            condition
        FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
        WHERE scheduled_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
          {filter_clause}
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY database_name, schema_name, name
            ORDER BY scheduled_time DESC
        ) = 1
    )
    SELECT DISTINCT
        database_name,
        schema_name,
        task_name,
        state,
        schedule,
        warehouse,
        ARRAY_SIZE(COALESCE(TRY_PARSE_JSON(predecessors), ARRAY_CONSTRUCT())) AS predecessor_count,
        predecessors
    FROM task_inventory
    ORDER BY database_name, schema_name, task_name
    """


def build_object_dependencies_sql(database: str = None) -> str:
    """SQL to extract object-level dependencies from Snowflake metadata."""
    db_filter = f"AND referenced_database_name = '{database}'" if database else ""
    return f"""
    SELECT
        referencing_database_name,
        referencing_schema_name,
        referencing_object_name,
        referencing_object_type,
        referenced_database_name,
        referenced_schema_name,
        referenced_object_name,
        referenced_object_type,
        dependency_type
    FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
    WHERE TRUE
      {db_filter}
    ORDER BY referenced_database_name, referenced_object_name
    LIMIT 500
    """


def build_downstream_impact_sql(entity_type: str, entity_name: str, database: str = None) -> str:
    """SQL to find all downstream dependents of a specific object."""
    db_filter = f"AND referenced_database_name = '{database}'" if database else ""
    return f"""
    WITH RECURSIVE downstream AS (
        SELECT
            referencing_database_name,
            referencing_schema_name,
            referencing_object_name,
            referencing_object_type,
            referenced_object_name,
            1 AS depth
        FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
        WHERE UPPER(referenced_object_name) = UPPER('{entity_name}')
          AND UPPER(referenced_object_type) = UPPER('{entity_type}')
          {db_filter}

        UNION ALL

        SELECT
            od.referencing_database_name,
            od.referencing_schema_name,
            od.referencing_object_name,
            od.referencing_object_type,
            od.referenced_object_name,
            d.depth + 1
        FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES od
        JOIN downstream d
          ON UPPER(od.referenced_object_name) = UPPER(d.referencing_object_name)
        WHERE d.depth < 5
    )
    SELECT DISTINCT
        referencing_database_name AS database_name,
        referencing_schema_name AS schema_name,
        referencing_object_name AS object_name,
        referencing_object_type AS object_type,
        depth AS dependency_depth,
        referenced_object_name AS depends_on
    FROM downstream
    ORDER BY depth, object_name
    LIMIT 100
    """


def build_dag_from_tasks(task_df) -> dict[str, Any]:
    """
    Build a DAG structure from task inventory data.

    Returns:
        {
            "nodes": [{"id": str, "label": str, "state": str, "type": str}],
            "edges": [{"source": str, "target": str}],
            "roots": [str],  # Tasks with no predecessors (entry points)
            "leaves": [str],  # Tasks with no dependents (exit points)
            "depth": int,     # Maximum DAG depth
        }
    """
    import pandas as pd
    import json

    if not isinstance(task_df, pd.DataFrame) or task_df.empty:
        return {"nodes": [], "edges": [], "roots": [], "leaves": [], "depth": 0}

    nodes = []
    edges = []
    all_task_ids = set()
    tasks_with_predecessors = set()

    for _, row in task_df.iterrows():
        db = str(row.get("DATABASE_NAME", ""))
        schema = str(row.get("SCHEMA_NAME", ""))
        name = str(row.get("TASK_NAME", ""))
        task_id = f"{db}.{schema}.{name}"
        state = str(row.get("STATE", "UNKNOWN"))

        all_task_ids.add(task_id)
        nodes.append({
            "id": task_id,
            "label": name,
            "state": state,
            "type": "task",
            "database": db,
            "schema": schema,
        })

        # Parse predecessors
        preds_raw = row.get("PREDECESSORS", "[]")
        try:
            if isinstance(preds_raw, str):
                preds = json.loads(preds_raw) if preds_raw.startswith("[") else []
            elif isinstance(preds_raw, list):
                preds = preds_raw
            else:
                preds = []
        except (json.JSONDecodeError, TypeError):
            preds = []

        for pred in preds:
            pred_name = str(pred).strip()
            if pred_name:
                # Normalize predecessor reference
                if "." not in pred_name:
                    pred_id = f"{db}.{schema}.{pred_name}"
                else:
                    pred_id = pred_name
                edges.append({"source": pred_id, "target": task_id})
                tasks_with_predecessors.add(task_id)

    # Identify roots and leaves
    targets = {e["target"] for e in edges}
    sources = {e["source"] for e in edges}
    roots = sorted(all_task_ids - tasks_with_predecessors)
    leaves = sorted(all_task_ids - sources)

    # Calculate depth via BFS
    depth = 0
    if edges:
        children = {}
        for e in edges:
            children.setdefault(e["source"], []).append(e["target"])

        visited = set()
        queue = [(r, 0) for r in roots]
        while queue:
            node, d = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            depth = max(depth, d)
            for child in children.get(node, []):
                queue.append((child, d + 1))

    return {
        "nodes": nodes,
        "edges": edges,
        "roots": roots,
        "leaves": leaves,
        "depth": depth,
    }


def render_dag_text(dag: dict[str, Any], *, max_depth: int = 5) -> str:
    """Render a DAG as indented text for display in st.code or captions."""
    if not dag.get("nodes"):
        return "No task dependencies found."

    # Build adjacency
    children = {}
    for edge in dag["edges"]:
        children.setdefault(edge["source"], []).append(edge["target"])

    # State indicators
    state_icons = {
        "SUCCEEDED": "✓",
        "FAILED": "✗",
        "SUSPENDED": "⏸",
        "STARTED": "▶",
        "UNKNOWN": "?",
    }

    node_map = {n["id"]: n for n in dag["nodes"]}
    lines = []
    visited = set()

    def _render_tree(node_id: str, indent: int = 0):
        if node_id in visited or indent > max_depth:
            return
        visited.add(node_id)
        node = node_map.get(node_id, {"label": node_id.split(".")[-1], "state": "UNKNOWN"})
        icon = state_icons.get(node.get("state", "UNKNOWN"), "?")
        prefix = "  " * indent + ("├─ " if indent > 0 else "")
        lines.append(f"{prefix}{icon} {node['label']}")
        for child in sorted(children.get(node_id, [])):
            _render_tree(child, indent + 1)

    for root in dag["roots"]:
        _render_tree(root)

    return "\n".join(lines) if lines else "No root tasks found."


def impact_summary(dag: dict[str, Any], failed_task: str) -> dict[str, Any]:
    """Calculate blast radius when a specific task fails."""
    children = {}
    for edge in dag["edges"]:
        children.setdefault(edge["source"], []).append(edge["target"])

    # BFS from failed task
    affected = set()
    queue = [failed_task]
    while queue:
        current = queue.pop(0)
        for child in children.get(current, []):
            if child not in affected:
                affected.add(child)
                queue.append(child)

    node_map = {n["id"]: n for n in dag["nodes"]}
    affected_nodes = [node_map[a] for a in affected if a in node_map]

    return {
        "failed_task": failed_task,
        "downstream_count": len(affected),
        "affected_tasks": [n["label"] for n in affected_nodes],
        "blast_radius": "Critical" if len(affected) > 10 else "High" if len(affected) > 5 else "Medium" if len(affected) > 0 else "Isolated",
    }
