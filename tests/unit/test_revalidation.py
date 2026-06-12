import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import aiosqlite

from sqlserver_semantic_mcp.config import get_config, reset_config
from sqlserver_semantic_mcp.infrastructure.cache import revalidation
from sqlserver_semantic_mcp.infrastructure.cache.probe import SchemaFingerprints
from sqlserver_semantic_mcp.infrastructure.cache.semantic import (
    get_object_definition, upsert_object_definition,
)
from sqlserver_semantic_mcp.infrastructure.cache.store import init_store


MOD = "sqlserver_semantic_mcp.infrastructure.cache.revalidation"


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "testdb")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_USER", "u")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_PASSWORD", "p")
    monkeypatch.setenv("SEMANTIC_MCP_CACHE_PATH", str(tmp_path / "t.db"))
    reset_config()
    revalidation.reset_state()
    yield get_config()
    revalidation.reset_state()
    reset_config()


def _fps(tables=None, objects=None, dependents=None) -> SchemaFingerprints:
    return SchemaFingerprints(
        tables=tables or {},
        objects=objects or {},
        table_dependents=dependents or {},
    )


async def _seed_baseline(cfg, fps: SchemaFingerprints) -> None:
    from sqlserver_semantic_mcp.infrastructure.cache.probe import (
        write_fingerprints,
    )
    await init_store(cfg.cache_path)
    async with aiosqlite.connect(cfg.cache_path) as db:
        await write_fingerprints(db, cfg.mssql_database, fps)
        await db.commit()


@pytest.mark.asyncio
async def test_no_drift_skips_warmup(cfg):
    fps = _fps(tables={("dbo", "Users"): "fp1"})
    await _seed_baseline(cfg, fps)

    with patch(f"{MOD}.fetch_fingerprints", return_value=fps), \
         patch(f"{MOD}.warmup_structural_cache", AsyncMock()) as warmup:
        result = await revalidation.revalidate_if_stale(cfg)

    warmup.assert_not_awaited()
    assert result["probed"] is True
    assert result["refreshed"] is False


@pytest.mark.asyncio
async def test_drift_triggers_warmup_and_dependency_cascade(cfg):
    await _seed_baseline(cfg, _fps(
        tables={("dbo", "Users"): "fp-old"},
        objects={("dbo", "vw_Users", "V"): "fp-v"},
    ))
    # vw_Users analysis is currently ready; Users will change underneath it
    await upsert_object_definition(
        cfg.cache_path, "testdb", "dbo", "vw_Users", "VIEW",
        object_hash="h", status="ready", definition="CREATE VIEW ...",
    )

    fresh = _fps(
        tables={("dbo", "Users"): "fp-new"},
        objects={("dbo", "vw_Users", "V"): "fp-v"},
        dependents={("dbo", "Users"): [("dbo", "vw_Users")]},
    )
    with patch(f"{MOD}.fetch_fingerprints", return_value=fresh), \
         patch(f"{MOD}.warmup_structural_cache", AsyncMock()) as warmup:
        result = await revalidation.revalidate_if_stale(cfg)

    warmup.assert_awaited_once_with(cfg, fingerprints=fresh)
    assert result["refreshed"] is True
    assert result["tables_changed"] == 1
    assert result["objects_marked_dirty"] == 1
    obj = await get_object_definition(
        cfg.cache_path, "testdb", "dbo", "vw_Users", "VIEW",
    )
    assert obj["status"] == "dirty"


@pytest.mark.asyncio
async def test_changed_view_body_marks_object_dirty(cfg):
    await _seed_baseline(cfg, _fps(
        objects={("dbo", "vw_X", "V"): "old-def"},
    ))
    await upsert_object_definition(
        cfg.cache_path, "testdb", "dbo", "vw_X", "VIEW",
        object_hash="h", status="ready",
    )
    fresh = _fps(objects={("dbo", "vw_X", "V"): "new-def"})
    with patch(f"{MOD}.fetch_fingerprints", return_value=fresh), \
         patch(f"{MOD}.warmup_structural_cache", AsyncMock()):
        result = await revalidation.revalidate_if_stale(cfg)

    assert result["objects_changed"] == 1
    obj = await get_object_definition(
        cfg.cache_path, "testdb", "dbo", "vw_X", "VIEW",
    )
    assert obj["status"] == "dirty"


@pytest.mark.asyncio
async def test_missing_baseline_warms_up_without_dirty_marks(cfg):
    await init_store(cfg.cache_path)
    fresh = _fps(tables={("dbo", "Users"): "fp"})
    with patch(f"{MOD}.fetch_fingerprints", return_value=fresh), \
         patch(f"{MOD}.warmup_structural_cache", AsyncMock()) as warmup:
        result = await revalidation.revalidate_if_stale(cfg)

    warmup.assert_awaited_once()
    assert result["baseline_created"] is True
    assert result["objects_marked_dirty"] == 0


@pytest.mark.asyncio
async def test_throttle_skips_until_interval_elapses(cfg):
    fps = _fps(tables={("dbo", "Users"): "fp"})
    await _seed_baseline(cfg, fps)

    with patch(f"{MOD}.fetch_fingerprints", return_value=fps) as fetch, \
         patch(f"{MOD}.warmup_structural_cache", AsyncMock()):
        first = await revalidation.revalidate_if_stale(cfg)
        second = await revalidation.revalidate_if_stale(cfg)

    assert first is not None
    assert second is None  # within probe_interval_s window
    assert fetch.call_count == 1


@pytest.mark.asyncio
async def test_probe_failure_is_swallowed_and_throttled(cfg):
    await _seed_baseline(cfg, _fps(tables={("dbo", "Users"): "fp"}))

    def boom(_cfg):
        raise ConnectionError("db down")

    with patch(f"{MOD}.fetch_fingerprints", side_effect=boom) as fetch, \
         patch(f"{MOD}.warmup_structural_cache", AsyncMock()) as warmup:
        result = await revalidation.revalidate_if_stale(cfg)
        again = await revalidation.revalidate_if_stale(cfg)

    assert result is None
    assert again is None
    assert fetch.call_count == 1  # failure also pushes the throttle window
    warmup.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_revalidate_cache_disabled_noop(cfg, monkeypatch):
    monkeypatch.setenv("SEMANTIC_MCP_CACHE_ENABLED", "false")
    reset_config()
    cfg = get_config()

    with patch(f"{MOD}.fetch_fingerprints") as fetch:
        await revalidation.maybe_revalidate(cfg)
        await asyncio.sleep(0)

    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_revalidate_runs_in_background(cfg):
    fps = _fps(tables={("dbo", "Users"): "fp"})
    await _seed_baseline(cfg, fps)

    with patch(f"{MOD}.fetch_fingerprints", return_value=fps) as fetch:
        await revalidation.maybe_revalidate(cfg)
        pending = list(revalidation._BACKGROUND_TASKS)
        assert len(pending) == 1
        await asyncio.gather(*pending)

    fetch.assert_called_once()
    assert not revalidation.is_due(cfg)


@pytest.mark.asyncio
async def test_note_refreshed_pushes_window(cfg):
    assert revalidation.is_due(cfg)
    revalidation.note_refreshed(cfg)
    assert not revalidation.is_due(cfg)
