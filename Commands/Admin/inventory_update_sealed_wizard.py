import discord
from discord import ui
from io import BytesIO

from Commands.BotSettings.admin_channel_helpers import get_admin_channel

SEALED_CONDITIONS = [
    ("Sealed Mint", "No rips, tears, imperfections"),
    ("Sealed Near Mint", "Some minor tears or imperfections"),
    ("Sealed With Imperfections", "Large tears or noticeable imperfections"),
    ("Not sealed but unopened", "Seal broken but packs unopened"),
    ("Open Box", "Seal broken and pack(s) opened"),
]


class UpdateSealedWizardView(ui.View):
    def __init__(self, bot, user, guild_id):
        super().__init__(timeout=1200)
        self.bot = bot
        self.user = user
        self.guild_id = guild_id

        self.product_name: str | None = None
        self.inventory_id: int | None = None
        self.inventory_row: dict | None = None

        self.message: discord.Message | None = None

    async def start(self, admin_channel: discord.TextChannel):
        embed = discord.Embed(
            title="Update Sealed Product — Step 1",
            description="Select a sealed product type to manage.",
            color=discord.Color.blurple(),
        )

        self.message = await admin_channel.send(embed=embed)
        await self.build_product_select()
        await self.message.edit(view=self)

    async def build_product_select(self):
        self.clear_items()

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT sp.product_name
                FROM inventory i
                JOIN sealed_product_list sp
                  ON sp.product_id = i.sealed_product_id
                WHERE i.guild_id = $1
                  AND i.csv_id = 'sealed_add'
                  AND i.sealed_product_id IS NOT NULL
                  AND i.is_active = TRUE
                  AND i.quantity_available >= 0
                ORDER BY sp.product_name ASC;
                """,
                self.guild_id,
            )

        options = [
            discord.SelectOption(label=row["product_name"], value=row["product_name"])
            for row in rows
        ]

        if not options:
            options = [discord.SelectOption(label="No sealed products available", value="__none__")]

        select = SealedUpdateProductTypeSelect(self, options)
        self.add_item(select)

    async def build_inventory_select(self):
        self.clear_items()

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    inventory_id,
                    pokemon_name,
                    series,
                    set_name,
                    price,
                    quantity_available
                FROM inventory i
                JOIN sealed_product_list sp
                  ON sp.product_id = i.sealed_product_id
                WHERE i.guild_id = $1
                  AND i.csv_id = 'sealed_add'
                  AND i.sealed_product_id IS NOT NULL
                  AND i.is_active = TRUE
                  AND sp.product_name = $2
                ORDER BY i.price ASC, i.series ASC, i.set_name ASC;
                """,
                self.guild_id,
                self.product_name,
            )

        options = []
        for row in rows:
            label = (
                f"{row['pokemon_name']} — {row['series']} — {row['set_name']} — "
                f"${row['price']} — Qty: {row['quantity_available']}"
            )
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(row["inventory_id"])
                )
            )

        if not options:
            options = [discord.SelectOption(label="No matching inventory rows", value="__none__")]

        select = SealedUpdateInventorySelect(self, options)
        self.add_item(select)

    async def load_inventory_row(self):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    inventory_id,
                    pokemon_name,
                    series,
                    set_name,
                    price,
                    quantity_available,
                    condition,
                    image_link,
                    sealed_product_id
                FROM inventory
                WHERE inventory_id = $1
                  AND guild_id = $2
                  AND csv_id = 'sealed_add'
                  AND sealed_product_id IS NOT NULL
                """,
                self.inventory_id,
                self.guild_id,
            )
        self.inventory_row = row

    async def build_action_buttons(self):
        self.clear_items()
        self.add_item(self.update_button)
        self.add_item(self.delete_button)

    @ui.button(label="Update Sealed Product", style=discord.ButtonStyle.primary)
    async def update_button(self, interaction: discord.Interaction, button: ui.Button):
        if not self.inventory_row:
            embed = discord.Embed(
                title="No Product Selected",
                description="Please select a sealed product first.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await self.show_field_select(interaction)

    @ui.button(label="Delete Sealed Product", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, button: ui.Button):
        if not self.inventory_row:
            embed = discord.Embed(
                title="No Product Selected",
                description="Please select a sealed product first.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await self.show_delete_confirmation(interaction)

    async def show_field_select(self, interaction: discord.Interaction):
        self.clear_items()

        options = [
            discord.SelectOption(label="Product Type", value="product_type"),
            discord.SelectOption(label="Series / Set", value="series_set"),
            discord.SelectOption(label="Price", value="price"),
            discord.SelectOption(label="Quantity Available", value="quantity"),
            discord.SelectOption(label="Condition", value="condition"),
            discord.SelectOption(label="Image", value="image"),
        ]

        field_select = SealedUpdateFieldSelect(self, options)
        self.add_item(field_select)

        embed = discord.Embed(
            title="Update Sealed Product — Select Field",
            description="Choose which field you want to update.",
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def show_delete_confirmation(self, interaction: discord.Interaction):
        self.clear_items()

        self.add_item(self.delete_confirm_button)
        self.add_item(self.delete_cancel_button)

        embed = discord.Embed(
            title="Confirm Delete Sealed Product",
            description=(
                "Are you sure you want to delete this product? All images and meta data will also be deleted. "
                "If you have 0 quantity available, but plan to add more, it is recommended to update the available "
                "quantity to 0."
            ),
            color=discord.Color.red(),
        )

        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def delete_confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM inventory
                WHERE inventory_id = $1
                  AND guild_id = $2
                  AND csv_id = 'sealed_add'
                  AND sealed_product_id IS NOT NULL
                """,
                self.inventory_id,
                self.guild_id,
            )

        embed = discord.Embed(
            title="Sealed Product Deleted",
            description="The sealed product has been deleted from inventory.",
            color=discord.Color.green(),
        )

        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def delete_cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="Delete Cancelled",
            description="The sealed product was not deleted.",
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    async def show_post_update_actions(self, interaction: discord.Interaction, field_name: str):
        self.clear_items()

        self.add_item(self.confirm_button)
        self.add_item(self.update_another_button)

        embed = discord.Embed(
            title="Field Updated",
            description=f"{field_name} has been updated successfully.\n\nChoose an option below.",
            color=discord.Color.green(),
        )

        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="Update Complete",
            description="Sealed product updates have been saved.",
            color=discord.Color.green(),
        )

        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    @ui.button(label="Update Another Field", style=discord.ButtonStyle.secondary)
    async def update_another_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.show_field_select(interaction)

    async def handle_update_product_type(self, interaction: discord.Interaction):
        self.clear_items()

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT product_id, product_name
                FROM sealed_product_list
                ORDER BY product_name ASC;
                """
            )

        options = [
            discord.SelectOption(label=row["product_name"], value=str(row["product_id"]))
            for row in rows
        ]

        select = SealedUpdateProductTypeChangeSelect(self, options)
        self.add_item(select)

        embed = discord.Embed(
            title="Update Product Type",
            description="Select a new sealed product type.",
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def handle_update_series_set(self, interaction: discord.Interaction):
        self.clear_items()

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT series
                FROM expansion_list
                ORDER BY series ASC;
                """
            )

        options = [
            discord.SelectOption(label=row["series"], value=row["series"])
            for row in rows
        ]

        series_select = SealedUpdateSeriesSelect(self, options)
        self.add_item(series_select)

        embed = discord.Embed(
            title="Update Series / Set",
            description="Select a new Series.",
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def handle_update_price(self, interaction: discord.Interaction):
        modal = SealedUpdatePriceModal(self)
        await interaction.response.send_modal(modal)

    async def handle_update_quantity(self, interaction: discord.Interaction):
        modal = SealedUpdateQuantityModal(self)
        await interaction.response.send_modal(modal)

    async def handle_update_condition(self, interaction: discord.Interaction):
        self.clear_items()

        options = [
            discord.SelectOption(label=name, value=name, description=desc)
            for name, desc in SEALED_CONDITIONS
        ]

        condition_select = SealedUpdateConditionSelect(self, options)
        self.add_item(condition_select)

        embed = discord.Embed(
            title="Update Condition",
            description="Select a new condition for this sealed product.",
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def handle_update_image(self, interaction: discord.Interaction):
        self.clear_items()

        embed = discord.Embed(
            title="Update Image",
            description="Upload a new image in this channel. I will use the first attachment you send.",
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(embed=embed, view=self)

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

        admin_channel = await get_admin_channel(self.bot, self.guild_id)
        file = discord.File(BytesIO(file_bytes), filename="sealed_update.jpg")
        sent_msg = await admin_channel.send(file=file)

        url = sent_msg.attachments[0].url
        if "?" in url:
            url = url.split("?")[0]

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET image_link = $1
                WHERE inventory_id = $2
                  AND guild_id = $3
                  AND csv_id = 'sealed_add'
                  AND sealed_product_id IS NOT NULL
                """,
                url,
                self.inventory_id,
                self.guild_id,
            )

        await self.load_inventory_row()

        # GREEN CONFIRMATION EMBED
        confirm_embed = discord.Embed(
            title="Image Updated Successfully",
            description="The sealed product image has been updated.",
            color=discord.Color.green(),
        )

        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

        await self.show_post_update_actions(
            interaction,
            field_name="Image"
        )


class SealedUpdateProductTypeSelect(ui.Select):
    def __init__(self, wizard: UpdateSealedWizardView, options):
        super().__init__(placeholder="Select Sealed Product Type", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__none__":
            await interaction.response.send_message(
                "No sealed products available for this guild.",
                ephemeral=True
            )
            return

        self.wizard.product_name = self.values[0]

        embed = discord.Embed(
            title="Update Sealed Product — Step 2",
            description="Select the specific sealed inventory entry to manage.",
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(embed=embed, view=self.wizard)
        await self.wizard.build_inventory_select()
        await interaction.message.edit(view=self.wizard)


class SealedUpdateInventorySelect(ui.Select):
    def __init__(self, wizard: UpdateSealedWizardView, options):
        super().__init__(placeholder="Select Sealed Inventory Entry", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__none__":
            await interaction.response.send_message(
                "No inventory rows found for this product.",
                ephemeral=True
            )
            return

        self.wizard.inventory_id = int(self.values[0])
        await self.wizard.load_inventory_row()
        await self.wizard.build_action_buttons()

        row = self.wizard.inventory_row

        embed = discord.Embed(
            title="Selected Sealed Product",
            description="You can now update or delete this sealed product.",
            color=discord.Color.blurple(),
        )

        embed.add_field(name="Product Type", value=row["pokemon_name"], inline=False)
        embed.add_field(name="Series", value=row["series"], inline=True)
        embed.add_field(name="Set", value=row["set_name"], inline=True)
        embed.add_field(name="Price", value=f"${row['price']}", inline=True)
        embed.add_field(name="Quantity Available", value=row["quantity_available"], inline=True)
        embed.add_field(name="Condition", value=row["condition"], inline=True)

        if row["image_link"]:
            embed.set_thumbnail(url=row["image_link"])

        await interaction.response.edit_message(embed=embed, view=self.wizard)


class SealedUpdateFieldSelect(ui.Select):
    def __init__(self, wizard: UpdateSealedWizardView, options):
        super().__init__(placeholder="Select Field to Update", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]

        if selected == "product_type":
            await self.wizard.handle_update_product_type(interaction)
            return

        if selected == "series_set":
            await self.wizard.handle_update_series_set(interaction)
            return

        if selected == "price":
            await self.wizard.handle_update_price(interaction)
            return

        if selected == "quantity":
            await self.wizard.handle_update_quantity(interaction)
            return

        if selected == "condition":
            await self.wizard.handle_update_condition(interaction)
            return

        if selected == "image":
            await self.wizard.handle_update_image(interaction)
            return


class SealedUpdateProductTypeChangeSelect(ui.Select):
    def __init__(self, wizard: UpdateSealedWizardView, options):
        super().__init__(placeholder="Select New Product Type", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        new_product_id = int(self.values[0])
        label = next(opt.label for opt in self.options if opt.value == self.values[0])

        async with self.wizard.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET sealed_product_id = $1,
                    pokemon_name = $2
                WHERE inventory_id = $3
                  AND guild_id = $4
                  AND csv_id = 'sealed_add'
                  AND sealed_product_id IS NOT NULL
                """,
                new_product_id,
                label,
                self.wizard.inventory_id,
                self.wizard.guild_id,
            )

        await self.wizard.load_inventory_row()

        await self.wizard.show_post_update_actions(
            interaction,
            field_name="Product Type"
        )


class SealedUpdateSeriesSelect(ui.Select):
    def __init__(self, wizard: UpdateSealedWizardView, options):
        super().__init__(placeholder="Select Series", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        series = self.values[0]

        async with self.wizard.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT set_name
                FROM expansion_list
                WHERE series = $1
                ORDER BY set_name ASC;
                """,
                series,
            )

        options = [
            discord.SelectOption(label=row["set_name"], value=row["set_name"])
            for row in rows
        ]

        if not options:
            await interaction.response.send_message(
                "No sets found for this series.",
                ephemeral=True
            )
            return

        self.wizard.clear_items()
        set_select = SealedUpdateSetSelect(self.wizard, series, options)
        self.wizard.add_item(set_select)

        embed = discord.Embed(
            title="Update Series / Set",
            description="Select a new Set.",
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(embed=embed, view=self.wizard)


class SealedUpdateSetSelect(ui.Select):
    def __init__(self, wizard: UpdateSealedWizardView, series: str, options):
        super().__init__(placeholder="Select Set", options=options)
        self.wizard = wizard
        self.series = series

    async def callback(self, interaction: discord.Interaction):
        set_name = self.values[0]

        async with self.wizard.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET series = $1,
                    set_name = $2
                WHERE inventory_id = $3
                  AND guild_id = $4
                  AND csv_id = 'sealed_add'
                  AND sealed_product_id IS NOT NULL
                """,
                self.series,
                set_name,
                self.wizard.inventory_id,
                self.wizard.guild_id,
            )

        await self.wizard.load_inventory_row()

        await self.wizard.show_post_update_actions(
            interaction,
            field_name="Series / Set"
        )


class SealedUpdatePriceModal(ui.Modal, title="Update Price"):
    price = ui.TextInput(label="New Price")

    def __init__(self, wizard: UpdateSealedWizardView):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_price = float(self.price.value.strip())
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

        async with self.wizard.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET price = $1
                WHERE inventory_id = $2
                  AND guild_id = $3
                  AND csv_id = 'sealed_add'
                  AND sealed_product_id IS NOT NULL
                """,
                new_price,
                self.wizard.inventory_id,
                self.wizard.guild_id,
            )

        await self.wizard.load_inventory_row()

        await self.wizard.show_post_update_actions(
            interaction,
            field_name="Price"
        )


class SealedUpdateQuantityModal(ui.Modal, title="Update Quantity Available"):
    quantity = ui.TextInput(label="New Quantity")

    def __init__(self, wizard: UpdateSealedWizardView):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_qty = int(self.quantity.value.strip())
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

        async with self.wizard.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET quantity_available = $1
                WHERE inventory_id = $2
                  AND guild_id = $3
                  AND csv_id = 'sealed_add'
                  AND sealed_product_id IS NOT NULL
                """,
                new_qty,
                self.wizard.inventory_id,
                self.wizard.guild_id,
            )

        await self.wizard.load_inventory_row()

        await self.wizard.show_post_update_actions(
            interaction,
            field_name="Quantity Available"
        )


class SealedUpdateConditionSelect(ui.Select):
    def __init__(self, wizard: UpdateSealedWizardView, options):
        super().__init__(placeholder="Select New Condition", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        new_condition = self.values[0]

        async with self.wizard.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET condition = $1
                WHERE inventory_id = $2
                  AND guild_id = $3
                  AND csv_id = 'sealed_add'
                  AND sealed_product_id IS NOT NULL
                """,
                new_condition,
                self.wizard.inventory_id,
                self.wizard.guild_id,
            )

        await self.wizard.load_inventory_row()

        await self.wizard.show_post_update_actions(
            interaction,
            field_name="Condition"
        )


async def start_update_sealed_wizard(interaction: discord.Interaction):
    bot = interaction.client
    guild_id = interaction.guild.id

    admin_channel = await get_admin_channel(bot, guild_id)
    if admin_channel is None:
        await interaction.response.send_message(
            "❌ Admin channel is not set. Use /bot_settings to configure it.",
            ephemeral=True
        )
        return

    view = UpdateSealedWizardView(bot, interaction.user, guild_id)

    embed = discord.Embed(
        title="Update Sealed Product Wizard",
        description="Starting sealed product update wizard in the admin channel.",
        color=discord.Color.blurple(),
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)
    await view.start(admin_channel)
