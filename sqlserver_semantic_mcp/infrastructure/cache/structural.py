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
from .probe import SchemaFingerprints, fetch_fingerprints, write_fingerprints

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


def compute_table_hashes(snap: "StructuralSnapshot") -> dict[tuple[str, str], str]:
    """Per-table structural hash over that table's columns/PKs/FKs/indexes.

    Enables targeted invalidation: only tables whose own structure changed
    get their semantic analysis marked dirty.
    """
    parts: dict[tuple[str, str], dict[str, list]] = {
        (s, t): {"columns": [], "primary_keys": [],
                 "foreign_keys": [], "indexes": []}
        for (s, t) in snap.tables
    }

    def _bucket(rows, kind: str) -> None:
        for row in rows:
            key = (row[0], row[1])
            if key in parts:
                parts[key][kind].append(list(row))

    _bucket(snap.columns, "columns")
    _bucket(snap.primary_keys, "primary_keys")
    _bucket(snap.foreign_keys, "foreign_keys")
    _bucket(snap.indexes, "indexes")

    return {
        key: _sha256({k: sorted(v) for k, v in buckets.items()})
        for key, buckets in parts.items()
    }


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
    fingerprints: Optional[SchemaFingerprints] = None,
) -> dict:
    structural_hash = compute_structural_hash(
        snap.tables, snap.columns, snap.primary_keys,
        snap.foreign_keys, snap.indexes,
    )
    table_hashes = compute_table_hashes(snap)
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
                "INSERT INTO sc_tables "
                "(database_name, schema_name, table_name, structural_hash) "
                "VALUES (?,?,?,?)",
                [(database, s, t, table_hashes[(s, t)])
                 for (s, t) in snap.tables],
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

            # Targeted cascade: dirty only tables whose own structure changed
            await db.execute(
                "UPDATE sem_table_analysis SET status='dirty' "
                "WHERE database_name=:db AND EXISTS ("
                "  SELECT 1 FROM sc_tables t"
                "  WHERE t.database_name = sem_table_analysis.database_name"
                "    AND t.schema_name = sem_table_analysis.schema_name"
                "    AND t.table_name = sem_table_analysis.table_name"
                "    AND t.structural_hash <> sem_table_analysis.structural_hash)",
                {"db": database},
            )
            # Drop semantic rows for tables/objects no longer present
            await db.execute(
                "DELETE FROM sem_table_analysis "
                "WHERE database_name=:db AND NOT EXISTS ("
                "  SELECT 1 FROM sc_tables t"
                "  WHERE t.database_name = sem_table_analysis.database_name"
                "    AND t.schema_name = sem_table_analysis.schema_name"
                "    AND t.table_name = sem_table_analysis.table_name)",
                {"db": database},
            )
            await db.execute(
                "UPDATE sem_object_definitions SET status='dirty' "
                "WHERE database_name=? AND object_hash<>?",
                (database, object_hash),
            )
            await db.execute(
                "DELETE FROM sem_object_definitions "
                "WHERE database_name=:db AND NOT EXISTS ("
                "  SELECT 1 FROM sc_objects o"
                "  WHERE o.database_name = sem_object_definitions.database_name"
                "    AND o.schema_name = sem_object_definitions.schema_name"
                "    AND o.object_name = sem_object_definitions.object_name)",
                {"db": database},
            )

            if fingerprints is not None:
                await write_fingerprints(db, database, fingerprints)

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


def fetch_snapshot_from_server(
    cfg: Config, conn: Optional[Any] = None,
) -> StructuralSnapshot:
    if conn is None:
        with open_connection(cfg) as owned:
            return fetch_snapshot_from_server(cfg, conn=owned)

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


def _fetch_warmup_data(cfg: Config) -> tuple[SchemaFingerprints, StructuralSnapshot]:
    # Fingerprints first: a change landing between the two fetches then
    # shows up as drift on the next probe instead of being missed.
    with open_connection(cfg) as conn:
        fps = fetch_fingerprints(cfg, conn=conn)
        snap = fetch_snapshot_from_server(cfg, conn=conn)
    return fps, snap


async def warmup_structural_cache(
    cfg: Config, fingerprints: Optional[SchemaFingerprints] = None,
) -> dict:
    """Fetch snapshot (and probe fingerprints) from SQL Server into SQLite.

    Returns the new hashes. A pre-fetched fingerprint set (from the probe)
    can be passed in to avoid re-running the probe queries.
    """
    if fingerprints is None:
        fingerprints, snap = _fetch_warmup_data(cfg)
    else:
        snap = fetch_snapshot_from_server(cfg)
    logger.info(
        "Structural snapshot: %d tables, %d columns, %d FKs, %d objects",
        len(snap.tables), len(snap.columns),
        len(snap.foreign_keys), len(snap.objects),
    )
    return await write_structural_snapshot(
        cfg.cache_path, cfg.mssql_database, snap, fingerprints=fingerprints,
    )
