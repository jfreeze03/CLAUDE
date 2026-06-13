"""Tests for compliance evidence collection."""
import pandas as pd
import pytest


class TestCompliance:
    def test_compliance_scorecard_empty(self, mock_streamlit):
        from utils.compliance_evidence import build_compliance_scorecard

        result = build_compliance_scorecard()
        assert result["overall_score"] == 80  # baseline
        assert "categories" in result

    def test_compliance_scorecard_with_escalations(self, mock_streamlit):
        from utils.compliance_evidence import build_compliance_scorecard

        escalations = pd.DataFrame({
            "QUERY_TYPE": ["GRANT"] * 15,
            "USER_NAME": ["ADMIN"] * 15,
        })
        result = build_compliance_scorecard(escalations_df=escalations)
        assert result["overall_score"] < 80
        assert any("privilege" in f.lower() for f in result["findings"])
        assert result["categories"]["privilege_management"]["events"] == 15

    def test_compliance_scorecard_brute_force(self, mock_streamlit):
        from utils.compliance_evidence import build_compliance_scorecard

        logins = pd.DataFrame({
            "USER_NAME": ["ATTACKER"] * 30,
            "DAILY_FAILURES": [25] * 30,
        })
        result = build_compliance_scorecard(failed_logins_df=logins)
        assert result["overall_score"] < 80
        assert any("brute force" in f.lower() for f in result["findings"])

    def test_compliance_scorecard_dormant_users(self, mock_streamlit):
        from utils.compliance_evidence import build_compliance_scorecard

        dormant = pd.DataFrame({
            "USER_NAME": [f"USER_{i}" for i in range(25)],
            "DAYS_INACTIVE": [120] * 25,
        })
        result = build_compliance_scorecard(dormant_users_df=dormant)
        assert result["overall_score"] < 80
        assert result["categories"]["access_hygiene"]["events"] == 25

    def test_sql_privilege_escalation(self, mock_streamlit):
        from utils.compliance_evidence import build_privilege_escalation_sql

        sql = build_privilege_escalation_sql(30)
        assert "QUERY_HISTORY" in sql
        assert "ACCOUNTADMIN" in sql
        assert "GRANT" in sql

    def test_sql_dormant_users(self, mock_streamlit):
        from utils.compliance_evidence import build_dormant_users_sql

        sql = build_dormant_users_sql(90)
        assert "LOGIN_HISTORY" in sql
        assert "days_inactive" in sql.lower()

    def test_sql_sensitive_access(self, mock_streamlit):
        from utils.compliance_evidence import build_sensitive_access_sql

        sql = build_sensitive_access_sql(7)
        assert "ACCESS_HISTORY" in sql
        assert "PII" in sql
