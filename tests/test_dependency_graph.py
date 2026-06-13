"""Tests for dependency graph and DAG analysis."""
import pandas as pd
import pytest
import json


class TestDependencyGraph:
    def test_build_dag_empty(self, mock_streamlit):
        from utils.dependency_graph import build_dag_from_tasks

        result = build_dag_from_tasks(pd.DataFrame())
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["depth"] == 0

    def test_build_dag_single_task(self, mock_streamlit):
        from utils.dependency_graph import build_dag_from_tasks

        df = pd.DataFrame({
            "DATABASE_NAME": ["DB1"],
            "SCHEMA_NAME": ["PUBLIC"],
            "TASK_NAME": ["ROOT_TASK"],
            "STATE": ["SUCCEEDED"],
            "PREDECESSORS": ["[]"],
        })
        result = build_dag_from_tasks(df)
        assert len(result["nodes"]) == 1
        assert len(result["roots"]) == 1
        assert result["depth"] == 0

    def test_build_dag_with_dependencies(self, mock_streamlit):
        from utils.dependency_graph import build_dag_from_tasks

        df = pd.DataFrame({
            "DATABASE_NAME": ["DB1", "DB1", "DB1"],
            "SCHEMA_NAME": ["PUBLIC", "PUBLIC", "PUBLIC"],
            "TASK_NAME": ["ROOT", "CHILD_A", "CHILD_B"],
            "STATE": ["SUCCEEDED", "SUCCEEDED", "FAILED"],
            "PREDECESSORS": ["[]", '["ROOT"]', '["ROOT"]'],
        })
        result = build_dag_from_tasks(df)
        assert len(result["nodes"]) == 3
        assert len(result["edges"]) == 2
        assert len(result["roots"]) == 1
        assert "DB1.PUBLIC.ROOT" in result["roots"]

    def test_impact_summary_isolated_task(self, mock_streamlit):
        from utils.dependency_graph import build_dag_from_tasks, impact_summary

        df = pd.DataFrame({
            "DATABASE_NAME": ["DB1"],
            "SCHEMA_NAME": ["PUBLIC"],
            "TASK_NAME": ["ISOLATED"],
            "STATE": ["FAILED"],
            "PREDECESSORS": ["[]"],
        })
        dag = build_dag_from_tasks(df)
        result = impact_summary(dag, "DB1.PUBLIC.ISOLATED")
        assert result["downstream_count"] == 0
        assert result["blast_radius"] == "Isolated"

    def test_impact_summary_cascading_failure(self, mock_streamlit):
        from utils.dependency_graph import build_dag_from_tasks, impact_summary

        df = pd.DataFrame({
            "DATABASE_NAME": ["DB1"] * 4,
            "SCHEMA_NAME": ["PUBLIC"] * 4,
            "TASK_NAME": ["ROOT", "CHILD_1", "CHILD_2", "GRANDCHILD"],
            "STATE": ["FAILED", "SUCCEEDED", "SUCCEEDED", "SUCCEEDED"],
            "PREDECESSORS": ["[]", '["ROOT"]', '["ROOT"]', '["CHILD_1"]'],
        })
        dag = build_dag_from_tasks(df)
        result = impact_summary(dag, "DB1.PUBLIC.ROOT")
        assert result["downstream_count"] == 3
        assert result["blast_radius"] in ("Medium", "High")

    def test_render_dag_text(self, mock_streamlit):
        from utils.dependency_graph import build_dag_from_tasks, render_dag_text

        df = pd.DataFrame({
            "DATABASE_NAME": ["DB1", "DB1"],
            "SCHEMA_NAME": ["PUBLIC", "PUBLIC"],
            "TASK_NAME": ["ROOT", "CHILD"],
            "STATE": ["SUCCEEDED", "SUCCEEDED"],
            "PREDECESSORS": ["[]", '["ROOT"]'],
        })
        dag = build_dag_from_tasks(df)
        text = render_dag_text(dag)
        assert "ROOT" in text
        assert "CHILD" in text

    def test_sql_generation(self, mock_streamlit):
        from utils.dependency_graph import build_task_dag_sql, build_object_dependencies_sql

        sql = build_task_dag_sql(database="DB1")
        assert "TASK_HISTORY" in sql
        assert "DB1" in sql

        sql2 = build_object_dependencies_sql()
        assert "OBJECT_DEPENDENCIES" in sql2
