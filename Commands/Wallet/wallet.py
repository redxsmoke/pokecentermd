import discord
from discord import app_commands
from discord.ext import commands


class Wallet(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="wallet",
        description="View your current coin balance"
    )
    async def wallet(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        guild_id = interaction.guild.id

        async with self.bot.db.acquire() as conn:
            balance = await conn.fetchval("""
                SELECT coin_balance
                FROM users
                WHERE user_id = $1
                AND guild_id = $2
            """, user_id, guild_id)

        if balance is None:
            balance = 0

        embed = discord.Embed(
            title="💰 Wallet",
            description=f"You currently have **{balance:,} Coins**.",
            color=discord.Color.gold()
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Wallet(bot))