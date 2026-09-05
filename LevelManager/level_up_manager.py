# level_up_manager.py

import discord

class LevelUpManager:
    def __init__(self, bot, pool):
        self.bot = bot
        self.pool = pool

    async def check_level_up(self, user_id: int, new_xp: int, channel: discord.TextChannel):
        """
        Checks if the user leveled up based on cd_levels table.
        If so, updates DB and sends a level-up embed.
        """

        async with self.pool.acquire() as conn:

            # Fetch current user level
            row = await conn.fetchrow(
                "SELECT level FROM users WHERE user_id = $1",
                user_id
            )
            if row is None:
                return

            old_level = row["level"]

            # Fetch the highest level where xp_required <= new_xp
            new_level_row = await conn.fetchrow(
                """
                SELECT level, exp_required, level_up_image_url
                FROM cd_levels
                WHERE exp_required <= $1
                ORDER BY exp_required DESC
                LIMIT 1
                """,
                new_xp
            )

            if new_level_row is None:
                return

            new_level = new_level_row["level"]

            # No level-up
            if new_level <= old_level:
                return

            # Update user level
            await conn.execute(
                """
                UPDATE users
                SET level = $1
                WHERE user_id = $2
                """,
                new_level,
                user_id
            )

            # Build level-up embed
            embed = discord.Embed(
                title=f"🎉 Level Up!",
                description=(
                    f"<@{user_id}> has leveled up!\n\n"
                    f"**Level {old_level} → Level {new_level}**\n"
                ),
                color=discord.Color.gold()
            )

            # Add thumbnail if exists
            if new_level_row["level_up_image_url"]:
                embed.set_thumbnail(url=new_level_row["level_up_image_url"])

            await channel.send(embed=embed)
