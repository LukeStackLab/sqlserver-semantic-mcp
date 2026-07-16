"""Workflow-layer MCP tools (v0.5)."""
from __future__ import annotations

from mcp.types import Tool

from ...services import relationship_service, semantic_service
from ..app import get_context, register_tool


_DETAIL_PROP = {
    "type": "string", "enum": ["brief", "standard", "full"], "default": "brief",
}


def register() -> None:
    register_tool(
        Tool(
            name="discover_relevant_tables",
            description=(
                "Return a small, ranked candidate set for a natural-language "
                "goal. Use before describe_table / find_join_path when the "
                "target tables are not yet known."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "goal":    {"type": "string"},
                    "schemas": {"type": "array",
                                "items": {"type": "string"}},
                    "keyword": {"type": "string"},
                    "limit":   {"type": "integer", "minimum": 1, "default": 10},
                    "classify": {"type": "boolean", "default": False},
                },
                "required": ["goal"],
            },
        ),
        _discover,
    )
    register_tool(
        Tool(
            name="suggest_next_tool",
            description=(
                "Given the agent's current state (optional query, goal, or "
                "discovered context), return the recommended next tool call. "
                "Runs no DB queries."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":           {"type": "string"},
                    "goal":            {"type": "string"},
                    "have_candidates": {"type": "boolean", "default": False},
                    "have_join_path":  {"type": "boolean", "default": False},
                    "have_object":     {"type": "string"},
                },
            },
        ),
        _suggest,
    )
    register_tool(
        Tool(
            name="bundle_context_for_next_step",
            description=(
                "Compress prior tool results into the minimum context the "
                "next tool needs. goal=joining expects items [{kind:table, "
                "schema, table}]; goal=object_impact expects [{kind:object, "
                "schema, object_name, object_type}]."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "goal":   {"type": "string",
                               "enum": ["joining", "object_impact"],
                               "default": "joining"},
                    "detail": _DETAIL_PROP,
                },
                "required": ["items"],
            },
        ),
        _bundle,
    )
    register_tool(
        Tool(
            name="score_join_candidate",
            description=(
                "Compute a usability score for a join path candidate. "
                "Penalises excess hops and bridge/audit/lookup hops."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "from_schema": {"type": "string"},
                    "from_table":  {"type": "string"},
                    "to_schema":   {"type": "string"},
                    "to_table":    {"type": "string"},
                    "max_hops":    {"type": "integer", "minimum": 1, "default": 5},
                },
                "required": ["from_schema", "from_table",
                             "to_schema", "to_table"],
            },
        ),
        _score_join,
    )

# ---- handlers ---------------------------------------------------------------


async def _discover(args: dict) -> dict:
    ctx = get_context()
    schemas = args.get("schemas") or None
    return await ctx.workflow.discover_relevant_tables(
        args["goal"],
        schemas=schemas,
        keyword=args.get("keyword"),
        limit=int(args.get("limit", 10)),
        classify=bool(args.get("classify", False)),
    )


async def _suggest(args: dict) -> dict:
    ctx = get_context()
    return ctx.workflow.suggest_next_tool(
        query=args.get("query"),
        goal=args.get("goal"),
        have_candidates=bool(args.get("have_candidates", False)),
        have_join_path=bool(args.get("have_join_path", False)),
        have_object=args.get("have_object"),
    )


async def _bundle(args: dict) -> dict:
    ctx = get_context()
    return await ctx.workflow.bundle_context_for_next_step(
        args["items"],
        goal=args.get("goal", "joining"),
        detail=args.get("detail", "brief"),
    )


# ---- reasoning helpers ------------------------------------------------------


_CLASSIFICATION_PENALTY = {
    "bridge": 0.25,
    "audit":  0.2,
    "lookup": 0.1,
}


async def _score_join(args: dict) -> dict:
    ctx = get_context()
    path = await relationship_service.find_join_path(
        ctx.cfg.cache_path, ctx.cfg.mssql_database,
        args["from_schema"], args["from_table"],
        args["to_schema"], args["to_table"],
        max_hops=args.get("max_hops", 5),
    )

    if path is None:
        return {
            "kind": "score_join_candidate",
            "detail": "brief",
            "found": False,
            "next_action": "broaden_or_pick_different_start",
            "recommended_tool": "discover_relevant_tables",
            "data": {"score": 0.0, "path": [], "penalties": []},
        }

    hops = len(path)
    score = 1.0 - (0.15 * max(hops - 1, 0))
    penalties: list[dict] = []

    for edge in path:
        schema = edge.get("to_schema")
        table = edge.get("to_table")
        if not schema or not table:
            continue
        cls = await semantic_service.classify_table(
            ctx.cfg.cache_path, ctx.cfg.mssql_database, schema, table,
        )
        penalty = _CLASSIFICATION_PENALTY.get(cls.get("type"), 0.0)
        if penalty:
            score -= penalty
            penalties.append({
                "at": f"{schema}.{table}",
                "classification": cls.get("type"),
                "penalty": penalty,
            })

    score = max(0.0, min(1.0, score))

    return {
        "kind": "score_join_candidate",
        "detail": "brief",
        "found": True,
        "confidence": score,
        "next_action": "execute" if score >= 0.5 else "consider_alternatives",
        "recommended_tool": (
            "plan_or_execute_query" if score >= 0.5 else "find_join_path"
        ),
        "data": {
            "score": round(score, 3),
            "hops": hops,
            "path": path,
            "penalties": penalties,
        },
    }
