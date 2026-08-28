# PART 1 — imports, sessions, modals, views

import discord
from discord.ext import commands
from discord import app_commands
from io import BytesIO
from datetime import datetime
import re

from .upcoming_show_announcements import (
    AnnouncementSession,
    AnnouncementStartView,
    PreviewAnnouncementView,
    EditAnnouncementFieldsView,
    DiscountOfferView,
    DiscountCodeView,
    DiscountPercentView,
    DiscountScopeView,
)

# ============================================================
#   WIZARD SESSION STORAGE
# ============================================================
class ShowWizardSession:
    def __init__(self, user_id):
        self.user_id = user_id
        self.show_name = None
        self.date = None
        self.time = None
        self.address = None
        self.city = None
        self.state = None
        self.zipcode = None
        self.flyer_url = None
        self.editing_show_id = None  # ⭐ Added for edit workflow

    def to_db_payload(self):
        return {
            "show_name": self.show_name,
            "date": self.date,
            "time": self.time,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "zipcode": self.zipcode,
            "flyer_url": self.flyer_url,
        }


# ============================================================
#   MODAL 1 — SHOW DETAILS
# ============================================================
class ShowDetailsModal(discord.ui.Modal, title="Add Show — Step 1"):
    show_name = discord.ui.TextInput(
        label="Show Name",
        placeholder="Example: TCG Card Expo",
        required=True
    )
    date = discord.ui.TextInput(
        label="Date",
        placeholder="Example: August 15, 2026",
        required=True
    )
    time = discord.ui.TextInput(
        label="Time",
        placeholder="Example: 10:00 AM – 4:00 PM",
        required=True
    )

    def __init__(self, cog, session):
        super().__init__()
        self.cog = cog
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        self.session.show_name = self.show_name.value.strip()
        self.session.date = self.date.value.strip()
        self.session.time = self.time.value.strip()

        await interaction.response.send_message(
            "**Step 1 complete.**\n\n**Step 2 — Address Information**",
            view=AddressStepView(self.cog, self.session),
            ephemeral=True
        )


# ============================================================
#   MODAL 2 — ADDRESS
# ============================================================
class AddressModal(discord.ui.Modal, title="Add Show — Step 2"):
    address = discord.ui.TextInput(
        label="Address",
        placeholder="Example: 123 Main Street",
        required=True
    )

    city = discord.ui.TextInput(
        label="City",
        placeholder="Example: City",
        required=True
    )

    state = discord.ui.TextInput(
        label="State",
        placeholder="Example: State or State Abbreviation",
        required=True
    )

    zipcode = discord.ui.TextInput(
        label="Zip Code",
        placeholder="Example: 21740",
        required=True
    )

    def __init__(self, cog, session):
        super().__init__()
        self.cog = cog
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        self.session.address = self.address.value.strip()
        self.session.city = self.city.value.strip()
        self.session.state = self.state.value.strip()
        self.session.zipcode = self.zipcode.value.strip()

        await interaction.response.send_message(
            "**Step 2 complete.**\n\n**Step 3 — Flyer Upload (Optional)**",
            view=FlyerStepView(self.cog, self.session),
            ephemeral=True
        )


# ============================================================
#   ADDRESS STEP VIEW
# ============================================================
class AddressStepView(discord.ui.View):
    def __init__(self, cog, session):
        super().__init__(timeout=300)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Enter Address", style=discord.ButtonStyle.primary)
    async def enter_address(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(AddressModal(self.cog, self.session))


# ============================================================
#   FLYER STEP VIEW — IMAGE UPLOAD → CDN URL
# ============================================================
class FlyerStepView(discord.ui.View):
    def __init__(self, cog, session):
        super().__init__(timeout=600)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Upload Flyer", style=discord.ButtonStyle.primary)
    async def upload_flyer(self, interaction: discord.Interaction, button):
        embed = discord.Embed(
            title="Upload Flyer",
            description=(
                "Please upload an image in this channel.\n\n"
                "I will use the **first attachment** you send."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        def check(m: discord.Message):
            return (
                m.author.id == self.session.user_id
                and m.channel.id == interaction.channel.id
                and m.attachments
            )

        try:
            msg = await self.cog.bot.wait_for("message", check=check, timeout=120)
        except Exception:
            fail = discord.Embed(
                title="No Image Received",
                description="No image was uploaded in time.",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=fail, ephemeral=True)
            return

        attachment = msg.attachments[0]
        file_bytes = await attachment.read()

        try:
            await msg.delete()
        except:
            pass

        file = discord.File(BytesIO(file_bytes), filename="flyer.jpg")
        sent_msg = await interaction.channel.send(file=file)

        url = sent_msg.attachments[0].url
        if "?" in url:
            url = url.split("?")[0]

        self.session.flyer_url = url

        embed = self.cog.build_preview_embed(self.session)
        await interaction.followup.send(
            "**Preview — Upcoming Show (Flyer Added)**",
            embed=embed,
            view=PreviewView(self.cog, self.session),
            ephemeral=True
        )

    @discord.ui.button(label="Skip Flyer", style=discord.ButtonStyle.secondary)
    async def skip_flyer(self, interaction: discord.Interaction, button):
        embed = self.cog.build_preview_embed(self.session)
        await interaction.response.send_message(
            "**Preview — Upcoming Show**",
            embed=embed,
            view=PreviewView(self.cog, self.session),
            ephemeral=True
        )
# PART 2 — edit fields, preview view, month/show selects, pagination

# ============================================================
#   EDIT FIELD SELECT + MODAL
# ============================================================
class EditFieldSelect(discord.ui.Select):
    def __init__(self, cog, session):
        self.cog = cog
        self.session = session

        options = [
            discord.SelectOption(label="Show Name", value="show_name"),
            discord.SelectOption(label="Date", value="date"),
            discord.SelectOption(label="Time", value="time"),
            discord.SelectOption(label="Address", value="address"),
            discord.SelectOption(label="City", value="city"),
            discord.SelectOption(label="State", value="state"),
            discord.SelectOption(label="Zip Code", value="zipcode"),
            discord.SelectOption(label="Flyer", value="flyer"),
        ]

        super().__init__(
            placeholder="Select a field to edit",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        field = self.values[0]

        if field == "flyer":
            await interaction.response.send_message(
                "Upload a new flyer image in this channel. I will use the first attachment you send.",
                ephemeral=True
            )

            def check(m: discord.Message):
                return (
                    m.author.id == self.session.user_id
                    and m.channel.id == interaction.channel.id
                    and m.attachments
                )

            try:
                msg = await self.cog.bot.wait_for("message", check=check, timeout=120)
            except Exception:
                fail = discord.Embed(
                    title="No Image Received",
                    description="No image was uploaded in time.",
                    color=discord.Color.red(),
                )
                await interaction.followup.send(embed=fail, ephemeral=True)
                return

            attachment = msg.attachments[0]
            file_bytes = await attachment.read()

            try:
                await msg.delete()
            except:
                pass

            file = discord.File(BytesIO(file_bytes), filename="flyer.jpg")
            sent_msg = await interaction.channel.send(file=file)

            url = sent_msg.attachments[0].url
            if "?" in url:
                url = url.split("?")[0]

            self.session.flyer_url = url

            embed = self.cog.build_preview_embed(self.session)
            await interaction.followup.send(
                "Updated Preview (Flyer Updated):",
                embed=embed,
                view=PreviewView(self.cog, self.session),
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            SingleFieldEditModal(self.cog, self.session, field)
        )


class EditFieldsView(discord.ui.View):
    def __init__(self, cog, session):
        super().__init__(timeout=300)
        self.add_item(EditFieldSelect(cog, session))


# ============================================================
#   SINGLE FIELD EDIT MODAL
# ============================================================
class SingleFieldEditModal(discord.ui.Modal):
    def __init__(self, cog, session, field):
        self.cog = cog
        self.session = session
        self.field = field

        super().__init__(title=f"Edit {field.replace('_', ' ').title()}")

        current_value = getattr(session, field, "") or ""

        self.input = discord.ui.TextInput(
            label=field.replace("_", " ").title(),
            default=current_value,
            placeholder=f"Enter new {field.replace('_', ' ')}",
            required=True
        )
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        setattr(self.session, self.field, self.input.value.strip())

        embed = self.cog.build_preview_embed(self.session)
        await interaction.response.edit_message(
            content="Updated Preview:",
            embed=embed,
            view=PreviewView(self.cog, self.session)
        )


# ============================================================
#   PREVIEW VIEW
# ============================================================
class PreviewView(discord.ui.View):
    def __init__(self, cog, session):
        super().__init__(timeout=600)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button):

        # ⭐ Defer to create a stable webhook for followups
        await interaction.response.defer(ephemeral=True)

        # ⭐ Editing mode
        if self.session.editing_show_id:
            await self.cog.update_show_into_db(self.session, interaction)
            await interaction.followup.send(
                "✅ Show updated successfully.",
                ephemeral=True
            )
            ann_session = self.cog.create_announcement_session_from_show(self.session)
            await self.cog.start_announcement_flow(interaction, ann_session)
            self.cog.end_session(self.session.user_id)
            return

        # ⭐ Add mode
        await self.cog.insert_show_into_db(self.session, interaction)
        await interaction.followup.send(
            "✅ Show added successfully.",
            ephemeral=True
        )
        ann_session = self.cog.create_announcement_session_from_show(self.session)
        await self.cog.start_announcement_flow(interaction, ann_session)
        self.cog.end_session(self.session.user_id)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(
            content="❌ Wizard cancelled.",
            embed=None,
            view=None
        )
        self.cog.end_session(self.session.user_id)

    @discord.ui.button(label="Edit Fields", style=discord.ButtonStyle.secondary)
    async def edit_fields(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(
            content="Select a field to edit:",
            view=EditFieldsView(self.cog, self.session)
        )


# ============================================================
#   MONTH SELECT FOR EDITING
# ============================================================
class EditShowMonthSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog

        options = [
            discord.SelectOption(label="January", value="1"),
            discord.SelectOption(label="February", value="2"),
            discord.SelectOption(label="March", value="3"),
            discord.SelectOption(label="April", value="4"),
            discord.SelectOption(label="May", value="5"),
            discord.SelectOption(label="June", value="6"),
            discord.SelectOption(label="July", value="7"),
            discord.SelectOption(label="August", value="8"),
            discord.SelectOption(label="September", value="9"),
            discord.SelectOption(label="October", value="10"),
            discord.SelectOption(label="November", value="11"),
            discord.SelectOption(label="December", value="12"),
        ]

        super().__init__(
            placeholder="Select a month to edit shows...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        month = int(self.values[0])
        await self.cog.show_month_results(interaction, month)


class EditShowMonthView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=600)
        self.add_item(EditShowMonthSelect(cog))


# ============================================================
#   SHOW SELECT FOR EDITING
# ============================================================
class EditShowSelect(discord.ui.Select):
    def __init__(self, cog, shows):
        self.cog = cog

        options = []
        for show in shows:
            label = f"{show['show_name']} — {show['date']}"
            options.append(discord.SelectOption(label=label, value=str(show["show_id"])))

        super().__init__(
            placeholder="Select a show to edit...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        show_id = int(self.values[0])
        await self.cog.load_edit_session(interaction, show_id)


class EditShowSelectView(discord.ui.View):
    def __init__(self, cog, shows):
        super().__init__(timeout=600)
        self.add_item(EditShowSelect(cog, shows))


# ============================================================
#   PAGINATION VIEW — 6 SHOWS PER PAGE
# ============================================================
class UpcomingShowsPagination(discord.ui.View):
    def __init__(self, cog, interaction, rows, page=0):
        super().__init__(timeout=600)
        self.cog = cog
        self.interaction = interaction
        self.rows = rows
        self.page = page
        self.per_page = 6

        total_pages = (len(rows) - 1) // self.per_page + 1

        self.prev_button.disabled = (page == 0)
        self.next_button.disabled = (page >= total_pages - 1)

        if total_pages == 1:
            self.prev_button.disabled = True
            self.next_button.disabled = True

    def get_page_embeds(self):
        start = self.page * self.per_page
        end = start + self.per_page
        chunk = self.rows[start:end]

        embeds = []
        for r in chunk:
            embed = discord.Embed(
                title=r["show_name"],
                color=discord.Color.gold()
            )
            if r["flyer_url"]:
                embed.set_thumbnail(url=r["flyer_url"])

            embed.description = (
                f"★ **Date:** {r['date']}\n"
                f"★ **Time:** {r['time']}\n"
                f"★ **Address:** {r['address']}, {r['city']}, {r['state']} {r['zipcode']}\n"
            )
            embed.set_footer(text=f"Show ID #{r['show_id']}")
            embeds.append(embed)

        return embeds

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button):
        self.page -= 1
        new_view = UpcomingShowsPagination(self.cog, interaction, self.rows, self.page)
        await interaction.response.edit_message(
            embeds=new_view.get_page_embeds(),
            view=new_view
        )

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button):
        self.page += 1
        new_view = UpcomingShowsPagination(self.cog, interaction, self.rows, self.page)
        await interaction.response.edit_message(
            embeds=new_view.get_page_embeds(),
            view=new_view
        )
# PART 3 — main cog, announcement helpers, DB ops, commands, setup

# ============================================================
#   MAIN COG
# ============================================================
class UpcomingShows(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self.announcement_sessions = {}

        self.admin_group = app_commands.Group(
            name="adminshows",
            description="Admin-only show management commands.",
            default_permissions=discord.Permissions(administrator=True)
        )

    def get_session(self, user_id):
        if user_id not in self.sessions:
            self.sessions[user_id] = ShowWizardSession(user_id)
        return self.sessions[user_id]

    def end_session(self, user_id):
        self.sessions.pop(user_id, None)

    # ---------------------------------------------------------
    # Announcement helpers
    # ---------------------------------------------------------
    def create_announcement_session_from_show(self, show_session: ShowWizardSession):
        ann = AnnouncementSession(show_session.user_id)
        ann.show_name = show_session.show_name
        ann.date = show_session.date
        ann.time = show_session.time
        ann.address = show_session.address
        ann.city = show_session.city
        ann.state = show_session.state
        ann.zipcode = show_session.zipcode
        ann.flyer_url = show_session.flyer_url
        self.announcement_sessions[show_session.user_id] = ann
        return ann

    def get_announcement_session(self, user_id):
        return self.announcement_sessions.get(user_id)

    def end_announcement_session(self, user_id):
        self.announcement_sessions.pop(user_id, None)

    async def start_announcement_flow(self, interaction: discord.Interaction, ann_session: AnnouncementSession):
        await interaction.followup.send(
            "Would you like to send an announcement for this show?",
            view=AnnouncementStartView(self, ann_session),
            ephemeral=True
        )

    # ---------------------------------------------------------
    # UPDATED EMBED BUILDER (embed-only announcement)
    # ---------------------------------------------------------
    def build_announcement_embed(self, ann_session: AnnouncementSession):
        embed = discord.Embed(
            title=ann_session.show_name or "Upcoming Show",
            color=discord.Color.gold()
        )

        embed.description = "**A new show was added to /upcomingshows!**\n"

        if ann_session.percent and ann_session.price_condition:
            if ann_session.price_condition.lower() == "any purchase":
                if ann_session.discount_code:
                    embed.description += (
                        f"**Attend this show and mention discount code {ann_session.discount_code} "
                        f"to receive {ann_session.percent}% off any purchase.**\n"
                    )
                else:
                    embed.description += (
                        f"**Attend this show to receive {ann_session.percent}% off any purchase.**\n"
                    )
            else:
                match = re.search(r"\$?(\d+)", ann_session.price_condition)
                cap = match.group(1) if match else ""
                if ann_session.discount_code:
                    embed.description += (
                        f"**Attend this show and mention discount code {ann_session.discount_code} "
                        f"to receive {ann_session.percent}% off cards ${cap} or less.**\n"
                    )
                else:
                    embed.description += (
                        f"**Attend this show to receive {ann_session.percent}% off cards ${cap} or less.**\n"
                    )

        embed.add_field(name="Date", value=ann_session.date or "N/A", inline=True)
        embed.add_field(name="Time", value=ann_session.time or "N/A", inline=True)

        full_address = f"{ann_session.address}, {ann_session.city}, {ann_session.state} {ann_session.zipcode}"
        embed.add_field(name="Address", value=full_address, inline=False)

        if ann_session.flyer_url:
            embed.set_image(url=ann_session.flyer_url)

        return embed

    # ---------------------------------------------------------
    # UPDATED BROADCAST — embed-only message (NO WEBHOOK ERRORS)
    # ---------------------------------------------------------
    async def send_announcement_broadcast(self, interaction: discord.Interaction, ann_session: AnnouncementSession):
        if interaction.guild is None:
            await interaction.followup.send(
                "Announcements cannot be sent in DMs.",
                ephemeral=True
            )
            self.end_announcement_session(ann_session.user_id)
            return

        async with self.bot.db.acquire() as conn:
            settings = await conn.fetchrow(
                """
                SELECT upcoming_shows_channel_id
                FROM guild_settings
                WHERE guild_id = $1;
                """,
                interaction.guild.id
            )

        if not settings or not settings["upcoming_shows_channel_id"]:
            await interaction.followup.send(
                "Upcoming shows channel is not set. Please configure it in /botsettings.",
                ephemeral=True
            )
            self.end_announcement_session(ann_session.user_id)
            return

        channel_id = settings["upcoming_shows_channel_id"]
        channel = interaction.guild.get_channel(channel_id)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                channel = None

        if channel is None:
            await interaction.followup.send(
                "Upcoming shows channel could not be found. Please verify upcoming_shows_channel_id.",
                ephemeral=True
            )
            self.end_announcement_session(ann_session.user_id)
            return

        embed = self.build_announcement_embed(ann_session)
        await channel.send(embed=embed)

        await interaction.followup.send(
            "✅ Announcement sent.",
            ephemeral=True
        )

        self.end_announcement_session(ann_session.user_id)

    # ---------------------------------------------------------
    # DATE VALIDATION (OPTION C — Flexible Parsing)
    # ---------------------------------------------------------
    def validate_date(self, date_str):
        from dateutil import parser

        try:
            parsed = parser.parse(date_str)
            return parsed.date()
        except Exception:
            raise ValueError(
                "❌ Invalid date format.\n\n"
                "Try formats like:\n"
                "• **August 23, 2026**\n"
                "• **1/1/2028**\n"
                "• **Jan 1 2028**\n"
                "• **2028-01-01**"
            )

    def build_preview_embed(self, session):
        embed = discord.Embed(
            title=session.show_name or "Upcoming Show",
            color=discord.Color.gold()
        )

        embed.add_field(name="Date", value=session.date or "N/A", inline=True)
        embed.add_field(name="Time", value=session.time or "N/A", inline=True)

        full_address = f"{session.address}, {session.city}, {session.state} {session.zipcode}"
        embed.add_field(name="Address", value=full_address, inline=False)

        if session.flyer_url:
            embed.set_thumbnail(url=session.flyer_url)

        return embed

    # ---------------------------------------------------------
    # INSERT SHOW — NOW WITH EMBEDDED DATE ERROR (SAFE INTERACTION)
    # ---------------------------------------------------------
    async def insert_show_into_db(self, session, interaction):

        payload = session.to_db_payload()

        try:
            parsed_date = self.validate_date(payload["date"])
        except ValueError as e:
            embed = discord.Embed(
                title="❌ Invalid Date Format",
                description=str(e),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        query = """
            INSERT INTO upcoming_shows (show_name, date, time, address, city, state, zipcode, is_active, flyer_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, $8)
        """

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                query,
                payload["show_name"],
                parsed_date,
                payload["time"],
                payload["address"],
                payload["city"],
                payload["state"],
                payload["zipcode"],
                payload["flyer_url"]
            )

    async def cog_load(self):
        add_cmd = app_commands.Command(
            name="addshow",
            description="Add an upcoming show.",
            callback=self.addshow
        )

        remove_cmd = app_commands.Command(
            name="removeshow",
            description="Deactivate a show by ID.",
            callback=self.removeshow
        )

        edit_cmd = app_commands.Command(
            name="editshow",
            description="Edit an existing upcoming show.",
            callback=self.editshow
        )

        self.admin_group.add_command(add_cmd)
        self.admin_group.add_command(remove_cmd)
        self.admin_group.add_command(edit_cmd)
        self.bot.tree.add_command(self.admin_group)

    async def addshow(self, interaction: discord.Interaction):

        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Admin commands cannot be used in DMs.",
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            settings = await conn.fetchrow(
                """
                SELECT admin_channel_id
                FROM guild_settings
                WHERE guild_id = $1;
                """,
                interaction.guild.id
            )

        if not settings or not settings["admin_channel_id"]:
            await interaction.response.send_message(
                "❌ Admin channel is not set. Please configure it in guild_settings.",
                ephemeral=True
            )
            return

        admin_channel_id = settings["admin_channel_id"]
        admin_channel = interaction.guild.get_channel(admin_channel_id)
        if admin_channel is None:
            try:
                admin_channel = await self.bot.fetch_channel(admin_channel_id)
            except Exception:
                admin_channel = None

        if admin_channel is None:
            await interaction.response.send_message(
                "❌ Admin channel could not be found. Please verify the admin_channel_id.",
                ephemeral=True
            )
            return

        session = self.get_session(interaction.user.id)

        await admin_channel.send(
            f"**Add Show Wizard started by {interaction.user.mention}.**\n\nClick below to begin.",
            view=StartWizardView(self, session)
        )

        await interaction.response.send_message(
            "📬 The Add Show wizard has been started in the admin channel.",
            ephemeral=True
        )

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
        except Exception:
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
    # /adminshows editshow — MONTH → SHOW DROPDOWN WORKFLOW
    # ---------------------------------------------------------
    async def editshow(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Select a month:",
            view=EditShowMonthView(self),
            ephemeral=True
        )

    # ---------------------------------------------------------
    # FETCH SHOWS BY MONTH
    # ---------------------------------------------------------
    async def show_month_results(self, interaction, month):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT show_id, show_name, date
                FROM upcoming_shows
                WHERE is_active = TRUE AND EXTRACT(MONTH FROM date) = $1
                ORDER BY date ASC;
                """,
                month
            )

        if not rows:
            await interaction.response.send_message(
                f"No shows found in month {month}.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Select a show to edit:",
            view=EditShowSelectView(self, rows),
            ephemeral=True
        )

    # ---------------------------------------------------------
    # LOAD EDIT SESSION — SHOW PREVIEWVIEW (NOT WIZARD)
    # ---------------------------------------------------------
    async def load_edit_session(self, interaction, show_id):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT show_name, date, time, address, city, state, zipcode, flyer_url
                FROM upcoming_shows
                WHERE show_id = $1 AND is_active = TRUE;
                """,
                show_id
            )

        if not row:
            await interaction.response.send_message(
                f"❌ Show ID {show_id} not found.",
                ephemeral=True
            )
            return

        session = self.get_session(interaction.user.id)
        session.show_name = row["show_name"]
        session.date = str(row["date"])
        session.time = row["time"]
        session.address = row["address"]
        session.city = row["city"]
        session.state = row["state"]
        session.zipcode = row["zipcode"]
        session.flyer_url = row["flyer_url"]
        session.editing_show_id = show_id

        embed = self.build_preview_embed(session)

        await interaction.response.send_message(
            f"📋 Editing **{row['show_name']} — {row['date']}**.\n\nUse the dropdown below to edit fields.",
            embed=embed,
            view=PreviewView(self, session),
            ephemeral=True
        )

    # ---------------------------------------------------------
    # UPDATE SHOW — NOW WITH EMBEDDED DATE ERROR (SAFE INTERACTION)
    # ---------------------------------------------------------
    async def update_show_into_db(self, session, interaction):

        payload = session.to_db_payload()

        try:
            parsed_date = self.validate_date(payload["date"])
        except ValueError as e:
            embed = discord.Embed(
                title="❌ Invalid Date Format",
                description=str(e),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        query = """
            UPDATE upcoming_shows
            SET show_name = $1,
                date = $2,
                time = $3,
                address = $4,
                city = $5,
                state = $6,
                zipcode = $7,
                flyer_url = $8
            WHERE show_id = $9;
        """

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                query,
                payload["show_name"],
                parsed_date,
                payload["time"],
                payload["address"],
                payload["city"],
                payload["state"],
                payload["zipcode"],
                payload["flyer_url"],
                session.editing_show_id
            )

    # ---------------------------------------------------------
    # /upcomingshows — PAGINATION ENABLED
    # ---------------------------------------------------------
    @app_commands.command(name="upcomingshows", description="View upcoming shows.")
    async def upcomingshows(self, interaction: discord.Interaction):

        try:
            async with self.bot.db.acquire() as conn:

                rows = await conn.fetch(
                    """
                    SELECT show_id, show_name, date, time, address, city, state, zipcode, flyer_url
                    FROM upcoming_shows
                    WHERE is_active = TRUE
                    ORDER BY date ASC;
                    """
                )
        except Exception:
            embed = discord.Embed(
                title="❌ Database Error",
                description="Failed to load shows.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not rows:
            embed = discord.Embed(
                title="📅 Upcoming Shows",
                description="No upcoming shows are currently active.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        view = UpcomingShowsPagination(self, interaction, rows, page=0)

        await interaction.response.send_message(
            embeds=view.get_page_embeds(),
            view=view,
            ephemeral=True
        )


# ============================================================
#   START WIZARD VIEW
# ============================================================
class StartWizardView(discord.ui.View):
    def __init__(self, cog, session):
        super().__init__(timeout=300)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Start Wizard", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(
            ShowDetailsModal(self.cog, self.session)
        )


# ============================================================
#   SETUP
# ============================================================
async def setup(bot):
    await bot.add_cog(UpcomingShows(bot))


