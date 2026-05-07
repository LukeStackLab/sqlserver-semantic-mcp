import asyncio
import logging

from mcp.server.stdio import stdio_server

from .config import get_config
from .infrastructure.background import background_fill_loop
from .infrastructure.cache.semantic import enqueue_all_tables
from .infrastructure.cache.store import init_store
from .infrastructure.cache.structural import (
    read_schema_version, warmup_structural_cache,
)
from .server.app import app, get_context
from .server import resources  # noqa: F401
from .server.prompts import register_prompts
from .server.tools import register_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("sqlserver_semantic_mcp")


async def _startup() -> asyncio.Task | None:
    cfg = get_config()
    logger.info(
        "Starting sqlserver-semantic-mcp against %s/%s",
        cfg.mssql_server, cfg.mssql_database,
    )

    await init_store(cfg.cache_path)

    bg_task: asyncio.Task | None = None
    if cfg.cache_enabled:
        existing = await read_schema_version(cfg.cache_path, cfg.mssql_database)
        should_warmup = (
            cfg.startup_mode == "full"
            or existing is None
        )
        if should_warmup:
            if existing is None:
                logger.info("No cache found; running structural warmup")
            else:
                logger.info(
                    "Startup mode '%s' requires a fresh structural warmup "
                    "(cached_at=%s)",
                    cfg.startup_mode,
                    existing["captured_at"],
                )
            result = await warmup_structural_cache(cfg)
            structural_hash = result["structural_hash"]
        else:
            logger.info(
                "Startup mode '%s' reuses existing cache (captured_at=%s)",
                cfg.startup_mode,
                existing["captured_at"],
            )
            structural_hash = existing["structural_hash"]
        await enqueue_all_tables(
            cfg.cache_path, cfg.mssql_database, structural_hash,
        )
        bg_task = asyncio.create_task(background_fill_loop(cfg))

    register_all()
    register_prompts()
    get_context()
    return bg_task


async def _run() -> None:
    bg_task = await _startup()
    try:
        async with stdio_server() as (r, w):
            await app.run(r, w, app.create_initialization_options())
    finally:
        if bg_task is not None:
            bg_task.cancel()
            try:
                await bg_task
            except (asyncio.CancelledError, Exception):
                pass


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
