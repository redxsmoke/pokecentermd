import discord
from discord import app_commands

ADMIN_ID = 337773020770729985  # Your admin ID


# ---------------------------------------------------------
#  DROPDOWN VIEW (Singles or Collection)
# ---------------------------------------------------------
class SellCardsDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Submit Singles (1-10 cards)", value="singles"),
            discord.SelectOption(label="Submit Collection (10+ cards)", value="collection")
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
            await interaction.response.send_modal(
                SubmitSingleCardModal(card_index=1, cards=[])
            )

        elif choice == "collection":
            await interaction.response.send_modal(
                SubmitCollectionModal()
            )


class SellCardsDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(SellCardsDropdown())


# ---------------------------------------------------------
#  SINGLES FLOW – 1 to 10 cards (or more)
# ---------------------------------------------------------
class SubmitSingleCardModal(discord.ui.Modal, title="Submit a Single Card"):
    def __init__(self, card_index: int, cards: list):
        super().__init__()
        self.card_index = card_index
        self.cards = cards

        self.name = discord.ui.TextInput(label="Card Name", required=True)
        self.set = discord.ui.TextInput(label="Set", required=True)
        self.number = discord.ui.TextInput(label="Card Number", required=True)
        self.condition = discord.ui.TextInput(label="Condition", required=True)
        self.price = discord.ui.TextInput(label="Asking Price", required=True)

        self.add_item(self.name)
        self.add_item(self.set)
        self.add_item(self.number)
        self.add_item(self.condition)
        self.add_item(self.price)

    async def on_submit(self, interaction: discord.Interaction):
        self.cards.append({
            "name": self.name.value,
            "set": self.set.value,
            "number": self.number.value,
            "condition": self.condition.value,
            "price": self.price.value
        })

        if self.card_index < 10:
            view = AddMoreCardsView(self.card_index, self.cards)
            await interaction.response.send_message(
                f"Card #{self.card_index} added. Add another?",
                view=view,
                ephemeral=True
            )
        else:
            await send_cards_to_admin(interaction, self.cards)


class AddMoreCardsView(discord.ui.View):
    def __init__(self, card_index, cards):
        super().__init__()
        self.card_index = card_index
        self.cards = cards

    @discord.ui.button(label="Add Another Card", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            SubmitSingleCardModal(card_index=self.card_index + 1, cards=self.cards)
        )

    @discord.ui.button(label="Submit", style=discord.ButtonStyle.success)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await send_cards_to_admin(interaction, self.cards)


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


# ---------------------------------------------------------
#  ADMIN DM FUNCTIONS
# ---------------------------------------------------------
async def send_cards_to_admin(interaction, cards):
    admin = interaction.client.get_user(ADMIN_ID)
    user = interaction.user

    embed = discord.Embed(
        title=f"{user.name} submitted cards for review",
        color=discord.Color.gold()
    )

    for c in cards:
        embed.add_field(
            name=c["name"],
            value=f"Set: {c['set']}\n"
                  f"Number: {c['number']}\n"
                  f"Condition: {c['condition']}\n"
                  f"Asking Price: {c['price']}",
            inline=False
        )

    await admin.send(embed=embed)
    await interaction.response.send_message("Your submission has been sent!", ephemeral=True)


async def send_collection_to_admin(interaction, url, notes):
    admin = interaction.client.get_user(ADMIN_ID)
    user = interaction.user

    # Use markdown link to force clickability
    embed = discord.Embed(
        title=f"{user.name} submitted a collection",
        description=f"[Click here to view collection]({url})",
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

    await admin.send(embed=embed)
    await interaction.response.send_message("Your collection has been submitted!", ephemeral=True)


# ---------------------------------------------------------
#  COMMAND: /sellyourcards
# ---------------------------------------------------------
async def setup(bot):
    @bot.tree.command(name="sellyourcards", description="Submit cards for us to buy")
    async def sellyourcards(interaction: discord.Interaction):

        buying_guide = (
            "**Buying Guide**\n"
            "We typically pay **70% - 75%** for singles, sometimes higher depending on the card and condition.\n"
            "Use **/buyingguide** for full details.\n\n"
            "**Choose your submission type below:**"
        )

        await interaction.response.send_message(
            buying_guide,
            view=SellCardsDropdownView(),
            ephemeral=True
        )
