import discord
from discord import app_commands
from discord.ext import commands

class MyBadges(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mybadges", description="View all badges you have earned.")
    async def mybadges(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with self.bot.db.acquire() as conn:
            # Fetch all badges for the user
            rows = await conn.fetch("""
                SELECT ub.badge_award_id, b.badge_id, b.name, b.description,
                       b.emoji_name, b.emoji_id, ub.awarded_at
                FROM user_badges ub
                JOIN badges b ON b.badge_id = ub.badge_id
                WHERE ub.user_id = $1
                ORDER BY ub.awarded_at ASC
            """, interaction.user.id)

            # Precompute badge numbers BEFORE leaving DB block
            badge_numbers = {}
            for row in rows:
                badge_numbers[row["badge_award_id"]] = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM user_badges
                    WHERE badge_id = $1
                    AND badge_award_id <= $2
                """, row["badge_id"], row["badge_award_id"])

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Badges",
            color=discord.Color.gold()
        )

        # ⭐ Add user avatar back
        if interaction.user.avatar:
            embed.set_thumbnail(url=interaction.user.avatar.url)
        else:
            embed.set_thumbnail(url=interaction.user.default_avatar.url)

        if not rows:
            embed.description = "📭 You have no badges yet."
            return await interaction.followup.send(embed=embed, ephemeral=True)

        for row in rows:

            emoji = f"<:{row['emoji_name']}:{row['emoji_id']}>"


            badge_number = badge_numbers[row["badge_award_id"]]

            embed.add_field(
                name=f"{emoji} {row['name']} (#{badge_number}/100)",
                value=(
                    f"{row['description']}\n"
                    f"*Awarded: {row['awarded_at'].strftime('%b %d, %Y')}*"
                ),
                inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=True)




async def setup(bot):
    await bot.add_cog(MyBadges(bot))