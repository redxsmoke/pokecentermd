import discord
from discord.ext import commands
from discord import ui
from io import BytesIO

class WizardStep:
    POKEMON_NAME = 1
    SERIES = 2
    SET_NAME = 3
    PRICE = 4
    CONDITION = 5
    GRADED_FIELDS = 6
    CONFIRM = 7


class UpdateSingleWizardView(ui.View):
    def __init__(self, bot, user):
        super().__init__(timeout=1200)
        self.bot = bot
        self.user = user

        self.state = {
            "pokemon_name": None,
            "card_number": None,
            "series": None,
            "set_name": None,
            "quantity_available": None,
            "price": None,
            "condition": None,
            "variant": None,
            "rarity": None,
            "graded": False,
            "grading_company": None,
            "grade": None,
            "image_link": None,
            "inventory_id": None,
        }

        self.step = WizardStep.POKEMON_NAME
        self.message: discord.Message | None = None

    async def update(self):
        self.clear_items()

        self.add_item(self.back_button)
        self.add_item(self.next_button)

        if self.step == WizardStep.SERIES:
            await self.add_series_select()

        if self.step == WizardStep.SET_NAME:
            await self.add_set_select()

        if self.step == WizardStep.CONDITION:
            self.add_item(ConditionSelect(self))

        if self.step == WizardStep.GRADED_FIELDS and self.state["graded"]:
            self.add_item(GradingCompanySelect(self))
            self.add_item(GradeSelect(self))

        self.finish_button.disabled = (self.step != WizardStep.CONFIRM)
        self.add_item(self.finish_button)

        embed = self.build_embed()
        await self.message.edit(embed=embed, view=self)

    def build_embed(self):
        if self.step == WizardStep.POKEMON_NAME:
            return discord.Embed(
                title="Step 1 — Card Details",
                description="Click **Next** to enter Pokémon name, card number, variant, rarity, and quantity.",
                color=discord.Color.blurple(),
            )

        if self.step == WizardStep.SERIES:
            return discord.Embed(
                title="Step 2 — Series",
                description="Select the Series from the dropdown.",
                color=discord.Color.blurple(),
            )

        if self.step == WizardStep.SET_NAME:
            return discord.Embed(
                title="Step 3 — Set",
                description="Select the Set from the dropdown.",
                color=discord.Color.blurple(),
            )

        if self.step == WizardStep.PRICE:
            return discord.Embed(
                title="Step 4 — Price",
                description="Click **Next** to enter the price.",
                color=discord.Color.blurple(),
            )

        if self.step == WizardStep.CONDITION:
            return discord.Embed(
                title="Step 5 — Condition",
                description="Select the card condition.",
                color=discord.Color.blurple(),
            )

        if self.step == WizardStep.GRADED_FIELDS:
            return discord.Embed(
                title="Step 6 — Graded Fields",
                description="Select grading company and grade.",
                color=discord.Color.blurple(),
            )

        if self.step == WizardStep.CONFIRM:
            embed = discord.Embed(
                title="Step 7 — Confirm",
                description="Review all details and click **Finish**.",
                color=discord.Color.green(),
            )

            for key, value in self.state.items():
                embed.add_field(
                    name=key.replace("_", " ").title(),
                    value=str(value),
                    inline=False,
                )

            return embed

    async def add_series_select(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT series FROM expansion_list ORDER BY series"
            )

        options = [
            discord.SelectOption(label=row["series"], value=row["series"])
            for row in rows
        ]

        self.add_item(SeriesSelect(self, options))

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

        self.add_item(SetSelect(self, options))

    @ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.step == WizardStep.POKEMON_NAME:
            await interaction.response.defer()
            return

        self.step -= 1
        await interaction.response.defer()
        await self.update()

    @ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.step == WizardStep.POKEMON_NAME:
            await interaction.response.send_modal(CombinedCardInfoModal(self))
            return

        if self.step == WizardStep.PRICE:
            await interaction.response.send_modal(PriceModal(self))
            return

        if self.step == WizardStep.CONDITION:
            if self.state["graded"]:
                self.step = WizardStep.GRADED_FIELDS
            else:
                self.step = WizardStep.CONFIRM
            await interaction.response.defer()
            await self.update()
            return

        if self.step == WizardStep.GRADED_FIELDS:
            self.step = WizardStep.CONFIRM
            await interaction.response.defer()
            await self.update()
            return

        if self.step == WizardStep.CONFIRM:
            await self.finish_wizard(interaction)
            return

    @ui.button(label="Finish", style=discord.ButtonStyle.success, disabled=True)
    async def finish_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.finish_wizard(interaction)

    async def finish_wizard(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Card Details Captured",
            description="Would you like to add an image for this card?",
            color=discord.Color.blurple(),
        )

        view = ImageDecisionView(self.bot, self.state, self.user)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        self.stop()


class ConditionSelect(ui.Select):
    def __init__(self, wizard: UpdateSingleWizardView):
        options = [
            discord.SelectOption(label="Near Mint", value="Near Mint"),
            discord.SelectOption(label="Lightly Played", value="Lightly Played"),
            discord.SelectOption(label="Moderately Played", value="Moderately Played"),
            discord.SelectOption(label="Heavily Played", value="Heavily Played"),
            discord.SelectOption(label="Damaged", value="Damaged"),
            discord.SelectOption(label="Graded", value="Graded"),
        ]
        super().__init__(placeholder="Select Condition", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        cond = self.values[0]
        self.wizard.state["condition"] = cond
        self.wizard.state["graded"] = cond == "Graded"

        self.wizard.step = WizardStep.GRADED_FIELDS if self.wizard.state["graded"] else WizardStep.CONFIRM

        await interaction.response.defer()
        await self.wizard.update()


class SeriesSelect(ui.Select):
    def __init__(self, wizard: UpdateSingleWizardView, options: list[discord.SelectOption]):
        super().__init__(placeholder="Select Series", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.state["series"] = self.values[0]
        self.wizard.step = WizardStep.SET_NAME
        await interaction.response.defer()
        await self.wizard.update()


class SetSelect(ui.Select):
    def __init__(self, wizard: UpdateSingleWizardView, options: list[discord.SelectOption]):
        super().__init__(placeholder="Select Set", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.state["set_name"] = self.values[0]
        self.wizard.step = WizardStep.PRICE
        await interaction.response.defer()
        await self.wizard.update()


class GradingCompanySelect(ui.Select):
    def __init__(self, wizard: UpdateSingleWizardView):
        options = [
            discord.SelectOption(label="PSA", value="PSA"),
            discord.SelectOption(label="CGC", value="CGC"),
            discord.SelectOption(label="TAG", value="TAG"),
            discord.SelectOption(label="Beckett", value="Beckett"),
            discord.SelectOption(label="SGC", value="SGC"),
            discord.SelectOption(label="ACE", value="ACE"),
            discord.SelectOption(label="Other", value="Other"),
        ]
        super().__init__(placeholder="Select Grading Company", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.state["grading_company"] = self.values[0]
        await interaction.response.defer()
        await self.wizard.update()


class GradeSelect(ui.Select):
    def __init__(self, wizard: UpdateSingleWizardView):
        options = [discord.SelectOption(label=str(i), value=str(i)) for i in range(1, 11)]
        options.append(discord.SelectOption(label="Enter custom grade", value="custom"))
        super().__init__(placeholder="Select Grade", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "custom":
            await interaction.response.send_modal(CustomGradeModal(self.wizard))
            return

        self.wizard.state["grade"] = val
        await interaction.response.defer()
        await self.wizard.update()


class CustomGradeModal(ui.Modal, title="Enter Custom Grade"):
    grade = ui.TextInput(label="Custom Grade")

    def __init__(self, wizard: UpdateSingleWizardView):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        self.wizard.state["grade"] = self.grade.value.strip()
        await interaction.response.defer()
        await self.wizard.update()


class CombinedCardInfoModal(ui.Modal, title="Card Details"):
    pokemon_name = ui.TextInput(label="Pokémon Name")
    card_number = ui.TextInput(label="Card Number")
    variant = ui.TextInput(label="Variant", required=False)
    rarity = ui.TextInput(label="Rarity", required=False)
    quantity = ui.TextInput(label="Quantity")

    def __init__(self, wizard: UpdateSingleWizardView):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        self.wizard.state["pokemon_name"] = self.pokemon_name.value.strip()
        self.wizard.state["card_number"] = self.card_number.value.strip()
        self.wizard.state["variant"] = self.variant.value.strip() or None
        self.wizard.state["rarity"] = self.rarity.value.strip() or None

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

        self.wizard.step = WizardStep.SERIES
        await interaction.response.defer()
        await self.wizard.update()


class PriceModal(ui.Modal, title="Enter Price"):
    price = ui.TextInput(label="Price")

    def __init__(self, wizard: UpdateSingleWizardView):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
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

        self.wizard.step = WizardStep.CONDITION
        await interaction.response.defer()
        await self.wizard.update()


class ImageDecisionView(ui.View):
    def __init__(self, bot, state, user):
        super().__init__(timeout=600)
        self.bot = bot
        self.state = state
        self.user = user

        # The original image is stored BEFORE the wizard mutates state
        self.original_image = state.get("original_image")

        # Dynamic button labels
        if self.original_image:
            self.upload_image.label = "Update Image"
            self.skip_image.label = "Don't Update Image"
        else:
            self.upload_image.label = "Upload Image"
            self.skip_image.label = "Don't Upload Image"

    @ui.button(label="Upload Image", style=discord.ButtonStyle.primary)
    async def upload_image(self, interaction: discord.Interaction, button: ui.Button):

        # Ask user to upload an image
        embed = discord.Embed(
            title="Upload Image",
            description="Please upload an image in this channel. I will use the first attachment you send.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Wait for the user's image
        def check(m: discord.Message):
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

        # Upload image to admin channel
        file = discord.File(BytesIO(file_bytes), filename="card.jpg")
        sent_msg = await admin_channel.send(file=file)

        url = sent_msg.attachments[0].url
        if "?" in url:
            url = url.split("?")[0]

        # Replace image with new one
        self.state["image_link"] = url

        await update_card_in_db(
            self.state,
            self.bot,
            interaction.guild.id,
            self.state["inventory_id"]
        )

        done = discord.Embed(
            title="Card Updated",
            description="Details for this card have been updated successfully.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=done, ephemeral=True)
        self.stop()

    @ui.button(label="Don't Upload Image", style=discord.ButtonStyle.secondary)
    async def skip_image(self, interaction: discord.Interaction, button: ui.Button):

        # Restore original image (THIS IS THE FIX)
        self.state["image_link"] = self.original_image

        await update_card_in_db(
            self.state,
            self.bot,
            interaction.guild.id,
            self.state["inventory_id"]
        )

        embed = discord.Embed(
            title="Card Updated",
            description="Details for this card have been updated successfully.",
            color=discord.Color.green(),
        )

        # FIX: followup.send prevents timeout
        await interaction.followup.send(embed=embed, ephemeral=True)

        self.stop()

    @ui.button(label="Don't Upload Image", style=discord.ButtonStyle.secondary)
    async def skip_image(self, interaction: discord.Interaction, button: ui.Button):

        # Correct: restore original image
        self.state["image_link"] = self.original_image

        await update_card_in_db(
            self.state,
            self.bot,
            interaction.guild.id,
            self.state["inventory_id"]
        )
        ...


async def update_card_in_db(state, bot, guild_id, inventory_id):
    async with bot.db.acquire() as conn:

        # --- UPDATE THE CARD ---
        await conn.execute(
            """
            UPDATE inventory
            SET
                pokemon_name = $1,
                series = $2,
                set_name = $3,
                card_number = $4,
                variant = $5,
                rarity = $6,
                price = $7,
                graded = $8,
                grading_company = $9,
                grade = $10,
                quantity_available = $11,
                image_link = $12,
                condition = $13,
                guild_id = $14
            WHERE inventory_id = $15
            """,
            state["pokemon_name"],
            state["series"],
            state["set_name"],
            state["card_number"],
            state["variant"],
            state["rarity"],
            float(state["price"]),
            state["graded"],
            state["grading_company"],
            state["grade"],
            state["quantity_available"],
            state["image_link"],
            state["condition"],
            guild_id,
            inventory_id
        )

        # --- FETCH WISHLIST FILTERS ---
        filters = await conn.fetch(
            """
            SELECT *
            FROM user_wishlist
            WHERE guild_id = $1
            """,
            guild_id
        )

        # --- CHECK FOR MATCHES ---
        for f in filters:
            match = True

            # pokemon_name (LIKE match)
            if f["pokemon_name"] and f["pokemon_name"].lower() not in state["pokemon_name"].lower():
                match = False

            # variant
            if f["variant"] and f["variant"].lower() not in (state["variant"] or "").lower():
                match = False

            # price <= wishlist price
            if f["price"] is not None and float(state["price"]) > f["price"]:
                match = False

            # condition exact match
            if f["condition"] and f["condition"] != state["condition"]:
                match = False

            # series exact match
            if f["series"] and f["series"] != state["series"]:
                match = False

            # set_name exact match
            if f["set_name"] and f["set_name"] != state["set_name"]:
                match = False

            if not match:
                continue

            # --- SEND DM TO USER ---
            try:
                user = await bot.fetch_user(f["user_id"])

                embed = discord.Embed(
                    title="Wishlist Match Found!",
                    description=(
                        f"A card matching your wishlist was updated:\n\n"
                        f"**{state['pokemon_name']}**\n"
                        f"Series: {state['series']}\n"
                        f"Set: {state['set_name']}\n"
                        f"Condition: {state['condition']}\n"
                        f"Price: ${state['price']}"
                    ),
                    color=discord.Color.green()
                )

                # ⭐ Add image thumbnail if available
                if state["image_link"]:
                    embed.set_thumbnail(url=state["image_link"])

                await user.send(embed=embed)

            except Exception as e:
                print(f"Failed to DM user {f['user_id']}: {e}")

async def get_admin_channel(bot, guild_id):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT admin_channel_id FROM guild_settings WHERE guild_id = $1",
            guild_id
        )

    if row and row["admin_channel_id"]:
        return bot.get_channel(row["admin_channel_id"])

    return None


async def start_update_single_wizard(
    interaction: discord.Interaction,
    bot: commands.Bot,
    inventory_id: int,
    card_row: dict
):

    admin_channel = await get_admin_channel(bot, interaction.guild.id)

    if admin_channel is None:
        await interaction.response.send_message(
            "❌ Admin channel is not set. Use /bot_settings to configure it.",
            ephemeral=True
        )
        return

    view = UpdateSingleWizardView(bot, interaction.user)
    view.state["inventory_id"] = inventory_id
    view.state["original_image"] = card_row.get("image_link")
    view.state["image_link"] = card_row.get("image_link")

    embed = view.build_embed()
    msg = await admin_channel.send(embed=embed, view=view)
    view.message = msg
    await interaction.response.defer(ephemeral=True)




__all__ = [
    "UpdateSingleWizardView",
    "start_update_single_wizard",
    "WizardStep",
    "ConditionSelect",
    "SeriesSelect",
    "SetSelect",
    "GradingCompanySelect",
    "GradeSelect",
    "CustomGradeModal",
    "CombinedCardInfoModal",
    "PriceModal",
    "ImageDecisionView",
]