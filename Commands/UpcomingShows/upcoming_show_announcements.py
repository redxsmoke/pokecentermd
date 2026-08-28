import discord
from discord.ext import commands
import re

# ============================================================
#   ANNOUNCEMENT SESSION STORAGE
# ============================================================
class AnnouncementSession:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.show_name = None
        self.date = None
        self.time = None
        self.address = None
        self.city = None
        self.state = None
        self.zipcode = None
        self.flyer_url = None

        self.discount_code = None
        self.percent = None
        self.price_condition = None


# ============================================================
#   START VIEW — ANNOUNCEMENT YES/NO
# ============================================================
class AnnouncementStartView(discord.ui.View):
    def __init__(self, cog, session: AnnouncementSession):
        super().__init__(timeout=600)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(
            content="Would you like to offer a discount for this show?",
            view=DiscountOfferView(self.cog, self.session)
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button):
        preview_embed = self.cog.build_announcement_embed(self.session)
        await interaction.response.edit_message(
            content=None,
            embed=preview_embed,
            view=PreviewAnnouncementView(self.cog, self.session)
        )


# ============================================================
#   DISCOUNT OFFER YES/NO
# ============================================================
class DiscountOfferView(discord.ui.View):
    def __init__(self, cog, session: AnnouncementSession):
        super().__init__(timeout=600)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(
            content="Would you like to enter a discount code?",
            view=DiscountCodeView(self.cog, self.session)
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button):
        preview_embed = self.cog.build_announcement_embed(self.session)
        await interaction.response.edit_message(
            content=None,
            embed=preview_embed,
            view=PreviewAnnouncementView(self.cog, self.session)
        )


# ============================================================
#   DISCOUNT CODE VIEW (ENTER / SKIP)
# ============================================================
class DiscountCodeView(discord.ui.View):
    def __init__(self, cog, session: AnnouncementSession):
        super().__init__(timeout=600)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Enter Discount Code", style=discord.ButtonStyle.primary)
    async def enter_code(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(DiscountCodeModal(self.cog, self.session))

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip_code(self, interaction: discord.Interaction, button):
        self.session.discount_code = None
        await interaction.response.edit_message(
            content="Select a discount percent:",
            view=DiscountPercentView(self.cog, self.session)
        )


# ============================================================
#   DISCOUNT CODE MODAL
# ============================================================
class DiscountCodeModal(discord.ui.Modal, title="Enter Discount Code"):
    code = discord.ui.TextInput(
        label="Discount Code",
        placeholder="Example: TCGEXPO15",
        required=False,
        max_length=15
    )

    def __init__(self, cog, session: AnnouncementSession):
        super().__init__()
        self.cog = cog
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        value = self.code.value.strip()
        self.session.discount_code = value if value else None

        # ⭐ Modernized: use followup after modal submit
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            "Select a discount percent:",
            view=DiscountPercentView(self.cog, self.session),
            ephemeral=True
        )
# ============================================================
#   DISCOUNT PERCENT SELECT
# ============================================================
class DiscountPercentSelect(discord.ui.Select):
    def __init__(self, cog, session: AnnouncementSession):
        self.cog = cog
        self.session = session

        options = []
        for p in range(5, 101, 5):
            options.append(discord.SelectOption(label=f"{p}%", value=str(p)))

        super().__init__(
            placeholder="Select discount percent...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        self.session.percent = int(self.values[0])
        await interaction.response.edit_message(
            content="Select discount scope:",
            view=DiscountScopeView(self.cog, self.session)
        )


class DiscountPercentView(discord.ui.View):
    def __init__(self, cog, session: AnnouncementSession):
        super().__init__(timeout=600)
        self.add_item(DiscountPercentSelect(cog, session))


# ============================================================
#   DISCOUNT SCOPE SELECT
# ============================================================
class DiscountScopeSelect(discord.ui.Select):
    def __init__(self, cog, session: AnnouncementSession):
        self.cog = cog
        self.session = session

        labels = [
            "Any purchase",
            "Cards under $5",
            "Cards under $10",
            "Cards under $15",
            "Cards under $20",
            "Cards under $25",
            "Cards under $30",
            "Cards under $50",
            "Cards under $75",
            "Cards under $100",
            "Cards under $150",
            "Cards under $200",
            "Cards under $250",
            "Cards under $300",
            "Cards under $400",
            "Cards under $500",
            "Cards under $750",
            "Cards under $1000",
        ]

        options = [discord.SelectOption(label=label, value=label) for label in labels]

        super().__init__(
            placeholder="Select discount scope...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        self.session.price_condition = self.values[0]

        preview_embed = self.cog.build_announcement_embed(self.session)

        await interaction.response.edit_message(
            content=None,
            embed=preview_embed,
            view=PreviewAnnouncementView(self.cog, self.session)
        )


class DiscountScopeView(discord.ui.View):
    def __init__(self, cog, session: AnnouncementSession):
        super().__init__(timeout=600)
        self.add_item(DiscountScopeSelect(cog, session))


# ============================================================
#   EDIT ANNOUNCEMENT FIELD SELECT
# ============================================================
class EditAnnouncementFieldSelect(discord.ui.Select):
    def __init__(self, cog, session: AnnouncementSession):
        self.cog = cog
        self.session = session

        options = [
            discord.SelectOption(label="Discount Code", value="discount_code"),
            discord.SelectOption(label="Percent", value="percent"),
            discord.SelectOption(label="Price Condition", value="price_condition"),
        ]

        super().__init__(
            placeholder="Select a field to edit",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        field = self.values[0]
        await interaction.response.send_modal(
            EditAnnouncementFieldModal(self.cog, self.session, field)
        )


class EditAnnouncementFieldsView(discord.ui.View):
    def __init__(self, cog, session: AnnouncementSession):
        super().__init__(timeout=600)
        self.add_item(EditAnnouncementFieldSelect(cog, session))


# ============================================================
#   EDIT ANNOUNCEMENT FIELD MODAL
# ============================================================
class EditAnnouncementFieldModal(discord.ui.Modal):
    def __init__(self, cog, session: AnnouncementSession, field: str):
        self.cog = cog
        self.session = session
        self.field = field

        title = field.replace("_", " ").title()
        super().__init__(title=f"Edit {title}")

        current_value = getattr(session, field, None)
        if current_value is None:
            current_value = ""

        self.input = discord.ui.TextInput(
            label=title,
            default=str(current_value) if current_value is not None else "",
            placeholder=f"Enter new {title}",
            required=False
        )
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        value = self.input.value.strip()

        if self.field == "percent":
            self.session.percent = int(value) if value else None
        else:
            setattr(self.session, self.field, value if value else None)

        preview_embed = self.cog.build_announcement_embed(self.session)

        await interaction.response.edit_message(
            content=None,
            embed=preview_embed,
            view=PreviewAnnouncementView(self.cog, self.session)
        )
# ============================================================
#   ANNOUNCEMENT PREVIEW VIEW — FULLY MODERNIZED (OPTION B)
# ============================================================
class PreviewAnnouncementView(discord.ui.View):
    def __init__(self, cog, session: AnnouncementSession):
        super().__init__(timeout=600)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Send Message", style=discord.ButtonStyle.success)
    async def send_message(self, interaction: discord.Interaction, button):

        # ⭐ CRITICAL FIX — ALWAYS DEFER FIRST
        # This creates a fresh webhook token that NEVER expires mid-flow.
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        bot = interaction.client

        async with bot.db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT upcoming_shows_channel_id
                FROM guild_settings
                WHERE guild_id = $1
                """,
                guild_id
            )

        upcoming_channel_id = row["upcoming_shows_channel_id"] if row else None

        if not upcoming_channel_id:
            embed = discord.Embed(
                title="Upcoming Shows Channel Not Configured",
                description=(
                    "You have not configured a designated channel to send upcoming show alerts.\n\n"
                    "Please use /botsettings and select a channel where you'd like the alerts sent."
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        channel = interaction.guild.get_channel(upcoming_channel_id)
        if channel is None:
            embed = discord.Embed(
                title="Upcoming Shows Channel Invalid",
                description=(
                    "The configured upcoming shows channel no longer exists.\n\n"
                    "Please use /botsettings and select a valid channel."
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # ⭐ SAFE — followup always works after defer
        await interaction.followup.send("Sending announcement...", ephemeral=True)

        await self.cog.send_announcement_broadcast(interaction, self.session)

    @discord.ui.button(label="Edit Message", style=discord.ButtonStyle.secondary)
    async def edit_message(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(
            content="Select a field to edit:",
            embed=None,
            view=EditAnnouncementFieldsView(self.cog, self.session)
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(
            content="Announcement cancelled. The show remains added.",
            embed=None,
            view=None
        )
        self.cog.end_announcement_session(self.session.user_id)

from discord.ext import commands



