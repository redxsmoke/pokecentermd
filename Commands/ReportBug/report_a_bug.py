import datetime
import discord
from discord import ui, app_commands
from discord.ext import commands

OWNER_ID = 337773020770729985


# -------------------------------------------------
# Modal Class (with date/time conversion FIX)
# -------------------------------------------------

class ReportBugModal(ui.Modal, title="Report a Bug"):
    def __init__(self, user: discord.User, guild_id: int | None):
        super().__init__()
        self.user = user
        self.guild_id = guild_id

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.date_time = ui.TextInput(
            label="Date & Time Discovered",
            default=now,
            required=True,
            style=discord.TextStyle.short
        )
        self.add_item(self.date_time)

        self.command_name = ui.TextInput(
            label="Which command has the bug?",
            placeholder="/examplecommand",
            required=True,
            style=discord.TextStyle.short
        )
        self.add_item(self.command_name)

        self.description = ui.TextInput(
            label="Description",
            placeholder="Brief description of the bug",
            required=True,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.description)

        self.additional = ui.TextInput(
            label="Additional Information (Optional)",
            required=False,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.additional)

    async def on_submit(self, interaction: discord.Interaction):

        # Convert date/time strings → proper date/time objects
        date_str = self.date_time.value.split(" ")[0]
        time_str = self.date_time.value.split(" ")[1]

        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        time_obj = datetime.datetime.strptime(time_str, "%H:%M:%S").time()

        pool = interaction.client.db  # your bot uses bot.db

        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_reported_bugs (
                    user_id,
                    guild_id,
                    date,
                    reported_at,
                    description,
                    additional_details,
                    status,
                    created_at
                )
                VALUES ($1,$2,$3,$4,$5,$6,'pending investigation', NOW())
            """,
                self.user.id,
                self.guild_id,
                date_obj,
                time_obj,
                self.description.value,
                self.additional.value
            )

        # DM the app creator
        creator = interaction.client.get_user(OWNER_ID)
        if creator:
            embed = discord.Embed(
                title="🐞 New Bug Report Submitted",
                color=0xE67E22
            )
            embed.add_field(name="Reporter", value=f"{self.user} ({self.user.id})", inline=False)
            embed.add_field(name="Guild ID", value=str(self.guild_id), inline=False)
            embed.add_field(name="Command", value=self.command_name.value, inline=False)
            embed.add_field(name="Description", value=self.description.value, inline=False)
            embed.add_field(name="Additional Info", value=self.additional.value or "None", inline=False)
            embed.add_field(name="Discovered At", value=self.date_time.value, inline=False)

            try:
                await creator.send(embed=embed)
            except:
                pass

        confirm = discord.Embed(
            title="🐞 Bug Report Submitted Successfully!",
            description=(
                "Thanks for taking time to report your findings!\n\n"
                "This message confirms your bug was submitted successfully.\n"
                "We are investigating the issue and if this issue is found to be a bug, "
                "you will receive a **Bug Catcher Badge**!"
            ),
            color=0x2ECC71
        )

        await interaction.response.send_message(embed=confirm, ephemeral=True)


# -------------------------------------------------
# Cog Class (correct architecture)
# -------------------------------------------------

class ReportBug(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="reportabug",
        description="Report a bug you discovered."
    )
    async def reportabug(self, interaction: discord.Interaction):
        modal = ReportBugModal(
            user=interaction.user,
            guild_id=interaction.guild.id if interaction.guild else None
        )
        await interaction.response.send_modal(modal)


# -------------------------------------------------
# Setup (Cog loader)
# -------------------------------------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(ReportBug(bot))
