import discord

# ---------------------------------------------------------
# SAFE SEND (same pattern as your update_single file)
# ---------------------------------------------------------

async def safe_send(interaction: discord.Interaction, **kwargs):
    if interaction.response.is_done():
        return await interaction.followup.send(**kwargs)
    else:
        return await interaction.response.send_message(**kwargs)


# ---------------------------------------------------------
# ENTRY POINT — WARNING + MANUAL ID FLOW
# ---------------------------------------------------------

async def start_delete_single_flow(interaction: discord.Interaction):
    warning = (
        "**Warning — Permanent Deletion**\n\n"
        "Deleting a card will permanently remove it and all of its data from your inventory.\n\n"
        "If you simply no longer have this card and want it removed from search results, "
        "use **/admin deactivate_single** instead. This hides the card without deleting it.\n\n"
        "You may reactivate hidden cards at any time using **/admin activate_single**.\n\n"
        "**If you continue, the card will be permanently deleted. This action cannot be undone.**"
    )

    class DeleteWarningView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)

        @discord.ui.button(label="Continue", style=discord.ButtonStyle.danger)
        async def continue_delete(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await safe_send(
                btn_interaction,
                content="Please enter the **inventory ID** of the card you want to delete.",
                ephemeral=True
            )

            def check(m: discord.Message):
                return (
                    m.author.id == btn_interaction.user.id
                    and m.channel.id == btn_interaction.channel.id
                )

            try:
                msg = await btn_interaction.client.wait_for("message", check=check, timeout=120)
            except Exception:
                await safe_send(
                    btn_interaction,
                    content="Timed out waiting for inventory ID.",
                    ephemeral=True
                )
                return

            try:
                inventory_id = int(msg.content.strip())
            except ValueError:
                await safe_send(
                    btn_interaction,
                    content="Invalid inventory ID.",
                    ephemeral=True
                )
                return

            await start_delete_single_flow_with_id(btn_interaction, inventory_id)

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await safe_send(
                btn_interaction,
                content="Delete cancelled.",
                ephemeral=True
            )

    await safe_send(
        interaction,
        content=warning,
        view=DeleteWarningView(),
        ephemeral=True
    )


# ---------------------------------------------------------
# ENTRY POINT — AUTOCOMPLETE FLOW
# ---------------------------------------------------------

async def start_delete_single_flow_with_id(interaction: discord.Interaction, inventory_id: int):
    async with interaction.client.db.acquire() as conn:
        card_row = await conn.fetchrow(
            """
            SELECT *
            FROM inventory
            WHERE inventory_id = $1 AND guild_id = $2
            """,
            inventory_id,
            interaction.guild.id
        )

    if not card_row:
        await safe_send(
            interaction,
            content="Card not found.",
            ephemeral=True
        )
        return

    card_row = dict(card_row)
    await send_delete_preview(interaction, card_row)


# ---------------------------------------------------------
# CARD PREVIEW + CONFIRM DELETE
# ---------------------------------------------------------

async def send_delete_preview(interaction: discord.Interaction, card_row):
    embed = discord.Embed(
        title=f"Confirm Delete — Inventory ID {card_row['inventory_id']}",
        description="Are you sure you want to permanently delete this card?",
        color=discord.Color.red()
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

    class ConfirmDeleteView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)

        @discord.ui.button(label="Confirm Delete", style=discord.ButtonStyle.danger)
        async def confirm(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            async with btn_interaction.client.db.acquire() as conn:
                await conn.execute(
                    """
                    DELETE FROM inventory
                    WHERE inventory_id = $1 AND guild_id = $2
                    """,
                    card_row["inventory_id"],
                    btn_interaction.guild.id
                )

            await safe_send(
                btn_interaction,
                content="Card has been permanently deleted.",
                ephemeral=True
            )

        @discord.ui.button(label="Select another card", style=discord.ButtonStyle.secondary)
        async def select_another(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await safe_send(
                btn_interaction,
                content="Please run `/admin delete_single` again to select another card.",
                ephemeral=True
            )

    await safe_send(
        interaction,
        embed=embed,
        view=ConfirmDeleteView(),
        ephemeral=True
    )


# ---------------------------------------------------------
# EXPORTS
# ---------------------------------------------------------

__all__ = [
    "start_delete_single_flow",
    "start_delete_single_flow_with_id"
]
