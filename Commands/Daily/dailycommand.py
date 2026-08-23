from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands

DAILY_COOLDOWN = 86400  # 24 hours
DAILY_POKEBALL_REWARD = 25
POKEBALL_ITEM_ID = 1  # Poké Ball item_id


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

            # Fetch last claim time from users table
            last_claim = await conn.fetchval("""
                SELECT daily_last_claim
                FROM users
                WHERE user_id = $1 AND guild_id = $2
            """, user_id, guild_id)

            now = datetime.utcnow()

            # Cooldown math
            if last_claim is None:
                elapsed = DAILY_COOLDOWN + 1
            else:
                elapsed = (now - last_claim).total_seconds()

            # Still on cooldown
            if elapsed < DAILY_COOLDOWN:
                remaining = DAILY_COOLDOWN - elapsed
                hours = int(remaining // 3600)
                minutes = int((remaining % 3600) // 60)

                embed = discord.Embed(
                    title="<:Pokeball1:1540418809939099818> Daily Already Claimed",
                    description=f"Come back in **{hours}h {minutes}m**",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Award 25 Poké Balls
            await conn.execute("""
                INSERT INTO user_pokemon_catch_items (user_id, guild_id, item_id, quantity)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, guild_id, item_id)
                DO UPDATE SET quantity = user_pokemon_catch_items.quantity + $4;
            """, user_id, guild_id, POKEBALL_ITEM_ID, DAILY_POKEBALL_REWARD)

            # Update daily_last_claim timestamp
            await conn.execute("""
                UPDATE users
                SET daily_last_claim = $1
                WHERE user_id = $2 AND guild_id = $3
            """, now, user_id, guild_id)

        # Success embed
        embed = discord.Embed(
            title="🎉 Daily Reward Claimed!",
            description=f"You received **{DAILY_POKEBALL_REWARD} Poké Balls. Catch some Pokémon using /catchpokemon**!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Poké Ball",
            value="<:Pokeball1:1540418809939099818>",
            inline=True
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Daily(bot))
