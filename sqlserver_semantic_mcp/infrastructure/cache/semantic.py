import json
from datetime import datetime, timezone
from typing import Optional
import aiosqlite


async def get_table_analysis(
    db_path: str, database: str, schema: str, table: str,
) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM sem_table_analysis "
            "WHERE database_name=? AND schema_name=? AND table_name=?",
            (database, schema, table),
        )
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        for k in ("classification", "column_analysis"):
            if d.get(k):
                d[k] = json.loads(d[k])
        d["is_lookup"] = bool(d["is_lookup"]) if d["is_lookup"] is not None else None
        return d


async def upsert_table_analysis(
    db_path: str, database: str, schema: str, table: str,
    *,
    structural_hash: str,
    status: str,
    classification: Optional[dict] = None,
    column_analysis: Optional[list] = None,
    is_lookup: Optional[bool] = None,
    error_message: Optional[str] = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO sem_table_analysis "
            "(database_name, schema_name, table_name, structural_hash, status, "
            " classification, column_analysis, is_lookup, computed_at, error_message) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                database, schema, table, structural_hash, status,
                json.dumps(classification) if classification else None,
                json.dumps(column_analysis) if column_analysis else None,
                int(is_lookup) if is_lookup is not None else None,
                datetime.now(timezone.utc).isoformat(),
                error_message,
            ),
        )
        await db.commit()


async def get_object_definition(
    db_path: str, database: str, schema: str, obj_name: str, obj_type: str,
) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM sem_object_definitions "
            "WHERE database_name=? AND schema_name=? "
            "AND object_name=? AND object_type=?",
            (database, schema, obj_name, obj_type),
        )
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        for k in ("dependencies", "affected_tables"):
            if d.get(k):
                d[k] = json.loads(d[k])
        return d


async def upsert_object_definition(
    db_path: str, database: str, schema: str, obj_name: str, obj_type: str,
    *,
    object_hash: str,
    status: str,
    definition: Optional[str] = None,
    dependencies: Optional[list] = None,
    affected_tables: Optional[list] = None,
    error_message: Optional[str] = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO sem_object_definitions "
            "(database_name, schema_name, object_name, object_type, object_hash, "
            " status, definition, dependencies, affected_tables, "
            " computed_at, error_message) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                database, schema, obj_name, obj_type, object_hash, status,
                definition,
                json.dumps(dependencies) if dependencies else None,
                json.dumps(affected_tables) if affected_tables else None,
                datetime.now(timezone.utc).isoformat(),
                error_message,
            ),
        )
        await db.commit()


async def list_pending_table_analyses(
    db_path: str, database: str, limit: int,
) -> list[tuple[str, str]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT schema_name, table_name FROM sem_table_analysis "
            "WHERE database_name=? AND status IN ('pending','dirty') "
            "ORDER BY schema_name, table_name LIMIT ?",
            (database, limit),
        )
        return [(r["schema_name"], r["table_name"]) for r in await cur.fetchall()]


async def enqueue_all_tables(db_path: str, database: str, structural_hash: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT schema_name, table_name FROM sc_tables "
            "WHERE database_name=?",
            (database,),
        )
        tables = await cur.fetchall()
        inserted = 0
        for (s, t) in tables:
            cur = await db.execute(
                "SELECT 1 FROM sem_table_analysis "
                "WHERE database_name=? AND schema_name=? AND table_name=?",
                (database, s, t),
            )
            if await cur.fetchone():
                continue
            await db.execute(
                "INSERT INTO sem_table_analysis "
                "(database_name, schema_name, table_name, structural_hash, status) "
                "VALUES (?,?,?,?,'pending')",
                (database, s, t, structural_hash),
            )
            inserted += 1
        await db.commit()
        return inserted
