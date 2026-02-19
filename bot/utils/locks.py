from __future__ import annotations

import asyncio
from collections import defaultdict


class GuildLockManager:
    def __init__(self) -> None:
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get(self, guild_id: int) -> asyncio.Lock:
        return self._locks[guild_id]
