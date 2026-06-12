"""Throttled cache revalidation driven by the L1 schema probe.

Flow per tool call (see server/app.py):
  - mode 'manual'  -> never probes; refresh only on startup / refresh tool.
  - mode 'probe'   -> if the throttle window elapsed, revalidate in the
                      background (stale-while-revalidate): the current call
                      is served from cache, drift is folded in for the next.
  - mode 'strict'  -> same throttle, but the call awaits the revalidation
                      so it always sees a validated schema.

A probe compares fresh catalog fingerprints against the SQLite baseline.
On drift it triggers the full structural warmup (which re-baselines the
fingerprints and dirty-marks changed tables) and additionally dirty-marks
changed modules plus modules depending on changed tables — covering view/
function bodies that SQL Server does not touch when an underlying table
changes.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from ...config import Config
from .probe import diff_fingerprints, fetch_fingerprints, read_fingerprints
from .semantic import mark_objects_dirty
from .structural import warmup_structural_cache

logger = logging.getLogger(__name__)


@dataclass
class _ProbeState:
    last_checked: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_STATES: dict[tuple[str, str], _ProbeState] = {}
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _state(cfg: Config) -> _ProbeState:
    key = (cfg.cache_path, cfg.mssql_database)
    if key not in _STATES:
        _STATES[key] = _ProbeState()
    return _STATES[key]


def reset_state() -> None:
    """Test helper only."""
    _STATES.clear()


def note_refreshed(cfg: Config) -> None:
    """Push the throttle window after an explicit warmup (no probe needed)."""
    _state(cfg).last_checked = time.monotonic()


def is_due(cfg: Config) -> bool:
    state = _state(cfg)
    return (
        state.last_checked == 0.0
        or time.monotonic() - state.last_checked >= cfg.probe_interval_s
    )


async def revalidate_if_stale(cfg: Config, *, force: bool = False) -> Optional[dict]:
    """Probe for schema drift; refresh the structural cache when found.

    Returns a summary dict when a probe ran, or None when throttled / failed.
    Single-flight: concurrent callers wait on the same probe.
    """
    state = _state(cfg)
    if not force and not is_due(cfg):
        return None

    async with state.lock:
        if not force and not is_due(cfg):
            return None  # another caller revalidated while we waited

        try:
            fresh = await asyncio.to_thread(fetch_fingerprints, cfg)
        except Exception:
            # DB unreachable: serve cache, retry after the next window.
            logger.warning("Schema probe failed; keeping cache", exc_info=True)
            state.last_checked = time.monotonic()
            return None

        stored_tables, stored_objects = await read_fingerprints(
            cfg.cache_path, cfg.mssql_database,
        )
        baseline_missing = not stored_tables and not stored_objects
        diff = diff_fingerprints(stored_tables, stored_objects, fresh)

        refreshed = False
        objects_marked = 0
        if diff.has_changes or baseline_missing:
            await warmup_structural_cache(cfg, fingerprints=fresh)
            refreshed = True
            if not baseline_missing:
                # Dependency cascade: modules referencing changed/removed
                # tables, plus modules whose own fingerprint changed.
                keys = {(s, n) for (s, n, _t) in diff.changed_objects}
                for tkey in (*diff.changed_tables, *diff.removed_tables):
                    keys.update(fresh.table_dependents.get(tkey, []))
                objects_marked = await mark_objects_dirty(
                    cfg.cache_path, cfg.mssql_database, keys,
                )
                logger.info(
                    "Schema drift detected (%s); cache refreshed, "
                    "%d dependent object(s) marked dirty",
                    diff.summary(), objects_marked,
                )

        state.last_checked = time.monotonic()
        return {
            "probed": True,
            "refreshed": refreshed,
            "baseline_created": baseline_missing,
            "objects_marked_dirty": objects_marked,
            **diff.summary(),
        }


async def maybe_revalidate(cfg: Config) -> None:
    """Mode-aware entry point used by the tool dispatcher. Never raises."""
    try:
        if not cfg.cache_enabled or cfg.cache_validation_mode == "manual":
            return
        if not is_due(cfg):
            return
        if cfg.cache_validation_mode == "strict":
            await revalidate_if_stale(cfg)
            return
        task = asyncio.create_task(revalidate_if_stale(cfg))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
    except Exception:
        logger.exception("maybe_revalidate failed")
