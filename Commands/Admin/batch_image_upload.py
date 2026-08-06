import discord
import asyncio
from io import BytesIO

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


async def batch_image_upload(interaction: discord.Interaction):

    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Admin commands cannot be used in DMs.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

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

    admin_channel = await get_admin_channel(interaction.client, interaction.guild.id)
    if admin_channel is None:
        await interaction.followup.send(
            content="❌ Admin channel is not set. Use /bot_settings to configure it.",
            ephemeral=True
        )
        return

    image_urls = []
    uploaded_messages = []

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
        file_bytes = await attachment.read()
        file = discord.File(BytesIO(file_bytes), filename=f"batch_upload_{i+1}.jpg")

        sent_msg = await admin_channel.send(file=file)
        uploaded_messages.append(sent_msg)

        await asyncio.sleep(0.35)
        url = sent_msg.attachments[0].url

        if "?" in url:
            url = url.split("?")[0]

        image_urls.append(url)

        try:
            await msg.delete()
        except:
            pass

        progress = discord.Embed(
            title="Image Received",
            description=f"Image {i+1}/6 uploaded successfully.",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=progress, ephemeral=True)

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

    view = BatchImageConfirmView(interaction.client, inventory_ids, image_urls, uploaded_messages)

    await interaction.followup.send(
        content="Review the images below. Confirm to save or Cancel to discard.",
        embeds=confirm_embeds,
        view=view,
        ephemeral=True
    )


class BatchImageConfirmView(discord.ui.View):
    def __init__(self, bot, inventory_ids, image_urls, uploaded_messages):
        super().__init__(timeout=300)
        self.bot = bot
        self.inventory_ids = inventory_ids
        self.image_urls = image_urls
        self.uploaded_messages = uploaded_messages

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):

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

        await interaction.response.edit_message(
            content="✅ Images saved successfully.",
            view=None,
            embeds=[]
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):

        # DELETE ONLY THE IMAGES FROM THIS SESSION
        for msg in self.uploaded_messages:
            try:
                await msg.delete()
            except Exception:
                pass

        await interaction.response.edit_message(
            content="❌ Batch image upload cancelled. All uploaded images for this session were deleted.",
            view=None,
            embeds=[]
        )
