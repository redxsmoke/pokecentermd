import discord
from discord import app_commands
from discord.ext import commands

class UserBadges(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="userbadges", description="View badges earned by another user.")
    @app_commands.describe(user="The user whose badges you want to view")
    async def userbadges(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)

        async with self.bot.db.acquire() as conn:
            # Fetch badges for the target user
            rows = await conn.fetch("""
                SELECT ub.badge_award_id, b.badge_id, b.name, b.description,
                       b.emoji_name, b.emoji_id, ub.awarded_at
                FROM user_badges ub
                JOIN badges b ON b.badge_id = ub.badge_id
                WHERE ub.user_id = $1
                ORDER BY ub.awarded_at ASC
            """, user.id)

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
            title=f"{user.display_name}'s Badges",
            color=discord.Color.blue()
        )

        # Add user avatar
        if user.avatar:
            embed.set_thumbnail(url=user.avatar.url)
        else:
            embed.set_thumbnail(url=user.default_avatar.url)

        if not rows:
            embed.description = "📭 This user has no badges."
            return await interaction.followup.send(embed=embed, ephemeral=True)

        lines = []
        for row in rows:
            # Only show emoji if bot can render it in THIS guild
            emoji = f"<:{row['emoji_name']}:{row['emoji_id']}>"


            badge_number = badge_numbers[row["badge_award_id"]]

            lines.append(
                f"{emoji} **{row['name']} (#{badge_number}/100)**\n"
                f"{row['description']}\n"
                f"*Awarded: {row['awarded_at'].strftime('%b %d, %Y')}*"
            )

        embed.description = "\n\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(UserBadges(bot))