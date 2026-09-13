import discord
import asyncio

# ---------------------------------------------------------
# GET ADMIN CHANNEL (correct guild_settings query)
# ---------------------------------------------------------
async def get_admin_channel(bot, guild_id: int):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT admin_channel_id
            FROM guild_settings
            WHERE guild_id = $1
            """,
            guild_id
        )

    if not row:
        return None

    channel_id = row["admin_channel_id"]
    return bot.get_channel(channel_id)


# ---------------------------------------------------------
# /admin batch_image_upload
# ---------------------------------------------------------
async def batch_image_upload(interaction: discord.Interaction):

    # Prevent DM/thread usage
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Admin commands cannot be used in DMs.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    # ---------------------------------------------------------
    # 1. Query ALL cards missing images
    # ---------------------------------------------------------
    async with interaction.client.db.acquire() as conn:
        all_rows = await conn.fetch(
            """
            SELECT inventory_id, pokemon_name, series, set_name,
                   card_number, variant, price, rarity,
                   graded, grading_company, grade,
                   quantity_available, image_link, condition
            FROM inventory
            WHERE guild_id = $1
              AND is_active = TRUE
              AND image_link IS NULL
              AND quantity_available >= 1
            ORDER BY pokemon_name ASC
            """,
            interaction.guild.id
        )

    total_missing = len(all_rows)

    if total_missing == 0:
        await interaction.followup.send(
            "All cards already have images. Nothing to upload.",
            ephemeral=True
        )
        return

    # ---------------------------------------------------------
    # PROCESS ONLY ONE BATCH PER RUN (FIX)
    # ---------------------------------------------------------
    batch_rows = all_rows[:6]
    inventory_ids = [r["inventory_id"] for r in batch_rows]

    # ---------------------------------------------------------
    # 2. Show the cards in this batch
    # ---------------------------------------------------------
    embeds = []
    for row in batch_rows:
        card_number = row["card_number"] or "—"
        set_display = "Mew 151" if row["set_name"] == "151" else row["set_name"]
        title = f"{row['pokemon_name']} #{card_number} — {set_display}"

        embed = discord.Embed(title=title, color=discord.Color.gold())
        graded_text = "Yes" if row["graded"] else "No"
        embed.description = (
            "__**Card Details**__\n\n"
            f"**Price:** ${row['price']}\n"
            f"**Condition:** {row['condition'] or 'Near Mint'}\n"
            f"**Graded:** {graded_text}\n"
        )
        embed.set_footer(text=f"Inventory ID: {row['inventory_id']}")
        embeds.append(embed)

    instruction_embed = discord.Embed(
        title="Batch Image Upload",
        description=(
            f"You have **{total_missing} cards** missing images.\n\n"
            f"This batch will upload **{len(batch_rows)} images**.\n"
            "Run the command again to continue uploading remaining cards.\n\n"
            "You will now upload images one at a time:\n"
            + "\n".join([f"• Image {i+1} → Card {i+1}" for i in range(len(batch_rows))])
            + "\n\nThis guarantees correct ordering."
        ),
        color=discord.Color.blue()
    )

    await interaction.followup.send(
        embeds=[instruction_embed] + embeds,
        ephemeral=True
    )

    # ---------------------------------------------------------
    # 3. Collect images one-by-one
    # ---------------------------------------------------------
    image_urls = []

    for i in range(len(batch_rows)):
        prompt = discord.Embed(
            title=f"Upload Image {i+1}/{len(batch_rows)}",
            description=(
                f"Please upload **image #{i+1}** now.\n\n"
                f"This image will be assigned to:\n"
                f"**{batch_rows[i]['pokemon_name']} — {batch_rows[i]['set_name']}**"
            ),
            color=discord.Color.blurple()
        )

        await interaction.followup.send(embed=prompt, ephemeral=True)

        def check(m: discord.Message):
            return (
                m.author.id == interaction.user.id
                and m.channel.id == interaction.channel.id
                and m.attachments
            )

        try:
            msg = await interaction.client.wait_for("message", timeout=180.0, check=check)
        except asyncio.TimeoutError:
            timeout_embed = discord.Embed(
                title="Timeout",
                description="You took too long to upload the image. Please restart `/admin batch_image_upload`.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=timeout_embed, ephemeral=True)
            return

        attachment = msg.attachments[0]

        # ⭐ FIX: Convert expiring CDN link → permanent CDN link
        url = attachment.url.split("?")[0]

        image_urls.append(url)

        progress = discord.Embed(
            title="Image Received",
            description=f"Image {i+1}/{len(batch_rows)} uploaded successfully.",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=progress, ephemeral=True)

    # ---------------------------------------------------------
    # 4. Preview confirmation
    # ---------------------------------------------------------
    confirm_embeds = []
    for row, url in zip(batch_rows, image_urls):
        card_number = row["card_number"] or "—"
        set_display = "Mew 151" if row["set_name"] == "151" else row["set_name"]
        title = f"{row['pokemon_name']} #{card_number} — {set_display}"

        embed = discord.Embed(title=title, color=discord.Color.green())
        embed.set_thumbnail(url=url)
        graded_text = "Yes" if row["graded"] else "No"
        embed.description = (
            "__**Card Details (Preview with Image)**__\n\n"
            f"**Price:** ${row['price']}\n"
            f"**Condition:** {row['condition'] or 'Near Mint'}\n"
            f"**Graded:** {graded_text}\n"
        )
        embed.set_footer(text=f"Inventory ID: {row['inventory_id']}")
        confirm_embeds.append(embed)

    view = BatchImageConfirmView(interaction.client, inventory_ids, image_urls)

    await interaction.followup.send(
        content="Review this batch. Confirm to save or Cancel to discard.",
        embeds=confirm_embeds,
        view=view,
        ephemeral=True
    )


# ---------------------------------------------------------
# CONFIRMATION VIEW
# ---------------------------------------------------------
class BatchImageConfirmView(discord.ui.View):
    def __init__(self, bot, inventory_ids, image_urls):
        super().__init__(timeout=300)
        self.bot = bot
        self.inventory_ids = inventory_ids
        self.image_urls = image_urls

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):

        await interaction.response.defer()

        for child in self.children:
            child.disabled = True

        async with self.bot.db.acquire() as conn:
            for inv_id, url in zip(self.inventory_ids, self.image_urls):
                await conn.execute(
                    """
                    UPDATE inventory
                    SET image_link = $2
                    WHERE inventory_id = $1
                      AND image_link IS NULL;
                    """,
                    inv_id,
                    url
                )

        try:
            await interaction.followup.edit_message(
                interaction.message.id,
                content="✅ Images saved successfully.\nRun `/admin batch_image_upload` again to add more.",
                view=None,
                embeds=[]
            )
        except discord.NotFound:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):

        await interaction.response.defer()

        for child in self.children:
            child.disabled = True

        try:
            await interaction.followup.edit_message(
                interaction.message.id,
                content="❌ Batch image upload cancelled. No changes were saved.",
                view=None,
                embeds=[]
            )
        except discord.NotFound:
            pass
