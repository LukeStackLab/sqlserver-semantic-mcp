import pytest
from unittest.mock import patch
from sqlserver_semantic_mcp.config import reset_config, get_config
from sqlserver_semantic_mcp.infrastructure.cache.store import init_store
from sqlserver_semantic_mcp.infrastructure.cache.structural import (
    write_structural_snapshot, StructuralSnapshot,
)
from sqlserver_semantic_mcp.services.object_service import describe_object


@pytest.mark.asyncio
async def test_describe_object_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "testdb")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_USER", "u")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_PASSWORD", "p")
    monkeypatch.setenv("SEMANTIC_MCP_CACHE_PATH", str(tmp_path / "t.db"))
    reset_config()
    cfg = get_config()

    await init_store(cfg.cache_path)
    snap = StructuralSnapshot(
        tables=[], columns=[], primary_keys=[], foreign_keys=[],
        indexes=[], objects=[("dbo", "v1", "VIEW")], comments=[],
    )
    await write_structural_snapshot(cfg.cache_path, "testdb", snap)

    with patch("sqlserver_semantic_mcp.services.object_service.fetch_one") as fo, \
         patch("sqlserver_semantic_mcp.services.object_service.fetch_all") as fa:
        fo.return_value = ("CREATE VIEW v1 AS SELECT 1",)
        fa.return_value = [("dbo", "Users", "USER_TABLE")]
        result = await describe_object("dbo", "v1", "VIEW", cfg=cfg)

    assert result["definition"].startswith("CREATE VIEW")
    assert "dbo.Users" in result["dependencies"]
    # P3: affected_tables now means write-targets. A SELECT-only view has none;
    # dbo.Users appears in read_tables instead.
    assert result["affected_tables"] == []
    # Note: v1's body is "SELECT 1" (no FROM), so read_tables is also empty.
    # For a richer read_tables test see test_object_write_intent.py.
