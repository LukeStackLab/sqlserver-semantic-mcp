import json
from sqlserver_semantic_mcp.config import reset_config
from sqlserver_semantic_mcp.services.policy_service import PolicyService


def test_service_initialises_with_builtin(monkeypatch):
    monkeypatch.delenv("SEMANTIC_MCP_POLICY_FILE", raising=False)
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "x")
    reset_config()
    svc = PolicyService()
    svc.load()
    assert svc.current_policy().profile_name == "readonly"


def test_validate_select(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "x")
    reset_config()
    svc = PolicyService()
    svc.load()
    res = svc.validate("SELECT 1")
    assert res["allowed"] is True
    assert res["intent"]["primary_operation"] == "SELECT"


def test_validate_blocked(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "x")
    reset_config()
    svc = PolicyService()
    svc.load()
    res = svc.validate("UPDATE T SET x=1 WHERE Id=1")
    assert res["allowed"] is False


def test_reload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # isolate from local .env
    pf = tmp_path / "p.json"
    pf.write_text(json.dumps({
        "active_profile": "ro",
        "profiles": {"ro": {"profile_name": "ro"}}
    }))
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "x")
    monkeypatch.setenv("SEMANTIC_MCP_POLICY_FILE", str(pf))
    monkeypatch.delenv("SEMANTIC_MCP_POLICY_PROFILE", raising=False)
    reset_config()
    svc = PolicyService()
    svc.load()
    assert svc.current_policy().profile_name == "ro"
    svc.reload()
    assert svc.current_policy().profile_name == "ro"
