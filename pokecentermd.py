import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# DB imports
from db.connection import init_db, get_pool

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # REQUIRED for on_member_join to fire

class MyBot(commands.Bot):
    async def setup_hook(self):
        # Initialize database connection
        await init_db()
        self.db = get_pool()

        # Load inventory cog
        await self.load_extension("Commands.Inventory.inventory")
        await self.load_extension("Commands.Cart.cart")
        await self.load_extension("Commands.Orders.myorderscommand")

        # Global sync for slash commands
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} slash commands")

bot = MyBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# -------------------------
#   WELCOME MESSAGE EVENT
# -------------------------
@bot.event
async def on_member_join(member):
    WELCOME_CHANNEL_ID = 1532117357147848825

    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        await channel.send(
            f"Welcome to the server {member.mention}!\n\n"
            "There are a few commands you can use to buy or sell your cards to us integrated into our channel:\n\n"
            "• **/inventory** – browse the cards we have available for sale and add them to your cart\n"
            "• **/cart** – submit and pay for your order\n"
            "• **/sellmycards** – send us cards you'd like to offload\n"
            "• **/currentlybuying** – view the inventory we are currently seeking\n"
            "• **/upcomingshows** – see what shows we are attending in the near future!\n\n"
            "To get a refresher about what commands the bot offers, use **/help**!"
        )

# -------------------------
#   HELP COMMAND (Embed + Ephemeral)
# -------------------------
@bot.tree.command(name="help", description="Shows all available commands and what they do.")
async def help_command(interaction: discord.Interaction):

    embed = discord.Embed(
        title="📘 Bot Command Guide",
        description="Here’s everything you can do with the bot:",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="🛒 /inventory",
        value="Browse the cards we have available for sale and add them to your cart.",
        inline=False
    )
    embed.add_field(
        name="💳 /cart",
        value="Submit and pay for your order.",
        inline=False
    )
    embed.add_field(
        name="📤 /sellmycards",
        value="Send us cards you'd like to offload.",
        inline=False
    )
    embed.add_field(
        name="📥 /currentlybuying",
        value="View the inventory we are currently seeking.",
        inline=False
    )
    embed.add_field(
        name="🎪 /upcomingshows",
        value="See what shows we are attending in the near future.",
        inline=False
    )
    embed.add_field(
        name="ℹ️ /help",
        value="View this command list again.",
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.run(TOKEN)
