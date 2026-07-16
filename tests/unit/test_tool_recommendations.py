"""Unit tests for suggest_next_tool (v0.5)."""
import pytest

from sqlserver_semantic_mcp.config import get_config, reset_config
from sqlserver_semantic_mcp.services.policy_service import PolicyService
from sqlserver_semantic_mcp.workflows.recommendations import suggest_next_tool


@pytest.fixture
def policy(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_USER", "u")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_PASSWORD", "p")
    reset_config()
    svc = PolicyService()
    svc.load()
    return svc


def test_suggest_recommends_discovery_for_bare_goal(policy):
    env = suggest_next_tool(policy=policy, goal="find customer revenue")
    assert env["next_action"] == "discover"
    assert "discover_relevant_tables" in env["data"]["recommended_tools"]


def test_suggest_recommends_fast_path_when_sql_known(policy):
    env = suggest_next_tool(policy=policy, query="SELECT TOP 1 * FROM dbo.T")
    assert env["data"]["route"]["route"] == "direct_execute"
    assert env["recommended_tool"] == "plan_or_execute_query"
