from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.security import SecurityService
from bot.utils.premium import PremiumRequiredError


class SecurityCog(commands.Cog):
    def __init__(self, bot: commands.Bot, security: SecurityService) -> None:
        self.bot = bot
        self.security = security

    security_group = app_commands.Group(name="security", description="Security controls")

    @security_group.command(name="status", description="View security status")
    async def status(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return

        settings = await self.security.get_guild_settings(interaction.guild.id)
        if not settings:
            await interaction.response.send_message("Guild settings not initialized yet.", ephemeral=True)
            return

        embed = discord.Embed(title="Security Status", color=discord.Color.orange())
        embed.add_field(name="Lockdown", value=str(bool(settings["lockdown_enabled"])), inline=True)
        embed.add_field(
            name="Join Burst",
            value=f"{settings['join_burst_count']} joins/{settings['join_burst_window_seconds']}s",
            inline=True,
        )
        embed.add_field(name="Min Account Age", value=f"{settings['min_account_age_hours']}h", inline=True)
        embed.add_field(name="Auto-kick Young", value=str(bool(settings["auto_kick_young_accounts"])), inline=True)
        embed.add_field(
            name="Link Spam",
            value=f"{settings['link_spam_threshold']} links/{settings['link_spam_window_seconds']}s",
            inline=True,
        )
        log_ch = settings["security_log_channel_id"]
        embed.add_field(name="Log Channel", value=f"<#{log_ch}>" if log_ch else "Not set", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="lockdown", description="Enable lockdown mode")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def lockdown(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.security.set_lockdown(interaction.guild, True)
        await interaction.followup.send("Lockdown enabled.", ephemeral=True)

    @security_group.command(name="unlock", description="Disable lockdown mode")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def unlock(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.security.set_lockdown(interaction.guild, False)
        await interaction.followup.send("Lockdown disabled.", ephemeral=True)

    @security_group.command(name="setlog", description="Set security log channel")
    @app_commands.describe(channel="Channel for security event logs")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setlog(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        await self.security.set_log_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"Security log channel set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="raidprediction", description="Premium: get raid risk forecast")
    async def raidprediction(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        try:
            prediction = await self.security.advanced_raid_prediction(interaction.guild.id)
        except PremiumRequiredError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.send_message(
            f"Risk: **{prediction['risk']}** | Score: {prediction['score']} | Incidents (1h): {prediction['incidents_last_hour']}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot, security: SecurityService) -> None:
    cog = SecurityCog(bot, security)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.security_group)
