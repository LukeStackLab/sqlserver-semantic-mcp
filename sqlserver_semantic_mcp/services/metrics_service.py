"""Per-tool response metrics recording and query.

See docs/superpowers/specs/2026-04-19-p4-measurement-design.md.
"""
from datetime import datetime, timezone
from typing import Optional

import aiosqlite


async def record_metric(
    db_path: str, tool_name: str, *,
    response_bytes: int,
    array_length: Optional[int] = None,
    fields_returned: Optional[int] = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO tool_metrics "
            "(tool_name, response_bytes, array_length, fields_returned, recorded_at) "
            "VALUES (?,?,?,?,?)",
            (tool_name, response_bytes, array_length, fields_returned,
             datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    vs = sorted(values)
    idx = max(0, int(0.95 * len(vs)) - 1)
    return vs[idx]


async def query_top_tools(db_path: str, *, limit: int = 10) -> list[dict]:
    """Return tool metrics aggregated, ordered by total_bytes desc."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT tool_name, COUNT(*) AS call_count, "
            "       SUM(response_bytes) AS total_bytes, "
            "       AVG(response_bytes) AS avg_bytes, "
            "       MAX(response_bytes) AS max_bytes "
            "FROM tool_metrics "
            "GROUP BY tool_name "
            "ORDER BY total_bytes DESC "
            "LIMIT ?",
            (limit,),
        )
        aggregated = [dict(r) for r in await cur.fetchall()]

        for row in aggregated:
            cur = await db.execute(
                "SELECT response_bytes FROM tool_metrics "
                "WHERE tool_name=? ORDER BY response_bytes",
                (row["tool_name"],),
            )
            values = [r[0] for r in await cur.fetchall()]
            row["p95_bytes"] = _p95(values)
            row["avg_bytes"] = int(row["avg_bytes"] or 0)
        return aggregated


async def clear_metrics(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("DELETE FROM tool_metrics")
        await db.commit()
        return cur.rowcount
