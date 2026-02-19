from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import asyncpg
import discord

from bot.cache import RedisCache
from bot.config import Settings
from bot.utils.locks import GuildLockManager

log = logging.getLogger(__name__)


@dataclass
class InviteAttribution:
    invite_code: str | None
    inviter_id: int | None
    confidence: float
    reason: str


class InviteTrackerService:
    def __init__(
        self,
        pool: asyncpg.Pool,
        cache: RedisCache,
        settings: Settings,
        lock_manager: GuildLockManager,
    ) -> None:
        self.pool = pool
        self.cache = cache
        self.settings = settings
        self.lock_manager = lock_manager

    @staticmethod
    def _snapshot_key(guild_id: int) -> str:
        return f"invite:snapshot:{guild_id}"

    async def ensure_guild_row(self, guild: discord.Guild) -> None:
        await self.pool.execute(
            """
            INSERT INTO guilds (
                guild_id,
                guild_name,
                join_burst_count,
                join_burst_window_seconds,
                min_account_age_hours,
                auto_kick_young_accounts,
                link_spam_threshold,
                link_spam_window_seconds,
                lockdown_slowmode_seconds,
                quarantine_role_name
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (guild_id) DO UPDATE
                SET guild_name = EXCLUDED.guild_name,
                    updated_at = NOW()
            """,
            guild.id,
            guild.name,
            self.settings.default_join_burst_count,
            self.settings.default_join_burst_window_seconds,
            self.settings.default_min_account_age_hours,
            self.settings.default_auto_kick_young_accounts,
            self.settings.default_link_spam_threshold,
            self.settings.default_link_spam_window_seconds,
            self.settings.default_lockdown_slowmode_seconds,
            self.settings.default_quarantine_role_name,
        )

    async def rebuild_guild_snapshot(self, guild: discord.Guild) -> None:
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            log.warning("Missing permissions to read invites for guild=%s", guild.id)
            return

        snapshot = {}
        for inv in invites:
            snapshot[inv.code] = {
                "uses": inv.uses or 0,
                "inviter_id": inv.inviter.id if inv.inviter else None,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
                "max_uses": inv.max_uses,
                "temporary": inv.temporary,
            }

        await self.cache.set_json(self._snapshot_key(guild.id), snapshot)

    async def rebuild_all_snapshots(self, guilds: list[discord.Guild]) -> None:
        for guild in guilds:
            await self.ensure_guild_row(guild)
            await self.rebuild_guild_snapshot(guild)

    async def on_invite_create(self, invite: discord.Invite) -> None:
        if not invite.guild:
            return
        key = self._snapshot_key(invite.guild.id)
        snapshot = await self.cache.get_json(key) or {}
        snapshot[invite.code] = {
            "uses": invite.uses or 0,
            "inviter_id": invite.inviter.id if invite.inviter else None,
            "created_at": invite.created_at.isoformat() if invite.created_at else None,
            "max_uses": invite.max_uses,
            "temporary": invite.temporary,
        }
        await self.cache.set_json(key, snapshot)

        await self.pool.execute(
            """
            INSERT INTO invites (guild_id, invite_code, inviter_id, uses, max_uses, is_temporary, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, NOW()))
            ON CONFLICT (guild_id, invite_code)
            DO UPDATE SET inviter_id = EXCLUDED.inviter_id,
                          uses = EXCLUDED.uses,
                          max_uses = EXCLUDED.max_uses,
                          is_temporary = EXCLUDED.is_temporary,
                          deleted_at = NULL,
                          updated_at = NOW()
            """,
            invite.guild.id,
            invite.code,
            invite.inviter.id if invite.inviter else None,
            invite.uses or 0,
            invite.max_uses,
            invite.temporary,
            invite.created_at,
        )

    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if not invite.guild:
            return
        key = self._snapshot_key(invite.guild.id)
        snapshot = await self.cache.get_json(key) or {}
        snapshot.pop(invite.code, None)
        await self.cache.set_json(key, snapshot)

        await self.pool.execute(
            """
            UPDATE invites
            SET deleted_at = NOW(), updated_at = NOW()
            WHERE guild_id = $1 AND invite_code = $2
            """,
            invite.guild.id,
            invite.code,
        )

    async def _fetch_current_invites(self, guild: discord.Guild) -> dict[str, dict]:
        invites = await guild.invites()
        current = {}
        for inv in invites:
            current[inv.code] = {
                "uses": inv.uses or 0,
                "inviter_id": inv.inviter.id if inv.inviter else None,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
                "max_uses": inv.max_uses,
                "temporary": inv.temporary,
            }
        return current

    async def _detect_used_invite(self, guild: discord.Guild, current: dict[str, dict]) -> InviteAttribution:
        previous = await self.cache.get_json(self._snapshot_key(guild.id)) or {}

        increased = []
        for code, now_val in current.items():
            old_uses = previous.get(code, {}).get("uses", 0)
            delta = now_val["uses"] - old_uses
            if delta > 0:
                increased.append((code, delta, now_val.get("inviter_id")))

        if not increased:
            return InviteAttribution(None, None, 0.2, "no_invite_delta")

        increased.sort(key=lambda x: x[1], reverse=True)
        winner = increased[0]
        if len(increased) == 1:
            return InviteAttribution(winner[0], winner[2], 0.96, "single_delta")

        confidence = max(0.45, 0.75 - ((len(increased) - 1) * 0.08))
        return InviteAttribution(winner[0], winner[2], confidence, "multi_delta")

    async def _upsert_user(self, user: discord.abc.User) -> None:
        await self.pool.execute(
            """
            INSERT INTO users (user_id, username, discriminator)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id)
            DO UPDATE SET username = EXCLUDED.username,
                          discriminator = EXCLUDED.discriminator,
                          updated_at = NOW()
            """,
            user.id,
            str(user),
            getattr(user, "discriminator", "0"),
        )

    async def _update_invite_stats(
        self,
        guild_id: int,
        inviter_id: int,
        is_fake: bool,
        is_rejoin: bool,
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO user_invite_stats (guild_id, user_id, total_invites, fake_invites, real_invites, rejoins)
            VALUES ($1, $2, 1, $3, $4, $5)
            ON CONFLICT (guild_id, user_id)
            DO UPDATE SET total_invites = user_invite_stats.total_invites + 1,
                          fake_invites = user_invite_stats.fake_invites + $3,
                          real_invites = user_invite_stats.real_invites + $4,
                          rejoins = user_invite_stats.rejoins + $5,
                          updated_at = NOW()
            """,
            guild_id,
            inviter_id,
            1 if is_fake else 0,
            0 if is_fake else 1,
            1 if is_rejoin else 0,
        )

    async def on_member_join(self, member: discord.Member) -> InviteAttribution:
        lock = self.lock_manager.get(member.guild.id)
        async with lock:
            now = datetime.now(timezone.utc)
            await self.ensure_guild_row(member.guild)
            await self._upsert_user(member)

            current = await self._fetch_current_invites(member.guild)
            attribution = await self._detect_used_invite(member.guild, current)
            await self.cache.set_json(self._snapshot_key(member.guild.id), current)

            settings_row = await self.pool.fetchrow(
                "SELECT min_account_age_hours FROM guilds WHERE guild_id = $1", member.guild.id
            )
            min_age = settings_row["min_account_age_hours"] if settings_row else self.settings.default_min_account_age_hours
            age_hours = max(0.0, (now - member.created_at).total_seconds() / 3600)
            is_fake = age_hours < min_age

            prior_leave = await self.pool.fetchrow(
                """
                SELECT id FROM invite_leaves
                WHERE guild_id = $1 AND member_id = $2
                ORDER BY left_at DESC
                LIMIT 1
                """,
                member.guild.id,
                member.id,
            )
            is_rejoin = prior_leave is not None

            await self.pool.execute(
                """
                INSERT INTO invite_joins (
                    guild_id,
                    member_id,
                    invite_code,
                    inviter_id,
                    joined_at,
                    attribution_confidence,
                    attribution_reason,
                    is_fake,
                    is_rejoin
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                member.guild.id,
                member.id,
                attribution.invite_code,
                attribution.inviter_id,
                now,
                attribution.confidence,
                attribution.reason,
                is_fake,
                is_rejoin,
            )

            if attribution.inviter_id:
                await self._update_invite_stats(
                    member.guild.id,
                    attribution.inviter_id,
                    is_fake,
                    is_rejoin,
                )

            if attribution.invite_code:
                await self.pool.execute(
                    """
                    INSERT INTO invites (guild_id, invite_code, inviter_id, uses)
                    VALUES ($1, $2, $3, 1)
                    ON CONFLICT (guild_id, invite_code)
                    DO UPDATE SET inviter_id = COALESCE(EXCLUDED.inviter_id, invites.inviter_id),
                                  uses = invites.uses + 1,
                                  updated_at = NOW()
                    """,
                    member.guild.id,
                    attribution.invite_code,
                    attribution.inviter_id,
                )

            if is_fake:
                score = round(min(1.0, (min_age - age_hours) / max(1.0, float(min_age))), 4)
                await self.pool.execute(
                    """
                    INSERT INTO fraud_flags (guild_id, member_id, reason, score, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    """,
                    member.guild.id,
                    member.id,
                    "young_account",
                    score,
                    {
                        "age_hours": age_hours,
                        "min_required_hours": min_age,
                    },
                )

            return attribution

    async def on_member_remove(self, member: discord.Member) -> None:
        row = await self.pool.fetchrow(
            """
            SELECT id, inviter_id
            FROM invite_joins
            WHERE guild_id = $1 AND member_id = $2
            ORDER BY joined_at DESC
            LIMIT 1
            """,
            member.guild.id,
            member.id,
        )
        inviter_id = row["inviter_id"] if row else None

        await self.pool.execute(
            """
            INSERT INTO invite_leaves (guild_id, member_id, inviter_id, left_at)
            VALUES ($1, $2, $3, NOW())
            """,
            member.guild.id,
            member.id,
            inviter_id,
        )

        if inviter_id:
            await self.pool.execute(
                """
                INSERT INTO user_invite_stats (guild_id, user_id, leaves)
                VALUES ($1, $2, 1)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET leaves = user_invite_stats.leaves + 1,
                              updated_at = NOW()
                """,
                member.guild.id,
                inviter_id,
            )

    async def add_bonus_invites(self, guild_id: int, user_id: int, amount: int, reason: str) -> None:
        if amount == 0:
            return
        await self.pool.execute(
            """
            INSERT INTO bonus_invites (guild_id, user_id, amount, reason)
            VALUES ($1, $2, $3, $4)
            """,
            guild_id,
            user_id,
            amount,
            reason,
        )
        await self.pool.execute(
            """
            INSERT INTO user_invite_stats (guild_id, user_id, bonus_invites)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id)
            DO UPDATE SET bonus_invites = user_invite_stats.bonus_invites + $3,
                          updated_at = NOW()
            """,
            guild_id,
            user_id,
            amount,
        )

    async def get_user_stats(self, guild_id: int, user_id: int) -> asyncpg.Record | None:
        return await self.pool.fetchrow(
            """
            SELECT guild_id, user_id, total_invites, real_invites, fake_invites, leaves, rejoins, bonus_invites,
                   (real_invites + bonus_invites - fake_invites - leaves) AS net_invites
            FROM user_invite_stats
            WHERE guild_id = $1 AND user_id = $2
            """,
            guild_id,
            user_id,
        )

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            """
            SELECT user_id, total_invites, real_invites, fake_invites, leaves, rejoins, bonus_invites,
                   (real_invites + bonus_invites - fake_invites - leaves) AS net_invites
            FROM user_invite_stats
            WHERE guild_id = $1
            ORDER BY net_invites DESC, total_invites DESC
            LIMIT $2
            """,
            guild_id,
            limit,
        )
