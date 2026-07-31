import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import re

ADMIN_ID = 337773020770729985


# ---------------------------------------------------------
#   MODAL FOR ADDING A SHOW
# ---------------------------------------------------------
class AddShowModal(discord.ui.Modal, title="Add Upcoming Show"):
    show_name = discord.ui.TextInput(label="Show Name", placeholder="Example: Baltimore Card Expo")
    show_date = discord.ui.TextInput(label="Date (YYYY-MM-DD)", placeholder="2026-08-15")
    time = discord.ui.TextInput(label="Time", placeholder="10:00 AM - 4:00 PM")
    address = discord.ui.TextInput(label="Address", placeholder="123 Main St")
    state_zip = discord.ui.TextInput(label="State + Zipcode", placeholder="MD 21701")

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):

        # Validate date
        try:
            parsed_date = datetime.strptime(self.show_date.value.strip(), "%Y-%m-%d").date()
        except Exception as e:
            print("CRASH (date parsing):", e)
            embed = discord.Embed(
                title="❌ Invalid Date",
                description="Use **YYYY-MM-DD** format.\nExample: `2026-08-15`",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Validate time
        time_input = self.time.value.strip()
        if not re.match(r"^[A-Za-z0-9:\s\-]+$", time_input):
            embed = discord.Embed(
                title="❌ Invalid Time Format",
                description="Example: `10:00 AM - 4:00 PM`",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Validate state + zip
        try:
            state, zipcode = self.state_zip.value.strip().split()
        except Exception as e:
            print("CRASH (state_zip split):", e)
            embed = discord.Embed(
                title="❌ Invalid State + Zipcode",
                description="Use format: `MD 21701`",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if len(state) != 2 or not state.isalpha():
            embed = discord.Embed(
                title="❌ Invalid State",
                description="State must be 2 letters.\nExample: `MD`",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not zipcode.isdigit() or len(zipcode) not in (5, 9):
            embed = discord.Embed(
                title="❌ Invalid Zipcode",
                description="Zipcode must be 5 or 9 digits.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Insert into DB
        try:
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO upcoming_shows (show_name, date, time, address, state, zipcode, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, TRUE);
                    """,
                    self.show_name.value,
                    parsed_date,
                    time_input,
                    self.address.value,
                    state.upper(),
                    zipcode
                )
        except Exception as e:
            print("CRASH (DB insert):", e)
            embed = discord.Embed(
                title="❌ Database Error",
                description="Failed to save the show.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="✅ Show Added",
            description=f"**{self.show_name.value}** has been added.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
#   COG
# ---------------------------------------------------------
class UpcomingShows(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # ADMIN GROUP (hidden from non-admins)
        self.admin_group = app_commands.Group(
            name="adminshows",
            description="Admin-only show management commands.",
            default_permissions=discord.Permissions(administrator=True)
        )

    async def cog_load(self):

        # /adminshows addshow
        add_cmd = app_commands.Command(
            name="addshow",
            description="Add an upcoming show.",
            callback=self.addshow
        )

        # /adminshows removeshow
        remove_cmd = app_commands.Command(
            name="removeshow",
            description="Deactivate a show by ID.",
            callback=self.removeshow
        )

        self.admin_group.add_command(add_cmd)
        self.admin_group.add_command(remove_cmd)

        self.bot.tree.add_command(self.admin_group)

    # ---------------------------------------------------------
    # /adminshows addshow
    # ---------------------------------------------------------
    async def addshow(self, interaction: discord.Interaction):

        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Admin commands cannot be used in DMs.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(AddShowModal(self.bot))

    # ---------------------------------------------------------
    # /adminshows removeshow
    # ---------------------------------------------------------
    async def removeshow(self, interaction: discord.Interaction, show_id: int):

        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Admin commands cannot be used in DMs.",
                ephemeral=True
            )
            return

        try:
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "UPDATE upcoming_shows SET is_active = FALSE WHERE show_id = $1;",
                    show_id
                )
        except Exception as e:
            print("CRASH (DB update):", e)
            embed = discord.Embed(
                title="❌ Database Error",
                description="Failed to deactivate the show.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🗑️ Show Deactivated",
            description=f"Show ID **{show_id}** is now inactive.",
            color=discord.Color.orange()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------------------------------------------------
    # /upcomingshows (public)
    # ---------------------------------------------------------
    @app_commands.command(name="upcomingshows", description="View upcoming shows.")
    async def upcomingshows(self, interaction: discord.Interaction):

        try:
            async with self.bot.db.acquire() as conn:

                await conn.execute(
                    """
                    UPDATE upcoming_shows
                    SET is_active = FALSE
                    WHERE date < CURRENT_DATE;
                    """
                )

                rows = await conn.fetch(
                    """
                    SELECT show_id, show_name, date, time, address, state, zipcode
                    FROM upcoming_shows
                    WHERE is_active = TRUE
                    ORDER BY date ASC;
                    """
                )
        except Exception as e:
            print("CRASH (DB fetch):", e)
            embed = discord.Embed(
                title="❌ Database Error",
                description="Failed to load shows.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not rows:
            embed = discord.Embed(
                title="🎪 Upcoming Shows",
                description="No upcoming shows are currently active.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🎪 Upcoming Shows",
            description="Here are the shows we are attending:",
            color=discord.Color.blue()
        )

        for r in rows:
            embed.add_field(
                name=f"📍 {r['show_name']} — {r['date']}",
                value=(
                    f"**🕒 Time:** {r['time']}\n"
                    f"**📌 Location:** {r['address']}, {r['state']} {r['zipcode']}\n"
                    f"**Show ID:** {r['show_id']}\n\n\u200B"
                ),
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(UpcomingShows(bot))
