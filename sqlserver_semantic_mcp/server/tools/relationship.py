from mcp.types import Tool

from ...services import relationship_service, semantic_service
from ..app import get_context, register_tool


_CLASSIFICATION_PENALTY = {"bridge": 0.25, "audit": 0.2, "lookup": 0.1}


def register() -> None:
    register_tool(
        Tool(
            name="get_table_relationships",
            description="List inbound + outbound FK relationships for a table.",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema": {"type": "string"},
                    "table":  {"type": "string"},
                },
                "required": ["schema", "table"],
            },
        ),
        _rels,
    )
    register_tool(
        Tool(
            name="find_join_path",
            description=(
                "Find a shortest FK-based join path between two tables "
                "(BFS, bidirectional edges). Use after candidate tables are "
                "known. For ranking multiple reasonable paths, call "
                "score_join_candidate next."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "from_schema": {"type": "string"},
                    "from_table":  {"type": "string"},
                    "to_schema":   {"type": "string"},
                    "to_table":    {"type": "string"},
                    "max_hops":    {"type": "integer", "minimum": 1, "default": 5},
                    "score": {"type": "boolean", "default": False,
                              "description": "true = also rank the path "
                                             "(penalises extra/bridge/audit/"
                                             "lookup hops)."},
                },
                "required": ["from_schema", "from_table", "to_schema", "to_table"],
            },
        ),
        _path,
    )
    register_tool(
        Tool(
            name="get_dependency_chain",
            description=(
                "List all tables reachable from a given table via FKs. "
                "schemas param limits the BFS frontier to allowed schemas "
                "(start table always included)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "schema":    {"type": "string"},
                    "table":     {"type": "string"},
                    "max_depth": {"type": "integer", "default": 10},
                    "schemas":   {"oneOf": [{"type": "string"},
                                            {"type": "array",
                                             "items": {"type": "string"}}]},
                },
                "required": ["schema", "table"],
            },
        ),
        _chain,
    )


async def _rels(args: dict) -> list[dict]:
    ctx = get_context()
    return await relationship_service.get_table_relationships(
        ctx.cfg.cache_path, ctx.cfg.mssql_database,
        args["schema"], args["table"],
    )


async def _path(args: dict) -> dict:
    ctx = get_context()
    path = await relationship_service.find_join_path(
        ctx.cfg.cache_path, ctx.cfg.mssql_database,
        args["from_schema"], args["from_table"],
        args["to_schema"], args["to_table"],
        max_hops=args.get("max_hops", 5),
    )
    if not args.get("score"):
        return {"found": path is not None, "path": path or []}

    if path is None:
        return {"found": False, "confidence": 0.0, "hops": 0, "path": [],
                "penalties": [], "next_action": "broaden_or_pick_different_start",
                "recommended_tool": "discover_relevant_tables"}

    hops = len(path)
    score = 1.0 - (0.15 * max(hops - 1, 0))
    penalties: list[dict] = []
    for edge in path:
        schema, table = edge.get("to_schema"), edge.get("to_table")
        if not schema or not table:
            continue
        cls = await semantic_service.classify_table(
            ctx.cfg.cache_path, ctx.cfg.mssql_database, schema, table)
        pen = _CLASSIFICATION_PENALTY.get(cls.get("type"), 0.0)
        if pen:
            score -= pen
            penalties.append({"at": f"{schema}.{table}",
                              "classification": cls.get("type"), "penalty": pen})
    score = max(0.0, min(1.0, score))
    return {"found": True, "confidence": round(score, 3), "hops": hops,
            "path": path, "penalties": penalties,
            "next_action": "execute" if score >= 0.5 else "consider_alternatives",
            "recommended_tool": ("plan_or_execute_query" if score >= 0.5
                                 else "find_join_path")}


async def _chain(args: dict) -> list[dict]:
    ctx = get_context()
    raw = args.get("schemas")
    if isinstance(raw, str):
        schemas = [raw] if raw else None
    elif isinstance(raw, list):
        schemas = [s for s in raw if isinstance(s, str) and s] or None
    else:
        schemas = None
    return await relationship_service.get_dependency_chain(
        ctx.cfg.cache_path, ctx.cfg.mssql_database,
        args["schema"], args["table"],
        max_depth=args.get("max_depth", 10),
        schemas=schemas,
    )
