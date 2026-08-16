import discord
from discord import app_commands
from discord.ext import commands
from io import BytesIO
import asyncio


# ---------------------------------------------------------
#  ADMIN LOOKUP (from guild_settings)
# ---------------------------------------------------------
async def get_admin_id(bot: commands.Bot, guild_id: int):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT admin_id
            FROM guild_settings
            WHERE guild_id = $1;
            """,
            guild_id
        )
    return row["admin_id"] if row else None


# ---------------------------------------------------------
#  Helper: Fetch guild_id from guild_settings
# ---------------------------------------------------------
async def get_guild_id_from_settings(bot: commands.Bot, discord_guild_id: int):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT guild_id
            FROM guild_settings
            WHERE guild_id = $1;
            """,
            discord_guild_id
        )
    return row["guild_id"] if row else discord_guild_id


# ---------------------------------------------------------
#  DROPDOWN VIEW (Singles or Collection)
# ---------------------------------------------------------
class SellCardsDropdown(discord.ui.Select):
    def __init__(self, guild_id: int):
        self.guild_id = guild_id  # ⭐ STORE GUILD ID SAFELY

        options = [
            discord.SelectOption(label="Submit Singles (1-5 cards)", value="singles"),
            discord.SelectOption(label="Submit Collection (6+ cards)", value="collection")
        ]

        super().__init__(
            placeholder="Choose submission type...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]

        if choice == "singles":
            try:
                # ⭐ NEVER use interaction.guild.id here (DM-safe)
                guild_id = self.guild_id

                view = SinglesWizardStartView(interaction.client, guild_id)

                embed = discord.Embed(
                    title="Singles Submission Wizard",
                    description="Click **Start Submission** below to begin.",
                    color=discord.Color.blurple()
                )

                await interaction.user.send(embed=embed, view=view)

                await interaction.response.send_message(
                    "📨 **Check your DMs** to complete the singles submission wizard.",
                    ephemeral=True
                )

            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ You must have DMs enabled to use this feature.",
                    ephemeral=True
                )

        elif choice == "collection":
            await interaction.response.send_modal(
                SubmitCollectionModal()
            )


class SellCardsDropdownView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__()
        self.add_item(SellCardsDropdown(guild_id))  # ⭐ PASS GUILD ID


# ---------------------------------------------------------
#  SINGLES WIZARD – DM-based flow
# ---------------------------------------------------------
class SinglesWizardStartView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.button(label="Start Submission", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        cards: list[dict] = []
        modal = SingleCardBasicModal(self.bot, cards, card_index=1, guild_id=self.guild_id)
        await interaction.response.send_modal(modal)


class SingleCardBasicModal(discord.ui.Modal, title="Card Details"):
    def __init__(self, bot: commands.Bot, cards: list[dict], card_index: int, guild_id: int):
        super().__init__()
        self.bot = bot
        self.cards = cards
        self.card_index = card_index
        self.guild_id = guild_id

        self.name = discord.ui.TextInput(label="Card Name", required=True)
        self.number = discord.ui.TextInput(label="Card Number", required=True)
        self.price = discord.ui.TextInput(label="Asking Price (e.g. 12.50)", required=True)

        self.add_item(self.name)
        self.add_item(self.number)
        self.add_item(self.price)

    async def on_submit(self, interaction: discord.Interaction):
        raw_price = self.price.value.strip()
        try:
            raw_price_clean = raw_price.replace("$", "").replace(",", "")
            price_val = float(raw_price_clean)
        except ValueError:
            embed = discord.Embed(
                title="Invalid Price",
                description="Price must be a valid number (e.g. 12.50).",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        card = {
            "name": self.name.value.strip(),
            "number": self.number.value.strip(),
            "price": price_val,
            "series": None,
            "set_name": None,
            "condition": None,
        }

        view = await create_series_view(self.bot, card, self.cards, self.card_index, self.guild_id)
        embed = discord.Embed(
            title=f"Card #{self.card_index} — Select Series",
            description="Choose the **Series** for this card.",
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, view=view)


async def create_series_view(bot: commands.Bot, card: dict, cards: list[dict], card_index: int, guild_id: int):
    async with bot.db.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT series FROM expansion_list ORDER BY series")

    options = [discord.SelectOption(label=row["series"], value=row["series"]) for row in rows]

    view = discord.ui.View(timeout=600)
    view.add_item(SeriesSelect(bot, card, cards, card_index, guild_id, options))
    return view


class SeriesSelect(discord.ui.Select):
    def __init__(self, bot, card, cards, card_index, guild_id, options):

        options.append(discord.SelectOption(label="Skip Series", value="__skip_series__"))

        super().__init__(placeholder="Select Series", options=options)
        self.bot = bot
        self.card = card
        self.cards = cards
        self.card_index = card_index
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):

        if self.values[0] == "__skip_series__":
            self.card["series"] = None
            self.card["set_name"] = None

            # Jump directly to condition selection
            view = discord.ui.View(timeout=600)
            view.add_item(ConditionSelect(self.bot, self.card, self.cards, self.card_index, self.guild_id))

            embed = discord.Embed(
                title=f"Card #{self.card_index} — Select Condition",
                description="Series/Set skipped.\n\nSelect the **condition** for this card.",
                color=discord.Color.blurple()
            )
            await interaction.response.edit_message(embed=embed, view=view)
            return

        # ⭐ Normal flow
        self.card["series"] = self.values[0]

        view = await create_set_view(self.bot, self.card, self.cards, self.card_index, self.guild_id)
        embed = discord.Embed(
            title=f"Card #{self.card_index} — Select Set",
            description=f"Series: **{self.card['series']}**\n\nChoose the **Set** for this card.",
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=view)


async def create_set_view(bot, card, cards, card_index, guild_id):
    async with bot.db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT set_name FROM expansion_list WHERE series = $1 ORDER BY set_name",
            card["series"]
        )

    options = [discord.SelectOption(label=row["set_name"], value=row["set_name"]) for row in rows]


    options.append(discord.SelectOption(label="Skip Set", value="__skip_set__"))

    view = discord.ui.View(timeout=600)
    view.add_item(SetSelect(bot, card, cards, card_index, guild_id, options))
    return view


class SetSelect(discord.ui.Select):
    def __init__(self, bot, card, cards, card_index, guild_id, options):
        super().__init__(placeholder="Select Set", options=options)
        self.bot = bot
        self.card = card
        self.cards = cards
        self.card_index = card_index
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):


        if self.values[0] == "__skip_set__":
            self.card["set_name"] = None

            view = discord.ui.View(timeout=600)
            view.add_item(ConditionSelect(self.bot, self.card, self.cards, self.card_index, self.guild_id))

            embed = discord.Embed(
                title=f"Card #{self.card_index} — Select Condition",
                description=(
                    f"Series: {self.card['series'] or 'Skipped'}\n"
                    f"Set: Skipped\n\n"
                    "Select the **condition** for this card."
                ),
                color=discord.Color.blurple()
            )
            await interaction.response.edit_message(embed=embed, view=view)
            return


        self.card["set_name"] = self.values[0]

        view = discord.ui.View(timeout=600)
        view.add_item(ConditionSelect(self.bot, self.card, self.cards, self.card_index, self.guild_id))

        embed = discord.Embed(
            title=f"Card #{self.card_index} — Select Condition",
            description=(
                f"Series: **{self.card['series']}**\n"
                f"Set: **{self.card['set_name']}**\n\n"
                "Select the **condition** for this card."
            ),
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=view)


class ConditionSelect(discord.ui.Select):
    def __init__(self, bot, card, cards, card_index, guild_id):
        options = [
            discord.SelectOption(label="Near Mint", value="Near Mint"),
            discord.SelectOption(label="Lightly Played", value="Lightly Played"),
            discord.SelectOption(label="Moderately Played", value="Moderately Played"),
            discord.SelectOption(label="Heavily Played", value="Heavily Played"),
            discord.SelectOption(label="Damaged", value="Damaged"),
            discord.SelectOption(label="Graded", value="Graded"),
        ]
        super().__init__(placeholder="Select Condition", options=options)
        self.bot = bot
        self.card = card
        self.cards = cards
        self.card_index = card_index
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        self.card["condition"] = self.values[0]
        self.cards.append(self.card)

        if len(self.cards) >= 5:
            embed = discord.Embed(
                title="Maximum Cards Reached",
                description="You have added the maximum of **5 cards**.\n\n"
                            "Next, you can optionally upload images for these cards.",
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=embed, view=None)
            await start_image_upload_flow(interaction, self.bot, self.cards, self.guild_id)
            return

        view = AddMoreCardsView(self.bot, self.cards, self.card_index, self.guild_id)
        embed = discord.Embed(
            title=f"Card #{self.card_index} Added",
            description="Would you like to add another card, or continue to the image upload step?",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=view)


class AddMoreCardsView(discord.ui.View):
    def __init__(self, bot, cards, last_index, guild_id):
        super().__init__(timeout=600)
        self.bot = bot
        self.cards = cards
        self.last_index = last_index
        self.guild_id = guild_id

        if len(self.cards) >= 10:
            self.add_button.disabled = True

    @discord.ui.button(label="Add Another Card", style=discord.ButtonStyle.primary)
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SingleCardBasicModal(self.bot, self.cards, card_index=self.last_index + 1, guild_id=self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Continue to Images", style=discord.ButtonStyle.success)
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)
        await start_image_upload_flow(interaction, self.bot, self.cards, self.guild_id)


# ---------------------------------------------------------
#  IMAGE UPLOAD FLOW (DM, up to 10 images)
# ---------------------------------------------------------
async def start_image_upload_flow(interaction, bot, cards, guild_id):
    channel = interaction.channel

    instructions = discord.Embed(
        title="Optional Image Upload",
        description=(
            "You may now upload **up to 10 images**.\n"
            "Send images in one message or multiple messages.\n"
            "Type `done` when finished or `skip` to continue without images."
        ),
        color=discord.Color.blurple()
    )
    await channel.send(embed=instructions)

    images = []

    def check(m):
        return m.author.id == interaction.user.id and m.channel.id == channel.id

    while True:
        try:
            msg = await bot.wait_for("message", timeout=600.0, check=check)
        except asyncio.TimeoutError:
            await channel.send(embed=discord.Embed(
                title="Timeout",
                description="Image upload timed out. Continuing without images.",
                color=discord.Color.red()
            ))
            break

        content = msg.content.lower().strip()

        if content == "skip":
            await channel.send(embed=discord.Embed(
                title="Skipping Images",
                description="Continuing without images.",
                color=discord.Color.orange()
            ))
            images = []
            break

        if content == "done":
            await channel.send(embed=discord.Embed(
                title="Image Upload Complete",
                description="Processing your submission. This may take a few moments...",
                color=discord.Color.green()
            ))
            break

        if msg.attachments:
            for att in msg.attachments:
                if len(images) >= 10:
                    await channel.send(embed=discord.Embed(
                        title="Image Limit Reached",
                        description="You have uploaded more than 10 images and terminated the process. Please try again and ensure no more than 10 images are uploaded.",
                        color=discord.Color.red()
                    ))
                    break
                images.append(att)

            await channel.send(embed=discord.Embed(
                title="Images Received",
                description=f"Total images: **{len(images)} / 10**",
                color=discord.Color.green()
            ))

            try:
                await msg.delete()
            except:
                pass
        else:
            await channel.send(embed=discord.Embed(
                title="No Attachments",
                description="Upload images or type `done`.",
                color=discord.Color.red()
            ))

    await finalize_submission(bot, interaction, cards, images, guild_id)


# ---------------------------------------------------------
#  FINAL SUBMISSION (send to admin + user confirmation)
# ---------------------------------------------------------
async def finalize_submission(bot, interaction, cards, images, guild_id):
    admin_id = await get_admin_id(bot, guild_id)
    if not admin_id:
        await interaction.channel.send(embed=discord.Embed(
            title="Admin Not Configured",
            description="❌ Admin is not configured for this server.",
            color=discord.Color.red()
        ))
        return

    admin = await bot.fetch_user(admin_id)
    if admin is None:
        await interaction.channel.send(embed=discord.Embed(
            title="Admin Not Found",
            description="❌ Could not find the admin user.",
            color=discord.Color.red()
        ))
        return

    embed = discord.Embed(
        title=f"{interaction.user.name} submitted cards",
        color=discord.Color.gold()
    )

    for idx, c in enumerate(cards, start=1):
        embed.add_field(
            name=f"Card #{idx}: {c['name']}",
            value=(
                f"Series: {c['series']}\n"
                f"Set: {c['set_name']}\n"
                f"Number: {c['number']}\n"
                f"Condition: {c['condition']}\n"
                f"Price: ${c['price']:.2f}"
            ),
            inline=False
        )
        embed.add_field(name="\u200b", value="\u200b", inline=False)

    files = []
    for i, att in enumerate(images, start=1):
        data = await att.read()
        files.append(discord.File(BytesIO(data), filename=f"submission_{interaction.user.id}_{i}.jpg"))

    await admin.send(embed=embed, files=files if files else None)

    await interaction.channel.send(embed=discord.Embed(
        title="Submission Successful",
        description="🎉 Your submission has been sent! An admin will contact you soon.",
        color=discord.Color.green()
    ))
# ---------------------------------------------------------
#  COLLECTIONS FLOW – 10+ cards
# ---------------------------------------------------------
class SubmitCollectionModal(discord.ui.Modal, title="Submit Your Collection"):
    url = discord.ui.TextInput(
        label="Collection URL",
        placeholder="Paste a link to your collection",
        required=True
    )

    notes = discord.ui.TextInput(
        label="Notes",
        style=discord.TextStyle.paragraph,
        placeholder="Notate cards not for sale or add extra info",
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        await send_collection_to_admin(interaction, self.url.value, self.notes.value)


async def send_collection_to_admin(interaction: discord.Interaction, url: str, notes: str):
    guild_id = interaction.guild.id if interaction.guild else None
    if guild_id is None:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Error",
                description="❌ This command must be used inside a server.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return

    admin_id = await get_admin_id(interaction.client, guild_id)
    if not admin_id:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Admin Not Configured",
                description="❌ No admin is configured for this server.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return

    admin = interaction.client.get_user(admin_id)
    if admin is None:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Admin Not Found",
                description="❌ Could not locate the admin user.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return

    user = interaction.user

    # Build admin embed
    embed = discord.Embed(
        title=f"{user.name} submitted a collection",
        description=f"[Click here to view the collection]({url})",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="Raw URL",
        value=url,
        inline=False
    )

    embed.add_field(
        name="Notes",
        value=notes or "None provided",
        inline=False
    )

    # Send to admin
    await admin.send(embed=embed)

    # Confirm to user
    confirm_embed = discord.Embed(
        title="Collection Submitted",
        description="Your collection has been sent to the admin. They will contact you soon.",
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=confirm_embed, ephemeral=True)
# ---------------------------------------------------------
#  COMMAND: /sellyourcards
# ---------------------------------------------------------
class SellCards(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="sellyourcards",
        description="Submit cards or a collection for us to buy"
    )
    async def sellyourcards(self, interaction: discord.Interaction):

        # ⭐ Prevent running inside DMs
        if interaction.guild is None:
            embed = discord.Embed(
                title="Cannot Run in DMs",
                description=(
                    "❌ This command must be used **inside a server**.\n\n"
                    "Please run `/sellyourcards` in the server where you want to submit your cards."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # ⭐ Safe to use guild_id now
        guild_id = await get_guild_id_from_settings(
            interaction.client,
            interaction.guild.id
        )

        buying_guide = (
            "**Buying Guide**\n"
            "We typically pay **70% - 75%** for singles, sometimes higher depending on the card and condition.\n"
            "Use **/buyingguide** for full details.\n\n"
            "**Choose your submission type below:**"
        )

        embed = discord.Embed(
            title="Sell Your Cards",
            description=buying_guide,
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(
            embed=embed,
            view=SellCardsDropdownView(guild_id),
            ephemeral=True
        )

# ---------------------------------------------------------
#  SETUP
# ---------------------------------------------------------
async def setup(bot: commands.Bot):
    await bot.add_cog(SellCards(bot))


