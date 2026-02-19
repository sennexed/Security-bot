from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import asyncpg
import discord

from bot.cache import RedisCache
from bot.config import Settings
from bot.utils.premium import PremiumRequiredError, assert_premium

log = logging.getLogger(__name__)
LINK_RE = re.compile(r"https?://|discord\.gg/", re.IGNORECASE)


class SecurityService:
    def __init__(self, pool: asyncpg.Pool, cache: RedisCache, settings: Settings) -> None:
        self.pool = pool
        self.cache = cache
        self.settings = settings

    async def get_guild_settings(self, guild_id: int) -> asyncpg.Record | None:
        return await self.pool.fetchrow("SELECT * FROM guilds WHERE guild_id = $1", guild_id)

    async def is_lockdown(self, guild_id: int) -> bool:
        row = await self.pool.fetchrow("SELECT lockdown_enabled FROM guilds WHERE guild_id = $1", guild_id)
        return bool(row and row["lockdown_enabled"])

    async def log_incident(
        self,
        guild_id: int,
        incident_type: str,
        severity: str,
        message: str,
        actor_id: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO incidents (guild_id, incident_type, severity, actor_id, message, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            guild_id,
            incident_type,
            severity,
            actor_id,
            message,
            metadata or {},
        )

    async def post_security_log(self, guild: discord.Guild, content: str) -> None:
        row = await self.pool.fetchrow(
            "SELECT security_log_channel_id FROM guilds WHERE guild_id = $1", guild.id
        )
        if not row or not row["security_log_channel_id"]:
            return
        channel = guild.get_channel(row["security_log_channel_id"])
        if channel and isinstance(channel, discord.TextChannel):
            try:
                await channel.send(content)
            except discord.HTTPException:
                log.exception("Failed posting security log for guild=%s", guild.id)

    async def check_join_burst(self, guild_id: int) -> bool:
        settings = await self.get_guild_settings(guild_id)
        if not settings:
            return False

        now = datetime.now(timezone.utc).timestamp()
        key = f"security:joins:{guild_id}"
        window = int(settings["join_burst_window_seconds"])
        threshold = int(settings["join_burst_count"])

        redis = self.cache.require_client()
        pipe = redis.pipeline()
        pipe.zadd(key, {str(now): now})
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zcard(key)
        pipe.expire(key, max(window, 60))
        _, _, count, _ = await pipe.execute()

        return int(count) >= threshold

    async def enforce_account_age(self, member: discord.Member) -> bool:
        settings = await self.get_guild_settings(member.guild.id)
        if not settings:
            return False
        min_age_hours = settings["min_account_age_hours"]
        auto_kick = settings["auto_kick_young_accounts"]
        age_hours = (datetime.now(timezone.utc) - member.created_at).total_seconds() / 3600

        if age_hours >= min_age_hours:
            return False

        await self.log_incident(
            member.guild.id,
            "young_account_detected",
            "medium",
            f"User {member.id} account age {age_hours:.1f}h below threshold {min_age_hours}h",
            actor_id=member.id,
            metadata={"age_hours": age_hours, "required_hours": min_age_hours},
        )

        if auto_kick:
            try:
                await member.kick(reason="Account too new during security policy enforcement")
                await self.log_incident(
                    member.guild.id,
                    "young_account_kicked",
                    "high",
                    f"Auto-kicked user {member.id} for young account",
                    actor_id=member.id,
                )
                await self.post_security_log(
                    member.guild,
                    f"[SECURITY] Auto-kicked <@{member.id}> for account age below threshold.",
                )
                return True
            except discord.Forbidden:
                log.warning("Missing permission to kick member=%s", member.id)
        return False

    async def apply_quarantine_if_lockdown(self, member: discord.Member) -> None:
        if not await self.is_lockdown(member.guild.id):
            return
        settings = await self.get_guild_settings(member.guild.id)
        if not settings:
            return
        role_name = settings["quarantine_role_name"] or self.settings.default_quarantine_role_name
        role = discord.utils.get(member.guild.roles, name=role_name)
        if role:
            try:
                await member.add_roles(role, reason="Lockdown quarantine")
            except discord.Forbidden:
                log.warning("Cannot assign quarantine role in guild=%s", member.guild.id)

    async def handle_link_spam(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        if not LINK_RE.search(message.content):
            return

        settings = await self.get_guild_settings(message.guild.id)
        if not settings:
            return

        window = int(settings["link_spam_window_seconds"])
        threshold = int(settings["link_spam_threshold"])

        key = f"security:links:{message.guild.id}:{message.author.id}"
        now = datetime.now(timezone.utc).timestamp()

        redis = self.cache.require_client()
        pipe = redis.pipeline()
        pipe.zadd(key, {str(now): now})
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zcard(key)
        pipe.expire(key, max(window, 60))
        _, _, count, _ = await pipe.execute()

        if int(count) < threshold:
            return

        if isinstance(message.author, discord.Member):
            timeout_until = datetime.now(timezone.utc) + timedelta(minutes=self.settings.security_timeout_minutes)
            try:
                await message.author.edit(
                    timed_out_until=timeout_until,
                    reason="Repeated link spam detected",
                )
                await self.log_incident(
                    message.guild.id,
                    "link_spam_timeout",
                    "high",
                    f"Timed out user {message.author.id} after repeated links",
                    actor_id=message.author.id,
                    metadata={"message_id": message.id, "count": int(count)},
                )
                await self.post_security_log(
                    message.guild,
                    f"[SECURITY] Timed out <@{message.author.id}> for repeated link spam.",
                )
            except discord.Forbidden:
                log.warning("Unable to timeout user=%s", message.author.id)

    async def set_log_channel(self, guild_id: int, channel_id: int) -> None:
        await self.pool.execute(
            "UPDATE guilds SET security_log_channel_id = $2, updated_at = NOW() WHERE guild_id = $1",
            guild_id,
            channel_id,
        )

    async def set_lockdown(self, guild: discord.Guild, enabled: bool) -> None:
        await self.pool.execute(
            "UPDATE guilds SET lockdown_enabled = $2, updated_at = NOW() WHERE guild_id = $1",
            guild.id,
            enabled,
        )

        if enabled:
            await self._enable_lockdown_controls(guild)
            await self.log_incident(guild.id, "lockdown_enabled", "critical", "Lockdown enabled")
            await self.post_security_log(guild, "[SECURITY] Lockdown enabled.")
        else:
            await self._disable_lockdown_controls(guild)
            await self.log_incident(guild.id, "lockdown_disabled", "medium", "Lockdown disabled")
            await self.post_security_log(guild, "[SECURITY] Lockdown disabled.")

    async def _enable_lockdown_controls(self, guild: discord.Guild) -> None:
        settings = await self.get_guild_settings(guild.id)
        if not settings:
            return

        slowmode = int(settings["lockdown_slowmode_seconds"])
        redis = self.cache.require_client()
        previous_slowmodes: dict[str, int] = {}

        for channel in guild.text_channels:
            previous_slowmodes[str(channel.id)] = channel.slowmode_delay
            try:
                await channel.edit(slowmode_delay=slowmode, reason="Security lockdown enabled")
            except discord.Forbidden:
                log.warning("Cannot set slowmode for channel=%s", channel.id)

        await self.cache.set_json(f"security:slowmode_backup:{guild.id}", previous_slowmodes, ex=86400)

        try:
            invites = await guild.invites()
            for inv in invites:
                try:
                    await inv.delete(reason="Security lockdown enabled")
                except discord.Forbidden:
                    log.warning("Cannot delete invite=%s in guild=%s", inv.code, guild.id)
        except discord.Forbidden:
            log.warning("Cannot list invites during lockdown for guild=%s", guild.id)

    async def _disable_lockdown_controls(self, guild: discord.Guild) -> None:
        backup = await self.cache.get_json(f"security:slowmode_backup:{guild.id}") or {}
        for channel in guild.text_channels:
            desired = int(backup.get(str(channel.id), 0))
            if channel.slowmode_delay == desired:
                continue
            try:
                await channel.edit(slowmode_delay=desired, reason="Security lockdown disabled")
            except discord.Forbidden:
                log.warning("Cannot restore slowmode for channel=%s", channel.id)

    async def advanced_raid_prediction(self, guild_id: int) -> dict:
        await assert_premium(self.pool, guild_id)
        incidents = await self.pool.fetch(
            """
            SELECT severity, created_at
            FROM incidents
            WHERE guild_id = $1
              AND created_at > NOW() - INTERVAL '1 hour'
            """,
            guild_id,
        )
        weight = {"low": 1, "medium": 2, "high": 4, "critical": 7}
        score = sum(weight.get(r["severity"], 1) for r in incidents)
        prediction = "high" if score >= 20 else "medium" if score >= 10 else "low"
        return {"risk": prediction, "score": score, "incidents_last_hour": len(incidents)}

    async def check_cross_server_blacklist(self, member: discord.Member) -> bool:
        try:
            await assert_premium(self.pool, member.guild.id)
        except PremiumRequiredError:
            return False

        row = await self.pool.fetchrow(
            """
            SELECT id
            FROM fraud_flags
            WHERE member_id = $1
              AND reason = 'cross_server_blacklist'
            LIMIT 1
            """,
            member.id,
        )
        if not row:
            return False

        await self.log_incident(
            member.guild.id,
            "cross_server_blacklist_hit",
            "critical",
            f"Member {member.id} matched cross-server blacklist",
            actor_id=member.id,
        )
        await self.post_security_log(
            member.guild,
            f"[SECURITY] Blacklist match for <@{member.id}>. Review recommended.",
        )
        return True

    async def invite_fraud_scoring(self, guild_id: int) -> list[asyncpg.Record]:
        await assert_premium(self.pool, guild_id)
        return await self.pool.fetch(
            """
            SELECT member_id,
                   AVG(score) AS avg_score,
                   COUNT(*) AS flags
            FROM fraud_flags
            WHERE guild_id = $1
            GROUP BY member_id
            ORDER BY avg_score DESC, flags DESC
            LIMIT 50
            """,
            guild_id,
        )
