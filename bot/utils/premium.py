from __future__ import annotations

import asyncpg


class PremiumRequiredError(PermissionError):
    """Raised when a premium-gated feature is used in a non-premium guild."""


async def assert_premium(pool: asyncpg.Pool, guild_id: int) -> None:
    row = await pool.fetchrow(
        """
        SELECT is_premium, premium_until
        FROM guilds
        WHERE guild_id = $1
        """,
        guild_id,
    )
    if not row:
        raise PremiumRequiredError("Guild has no settings record")
    if not row["is_premium"]:
        raise PremiumRequiredError("This feature requires premium")
