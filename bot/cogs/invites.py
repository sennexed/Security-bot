from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.invite_tracker import InviteTrackerService


class InvitesCog(commands.Cog):
    def __init__(self, bot: commands.Bot, tracker: InviteTrackerService) -> None:
        self.bot = bot
        self.tracker = tracker

    @app_commands.command(name="invites", description="View invite stats for yourself or another user")
    @app_commands.describe(user="Optional member to inspect")
    async def invites(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        target = user or interaction.user
        stats = await self.tracker.get_user_stats(interaction.guild.id, target.id)
        if not stats:
            await interaction.response.send_message(f"No invite stats for {target.mention} yet.", ephemeral=True)
            return

        embed = discord.Embed(title=f"Invite Stats: {target}", color=discord.Color.blurple())
        embed.add_field(name="Total", value=str(stats["total_invites"]), inline=True)
        embed.add_field(name="Real", value=str(stats["real_invites"]), inline=True)
        embed.add_field(name="Fake", value=str(stats["fake_invites"]), inline=True)
        embed.add_field(name="Leaves", value=str(stats["leaves"]), inline=True)
        embed.add_field(name="Rejoins", value=str(stats["rejoins"]), inline=True)
        embed.add_field(name="Bonus", value=str(stats["bonus_invites"]), inline=True)
        embed.add_field(name="Net", value=str(stats["net_invites"]), inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Show top inviters")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        rows = await self.tracker.leaderboard(interaction.guild.id, limit=10)
        if not rows:
            await interaction.response.send_message("No invite data yet.", ephemeral=True)
            return

        lines = []
        for idx, row in enumerate(rows, start=1):
            member = interaction.guild.get_member(row["user_id"])
            name = member.mention if member else f"<@{row['user_id']}>"
            lines.append(
                f"`#{idx}` {name} | Net: **{row['net_invites']}** | Total: {row['total_invites']} "
                f"(R:{row['real_invites']} F:{row['fake_invites']} L:{row['leaves']} B:{row['bonus_invites']})"
            )

        embed = discord.Embed(title="Invite Leaderboard", description="\n".join(lines), color=discord.Color.green())
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot, tracker: InviteTrackerService) -> None:
    await bot.add_cog(InvitesCog(bot, tracker))
