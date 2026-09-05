import discord
from discord.ext import commands
from discord import app_commands

from db.connection import get_pool


class LevelView(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mylevel", description="View your current level and EXP progress.")
    async def mylevel(self, interaction: discord.Interaction):

        pool = get_pool()
        guild_id = interaction.guild.id

        async with pool.acquire() as conn:


            user = await conn.fetchrow(
                """
                SELECT exp, level
                FROM users
                WHERE user_id = $1
                  AND guild_id = $2
                """,
                interaction.user.id,
                guild_id
            )

            if not user:
                return await interaction.response.send_message(
                    "You do not have any EXP yet.",
                    ephemeral=True
                )

            exp = user["exp"]
            level = user["level"]

            # Fetch current + next level EXP requirements
            current_row = await conn.fetchrow(
                "SELECT exp_required FROM cd_levels WHERE level = $1",
                level
            )

            next_row = await conn.fetchrow(
                "SELECT exp_required FROM cd_levels WHERE level = $1",
                level + 1
            )

            current_required = current_row["exp_required"] if current_row else 0
            next_required = next_row["exp_required"] if next_row else current_required

            # Progress math
            span = next_required - current_required
            gained = exp - current_required

            progress = max(0, min(gained / span, 1))
            filled = int(progress * 20)
            bar = "█" * filled + "░" * (20 - filled)

        # Build embed
        embed = discord.Embed(
            title=f"🏅 {interaction.user.name}'s Level",
            color=discord.Color.blurple()
        )

        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        embed.add_field(name="📘 Level", value=f"**{level}**", inline=True)
        embed.add_field(name="🔥 Total EXP", value=f"**{exp:,}**", inline=True)

        embed.add_field(
            name="📈 Progress to next level",
            value=f"`{bar}`\n**{gained:,}/{span:,} EXP**",
            inline=False
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(LevelView(bot))
