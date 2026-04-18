import hashlib
from typing import Any

from mcp.types import Tool

from ...services import object_service
from ..app import get_context, register_tool


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema":             {"type": "string"},
        "name":               {"type": "string"},
        "include_definition": {"type": "boolean", "default": False},
    },
    "required": ["schema", "name"],
}


def register() -> None:
    register_tool(
        Tool(
            name="describe_view",
            description=(
                "Return view metadata + dependencies. By default the full SQL "
                "definition is stripped and replaced with definition_hash + "
                "definition_bytes. Pass include_definition=true to get the full text."
            ),
            inputSchema=_INPUT_SCHEMA,
        ),
        _describe_view,
    )
    register_tool(
        Tool(
            name="describe_procedure",
            description=(
                "Return procedure metadata + dependencies. By default the full SQL "
                "definition is stripped and replaced with definition_hash + "
                "definition_bytes. Pass include_definition=true to get the full text."
            ),
            inputSchema=_INPUT_SCHEMA,
        ),
        _describe_procedure,
    )
    register_tool(
        Tool(
            name="trace_object_dependencies",
            description="Return a list of objects/tables the given object depends on.",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema": {"type": "string"},
                    "name":   {"type": "string"},
                    "type":   {"type": "string",
                               "enum": ["VIEW", "PROCEDURE", "FUNCTION"]},
                },
                "required": ["schema", "name", "type"],
            },
        ),
        _trace,
    )


def _apply_definition_policy(obj: dict, include_definition: bool) -> dict:
    definition = obj.get("definition")
    if not isinstance(definition, str) or not definition:
        return obj

    encoded = definition.encode("utf-8")
    digest = hashlib.sha1(encoded).hexdigest()[:8]
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if k == "definition":
            if include_definition:
                out[k] = v
            continue
        out[k] = v
    out["definition_hash"] = digest
    out["definition_bytes"] = len(encoded)
    return out


async def _describe_view(args: dict) -> dict:
    ctx = get_context()
    include = bool(args.get("include_definition", False))
    obj = await object_service.describe_object(
        args["schema"], args["name"], "VIEW", ctx.cfg,
    )
    return _apply_definition_policy(obj, include)


async def _describe_procedure(args: dict) -> dict:
    ctx = get_context()
    include = bool(args.get("include_definition", False))
    obj = await object_service.describe_object(
        args["schema"], args["name"], "PROCEDURE", ctx.cfg,
    )
    return _apply_definition_policy(obj, include)


async def _trace(args: dict) -> list[str]:
    ctx = get_context()
    return await object_service.trace_dependencies(
        args["schema"], args["name"], args["type"], ctx.cfg,
    )
