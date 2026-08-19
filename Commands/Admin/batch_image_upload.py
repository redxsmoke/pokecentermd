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
    # 1. Query cards missing images
    # ---------------------------------------------------------
    async with interaction.client.db.acquire() as conn:
        rows = await conn.fetch(
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

    if len(rows) < 6:
        embed = discord.Embed(
            title="Batch Image Upload",
            description="Not enough cards without images. At least 6 are required.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    batch_rows = rows[:6]
    inventory_ids = [r["inventory_id"] for r in batch_rows]

    # ---------------------------------------------------------
    # 2. Show the 6 cards
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
            "You will now upload **6 images one at a time**.\n\n"
            "I will prompt you for each image:\n"
            "• Image 1 → Card 1\n"
            "• Image 2 → Card 2\n"
            "• ...\n"
            "• Image 6 → Card 6\n\n"
            "This guarantees correct ordering."
        ),
        color=discord.Color.blue()
    )

    await interaction.followup.send(
        embeds=[instruction_embed] + embeds,
        ephemeral=True
    )

    # ---------------------------------------------------------
    # 3. Collect 6 images one-by-one (FIXED)
    # ---------------------------------------------------------
    image_urls = []

    for i in range(6):
        prompt = discord.Embed(
            title=f"Upload Image {i+1}/6",
            description=f"Please upload **image #{i+1}** now.\n\n"
                        f"This image will be assigned to:\n"
                        f"**{batch_rows[i]['pokemon_name']} — {batch_rows[i]['set_name']}**",
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

        # ⭐ FIX: Use original CDN URL — DO NOT re-upload
        url = attachment.url

        # ⭐ DO NOT DELETE THE MESSAGE — deleting it deletes the CDN file
        # (This was the cause of disappearing images)

        image_urls.append(url)

        progress = discord.Embed(
            title="Image Received",
            description=f"Image {i+1}/6 uploaded successfully.",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=progress, ephemeral=True)

    # ---------------------------------------------------------
    # 4. Build confirmation embeds (SAFE)
    # ---------------------------------------------------------
    confirm_embeds = []
    for row, url in zip(batch_rows, image_urls):
        card_number = row["card_number"] or "—"
        set_display = "Mew 151" if row["set_name"] == "151" else row["set_name"]
        title = f"{row['pokemon_name']} #{card_number} — {set_display}"

        embed = discord.Embed(title=title, color=discord.Color.green())
        embed.set_thumbnail(url=url)  # SAFE — original CDN URL
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
        content="Review the images below. Confirm to save or Cancel to discard.",
        embeds=confirm_embeds,
        view=view,
        ephemeral=True
    )


# ---------------------------------------------------------
# CONFIRMATION VIEW (UPDATED)
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

        # Disable buttons
        for child in self.children:
            child.disabled = True

        # Save images to DB
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

        # Edit message
        try:
            await interaction.followup.edit_message(
                interaction.message.id,
                content="✅ Images saved successfully.",
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
