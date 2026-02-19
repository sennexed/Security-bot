from __future__ import annotations

import asyncio
import logging

import uvicorn
from dotenv import load_dotenv

from api.app import create_api
from bot.cache import RedisCache
from bot.config import load_settings
from bot.db import Database
from bot.logging import configure_logging
from bot.main import create_bot
from bot.services.analytics import AnalyticsService
from bot.services.security import SecurityService


async def main() -> None:
    load_dotenv()
    settings = load_settings()
    configure_logging(settings.log_level)
    log = logging.getLogger("runner")

    db = Database(settings.postgres_dsn)
    cache = RedisCache(settings.redis_url)

    await db.connect()
    await cache.connect()
    pool = db.require_pool()

    bot = await create_bot(settings, pool, cache)
    analytics = AnalyticsService(pool)
    security = SecurityService(pool, cache, settings)
    api = create_api(analytics, security)

    config = uvicorn.Config(api, host=settings.api_host, port=settings.api_port, log_level=settings.log_level.lower())
    server = uvicorn.Server(config)

    async def run_api() -> None:
        await server.serve()

    async def run_bot() -> None:
        await bot.start(settings.discord_token)

    tasks = [asyncio.create_task(run_api()), asyncio.create_task(run_bot())]

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            exc = task.exception()
            if exc:
                raise exc
        for task in pending:
            task.cancel()
    finally:
        await bot.close()
        await cache.close()
        await db.close()
        log.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
