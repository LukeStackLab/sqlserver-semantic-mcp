from mcp.types import Tool

from ...services import metrics_service
from ..app import get_context, register_tool


def register() -> None:
    register_tool(
        Tool(
            name="get_tool_metrics",
            description=(
                "Return per-tool payload metrics (call_count, total_bytes, "
                "avg_bytes, p95_bytes, max_bytes) ordered by total_bytes desc. "
                "Use to find the heaviest tools for optimization targeting."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "default": 10},
                },
            },
        ),
        _top,
    )
    register_tool(
        Tool(
            name="reset_tool_metrics",
            description="Delete all recorded tool metrics. Returns deleted count.",
            inputSchema={"type": "object", "properties": {}},
        ),
        _reset,
    )


async def _top(args: dict) -> list[dict]:
    ctx = get_context()
    limit = int(args.get("limit", 10))
    return await metrics_service.query_top_tools(ctx.cfg.cache_path, limit=limit)


async def _reset(args: dict) -> dict:
    ctx = get_context()
    n = await metrics_service.clear_metrics(ctx.cfg.cache_path)
    return {"deleted": n}
