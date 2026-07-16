"""Unit tests for find_join_path's score flag (folds in score_join_candidate)."""
import pytest


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "testdb")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_USER", "u")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_PASSWORD", "p")
    monkeypatch.setenv("SEMANTIC_MCP_CACHE_PATH", str(tmp_path / "t.db"))
    from sqlserver_semantic_mcp.config import reset_config
    reset_config()
    from sqlserver_semantic_mcp.server.app import reset_context
    reset_context()


@pytest.mark.asyncio
async def test_find_join_path_score_false_skips_classify(monkeypatch, env):
    from sqlserver_semantic_mcp.server.tools import relationship

    async def fake_path(*a, **k):
        return [{"to_schema": "dbo", "to_table": "Bridge"}]
    called = {"n": 0}

    async def fake_classify(*a, **k):
        called["n"] += 1
        return {"type": "bridge"}
    monkeypatch.setattr(relationship.relationship_service, "find_join_path", fake_path)
    monkeypatch.setattr(
        "sqlserver_semantic_mcp.services.semantic_service.classify_table",
        fake_classify,
    )

    out = await relationship._path({"from_schema": "dbo", "from_table": "A",
                                    "to_schema": "dbo", "to_table": "B"})
    assert out == {"found": True, "path": [{"to_schema": "dbo", "to_table": "Bridge"}]}
    assert called["n"] == 0  # perf check: score=false must not run per-hop classify


@pytest.mark.asyncio
async def test_find_join_path_score_true_returns_confidence(monkeypatch, env):
    from sqlserver_semantic_mcp.server.tools import relationship

    async def fake_path(*a, **k):
        return [{"to_schema": "dbo", "to_table": "Bridge"}]

    async def fake_classify(*a, **k):
        return {"type": "bridge"}
    monkeypatch.setattr(relationship.relationship_service, "find_join_path", fake_path)
    monkeypatch.setattr(
        "sqlserver_semantic_mcp.services.semantic_service.classify_table",
        fake_classify,
    )

    out = await relationship._path({"from_schema": "dbo", "from_table": "A",
                                    "to_schema": "dbo", "to_table": "B", "score": True})
    assert out["found"] is True
    assert "confidence" in out and out["confidence"] < 1.0  # bridge hop penalises
    assert out["penalties"]
