import pytest
from sqlserver_semantic_mcp.config import reset_config, get_config
from sqlserver_semantic_mcp.infrastructure.cache.store import init_store
from sqlserver_semantic_mcp.infrastructure.cache.structural import (
    write_structural_snapshot, StructuralSnapshot,
)
from sqlserver_semantic_mcp.infrastructure.cache.semantic import (
    enqueue_all_tables, list_pending_table_analyses, get_table_analysis,
)
from sqlserver_semantic_mcp.infrastructure.background import (
    run_background_fill_once,
)


@pytest.mark.asyncio
async def test_background_processes_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "testdb")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_USER", "u")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_PASSWORD", "p")
    monkeypatch.setenv("SEMANTIC_MCP_CACHE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("SEMANTIC_MCP_BACKGROUND_BATCH_SIZE", "10")
    reset_config()
    cfg = get_config()

    await init_store(cfg.cache_path)
    snap = StructuralSnapshot(
        tables=[("dbo", "Users"), ("dbo", "Orders")],
        columns=[
            ("dbo", "Users", "Id", "int", None, 0, None, 1),
            ("dbo", "Users", "Name", "nvarchar", 50, 0, None, 2),
            ("dbo", "Orders", "Id", "int", None, 0, None, 1),
        ],
        primary_keys=[("dbo", "Users", "Id"), ("dbo", "Orders", "Id")],
        foreign_keys=[],
        indexes=[], objects=[], comments=[],
    )
    await write_structural_snapshot(cfg.cache_path, "testdb", snap)
    await enqueue_all_tables(cfg.cache_path, "testdb")

    processed = await run_background_fill_once(cfg)
    assert processed >= 2

    for s, t in [("dbo", "Users"), ("dbo", "Orders")]:
        r = await get_table_analysis(cfg.cache_path, "testdb", s, t)
        assert r["status"] == "ready"

    pending = await list_pending_table_analyses(cfg.cache_path, "testdb", 10)
    assert pending == []
