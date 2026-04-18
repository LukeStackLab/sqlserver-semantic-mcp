from typing import Optional
from collections import deque
import aiosqlite


async def get_table_relationships(
    db_path: str, database: str, schema: str, table: str,
) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT schema_name, table_name, column_name, "
            "       ref_schema, ref_table, ref_column "
            "FROM sc_foreign_keys "
            "WHERE database_name=? AND schema_name=? AND table_name=?",
            (database, schema, table),
        )
        outbound = [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            "SELECT schema_name, table_name, column_name, "
            "       ref_schema, ref_table, ref_column "
            "FROM sc_foreign_keys "
            "WHERE database_name=? AND ref_schema=? AND ref_table=?",
            (database, schema, table),
        )
        inbound = [dict(r) for r in await cur.fetchall()]

    results = []
    for r in outbound:
        results.append({
            "direction": "outbound",
            "from_schema": r["schema_name"], "from_table": r["table_name"],
            "from_column": r["column_name"],
            "to_schema": r["ref_schema"], "to_table": r["ref_table"],
            "to_column": r["ref_column"],
            "type": "many_to_one",
        })
    for r in inbound:
        results.append({
            "direction": "inbound",
            "from_schema": r["schema_name"], "from_table": r["table_name"],
            "from_column": r["column_name"],
            "to_schema": r["ref_schema"], "to_table": r["ref_table"],
            "to_column": r["ref_column"],
            "type": "one_to_many",
        })
    return results


async def _load_fk_graph(
    db_path: str, database: str,
) -> dict[tuple[str, str], list[dict]]:
    graph: dict[tuple[str, str], list[dict]] = {}
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT schema_name, table_name, column_name, "
            "       ref_schema, ref_table, ref_column "
            "FROM sc_foreign_keys WHERE database_name=?",
            (database,),
        )
        for r in await cur.fetchall():
            src = (r["schema_name"], r["table_name"])
            dst = (r["ref_schema"], r["ref_table"])
            graph.setdefault(src, []).append({
                "from_schema": src[0], "from_table": src[1],
                "from_column": r["column_name"],
                "to_schema": dst[0], "to_table": dst[1],
                "to_column": r["ref_column"],
                "direction": "outbound",
            })
            graph.setdefault(dst, []).append({
                "from_schema": dst[0], "from_table": dst[1],
                "from_column": r["ref_column"],
                "to_schema": src[0], "to_table": src[1],
                "to_column": r["column_name"],
                "direction": "inbound",
            })
    return graph


async def find_join_path(
    db_path: str, database: str,
    from_schema: str, from_table: str,
    to_schema: str, to_table: str,
    max_hops: int = 5,
) -> Optional[list[dict]]:
    graph = await _load_fk_graph(db_path, database)
    start = (from_schema, from_table)
    target = (to_schema, to_table)
    if start == target:
        return []

    queue = deque([(start, [])])
    visited = {start}
    while queue:
        node, path = queue.popleft()
        if len(path) >= max_hops:
            continue
        for edge in graph.get(node, []):
            nxt = (edge["to_schema"], edge["to_table"])
            if nxt in visited:
                continue
            new_path = path + [edge]
            if nxt == target:
                return new_path
            visited.add(nxt)
            queue.append((nxt, new_path))
    return None


async def get_dependency_chain(
    db_path: str, database: str, schema: str, table: str,
    max_depth: int = 10,
    *, schemas: Optional[list[str]] = None,
) -> list[dict]:
    graph = await _load_fk_graph(db_path, database)
    start = (schema, table)
    visited: dict[tuple[str, str], int] = {start: 0}
    queue = deque([start])
    allowed = set(schemas) if schemas else None

    while queue:
        node = queue.popleft()
        depth = visited[node]
        if depth >= max_depth:
            continue
        for edge in graph.get(node, []):
            nxt = (edge["to_schema"], edge["to_table"])
            if nxt not in visited:
                if allowed is not None and nxt[0] not in allowed:
                    continue
                visited[nxt] = depth + 1
                queue.append(nxt)

    return [
        {"schema_name": s, "table_name": t, "depth": d}
        for (s, t), d in visited.items()
        if (s, t) != start
    ]
