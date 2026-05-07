from typing import Optional

from mcp.types import Tool

from ...services import semantic_service
from ..app import get_context, register_tool
from .shape import project_classify, resolve_detail


_DETAIL_PROP = {
    "type": "string", "enum": ["brief", "standard", "full"],
    "default": "brief",
    "description": "brief = type+confidence only; standard/full include reasons.",
}


def register() -> None:
    register_tool(
        Tool(
            name="classify_table",
            description="Classify a table (fact / dimension / lookup / bridge / audit).",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema": {"type": "string"},
                    "table":  {"type": "string"},
                    "force":  {"type": "boolean", "default": False},
                    "detail": _DETAIL_PROP,
                },
                "required": ["schema", "table"],
            },
        ),
        _classify,
    )
    register_tool(
        Tool(
            name="analyze_columns",
            description="Return semantic labels for each column (audit, status, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema": {"type": "string"},
                    "table":  {"type": "string"},
                },
                "required": ["schema", "table"],
            },
        ),
        _columns,
    )
    register_tool(
        Tool(
            name="detect_lookup_tables",
            description=(
                "Scan DB and return likely lookup tables. Supports schema / "
                "keyword / confidence_min filters to limit the sweep."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "schema":         {"oneOf": [{"type": "string"},
                                                 {"type": "array",
                                                  "items": {"type": "string"}}]},
                    "keyword":        {"type": "string"},
                    "confidence_min": {"type": "number",
                                       "minimum": 0.0, "maximum": 1.0,
                                       "default": 0.0},
                },
            },
        ),
        _lookups,
    )


def _normalize_schema_filter(raw) -> Optional[list[str]]:
    if raw is None:
        return None
    if isinstance(raw, str):
        return [raw] if raw else None
    if isinstance(raw, list):
        vals = [s for s in raw if isinstance(s, str) and s]
        return vals or None
    return None


async def _classify(args: dict) -> dict:
    ctx = get_context()
    detail = resolve_detail(args)
    classification = await semantic_service.classify_table(
        ctx.cfg.cache_path, ctx.cfg.mssql_database,
        args["schema"], args["table"],
        force=args.get("force", False),
    )
    return project_classify(classification, detail)


async def _columns(args: dict) -> list[dict]:
    ctx = get_context()
    return await semantic_service.analyze_columns(
        ctx.cfg.cache_path, ctx.cfg.mssql_database,
        args["schema"], args["table"],
    )


async def _lookups(args: dict) -> list[dict]:
    ctx = get_context()
    schemas = _normalize_schema_filter(args.get("schema"))
    keyword = args.get("keyword") or None
    confidence_min = float(args.get("confidence_min", 0.0))
    return await semantic_service.detect_lookup_tables(
        ctx.cfg.cache_path, ctx.cfg.mssql_database,
        schemas=schemas, keyword=keyword, confidence_min=confidence_min,
    )
