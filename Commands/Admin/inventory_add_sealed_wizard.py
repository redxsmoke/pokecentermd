import discord
from discord import ui
from io import BytesIO

from Commands.BotSettings.admin_channel_helpers import (
    get_admin_channel,
    get_singles_role,
    get_singles_notifications_enabled,
    get_singles_channel
)


class SealedWizardStep:
    PRODUCT_TYPE = 1
    SERIES = 2
    SET_NAME = 3
    QUANTITY = 4
    PRICE = 5
    CONDITION = 6
    CONFIRM = 7


SEALED_CONDITIONS = [
    ("Sealed Mint", "No rips, tears, imperfections"),
    ("Sealed Near Mint", "Some minor tears or imperfections"),
    ("Sealed With Imperfections", "Large tears or noticeable imperfections"),
    ("Not sealed but unopened", "Seal broken but packs unopened"),
    ("Open Box", "Seal broken and pack(s) opened"),
]


class AddSealedWizardView(ui.View):
    def __init__(self, bot, user):
        super().__init__(timeout=1200)
        self.bot = bot
        self.user = user

        self.state = {
            "pokemon_name": None,
            "series": None,
            "set_name": None,
            "quantity_available": None,
            "price": None,
            "condition": None,
            "image_link": None,
        }

        self.step = SealedWizardStep.PRODUCT_TYPE
        self.message: discord.Message | None = None

    async def start(self, interaction: discord.Interaction):
        admin_channel = await get_admin_channel(self.bot, interaction.guild.id)

        if admin_channel is None:
            await interaction.response.send_message(
                "❌ Admin channel is not set. Use /bot_settings to configure it.",
                ephemeral=True
            )
            return

        embed = self.build_embed()

        # Initial message WITHOUT view
        self.message = await admin_channel.send(embed=embed)

        # Build UI immediately so select menus appear
        await self.update()

     
    async def update(self):
        self.clear_items()

        if self.step != SealedWizardStep.CONFIRM:
            self.add_item(self.back_button)
            self.add_item(self.next_button)

        if self.step == SealedWizardStep.PRODUCT_TYPE:
            await self.add_product_type_select()

        if self.step == SealedWizardStep.SERIES:
            await self.add_series_select()

        if self.step == SealedWizardStep.SET_NAME:
            await self.add_set_select()

        if self.step == SealedWizardStep.CONDITION:
            self.add_item(SealedConditionSelect(self))

        # Finish + Cancel buttons only at confirm
        self.finish_button.disabled = (self.step != SealedWizardStep.CONFIRM)
        self.cancel_button.disabled = (self.step != SealedWizardStep.CONFIRM)

        self.add_item(self.finish_button)
        self.add_item(self.cancel_button)

        embed = self.build_embed()
        await self.message.edit(embed=embed, view=self)

    def build_embed(self):
        if self.step == SealedWizardStep.PRODUCT_TYPE:
            return discord.Embed(
                title="Step 1 — Sealed Product Type",
                description="Select the type of sealed product.",
                color=discord.Color.blurple(),
            )

        if self.step == SealedWizardStep.SERIES:
            return discord.Embed(
                title="Step 2 — Series",
                description="Select the Series.",
                color=discord.Color.blurple(),
            )

        if self.step == SealedWizardStep.SET_NAME:
            return discord.Embed(
                title="Step 3 — Set",
                description="Select the Set.",
                color=discord.Color.blurple(),
            )

        if self.step == SealedWizardStep.QUANTITY:
            return discord.Embed(
                title="Step 4 — Quantity",
                description="Click **Next** to enter quantity.",
                color=discord.Color.blurple(),
            )

        if self.step == SealedWizardStep.PRICE:
            return discord.Embed(
                title="Step 5 — Price",
                description="Click **Next** to enter price.",
                color=discord.Color.blurple(),
            )

        if self.step == SealedWizardStep.CONDITION:
            return discord.Embed(
                title="Step 6 — Condition",
                description="Select the sealed product condition.",
                color=discord.Color.blurple(),
            )

        if self.step == SealedWizardStep.CONFIRM:
            embed = discord.Embed(
                title="Step 7 — Confirm",
                description="Review all details and click **Finish** or **Cancel**.",
                color=discord.Color.green(),
            )

            # Exclude image_link from preview
            for key, value in self.state.items():
                if key == "image_link":
                    continue

                embed.add_field(
                    name=key.replace("_", " ").title(),
                    value=str(value),
                    inline=False,
                )

            return embed

    async def add_product_type_select(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT product_name FROM sealed_product_list ORDER BY product_name"
            )

        options = [
            discord.SelectOption(label=row["product_name"], value=row["product_name"])
            for row in rows
        ]

        self.add_item(SealedProductTypeSelect(self, options))

    async def add_series_select(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT series FROM expansion_list ORDER BY series"
            )

        options = [
            discord.SelectOption(label=row["series"], value=row["series"])
            for row in rows
        ]

        self.add_item(SealedSeriesSelect(self, options))

    async def add_set_select(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT set_name FROM expansion_list WHERE series = $1 ORDER BY set_name",
                self.state["series"],
            )

        options = [
            discord.SelectOption(label=row["set_name"], value=row["set_name"])
            for row in rows
        ]

        self.add_item(SealedSetSelect(self, options))

    @ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.step == SealedWizardStep.PRODUCT_TYPE:
            await interaction.response.defer()
            return

        self.step -= 1
        await interaction.response.defer()
        await self.update()

    @ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.step == SealedWizardStep.QUANTITY:
            await interaction.response.send_modal(SealedQuantityModal(self))
            return

        if self.step == SealedWizardStep.PRICE:
            await interaction.response.send_modal(SealedPriceModal(self))
            return

        if self.step == SealedWizardStep.CONDITION:
            self.step = SealedWizardStep.CONFIRM
            await interaction.response.defer()
            await self.update()
            return

        if self.step == SealedWizardStep.CONFIRM:
            await self.finish_wizard(interaction)
            return

        self.step += 1
        await interaction.response.defer()
        await self.update()

    @ui.button(label="Finish", style=discord.ButtonStyle.success, disabled=True)
    async def finish_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.finish_wizard(interaction)

    @ui.button(label="Cancel", style=discord.ButtonStyle.danger, disabled=True)
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
  
        # Update admin channel message
        cancel_embed = discord.Embed(
            title="Wizard Cancelled",
            description="No sealed product was added.",
            color=discord.Color.red()
        )
        await self.message.edit(embed=cancel_embed, view=None)

        self.stop()

    async def finish_wizard(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Upload Image",
            description="Would you like to upload an image for this sealed product?",
            color=discord.Color.blurple(),
        )

        view = SealedImageDecisionView(self.bot, self.state, self.user)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        self.stop()


class SealedProductTypeSelect(ui.Select):
    def __init__(self, wizard, options):
        super().__init__(placeholder="Select Sealed Product Type", options=options)
        self.wizard = wizard

    async def callback(self, interaction):
        self.wizard.state["pokemon_name"] = self.values[0]
        self.wizard.step = SealedWizardStep.SERIES
        await interaction.response.defer()
        await self.wizard.update()


class SealedSeriesSelect(ui.Select):
    def __init__(self, wizard, options):
        super().__init__(placeholder="Select Series", options=options)
        self.wizard = wizard

    async def callback(self, interaction):
        self.wizard.state["series"] = self.values[0]
        self.wizard.step = SealedWizardStep.SET_NAME
        await interaction.response.defer()
        await self.wizard.update()


class SealedSetSelect(ui.Select):
    def __init__(self, wizard, options):
        super().__init__(placeholder="Select Set", options=options)
        self.wizard = wizard

    async def callback(self, interaction):
        self.wizard.state["set_name"] = self.values[0]
        self.wizard.step = SealedWizardStep.QUANTITY
        await interaction.response.defer()
        await self.wizard.update()


class SealedConditionSelect(ui.Select):
    def __init__(self, wizard):
        options = [
            discord.SelectOption(label=name, value=name, description=desc)
            for name, desc in SEALED_CONDITIONS
        ]
        super().__init__(placeholder="Select Condition", options=options)
        self.wizard = wizard

    async def callback(self, interaction):
        self.wizard.state["condition"] = self.values[0]
        self.wizard.step = SealedWizardStep.CONFIRM
        await interaction.response.defer()
        await self.wizard.update()


class SealedQuantityModal(ui.Modal, title="Enter Quantity"):
    quantity = ui.TextInput(label="Quantity")

    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction):
        try:
            self.wizard.state["quantity_available"] = int(self.quantity.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Invalid Quantity",
                    description="Quantity must be an integer.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        self.wizard.step = SealedWizardStep.PRICE
        await interaction.response.defer()
        await self.wizard.update()


class SealedPriceModal(ui.Modal, title="Enter Price"):
    price = ui.TextInput(label="Price")

    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction):
        try:
            self.wizard.state["price"] = float(self.price.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Invalid Price",
                    description="Price must be a number.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        self.wizard.step = SealedWizardStep.CONDITION
        await interaction.response.defer()
        await self.wizard.update()


class SealedImageDecisionView(ui.View):
    def __init__(self, bot, state, user):
        super().__init__(timeout=600)
        self.bot = bot
        self.state = state
        self.user = user

    @ui.button(label="Upload Image", style=discord.ButtonStyle.primary)
    async def upload_image(self, interaction, button):
        embed = discord.Embed(
            title="Upload Image",
            description="Upload an image in this channel. I will use the first attachment you send.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        def check(m):
            return (
                m.author.id == self.user.id
                and m.channel.id == interaction.channel.id
                and m.attachments
            )

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=120)
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

        admin_channel = await get_admin_channel(self.bot, interaction.guild.id)
        if admin_channel is None:
            await interaction.followup.send(
                "❌ Admin channel is not set. Use /bot_settings to configure it.",
                ephemeral=True
            )
            return

        file = discord.File(BytesIO(file_bytes), filename="sealed.jpg")
        sent_msg = await admin_channel.send(file=file)

        url = sent_msg.attachments[0].url
        if "?" in url:
            url = url.split("?")[0]

        self.state["image_link"] = url

        await insert_sealed_into_db(self.state, self.bot, interaction.guild.id)
        await send_sealed_notification(self.bot, interaction.guild.id)

        done = discord.Embed(
            title="Sealed Product Added",
            description="Sealed product added successfully.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=done, ephemeral=True)
        self.stop()

    @ui.button(label="Don't Upload Image", style=discord.ButtonStyle.secondary)
    async def skip_image(self, interaction, button):
        self.state["image_link"] = None

        await insert_sealed_into_db(self.state, self.bot, interaction.guild.id)
        await send_sealed_notification(self.bot, interaction.guild.id)

        embed = discord.Embed(
            title="Sealed Product Added",
            description="Sealed product added successfully.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        self.stop()


async def insert_sealed_into_db(state, bot, guild_id):
    async with bot.db.acquire() as conn:

        # Look up sealed_product_id from sealed_product_list
        sealed_product_id = await conn.fetchval(
            """
            SELECT product_id
            FROM sealed_product_list
            WHERE product_name = $1
            """,
            state["pokemon_name"]
        )

        # Check for an existing matching sealed product
        existing = await conn.fetchrow(
            """
            SELECT inventory_id, quantity_available
            FROM inventory
            WHERE guild_id = $1
              AND csv_id = 'sealed_add'
              AND sealed_product_id = $2
              AND series = $3
              AND set_name = $4
              AND condition = $5
              AND price = $6
              AND is_active = TRUE
            """,
            guild_id,
            sealed_product_id,
            state["series"],
            state["set_name"],
            state["condition"],
            float(state["price"])
        )

        # If exists → update quantity_available
        if existing:
            new_qty = existing["quantity_available"] + state["quantity_available"]

            await conn.execute(
                """
                UPDATE inventory
                SET quantity_available = $1
                WHERE inventory_id = $2
                """,
                new_qty,
                existing["inventory_id"]
            )
            return  # Done — no new row created

        # Otherwise → insert new sealed inventory row
        await conn.execute(
            """
            INSERT INTO inventory (
                csv_id, pokemon_name, series, set_name, card_number,
                variant, rarity, price, graded, grading_company, grade,
                quantity_available, image_link, condition,
                date_added, illustrator, guild_id,
                sealed_product_id
            )
            VALUES (
                'sealed_add', $1, $2, $3, NULL,
                NULL, NULL, $4, NULL, NULL, NULL,
                $5, $6, $7,
                CURRENT_DATE, NULL, $8,
                $9
            )
            """,
            state["pokemon_name"],
            state["series"],
            state["set_name"],
            float(state["price"]),
            state["quantity_available"],
            state["image_link"],
            state["condition"],
            guild_id,
            sealed_product_id
        )




async def send_sealed_notification(bot, guild_id):
    notifications_enabled = await get_singles_notifications_enabled(bot, guild_id)
    if not notifications_enabled:
        return

    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT inventory_id, pokemon_name, condition, price, series, set_name, image_link
            FROM inventory
            WHERE guild_id = $1
              AND date_added = CURRENT_DATE
            ORDER BY inventory_id DESC
            LIMIT 1
            """,
            guild_id
        )

    if not row:
        return

    singles_channel = await get_singles_channel(bot, guild_id)
    singles_role = await get_singles_role(bot, guild_id)
    ping_text = singles_role.mention if singles_role else ""

    if singles_channel is None:
        admin_channel = await get_admin_channel(bot, guild_id)
        if admin_channel:
            await admin_channel.send(
                embed=discord.Embed(
                    title="⚠️ Sealed Notification Not Sent",
                    description=(
                        "A new sealed product notification was **not sent** because no "
                        "Singles Notification Channel has been configured.\n\n"
                        "Please set one using:\n"
                        "**/admin bot_settings → Set Singles Notification Channel**\n\n"
                        "Or disable Singles notifications using:\n"
                        "**/admin bot_settings → Toggle Singles Notifications**"
                    ),
                    color=discord.Color.orange()
                )
            )
        return

    embed = discord.Embed(
        title="📢 New Sealed Product Added!",
        description="A new sealed product has just been added to the shop.",
        color=discord.Color.blue()
    )

    embed.add_field(name="Product", value=row["pokemon_name"], inline=False)
    embed.add_field(name="Condition", value=row["condition"], inline=False)
    embed.add_field(name="Price", value=f"${row['price']}", inline=False)
    embed.add_field(name="Series", value=row["series"], inline=False)
    embed.add_field(name="Set", value=row["set_name"], inline=False)

    if row["image_link"]:
        embed.set_thumbnail(url=row["image_link"])

    await singles_channel.send(content=ping_text, embed=embed)


async def start_add_sealed_wizard(interaction: discord.Interaction, bot):
    view = AddSealedWizardView(bot, interaction.user)
    await view.start(interaction)
