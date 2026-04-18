import json
import logging
from typing import Any, Awaitable, Callable

from mcp.server import Server
from mcp.types import Tool, TextContent

from ..config import Config, get_config
from ..services import metrics_service
from ..services.policy_service import PolicyService
from ..services.query_service import QueryService
from .compact import compact

logger = logging.getLogger(__name__)


class Context:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.policy = PolicyService(cfg)
        self.query = QueryService(self.policy, cfg)


_ctx: Context | None = None


def get_context() -> Context:
    global _ctx
    if _ctx is None:
        _ctx = Context(get_config())
        _ctx.policy.load()
    return _ctx


def reset_context() -> None:
    global _ctx
    _ctx = None


app = Server("sqlserver-semantic-mcp")

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]
_TOOL_REGISTRY: dict[str, tuple[Tool, ToolHandler]] = {}


def register_tool(tool: Tool, handler: ToolHandler) -> None:
    _TOOL_REGISTRY[tool.name] = (tool, handler)


@app.list_tools()
async def _list_tools() -> list[Tool]:
    return [t for (t, _) in _TOOL_REGISTRY.values()]


@app.call_tool()
async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name not in _TOOL_REGISTRY:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    _t, handler = _TOOL_REGISTRY[name]
    try:
        result = await handler(arguments or {})
        shaped = compact(result)
        text = json.dumps(
            shaped, ensure_ascii=False, default=str, separators=(",", ":"),
        )
        if get_config().metrics_enabled:
            try:
                await metrics_service.record_metric(
                    get_config().cache_path, name,
                    response_bytes=len(text.encode("utf-8")),
                    array_length=len(shaped) if isinstance(shaped, list) else None,
                    fields_returned=len(shaped) if isinstance(shaped, dict) else None,
                )
            except Exception:
                logger.exception("metrics_service.record_metric failed")
        return [TextContent(type="text", text=text)]
    except Exception as e:
        logger.exception("Tool %s raised", name)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
