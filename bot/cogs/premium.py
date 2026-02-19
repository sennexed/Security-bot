from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.premium import PremiumService


class PremiumCog(commands.Cog):
    premium_group = app_commands.Group(name="premium", description="Premium license management")

    def __init__(self, bot: commands.Bot, premium: PremiumService) -> None:
        self.bot = bot
        self.premium = premium

    @premium_group.command(name="status", description="View premium status")
    async def status(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return

        status = await self.premium.premium_status(interaction.guild.id)
        if not status:
            await interaction.response.send_message("Guild not initialized yet.", ephemeral=True)
            return

        active = bool(status["is_premium"])
        until = status["premium_until"]
        until_text = until.isoformat() if until else "No expiration"
        await interaction.response.send_message(
            f"Premium: **{active}**\nExpires: **{until_text}**",
            ephemeral=True,
        )

    @premium_group.command(name="activate", description="Activate a premium key")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(license_key="Premium license key")
    async def activate(self, interaction: discord.Interaction, license_key: str) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return

        ok = await self.premium.activate_license(interaction.guild.id, license_key, interaction.user.id)
        if not ok:
            await interaction.response.send_message("License activation failed.", ephemeral=True)
            return

        await interaction.response.send_message("Premium activated for this guild.", ephemeral=True)


async def setup(bot: commands.Bot, premium: PremiumService) -> None:
    cog = PremiumCog(bot, premium)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.premium_group)
