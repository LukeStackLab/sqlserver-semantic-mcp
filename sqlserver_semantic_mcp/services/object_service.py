import logging
import re
from typing import Optional

from ..config import Config, get_config
from ..domain.enums import SqlOperation
from ..infrastructure.cache.semantic import (
    get_object_definition, upsert_object_definition,
)
from ..infrastructure.cache.structural import read_schema_version
from ..infrastructure.connection import fetch_one, fetch_all
from ..infrastructure.queries.object_queries import (
    GET_OBJECT_DEFINITION, GET_OBJECT_DEPENDENCIES,
)
from ..policy.analyzer import (
    _strip_comments, _split_statements, _detect_operation, _IDENT,
)

logger = logging.getLogger(__name__)


_WRITE_OPS = {
    SqlOperation.UPDATE, SqlOperation.INSERT, SqlOperation.DELETE,
    SqlOperation.MERGE, SqlOperation.TRUNCATE,
    SqlOperation.DROP, SqlOperation.ALTER, SqlOperation.CREATE,
    SqlOperation.EXEC, SqlOperation.EXECUTE,
}


def _write_target(sql: str, operation: SqlOperation) -> Optional[str]:
    patterns = {
        SqlOperation.UPDATE:   rf"\bUPDATE\s+({_IDENT})",
        SqlOperation.INSERT:   rf"\bINTO\s+({_IDENT})",
        SqlOperation.DELETE:   rf"\bDELETE\s+(?:FROM\s+)?({_IDENT})",
        SqlOperation.MERGE:    rf"\bMERGE\s+(?:INTO\s+)?({_IDENT})",
        SqlOperation.TRUNCATE: rf"\bTRUNCATE\s+TABLE\s+({_IDENT})",
    }
    pat = patterns.get(operation)
    if not pat:
        return None
    m = re.search(pat, sql, re.IGNORECASE)
    return m.group(1) if m else None


def _from_join_sources(sql: str) -> list[str]:
    tables: list[str] = []
    tables.extend(re.findall(rf"\bFROM\s+({_IDENT})", sql, re.IGNORECASE))
    tables.extend(re.findall(rf"\bJOIN\s+({_IDENT})", sql, re.IGNORECASE))
    return tables


_WRITE_PATTERNS = [
    rf"\bUPDATE\s+({_IDENT})",
    rf"\bINSERT\s+INTO\s+({_IDENT})",
    rf"\bDELETE\s+FROM\s+({_IDENT})",
    rf"\bMERGE\s+(?:INTO\s+)?({_IDENT})",
    rf"\bTRUNCATE\s+TABLE\s+({_IDENT})",
]


def split_read_write(sql: str) -> tuple[list[str], list[str]]:
    """Split a SQL body (e.g. a PROCEDURE definition) into (read_tables, write_tables).

    Regex-based. Scans the entire SQL for write-operation patterns (UPDATE/INSERT/
    DELETE/MERGE/TRUNCATE TABLE) and for read-source patterns (FROM/JOIN).
    Write targets are excluded from reads even if they also appear as FROM aliases
    in the same statement (write-intent wins).

    Known limitations: CTE names may appear as reads; dynamic SQL is invisible.
    Returns ([], []) on empty input.
    """
    if not sql or not sql.strip():
        return [], []

    clean = _strip_comments(sql)

    writes: list[str] = []
    for pat in _WRITE_PATTERNS:
        writes.extend(re.findall(pat, clean, re.IGNORECASE))

    # Read sources = FROM / JOIN, excluding DELETE FROM target
    # Strip DELETE FROM fragments so they don't double-count
    read_scan = re.sub(
        rf"\bDELETE\s+FROM\s+{_IDENT}", "", clean, flags=re.IGNORECASE,
    )
    reads: list[str] = []
    reads.extend(re.findall(rf"\bFROM\s+({_IDENT})", read_scan, re.IGNORECASE))
    reads.extend(re.findall(rf"\bJOIN\s+({_IDENT})", read_scan, re.IGNORECASE))

    # Dedup preserving order
    def _dedup(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for t in items:
            k = t.lower()
            if k not in seen:
                seen.add(k)
                out.append(t)
        return out

    writes_d = _dedup(writes)
    # Reads: dedup, then remove any table that is also in writes (write-intent wins)
    write_keys = {w.lower() for w in writes_d}
    reads_d = [r for r in _dedup(reads) if r.lower() not in write_keys]

    return reads_d, writes_d


def _augment_read_write(obj: dict) -> dict:
    """Add read_tables/write_tables derived from the cached definition."""
    if not obj:
        return obj
    definition = obj.get("definition")
    if isinstance(definition, str) and definition:
        try:
            reads, writes = split_read_write(definition)
        except Exception:
            logger.exception("split_read_write failed; falling back")
            reads, writes = obj.get("dependencies", []) or [], []
        out = dict(obj)
        out["read_tables"] = reads
        out["write_tables"] = writes
        # Legacy: affected_tables aliases write_tables (name now matches intent)
        out["affected_tables"] = writes
        return out
    return obj


async def describe_object(
    schema: str, object_name: str, object_type: str,
    cfg: Optional[Config] = None,
) -> dict:
    cfg = cfg or get_config()
    db = cfg.mssql_database
    ver = await read_schema_version(cfg.cache_path, db)
    object_hash = ver["object_hash"] if ver else ""

    cached = await get_object_definition(
        cfg.cache_path, db, schema, object_name, object_type,
    )
    if cached and cached["status"] == "ready" \
            and cached.get("object_hash") == object_hash:
        return _augment_read_write(cached)

    qualified = f"{schema}.{object_name}"
    try:
        def_row = fetch_one(cfg, GET_OBJECT_DEFINITION, (qualified,))
        definition = def_row[0] if def_row and def_row[0] else None
        dep_rows = fetch_all(cfg, GET_OBJECT_DEPENDENCIES, (qualified,))
        dependencies = [f"{r[0]}.{r[1]}" for r in dep_rows if r[0]]
        affected = [
            f"{r[0]}.{r[1]}" for r in dep_rows
            if r[2] and "TABLE" in str(r[2]).upper()
        ]
        await upsert_object_definition(
            cfg.cache_path, db, schema, object_name, object_type,
            object_hash=object_hash, status="ready",
            definition=definition, dependencies=dependencies,
            affected_tables=affected,
        )
        fresh = await get_object_definition(
            cfg.cache_path, db, schema, object_name, object_type,
        )
        return _augment_read_write(fresh)
    except Exception as e:
        logger.exception("describe_object failed")
        await upsert_object_definition(
            cfg.cache_path, db, schema, object_name, object_type,
            object_hash=object_hash, status="error",
            error_message=str(e),
        )
        return {"status": "error", "error_message": str(e)}


async def trace_dependencies(
    schema: str, object_name: str, object_type: str,
    cfg: Optional[Config] = None,
) -> list[str]:
    obj = await describe_object(schema, object_name, object_type, cfg)
    return obj.get("dependencies", []) if obj else []
