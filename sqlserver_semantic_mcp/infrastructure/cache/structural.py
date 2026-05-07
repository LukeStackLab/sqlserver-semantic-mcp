import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

from ...config import Config
from ..connection import open_connection
from ..queries.metadata_queries import (
    GET_TABLES, GET_COLUMNS, GET_PRIMARY_KEYS,
    GET_FOREIGN_KEYS, GET_INDEXES, GET_OBJECTS,
)
from ..queries.comment_queries import GET_COMMENTS

logger = logging.getLogger(__name__)


@dataclass
class StructuralSnapshot:
    tables: list[tuple]          # (schema, table)
    columns: list[tuple]         # (schema, table, col, type, maxlen, nullable, default, ordinal)
    primary_keys: list[tuple]    # (schema, table, col)
    foreign_keys: list[tuple]    # (schema, table, col, ref_schema, ref_table, ref_col)
    indexes: list[tuple]         # (schema, table, index_name, is_unique, is_pk, cols)
    objects: list[tuple]         # (schema, name, type)
    comments: list[tuple]        # (schema, object, column, description)


def _sha256(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_structural_hash(
    tables, columns, primary_keys, foreign_keys, indexes,
) -> str:
    return _sha256({
        "tables": sorted([list(t) for t in tables]),
        "columns": sorted([list(c) for c in columns]),
        "primary_keys": sorted([list(p) for p in primary_keys]),
        "foreign_keys": sorted([list(f) for f in foreign_keys]),
        "indexes": sorted([list(i) for i in indexes]),
    })


def compute_object_hash(objects) -> str:
    return _sha256({"objects": sorted([list(o) for o in objects])})


def compute_comment_hash(comments) -> str:
    return _sha256({"comments": sorted([list(c) for c in comments])})


async def read_schema_version(db_path: str, database: str) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM schema_version WHERE database_name = ?",
            (database,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def write_structural_snapshot(
    db_path: str, database: str, snap: StructuralSnapshot,
) -> dict:
    structural_hash = compute_structural_hash(
        snap.tables, snap.columns, snap.primary_keys,
        snap.foreign_keys, snap.indexes,
    )
    object_hash = compute_object_hash(snap.objects)
    comment_hash = compute_comment_hash(snap.comments)
    captured_at = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(db_path) as db:
        await db.execute("BEGIN")
        try:
            for tbl in [
                "sc_tables", "sc_columns", "sc_primary_keys",
                "sc_foreign_keys", "sc_indexes", "sc_objects", "sc_comments",
            ]:
                await db.execute(
                    f"DELETE FROM {tbl} WHERE database_name = ?", (database,),
                )

            await db.executemany(
                "INSERT INTO sc_tables (database_name, schema_name, table_name) "
                "VALUES (?,?,?)",
                [(database, s, t) for (s, t) in snap.tables],
            )
            await db.executemany(
                "INSERT INTO sc_columns "
                "(database_name, schema_name, table_name, column_name, data_type, "
                "max_length, is_nullable, column_default, ordinal_position) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                [(database, *row) for row in snap.columns],
            )
            await db.executemany(
                "INSERT INTO sc_primary_keys "
                "(database_name, schema_name, table_name, column_name) "
                "VALUES (?,?,?,?)",
                [(database, *row) for row in snap.primary_keys],
            )
            await db.executemany(
                "INSERT INTO sc_foreign_keys "
                "(database_name, schema_name, table_name, column_name, "
                "ref_schema, ref_table, ref_column) VALUES (?,?,?,?,?,?,?)",
                [(database, *row) for row in snap.foreign_keys],
            )
            await db.executemany(
                "INSERT INTO sc_indexes "
                "(database_name, schema_name, table_name, index_name, "
                "is_unique, is_primary_key, columns) VALUES (?,?,?,?,?,?,?)",
                [(database, *row) for row in snap.indexes],
            )
            await db.executemany(
                "INSERT INTO sc_objects "
                "(database_name, schema_name, object_name, object_type) "
                "VALUES (?,?,?,?)",
                [(database, *row) for row in snap.objects],
            )
            await db.executemany(
                "INSERT INTO sc_comments "
                "(database_name, schema_name, object_name, column_name, description) "
                "VALUES (?,?,?,?,?)",
                [(database, *row) for row in snap.comments],
            )

            await db.execute(
                "INSERT OR REPLACE INTO schema_version "
                "(database_name, structural_hash, object_hash, comment_hash, "
                " captured_at) VALUES (?,?,?,?,?)",
                (database, structural_hash, object_hash, comment_hash, captured_at),
            )

            # Cascade: mark stale semantic rows dirty
            await db.execute(
                "UPDATE sem_table_analysis SET status='dirty' "
                "WHERE database_name=? AND structural_hash<>?",
                (database, structural_hash),
            )
            await db.execute(
                "UPDATE sem_object_definitions SET status='dirty' "
                "WHERE database_name=? AND object_hash<>?",
                (database, object_hash),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return {
        "structural_hash": structural_hash,
        "object_hash": object_hash,
        "comment_hash": comment_hash,
        "captured_at": captured_at,
    }


def fetch_snapshot_from_server(cfg: Config) -> StructuralSnapshot:
    queries = (
        GET_TABLES,
        GET_COLUMNS,
        GET_PRIMARY_KEYS,
        GET_FOREIGN_KEYS,
        GET_INDEXES,
        GET_OBJECTS,
        GET_COMMENTS,
    )
    results: list[list[tuple]] = []
    with open_connection(cfg) as conn:
        cursor = conn.cursor()
        try:
            for sql in queries:
                cursor.execute(sql)
                results.append(list(cursor.fetchall()))
        finally:
            cursor.close()

    return StructuralSnapshot(
        tables=results[0],
        columns=results[1],
        primary_keys=results[2],
        foreign_keys=results[3],
        indexes=results[4],
        objects=results[5],
        comments=results[6],
    )


async def warmup_structural_cache(cfg: Config) -> dict:
    """Fetch snapshot from SQL Server and write to SQLite. Returns hashes."""
    snap = fetch_snapshot_from_server(cfg)
    logger.info(
        "Structural snapshot: %d tables, %d columns, %d FKs, %d objects",
        len(snap.tables), len(snap.columns),
        len(snap.foreign_keys), len(snap.objects),
    )
    return await write_structural_snapshot(cfg.cache_path, cfg.mssql_database, snap)
