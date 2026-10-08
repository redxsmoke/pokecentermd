from datetime import datetime, timedelta
import random

import discord
from discord import app_commands
from discord.ext import commands

DAILY_COOLDOWN = 86400  # 24 hours
DAILY_POKEBALL_REWARD = 25
POKEBALL_ITEM_ID = 1  # Poké Ball item_id

BASE_COIN_REWARD = 1000
BASE_EXP_REWARD = 100

COIN_MIN_MULTIPLIER = 1.1
COIN_MAX_MULTIPLIER = 4.3

EXP_MIN_MULTIPLIER = 1.1
EXP_MAX_MULTIPLIER = 4.6


class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="daily",
        description="Claim your daily Poké Ball reward"
    )
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id

        async with self.bot.db.acquire() as conn:

            user_data = await conn.fetchrow("""
                SELECT daily_last_claim, daily_streak
                FROM users
                WHERE user_id = $1
                  AND guild_id = $2
            """, user_id, guild_id)

            last_claim = user_data["daily_last_claim"] if user_data else None
            streak = user_data["daily_streak"] if user_data else 0

            now = datetime.utcnow()

            # Cooldown check
            if last_claim is None:
                elapsed = DAILY_COOLDOWN + 1
            else:
                elapsed = (now - last_claim).total_seconds()

            if elapsed < DAILY_COOLDOWN:
                remaining = DAILY_COOLDOWN - elapsed
                hours = int(remaining // 3600)
                minutes = int((remaining % 3600) // 60)

                embed = discord.Embed(
                    title="<:Pokeball1:1540418809939099818> Daily Already Claimed",
                    description=f"Come back in **{hours}h {minutes}m**",
                    color=discord.Color.red()
                )

                await interaction.followup.send(
                    embed=embed,
                    ephemeral=True
                )
                return

            # Update streak
            if last_claim and (now - last_claim) <= timedelta(hours=48):
                streak += 1
            else:
                streak = 1

            # Coin reward
            coin_base = int(
                BASE_COIN_REWARD * (1 + ((streak - 1) * 0.25))
            )

            coin_multiplier = round(
                random.uniform(
                    COIN_MIN_MULTIPLIER,
                    COIN_MAX_MULTIPLIER
                ),
                2
            )

            coin_reward = int(
                coin_base * coin_multiplier
            )

            # EXP reward
            exp_base = int(
                BASE_EXP_REWARD * (1 + ((streak - 1) * 0.25))
            )

            exp_multiplier = round(
                random.uniform(
                    EXP_MIN_MULTIPLIER,
                    EXP_MAX_MULTIPLIER
                ),
                2
            )

            exp_reward = int(
                exp_base * exp_multiplier
            )

            # Award Poké Balls
            await conn.execute("""
                INSERT INTO user_pokemon_catch_items (
                    user_id,
                    guild_id,
                    item_id,
                    quantity
                )
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, guild_id, item_id)
                DO UPDATE SET
                    quantity = user_pokemon_catch_items.quantity + $4;
            """,
                user_id,
                guild_id,
                POKEBALL_ITEM_ID,
                DAILY_POKEBALL_REWARD
            )

            # Award coins, EXP, and update streak
            await conn.execute("""
                UPDATE users
                SET
                    coin_balance = coin_balance + $1,
                    exp = exp + $2,
                    daily_streak = $3,
                    daily_last_claim = $4
                WHERE user_id = $5
                  AND guild_id = $6
            """,
                coin_reward,
                exp_reward,
                streak,
                now,
                user_id,
                guild_id
            )

        embed = discord.Embed(
            title="🎉 Daily Reward Claimed!",
            description=(
                f"You received **{DAILY_POKEBALL_REWARD} Poké Balls**, "
                f"**{coin_reward:,} Coins**, and "
                f"**{exp_reward:,} EXP**!"
            ),
            color=discord.Color.green()
        )

        embed.add_field(
            name="Poké Balls",
            value=f"<:Pokeball1:1540418809939099818> {DAILY_POKEBALL_REWARD}",
            inline=True
        )

        embed.add_field(
            name="Coins",
            value=f"🪙 {coin_reward:,}",
            inline=True
        )

        embed.add_field(
            name="EXP",
            value=f"⭐ {exp_reward:,}",
            inline=True
        )

        embed.add_field(
            name="Daily Streak",
            value=f"🔥 {streak}",
            inline=True
        )

        embed.add_field(
            name="Coin Multiplier",
            value=f"{coin_multiplier}x",
            inline=True
        )

        embed.add_field(
            name="EXP Multiplier",
            value=f"{exp_multiplier}x",
            inline=True
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Daily(bot))