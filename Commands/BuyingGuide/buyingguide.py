import discord
from discord.ext import commands
from discord import app_commands


# ---------------------------------------------------------
# Dropdown Menu
# ---------------------------------------------------------
class BuyingGuideDropdown(discord.ui.Select):
    def __init__(self, bot, rows):
        self.bot = bot
        self.rows = rows

        options = [
            discord.SelectOption(
                label=r["type_description"],
                value=str(r["type_id"])
            )
            for r in rows
        ]

        super().__init__(
            placeholder="Select a category...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        selected_id = int(self.values[0])

        # Find selected row
        row = next((r for r in self.rows if r["type_id"] == selected_id), None)

        if not row:
            await interaction.response.send_message(
                "Error: Category not found.",
                ephemeral=True
            )
            return

        # Determine status + color
        active = row["active"]
        status_text = "Currently Buying" if active else "Not Currently Buying"
        color = discord.Color.green() if active else discord.Color.red()

        embed = discord.Embed(
            title=f"{row['type_description']}",
            color=color
        )

        embed.add_field(name="Rate", value=row["rate"], inline=False)
        embed.add_field(name="Status", value=status_text, inline=False)


        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
# View Wrapper
# ---------------------------------------------------------
class BuyingGuideView(discord.ui.View):
    def __init__(self, bot, rows):
        super().__init__(timeout=None)
        self.add_item(BuyingGuideDropdown(bot, rows))


# ---------------------------------------------------------
# Cog
# ---------------------------------------------------------
class BuyingGuide(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="buyingguide", description="View our current buying rates and categories.")
    async def buyingguide(self, interaction: discord.Interaction):

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT type_id, type_description, rate, active
                FROM buying_guide
                WHERE display_in_app = TRUE
                ORDER BY type_id ASC;
                """
            )

        if not rows:
            await interaction.response.send_message(
                "No buying guide data found.",
                ephemeral=True
            )
            return

        view = BuyingGuideView(self.bot, rows)

        embed = discord.Embed(
            title="📘 Buying Guide",
            description="Select a category below to view details.",
            color=discord.Color.blue()
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(BuyingGuide(bot))
