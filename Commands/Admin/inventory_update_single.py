import discord
from io import BytesIO

# ---------------------------------------------------------
#   SAFE SEND — USES RESPONSE OR FOLLOWUP (NO CHANNEL.SEND)
# ---------------------------------------------------------

async def safe_send(interaction: discord.Interaction, **kwargs):
    """
    Sends a message safely depending on interaction state.
    - If interaction.response is not yet used → interaction.response.send_message()
    - If interaction.response is already used → interaction.followup.send()
    """
    if interaction.response.is_done():
        return await interaction.followup.send(**kwargs)
    else:
        return await interaction.response.send_message(**kwargs)


# ---------------------------------------------------------
#   START UPDATE SINGLE FLOW (manual ID entry)
# ---------------------------------------------------------

async def start_update_single_flow(interaction: discord.Interaction):
    await safe_send(
        interaction,
        content="Please enter the **inventory ID** of the card you want to update.",
        ephemeral=True
    )

    def check(m: discord.Message):
        return (
            m.author.id == interaction.user.id
            and m.channel.id == interaction.channel.id
        )

    try:
        msg = await interaction.client.wait_for("message", check=check, timeout=120)
    except Exception:
        await safe_send(
            interaction,
            content="Timed out waiting for inventory ID.",
            ephemeral=True
        )
        return

    try:
        inventory_id = int(msg.content.strip())
    except ValueError:
        await send_invalid_inventory_id(interaction)
        return

    async with interaction.client.db.acquire() as conn:
        card_row = await conn.fetchrow(
            """
            SELECT *
            FROM inventory
            WHERE inventory_id = $1 AND guild_id = $2 AND is_active = TRUE
            """,
            inventory_id,
            interaction.guild.id
        )

    if not card_row:
        await send_invalid_inventory_id(interaction)
        return

    card_row = dict(card_row)
    await send_card_preview(interaction, card_row)


# ---------------------------------------------------------
#   START UPDATE FLOW FROM AUTOCOMPLETE
# ---------------------------------------------------------

async def start_update_single_flow_with_id(interaction: discord.Interaction, inventory_id: int):
    async with interaction.client.db.acquire() as conn:
        card_row = await conn.fetchrow(
            """
            SELECT *
            FROM inventory
            WHERE inventory_id = $1 AND guild_id = $2 AND is_active = TRUE
            """,
            inventory_id,
            interaction.guild.id
        )

    if not card_row:
        await send_invalid_inventory_id(interaction)
        return

    card_row = dict(card_row)
    await send_card_preview(interaction, card_row)


# ---------------------------------------------------------
#   INVALID INVENTORY ID
# ---------------------------------------------------------

async def send_invalid_inventory_id(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Invalid Inventory ID",
        description=(
            "Invalid inventory ID.\n\n"
            "Please run **/inventory** to obtain the inventory ID if you do not know it."
        ),
        color=discord.Color.red()
    )

    await safe_send(
        interaction,
        embed=embed,
        view=RetryInventoryIdView(interaction),
        ephemeral=True
    )


class RetryInventoryIdView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=120)
        self.interaction = interaction

    @discord.ui.button(label="Retry", style=discord.ButtonStyle.primary)
    async def retry(self, button_interaction: discord.Interaction, button: discord.ui.Button):
        await start_update_single_flow(button_interaction)


# ---------------------------------------------------------
#   CARD PREVIEW
# ---------------------------------------------------------

async def send_card_preview(interaction: discord.Interaction, card_row):
    embed = discord.Embed(
        title=f"Confirm Card — Inventory ID {card_row['inventory_id']}",
        description="Please confirm this is the card you'd like to update.",
        color=discord.Color.blurple()
    )

    embed.add_field(name="Pokémon Name", value=card_row["pokemon_name"], inline=False)
    embed.add_field(name="Series", value=card_row["series"], inline=False)
    embed.add_field(name="Set Name", value=card_row["set_name"], inline=False)
    embed.add_field(name="Card Number", value=card_row["card_number"], inline=False)
    embed.add_field(name="Price", value=str(card_row["price"]), inline=False)
    embed.add_field(name="Quantity Available", value=str(card_row["quantity_available"]), inline=False)

    image_link = card_row.get("image_link")
    if image_link:
        embed.set_thumbnail(url=image_link)
    else:
        embed.add_field(name="Image", value="No image available", inline=False)

    await safe_send(
        interaction,
        embed=embed,
        view=ConfirmCardView(card_row),
        ephemeral=True
    )


class ConfirmCardView(discord.ui.View):
    def __init__(self, card_row):
        super().__init__(timeout=300)
        self.card_row = card_row

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_update_field_dropdown(interaction, self.card_row)

    @discord.ui.button(label="Select another card", style=discord.ButtonStyle.secondary)
    async def select_another(self, interaction: discord.Interaction, button: discord.ui.Button):
        await start_update_single_flow(interaction)


# ---------------------------------------------------------
#   FIELD DROPDOWN
# ---------------------------------------------------------

async def show_update_field_dropdown(interaction: discord.Interaction, card_row):
    embed = discord.Embed(
        title=f"Update Card — Inventory ID {card_row['inventory_id']}",
        description="Select a field to update.",
        color=discord.Color.blurple()
    )

    await safe_send(
        interaction,
        embed=embed,
        view=UpdateFieldView(card_row),
        ephemeral=True
    )


class UpdateFieldView(discord.ui.View):
    def __init__(self, card_row):
        super().__init__(timeout=300)
        self.add_item(UpdateFieldSelect(card_row))


class UpdateFieldSelect(discord.ui.Select):
    def __init__(self, card_row):
        options = [
            discord.SelectOption(label="Price", value="price"),
            discord.SelectOption(label="Quantity Available", value="quantity"),
            discord.SelectOption(label="Condition", value="condition"),
            discord.SelectOption(label="Image", value="image"),
            discord.SelectOption(label="Series & Set", value="series_set"),
            discord.SelectOption(label="Card Number", value="card_number"),
            discord.SelectOption(label="Pokemon Name", value="pokemon_name"),
            discord.SelectOption(label="Update all fields", value="update_all"),
            discord.SelectOption(label="Hide from results", value="hide"),


        ]
        super().__init__(placeholder="Select a field to update", options=options)
        self.card_row = card_row

    async def callback(self, interaction: discord.Interaction):
        field = self.values[0]

        if field == "price":
            await interaction.response.send_modal(UpdatePriceModal(self.card_row))
            return

        if field == "quantity":
            await interaction.response.send_modal(UpdateQuantityModal(self.card_row))
            return

        if field == "condition":
            await show_update_condition_dropdown(interaction, self.card_row)
            return

        if field == "image":
            await start_update_image_flow(interaction, self.card_row)
            return

        if field == "series_set":
            await show_update_series_dropdown(interaction, self.card_row)
            return

        if field == "card_number":
            await interaction.response.send_modal(UpdateCardNumberModal(self.card_row))
            return

        if field == "pokemon_name":
            await interaction.response.send_modal(UpdatePokemonNameModal(self.card_row))
            return

        if field == "update_all":
            await start_update_all_fields_wizard(interaction, self.card_row)

        if field == "hide":
            await hide_card(interaction, self.card_row)
            return



# ---------------------------------------------------------
#   PRICE UPDATE
# ---------------------------------------------------------

class UpdatePriceModal(discord.ui.Modal, title="Update Price"):
    price = discord.ui.TextInput(label="New Price")

    def __init__(self, card_row):
        super().__init__()
        self.card_row = card_row

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.price.value.strip().replace("$", "")
        try:
            new_price = float(raw)
        except ValueError:
            await safe_send(
                interaction,
                embed=discord.Embed(
                    title="Invalid Price",
                    description="Price must be a number.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET price = $1
                WHERE inventory_id = $2 AND guild_id = $3
                """,
                new_price,
                self.card_row["inventory_id"],
                interaction.guild.id
            )

        self.card_row["price"] = new_price
        await send_update_success(interaction, self.card_row, "Price updated successfully.")


# ---------------------------------------------------------
#   CARD NUMBER / NAME / QUANTITY
# ---------------------------------------------------------

class UpdateCardNumberModal(discord.ui.Modal, title="Update Card Number"):
    card_number = discord.ui.TextInput(label="Card Number")

    def __init__(self, card_row):
        super().__init__()
        self.card_row = card_row

    async def on_submit(self, interaction: discord.Interaction):
        new_number = self.card_number.value.strip()

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET card_number = $1
                WHERE inventory_id = $2 AND guild_id = $3
                """,
                new_number,
                self.card_row["inventory_id"],
                interaction.guild.id
            )

        self.card_row["card_number"] = new_number
        await send_update_success(interaction, self.card_row, "Card number updated successfully.")


class UpdatePokemonNameModal(discord.ui.Modal, title="Update Pokémon Name"):
    pokemon_name = discord.ui.TextInput(label="Pokémon Name")

    def __init__(self, card_row):
        super().__init__()
        self.card_row = card_row

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.pokemon_name.value.strip()

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET pokemon_name = $1
                WHERE inventory_id = $2 AND guild_id = $3
                """,
                new_name,
                self.card_row["inventory_id"],
                interaction.guild.id
            )

        self.card_row["pokemon_name"] = new_name
        await send_update_success(interaction, self.card_row, "Pokémon name updated successfully.")


class UpdateQuantityModal(discord.ui.Modal, title="Update Quantity Available"):
    quantity = discord.ui.TextInput(label="New Quantity")

    def __init__(self, card_row):
        super().__init__()
        self.card_row = card_row

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_qty = int(self.quantity.value.strip())
        except ValueError:
            await safe_send(
                interaction,
                embed=discord.Embed(
                    title="Invalid Quantity",
                    description="Quantity must be an integer.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET quantity_available = $1
                WHERE inventory_id = $2 AND guild_id = $3
                """,
                new_qty,
                self.card_row["inventory_id"],
                interaction.guild.id
            )

        self.card_row["quantity_available"] = new_qty
        await send_update_success(interaction, self.card_row, "Quantity updated successfully.")


# ---------------------------------------------------------
#   CONDITION UPDATE — GRADED FLOW
# ---------------------------------------------------------

async def show_update_condition_dropdown(interaction: discord.Interaction, card_row):
    embed = discord.Embed(
        title=f"Update Condition — Inventory ID {card_row['inventory_id']}",
        description="Select the new condition.",
        color=discord.Color.blurple()
    )

    class ConditionSelect(discord.ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(label="Near Mint", value="Near Mint"),
                discord.SelectOption(label="Lightly Played", value="Lightly Played"),
                discord.SelectOption(label="Moderately Played", value="Moderately Played"),
                discord.SelectOption(label="Heavily Played", value="Heavily Played"),
                discord.SelectOption(label="Damaged", value="Damaged"),
                discord.SelectOption(label="Graded", value="Graded"),
            ]
            super().__init__(placeholder="Select Condition", options=options)

        async def callback(self, inner_interaction: discord.Interaction):
            new_condition = self.values[0]
            card_row["condition"] = new_condition
            card_row["graded"] = (new_condition == "Graded")

            if new_condition != "Graded":
                await inner_interaction.response.defer(ephemeral=True)

                async with inner_interaction.client.db.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE inventory
                        SET condition = $1, graded = FALSE
                        WHERE inventory_id = $2 AND guild_id = $3
                        """,
                        new_condition,
                        card_row["inventory_id"],
                        inner_interaction.guild.id
                    )

                await send_update_success(inner_interaction, card_row, "Condition updated successfully.")
                return

            await show_update_grading_company_dropdown(inner_interaction, card_row)

    view = discord.ui.View(timeout=300)
    view.add_item(ConditionSelect())

    await safe_send(
        interaction,
        embed=embed,
        view=view,
        ephemeral=True
    )


# ---------------------------------------------------------
#   GRADING COMPANY DROPDOWN
# ---------------------------------------------------------

async def show_update_grading_company_dropdown(interaction: discord.Interaction, card_row):
    embed = discord.Embed(
        title=f"Select Grading Company — Inventory ID {card_row['inventory_id']}",
        description="Select the grading company.",
        color=discord.Color.blurple()
    )

    class GradingCompanySelect(discord.ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(label="PSA", value="PSA"),
                discord.SelectOption(label="CGC", value="CGC"),
                discord.SelectOption(label="Beckett", value="Beckett"),
                discord.SelectOption(label="TAG", value="TAG"),
                discord.SelectOption(label="ACE", value="ACE"),
                discord.SelectOption(label="SGC", value="SGC"),
                discord.SelectOption(label="Other", value="Other"),
            ]
            super().__init__(placeholder="Select Grading Company", options=options)

        async def callback(self, inner_interaction: discord.Interaction):
            company = self.values[0]
            card_row["grading_company"] = company
            await show_update_grade_dropdown(inner_interaction, card_row)

    view = discord.ui.View(timeout=300)
    view.add_item(GradingCompanySelect())

    await safe_send(
        interaction,
        embed=embed,
        view=view,
        ephemeral=True
    )


# ---------------------------------------------------------
#   GRADE DROPDOWN (10 → 1 + CUSTOM)
# ---------------------------------------------------------

async def show_update_grade_dropdown(interaction: discord.Interaction, card_row):
    embed = discord.Embed(
        title=f"Update Grade — Inventory ID {card_row['inventory_id']}",
        description="Select grade.",
        color=discord.Color.blurple()
    )

    class GradeSelect(discord.ui.Select):
        def __init__(self):
            options = [discord.SelectOption(label=str(i), value=str(i)) for i in range(10, 0, -1)]
            options.append(discord.SelectOption(label="Custom", value="custom"))
            super().__init__(placeholder="Select Grade", options=options)

        async def callback(self, inner_interaction: discord.Interaction):
            val = self.values[0]

            if val == "custom":
                await inner_interaction.response.send_modal(UpdateCustomGradeModal(card_row))
                return

            await inner_interaction.response.defer(ephemeral=True)

            card_row["grade"] = val
            card_row["condition"] = "Graded"
            card_row["graded"] = True

            async with inner_interaction.client.db.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET condition = 'Graded',
                        graded = TRUE,
                        grading_company = $1,
                        grade = $2
                    WHERE inventory_id = $3 AND guild_id = $4
                    """,
                    card_row["grading_company"],
                    card_row["grade"],
                    card_row["inventory_id"],
                    inner_interaction.guild.id
                )

            await send_update_success(inner_interaction, card_row, "Graded fields updated successfully.")

    view = discord.ui.View(timeout=300)
    view.add_item(GradeSelect())

    await safe_send(
        interaction,
        embed=embed,
        view=view,
        ephemeral=True
    )


# ---------------------------------------------------------
#   CUSTOM GRADE MODAL
# ---------------------------------------------------------

class UpdateCustomGradeModal(discord.ui.Modal, title="Custom Grade"):
    custom_grade = discord.ui.TextInput(label="Enter Custom Grade")

    def __init__(self, card_row):
        super().__init__()
        self.card_row = card_row

    async def on_submit(self, interaction: discord.Interaction):
        grade = self.custom_grade.value.strip()
        self.card_row["grade"] = grade
        self.card_row["condition"] = "Graded"
        self.card_row["graded"] = True

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET condition = 'Graded',
                    graded = TRUE,
                    grading_company = $1,
                    grade = $2
                WHERE inventory_id = $3 AND guild_id = $4
                """,
                self.card_row["grading_company"],
                grade,
                self.card_row["inventory_id"],
                interaction.guild.id
            )

        await send_update_success(interaction, self.card_row, "Custom grade saved successfully.")


# ---------------------------------------------------------
#   SERIES UPDATE
# ---------------------------------------------------------

async def show_update_series_dropdown(interaction: discord.Interaction, card_row):
    async with interaction.client.db.acquire() as conn:
        series_rows = await conn.fetch(
            "SELECT DISTINCT series FROM expansion_list ORDER BY series"
        )

    series_options = [
        discord.SelectOption(label=r["series"], value=r["series"])
        for r in series_rows
    ]

    embed = discord.Embed(
        title=f"Update Series — Inventory ID {card_row['inventory_id']}",
        description="Select the new series.",
        color=discord.Color.blurple()
    )

    class SeriesSelect(discord.ui.Select):
        def __init__(self):
            super().__init__(placeholder="Select Series", options=series_options)

        async def callback(self, inner_interaction: discord.Interaction):
            await inner_interaction.response.defer(ephemeral=True)

            card_row["series"] = self.values[0]
            await show_update_set_dropdown(inner_interaction, card_row)

    view = discord.ui.View(timeout=300)
    view.add_item(SeriesSelect())

    await safe_send(
        interaction,
        embed=embed,
        view=view,
        ephemeral=True
    )


# ---------------------------------------------------------
#   SET UPDATE
# ---------------------------------------------------------

async def show_update_set_dropdown(interaction: discord.Interaction, card_row):
    async with interaction.client.db.acquire() as conn:
        set_rows = await conn.fetch(
            "SELECT set_name FROM expansion_list WHERE series = $1 ORDER BY set_name",
            card_row["series"]
        )

    set_options = [
        discord.SelectOption(label=r["set_name"], value=r["set_name"])
        for r in set_rows
    ]

    embed = discord.Embed(
        title=f"Update Set — Inventory ID {card_row['inventory_id']}",
        description="Select the new set.",
        color=discord.Color.blurple()
    )

    class SetSelect(discord.ui.Select):
        def __init__(self):
            super().__init__(placeholder="Select Set", options=set_options)

        async def callback(self, inner_interaction: discord.Interaction):
            card_row["set_name"] = self.values[0]

            async with inner_interaction.client.db.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET series = $1, set_name = $2
                    WHERE inventory_id = $3 AND guild_id = $4
                    """,
                    card_row["series"],
                    card_row["set_name"],
                    card_row["inventory_id"],
                    inner_interaction.guild.id
                )

            await send_update_success(inner_interaction, card_row, "Series & Set updated successfully.")

    view = discord.ui.View(timeout=300)
    view.add_item(SetSelect())

    await safe_send(
        interaction,
        embed=embed,
        view=view,
        ephemeral=True
    )


# ---------------------------------------------------------
#   IMAGE UPDATE
# ---------------------------------------------------------
async def hide_card(interaction: discord.Interaction, card_row):
    async with interaction.client.db.acquire() as conn:
        await conn.execute(
            """
            UPDATE inventory
            SET is_active = FALSE
            WHERE inventory_id = $1 AND guild_id = $2
            """,
            card_row["inventory_id"],
            interaction.guild.id
        )

    await send_update_success(
        interaction,
        card_row,
        "This card has been hidden and will no longer appear in Update Single search.\n\n"
        "To undo this, run **/activate_single**."
    )



async def start_update_image_flow(interaction: discord.Interaction, card_row):
    embed = discord.Embed(
        title="Upload New Image",
        description="Please upload an image in this channel. I will use the first attachment you send.",
        color=discord.Color.blurple(),
    )

    await safe_send(interaction, embed=embed, ephemeral=True)

    def check(m: discord.Message):
        return (
            m.author.id == interaction.user.id
            and m.channel.id == interaction.channel.id
            and m.attachments
        )

    try:
        msg = await interaction.client.wait_for("message", check=check, timeout=120)
    except Exception:
        fail = discord.Embed(
            title="No Image Received",
            description="No image was uploaded in time.",
            color=discord.Color.red(),
        )
        await safe_send(interaction, embed=fail, ephemeral=True)
        return

    attachment = msg.attachments[0]
    file_bytes = await attachment.read()

    try:
        await msg.delete()
    except:
        pass

    admin_channel = await get_admin_channel(interaction.client, interaction.guild.id)
    if admin_channel is None:
        await safe_send(
            interaction,
            content="❌ Admin channel is not set. Use /bot_settings to configure it.",
            ephemeral=True
        )
        return

    file = discord.File(BytesIO(file_bytes), filename="card_update.jpg")
    sent_msg = await admin_channel.send(file=file)

    url = sent_msg.attachments[0].url
    if "?" in url:
        url = url.split("?")[0]

    def safe_image(u: str) -> str:
        if not u:
            return None
        u = u.strip()
        valid_ext = (".jpg", ".jpeg", ".png", ".gif", ".webp")
        if not any(u.lower().endswith(ext) for ext in valid_ext):
            return None
        if not (u.startswith("http://") or u.startswith("https://")):
            return None
        return u

    final_url = safe_image(url)

    async with interaction.client.db.acquire() as conn:
        await conn.execute(
            """
            UPDATE inventory
            SET image_link = $1
            WHERE inventory_id = $2 AND guild_id = $3
            """,
            final_url,
            card_row["inventory_id"],
            interaction.guild.id
        )

    card_row["image_link"] = final_url

    await send_update_success(interaction, card_row, "Image updated successfully.")


# ---------------------------------------------------------
#   UPDATE ALL FIELDS WIZARD
# ---------------------------------------------------------

async def start_update_all_fields_wizard(interaction: discord.Interaction, card_row):
    from Commands.Admin.inventory_add_single_wizard import AddSingleWizardView

    wizard = AddSingleWizardView(interaction.client, interaction.user)

    wizard.state["pokemon_name"] = card_row["pokemon_name"]
    wizard.state["card_number"] = card_row["card_number"]
    wizard.state["series"] = card_row["series"]
    wizard.state["set_name"] = card_row["set_name"]
    wizard.state["quantity_available"] = card_row["quantity_available"]
    wizard.state["price"] = card_row["price"]
    wizard.state["condition"] = card_row["condition"]
    wizard.state["variant"] = card_row["variant"]
    wizard.state["rarity"] = card_row["rarity"]
    wizard.state["graded"] = card_row["graded"]
    wizard.state["grading_company"] = card_row["grading_company"]
    wizard.state["grade"] = card_row["grade"]
    wizard.state["image_link"] = card_row["image_link"]

    wizard.step = 1

    admin_channel = await get_admin_channel(interaction.client, interaction.guild.id)
    if admin_channel is None:
        await safe_send(
            interaction,
            content="❌ Admin channel is not set. Use /bot_settings to configure it.",
            ephemeral=True
        )
        return

    embed = wizard.build_embed()
    msg = await admin_channel.send(embed=embed, view=wizard)
    wizard.message = msg

    await safe_send(
        interaction,
        content="Update-all-fields wizard started in the admin channel.",
        ephemeral=True
    )


# ---------------------------------------------------------
#   SHARED SUCCESS MESSAGE
# ---------------------------------------------------------

async def send_update_success(interaction: discord.Interaction, card_row, message: str):
    embed = discord.Embed(
        title="Updated Successfully",
        description=message,
        color=discord.Color.green()
    )

    if interaction.response.is_done():
        await interaction.followup.send(
            embed=embed,
            view=AfterUpdateView(card_row),
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            embed=embed,
            view=AfterUpdateView(card_row),
            ephemeral=True
        )


class AfterUpdateView(discord.ui.View):
    def __init__(self, card_row):
        super().__init__(timeout=300)
        self.card_row = card_row

    @discord.ui.button(label="Update another field", style=discord.ButtonStyle.primary)
    async def update_another(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_update_field_dropdown(interaction, self.card_row)

    @discord.ui.button(label="Finish", style=discord.ButtonStyle.secondary)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_send(
            interaction,
            content="Your changes were successful.",
            ephemeral=True
        )
        self.stop()


# ---------------------------------------------------------
#   ADMIN CHANNEL LOOKUP
# ---------------------------------------------------------

async def get_admin_channel(bot, guild_id):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT admin_channel_id FROM guild_settings WHERE guild_id = $1",
            guild_id
        )

    if row and row["admin_channel_id"]:
        return bot.get_channel(row["admin_channel_id"])

    return None


# ---------------------------------------------------------
#   EXPORTS
# ---------------------------------------------------------

__all__ = [
    "start_update_single_flow",
    "start_update_single_flow_with_id"
]
