from __future__ import annotations

import asyncpg

from bot.utils.premium import assert_premium


class AnalyticsService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def guild_overview(self, guild_id: int) -> dict:
        row = await self.pool.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM invite_joins WHERE guild_id = $1) AS total_joins,
                (SELECT COUNT(*) FROM invite_leaves WHERE guild_id = $1) AS total_leaves,
                (SELECT COUNT(*) FROM incidents WHERE guild_id = $1) AS total_incidents,
                (SELECT COUNT(*) FROM fraud_flags WHERE guild_id = $1) AS total_fraud_flags,
                (SELECT is_premium FROM guilds WHERE guild_id = $1) AS is_premium
            """,
            guild_id,
        )
        return dict(row) if row else {}

    async def guild_invites(self, guild_id: int) -> list[dict]:
        rows = await self.pool.fetch(
            """
            SELECT invite_code, inviter_id, uses, max_uses, is_temporary, created_at, updated_at
            FROM invites
            WHERE guild_id = $1
            ORDER BY uses DESC, updated_at DESC
            """,
            guild_id,
        )
        return [dict(r) for r in rows]

    async def guild_security(self, guild_id: int) -> dict:
        incidents = await self.pool.fetch(
            """
            SELECT incident_type, severity, actor_id, message, metadata, created_at
            FROM incidents
            WHERE guild_id = $1
            ORDER BY created_at DESC
            LIMIT 100
            """,
            guild_id,
        )
        settings = await self.pool.fetchrow(
            """
            SELECT lockdown_enabled, join_burst_count, join_burst_window_seconds,
                   min_account_age_hours, auto_kick_young_accounts,
                   link_spam_threshold, link_spam_window_seconds
            FROM guilds
            WHERE guild_id = $1
            """,
            guild_id,
        )
        return {
            "settings": dict(settings) if settings else {},
            "recent_incidents": [dict(i) for i in incidents],
        }

    async def leaderboard(self, limit: int = 25) -> list[dict]:
        rows = await self.pool.fetch(
            """
            SELECT guild_id, user_id, total_invites, real_invites, fake_invites, leaves, rejoins, bonus_invites,
                   (real_invites + bonus_invites - fake_invites - leaves) AS net_invites
            FROM user_invite_stats
            ORDER BY net_invites DESC, total_invites DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]

    async def incidents(self, limit: int = 200) -> list[dict]:
        rows = await self.pool.fetch(
            """
            SELECT guild_id, incident_type, severity, actor_id, message, metadata, created_at
            FROM incidents
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]

    async def security_analytics(self, guild_id: int) -> dict:
        await assert_premium(self.pool, guild_id)
        row = await self.pool.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM incidents WHERE guild_id = $1 AND created_at > NOW() - INTERVAL '24 hour') AS incidents_24h,
                (SELECT COUNT(*) FROM fraud_flags WHERE guild_id = $1 AND created_at > NOW() - INTERVAL '24 hour') AS fraud_flags_24h,
                (SELECT AVG(score) FROM fraud_flags WHERE guild_id = $1 AND created_at > NOW() - INTERVAL '24 hour') AS avg_fraud_score_24h
            """,
            guild_id,
        )
        return dict(row) if row else {}
