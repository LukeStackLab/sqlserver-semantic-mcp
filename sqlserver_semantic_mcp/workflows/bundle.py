"""Bundle prior tool results into a compact handoff for the next step."""
from __future__ import annotations

from typing import Optional

from ..config import Config, get_config
from ..services import metadata_service, object_service, semantic_service
from ..services.semantic_service import _column_semantic
from .contracts import ToolEnvelope


_JOIN_IMPORTANT = 6


async def _table_summary_for_joining(
    db_path: str, database: str, schema: str, table: str,
) -> Optional[dict]:
    full = await metadata_service.describe_table(db_path, database, schema, table)
    if full is None:
        return None
    cls = await semantic_service.classify_table(db_path, database, schema, table)
    pk = full.get("primary_key", []) or []
    fks = full.get("foreign_keys", []) or []

    important: list[str] = []
    seen: set[str] = set()

    def push(name: Optional[str]) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        important.append(name)

    for col in pk:
        push(col)
    for fk in fks:
        push(fk.get("column_name"))
    for c in full.get("columns", []):
        if len(important) >= _JOIN_IMPORTANT:
            break
        sem = _column_semantic(c)
        if sem and sem != "generic":
            push(c["column_name"])
    for c in full.get("columns", []):
        if len(important) >= _JOIN_IMPORTANT:
            break
        push(c["column_name"])

    fk_edges = [
        {
            "via_column": fk.get("column_name"),
            "to_table": f"{fk.get('ref_schema')}.{fk.get('ref_table')}",
            "to_column": fk.get("ref_column"),
        }
        for fk in fks
    ]

    return {
        "table": f"{schema}.{table}",
        "classification": cls.get("type", "unknown"),
        "pk": list(pk),
        "important_columns": important[:_JOIN_IMPORTANT],
        "fk_edges": fk_edges,
    }


async def _object_summary_for_impact(
    schema: str,
    object_name: str,
    object_type: str,
    cfg: Config,
) -> Optional[dict]:
    obj = await object_service.describe_object(
        schema, object_name, object_type, cfg,
    )
    if not obj:
        return None
    return {
        "object": f"{schema}.{object_name}",
        "type": object_type,
        "reads": list(obj.get("read_tables", []) or []),
        "writes": list(obj.get("write_tables", []) or []),
        "depends_on": list(obj.get("dependencies", []) or []),
        "status": obj.get("status"),
    }


async def bundle_context_for_next_step(
    items: list[dict],
    *,
    goal: str = "joining",
    detail: str = "brief",
    cfg: Optional[Config] = None,
) -> dict:
    """Compress prior discoveries into the minimum context the next
    tool needs. Supported goals: ``joining``, ``object_impact``.
    """
    cfg = cfg or get_config()
    db_path = cfg.cache_path
    database = cfg.mssql_database

    if goal == "joining":
        tables: list[dict] = []
        for item in items or []:
            if item.get("kind") != "table":
                continue
            schema = item["schema"]
            table = item["table"]
            summary = await _table_summary_for_joining(
                db_path, database, schema, table,
            )
            if summary is not None:
                tables.append(summary)
        return ToolEnvelope(
            kind="bundle_context_for_next_step",
            detail=detail,
            next_action="find_or_score_join",
            recommended_tool="score_join_candidate",
            bundle_key="joining",
            data={
                "bundle_type": "joining",
                "tables": tables,
            },
        ).to_dict()

    if goal == "object_impact":
        objects: list[dict] = []
        for item in items or []:
            if item.get("kind") != "object":
                continue
            summary = await _object_summary_for_impact(
                item["schema"], item["object_name"], item["object_type"], cfg,
            )
            if summary is not None:
                objects.append(summary)
        return ToolEnvelope(
            kind="bundle_context_for_next_step",
            detail=detail,
            next_action="trace_impact",
            recommended_tool="describe_object",
            bundle_key="object_impact",
            data={
                "bundle_type": "object_impact",
                "objects": objects,
            },
        ).to_dict()

    return ToolEnvelope(
        kind="bundle_context_for_next_step",
        detail=detail,
        next_action="none",
        data={
            "bundle_type": goal,
            "error": f"unsupported goal '{goal}'",
            "supported_goals": ["joining", "object_impact"],
        },
    ).to_dict()
