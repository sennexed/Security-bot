from __future__ import annotations

import logging

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

from bot.cache import RedisCache
from bot.cogs.invites import InvitesCog
from bot.cogs.premium import PremiumCog
from bot.cogs.security import SecurityCog
from bot.config import Settings
from bot.services.analytics import AnalyticsService
from bot.services.invite_tracker import InviteTrackerService
from bot.services.premium import PremiumService
from bot.services.security import SecurityService
from bot.utils.locks import GuildLockManager

log = logging.getLogger(__name__)


class InviteSecurityBot(commands.AutoShardedBot):
    def __init__(
        self,
        settings: Settings,
        pool: asyncpg.Pool,
        cache: RedisCache,
    ) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            application_id=settings.application_id,
        )

        self.settings = settings
        self.pool = pool
        self.cache = cache

        self.locks = GuildLockManager()
        self.invite_tracker = InviteTrackerService(pool, cache, settings, self.locks)
        self.security = SecurityService(pool, cache, settings)
        self.premium = PremiumService(pool)
        self.analytics = AnalyticsService(pool)

        self._synced = False

async def setup_hook(self) -> None:
        await self.add_cog(InvitesCog(self, self.invite_tracker))
        await self.add_cog(SecurityCog(self, self.security))
        await self.add_cog(PremiumCog(self, self.premium))

        await self.tree.sync()

    async def on_ready(self) -> None:
        if not self._synced:
            await self.tree.sync()
            self._synced = True
            log.info("Slash commands synced")

        log.info("Bot ready: %s (%s)", self.user, self.user.id if self.user else "n/a")
        await self.invite_tracker.rebuild_all_snapshots(self.guilds)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.invite_tracker.ensure_guild_row(guild)
        await self.invite_tracker.rebuild_guild_snapshot(guild)

    async def on_invite_create(self, invite: discord.Invite) -> None:
        await self.invite_tracker.on_invite_create(invite)
        if invite.guild and await self.security.is_lockdown(invite.guild.id):
            try:
                await invite.delete(reason="Invite blocked during lockdown")
                await self.security.log_incident(
                    invite.guild.id,
                    "invite_blocked_lockdown",
                    "high",
                    f"Invite {invite.code} blocked during lockdown",
                    actor_id=invite.inviter.id if invite.inviter else None,
                )
            except discord.Forbidden:
                log.warning("Unable to delete invite during lockdown in guild=%s", invite.guild.id)

    async def on_invite_delete(self, invite: discord.Invite) -> None:
        await self.invite_tracker.on_invite_delete(invite)

    async def on_member_join(self, member: discord.Member) -> None:
        attribution = await self.invite_tracker.on_member_join(member)
        await self.security.apply_quarantine_if_lockdown(member)

        burst = await self.security.check_join_burst(member.guild.id)
        if burst:
            await self.security.log_incident(
                member.guild.id,
                "join_burst_detected",
                "critical",
                f"Join burst threshold exceeded in guild {member.guild.id}",
                metadata={"new_member": member.id},
            )
            await self.security.post_security_log(
                member.guild,
                "[SECURITY] Join burst detected. Consider immediate lockdown.",
            )

        await self.security.enforce_account_age(member)
        await self.security.check_cross_server_blacklist(member)

        if attribution.inviter_id:
            await self.security.post_security_log(
                member.guild,
                f"[INVITE] <@{member.id}> joined via `{attribution.invite_code}` from <@{attribution.inviter_id}> "
                f"(confidence {attribution.confidence:.2f}).",
            )

    async def on_member_remove(self, member: discord.Member) -> None:
        await self.invite_tracker.on_member_remove(member)

    async def on_message(self, message: discord.Message) -> None:
        await self.security.handle_link_spam(message)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        log.exception("Slash command error", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send(f"Error: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"Error: {error}", ephemeral=True)


async def create_bot(settings: Settings, pool: asyncpg.Pool, cache: RedisCache) -> InviteSecurityBot:
    return InviteSecurityBot(settings, pool, cache)
