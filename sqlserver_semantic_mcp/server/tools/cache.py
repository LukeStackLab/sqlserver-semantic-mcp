from mcp.types import Tool

from ...infrastructure.cache import revalidation
from ...infrastructure.cache.structural import warmup_structural_cache
from ..app import get_context, register_tool


def register() -> None:
    register_tool(
        Tool(
            name="refresh_schema_cache",
            description=(
                "Re-fetch structural metadata from SQL Server and update SQLite cache. "
                "Semantic rows whose hash changed become 'dirty' and will recompute."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        _refresh,
    )


async def _refresh(args: dict) -> dict:
    ctx = get_context()
    result = await warmup_structural_cache(ctx.cfg)
    revalidation.note_refreshed(ctx.cfg)
    return {"refreshed": True, **result}
