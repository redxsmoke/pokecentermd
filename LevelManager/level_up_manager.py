import discord

class LevelUpManager:
    def __init__(self, bot, pool):
        self.bot = bot
        self.pool = pool

    def format_reward_message(self, reward):
        r_type = reward["type"]
        value = reward["value"]

        # Percent off
        if r_type == "percent_off":
            return f"You earned **{value}% off** your next order!"

        # Percent off with minimum
        if r_type == "percent_off_min":
            return f"You earned **{value}% off** orders over **${reward['min_amount']:.2f}**!"

        # Flat amount off
        if r_type == "flat_off":
            return f"You earned **${value:.2f} off** your next order!"

        # Flat amount off with minimum
        if r_type == "flat_off_min":
            return f"You earned **${value:.2f} off** any order over **${reward['min_amount']:.2f}**!"

        # Free shipping
        if r_type == "free_shipping":
            return "You earned **FREE shipping** on your next order!"

        # Free shipping with minimum
        if r_type == "free_shipping_min":
            return f"You earned **FREE shipping** on orders over **${reward['min_amount']:.2f}**!"

        # Fallback
        return f"You earned a new reward: **{reward['name']}**!"

    async def check_level_up(self, user_id: int, new_xp: int, channel: discord.TextChannel):
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

            # Level-up embed
            embed = discord.Embed(
                title=f"🎉 Level Up!",
                description=(
                    f"<@{user_id}> has leveled up!\n\n"
                    f"**Level {old_level} → Level {new_level}**\n"
                ),
                color=discord.Color.gold()
            )

            if new_level_row["level_up_image_url"]:
                embed.set_thumbnail(url=new_level_row["level_up_image_url"])

            await channel.send(embed=embed)

            # ============================================================
            # ⭐ Rewards trigger when reaching OR passing over levels
            # ============================================================

            reward_rows = await conn.fetch(
                """
                SELECT reward_id, name, category, type, value, min_amount
                FROM guild_rewards
                WHERE guild_id = $1
                  AND active = TRUE
                  AND required_level BETWEEN $2 AND $3
                """,
                channel.guild.id,
                old_level + 1,
                new_level
            )

            if not reward_rows:
                return

            # Send human-readable reward messages
            for reward in reward_rows:
                human_message = self.format_reward_message(reward)

                reward_embed = discord.Embed(
                    title="🏆 Reward Earned!",
                    description=(
                        f"<@{user_id}> unlocked a new reward!\n\n"
                        f"{human_message}\n\n"
                        f"You can use this reward during checkout!"
                    ),
                    color=discord.Color.green()
                )

                await channel.send(embed=reward_embed)

