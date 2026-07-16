"""Unit tests for the workflow router (v0.5)."""
import pytest

from sqlserver_semantic_mcp.config import reset_config
from sqlserver_semantic_mcp.services.policy_service import PolicyService
from sqlserver_semantic_mcp.workflows.router import route_query


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


def test_empty_query_routes_to_policy_only(policy):
    dec = route_query("", policy=policy)
    assert dec.route == "policy_only"


def test_natural_language_routes_to_discovery(policy):
    dec = route_query("list all customers who bought stuff", policy=policy)
    assert dec.route == "discovery"
    assert "discover_relevant_tables" in dec.recommended_tools


def test_allowed_select_routes_to_direct_execute(policy):
    dec = route_query("SELECT TOP 5 * FROM dbo.Users", policy=policy)
    assert dec.route == "direct_execute"
    assert "plan_or_execute_query" in dec.recommended_tools


def test_disallowed_drop_routes_to_direct_validate(policy):
    dec = route_query("DROP TABLE dbo.Users", policy=policy)
    assert dec.route == "direct_validate"
    assert "plan_or_execute_query" in dec.recommended_tools
