from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import asyncpg


class PremiumService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    async def premium_status(self, guild_id: int) -> asyncpg.Record | None:
        return await self.pool.fetchrow(
            """
            SELECT is_premium, premium_until, premium_license_id
            FROM guilds
            WHERE guild_id = $1
            """,
            guild_id,
        )

    async def activate_license(self, guild_id: int, raw_key: str, actor_id: int) -> bool:
        key_hash = self._hash_key(raw_key)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                lic = await conn.fetchrow(
                    """
                    SELECT id, is_active, max_guilds, expires_at,
                           COALESCE(array_length(activated_guild_ids, 1), 0) AS used_count,
                           activated_guild_ids
                    FROM premium_licenses
                    WHERE key_hash = $1
                    FOR UPDATE
                    """,
                    key_hash,
                )

                if not lic or not lic["is_active"]:
                    return False

                expires = lic["expires_at"]
                if expires and expires < datetime.now(timezone.utc):
                    return False

                activated = list(lic["activated_guild_ids"] or [])
                if guild_id not in activated and len(activated) >= lic["max_guilds"]:
                    return False

                if guild_id not in activated:
                    activated.append(guild_id)
                    await conn.execute(
                        """
                        UPDATE premium_licenses
                        SET activated_guild_ids = $2,
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                        lic["id"],
                        activated,
                    )

                await conn.execute(
                    """
                    UPDATE guilds
                    SET is_premium = TRUE,
                        premium_license_id = $2,
                        premium_until = $3,
                        updated_at = NOW()
                    WHERE guild_id = $1
                    """,
                    guild_id,
                    lic["id"],
                    expires,
                )

                await conn.execute(
                    """
                    INSERT INTO incidents (guild_id, incident_type, severity, actor_id, message, metadata)
                    VALUES ($1, 'premium_activated', 'low', $2, 'Premium license activated', $3::jsonb)
                    """,
                    guild_id,
                    actor_id,
                    {"license_id": lic["id"]},
                )

                return True
