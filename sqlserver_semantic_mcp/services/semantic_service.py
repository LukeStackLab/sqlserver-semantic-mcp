import json
import re
from typing import Optional
import aiosqlite

from ..infrastructure.cache.semantic import (
    upsert_table_analysis, get_table_analysis,
)
from ..infrastructure.cache.structural import read_schema_version


_AUDIT_COL_PATTERNS = {
    "audit_timestamp": re.compile(
        r"^(created|updated|modified|deleted)(_?at|_?on|_?time|_?date)?$", re.I),
    "audit_user":      re.compile(
        r"^(created|updated|modified|deleted)_?by$", re.I),
    "soft_delete":     re.compile(r"^(is_)?deleted$|^deleted_at$", re.I),
    "status":          re.compile(r"^(status|state)(_?code|_?id)?$", re.I),
    "type":            re.compile(r"^(type|category|kind)(_?code|_?id)?$", re.I),
}

_LOOKUP_NAME_COLS = {"code", "name", "label", "description", "value"}

_COMMON_FILTER_SEMANTICS = frozenset({
    "status", "type", "audit_timestamp", "soft_delete",
})


async def _load_table_structure(
    db_path: str, database: str, schema: str, table: str,
) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT 1 FROM sc_tables WHERE database_name=? "
            "AND schema_name=? AND table_name=?",
            (database, schema, table),
        )
        if not await cur.fetchone():
            return None

        cur = await db.execute(
            "SELECT column_name, data_type, max_length, is_nullable, ordinal_position "
            "FROM sc_columns WHERE database_name=? AND schema_name=? AND table_name=? "
            "ORDER BY ordinal_position",
            (database, schema, table),
        )
        columns = [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            "SELECT column_name FROM sc_primary_keys "
            "WHERE database_name=? AND schema_name=? AND table_name=?",
            (database, schema, table),
        )
        pk = [r["column_name"] for r in await cur.fetchall()]

        cur = await db.execute(
            "SELECT column_name, ref_schema, ref_table FROM sc_foreign_keys "
            "WHERE database_name=? AND schema_name=? AND table_name=?",
            (database, schema, table),
        )
        fks = [dict(r) for r in await cur.fetchall()]

    return {"columns": columns, "primary_key": pk, "foreign_keys": fks}


def _column_semantic(col: dict) -> Optional[str]:
    name = col["column_name"]
    for sem, pat in _AUDIT_COL_PATTERNS.items():
        if pat.match(name):
            return sem
    return None


def _classify(struct: dict, table: str) -> dict:
    cols = struct["columns"]
    fks = struct["foreign_keys"]
    col_names = [c["column_name"].lower() for c in cols]

    reasons: list[str] = []

    # Audit heuristic
    audit_like = sum(1 for c in cols if _column_semantic(c) in (
        "audit_timestamp", "audit_user"))
    if audit_like >= 2 and len(cols) <= 6:
        reasons.append(f"{audit_like} audit-style columns dominate")
        return {"type": "audit", "confidence": 0.75, "reasons": reasons}

    # Bridge: 2+ FKs and almost all columns are FKs
    if len(fks) >= 2 and len(cols) <= len(fks) + 2:
        reasons.append(f"{len(fks)} FKs over {len(cols)} columns")
        return {"type": "bridge", "confidence": 0.8, "reasons": reasons}

    # Fact: >= 2 FKs
    if len(fks) >= 2:
        reasons.append(f"{len(fks)} FKs")
        return {"type": "fact", "confidence": 0.7, "reasons": reasons}

    # Lookup: few columns, contains code/name-like column names
    small = len(cols) <= 4
    lookup_cols = sum(1 for n in col_names if n in _LOOKUP_NAME_COLS)
    name_suggests_lookup = bool(re.search(
        r"(status|code|type|category|kind|lookup)$", table, re.I,
    ))
    if small and (lookup_cols >= 2 or name_suggests_lookup):
        reasons.append("small row width + lookup-like columns/name")
        return {"type": "lookup", "confidence": 0.75, "reasons": reasons}

    # Dimension fallback
    if len(fks) <= 1 and len(cols) >= 3:
        reasons.append("few FKs with multiple descriptive columns")
        return {"type": "dimension", "confidence": 0.5, "reasons": reasons}

    return {"type": "unknown", "confidence": 0.2,
            "reasons": reasons or ["no rule matched"]}


async def classify_table(
    db_path: str, database: str, schema: str, table: str,
    *, force: bool = False,
) -> dict:
    ver = await read_schema_version(db_path, database)
    structural_hash = ver["structural_hash"] if ver else ""

    if not force:
        cached = await get_table_analysis(db_path, database, schema, table)
        if cached and cached["status"] == "ready" \
                and cached.get("structural_hash") == structural_hash:
            return cached["classification"]

    struct = await _load_table_structure(db_path, database, schema, table)
    if struct is None:
        return {"type": "unknown", "confidence": 0.0,
                "reasons": ["table not found"]}

    classification = _classify(struct, table)
    column_analysis = [
        {"column": c["column_name"],
         "semantic_type": _column_semantic(c) or "generic"}
        for c in struct["columns"]
    ]
    is_lookup = classification["type"] == "lookup"

    await upsert_table_analysis(
        db_path, database, schema, table,
        structural_hash=structural_hash, status="ready",
        classification=classification,
        column_analysis=column_analysis,
        is_lookup=is_lookup,
    )
    return classification


async def analyze_columns(
    db_path: str, database: str, schema: str, table: str,
) -> list[dict]:
    await classify_table(db_path, database, schema, table)
    cached = await get_table_analysis(db_path, database, schema, table)
    return cached.get("column_analysis", []) if cached else []


async def summarize_for_joining(
    db_path: str, database: str, schema: str, table: str,
) -> Optional[dict]:
    """Return reasoning-ready info for joining against this table.

    Shape: {table, pk, classification, join_candidates, common_filter_columns}
    """
    struct = await _load_table_structure(db_path, database, schema, table)
    if struct is None:
        return None

    join_candidates = [
        {"via_column": fk["column_name"],
         "to_table": f"{fk['ref_schema']}.{fk['ref_table']}"}
        for fk in struct["foreign_keys"]
    ]

    common_filter_columns = [
        c["column_name"] for c in struct["columns"]
        if (_column_semantic(c) or "") in _COMMON_FILTER_SEMANTICS
    ]

    classification = _classify(struct, table)

    return {
        "table": f"{schema}.{table}",
        "pk": struct["primary_key"],
        "classification": classification["type"],
        "join_candidates": join_candidates,
        "common_filter_columns": common_filter_columns,
    }


async def detect_lookup_tables(
    db_path: str, database: str, *,
    schemas: Optional[list[str]] = None,
    keyword: Optional[str] = None,
    confidence_min: float = 0.0,
) -> list[dict]:
    ver = await read_schema_version(db_path, database)
    current_hash = ver["structural_hash"] if ver else ""

    results: list[dict] = []
    need_classify: list[tuple[str, str]] = []

    kw_lower = keyword.lower() if keyword else None

    def passes_filter(s: str, t: str) -> bool:
        if schemas and s not in schemas:
            return False
        if kw_lower and kw_lower not in f"{s}.{t}".lower():
            return False
        return True

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT schema_name, table_name FROM sc_tables "
            "WHERE database_name=?",
            (database,),
        )
        all_tables = [(r["schema_name"], r["table_name"])
                      for r in await cur.fetchall()
                      if passes_filter(r["schema_name"], r["table_name"])]

        # Fast path: read ready+fresh lookup rows from cache
        cur = await db.execute(
            "SELECT schema_name, table_name, classification FROM sem_table_analysis "
            "WHERE database_name=? AND status='ready' "
            "AND structural_hash=? AND is_lookup=1",
            (database, current_hash),
        )
        cached_hits = {
            (r["schema_name"], r["table_name"]):
                json.loads(r["classification"]) if r["classification"] else None
            for r in await cur.fetchall()
        }

        # Tables whose analysis is missing / stale / non-lookup-ready
        cur = await db.execute(
            "SELECT schema_name, table_name, status, structural_hash "
            "FROM sem_table_analysis "
            "WHERE database_name=?",
            (database,),
        )
        cache_state = {
            (r["schema_name"], r["table_name"]):
                (r["status"], r["structural_hash"])
            for r in await cur.fetchall()
        }

    for (s, t) in all_tables:
        if (s, t) in cached_hits:
            cls = cached_hits[(s, t)] or {"confidence": 0.75}
            conf = cls.get("confidence", 0.75)
            if conf >= confidence_min:
                results.append({
                    "schema_name": s, "table_name": t,
                    "confidence": conf,
                })
            continue
        state = cache_state.get((s, t))
        # Needs classification if: no row, dirty/pending, or hash mismatch
        if state is None or state[0] != "ready" or state[1] != current_hash:
            need_classify.append((s, t))

    for (s, t) in need_classify:
        c = await classify_table(db_path, database, s, t)
        if c.get("type") == "lookup":
            conf = c.get("confidence", 0.75)
            if conf >= confidence_min:
                results.append({
                    "schema_name": s, "table_name": t,
                    "confidence": conf,
                })
    return results
