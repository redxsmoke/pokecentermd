import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# DB imports
from db.connection import init_db, get_pool

# -------------------------
#   SHOP STATE VARIABLES
# -------------------------
SHOP_OPEN = True
SHOP_CLOSE_REASON = None

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True   # REQUIRED for on_member_join


class MyBot(commands.Bot):
    async def setup_hook(self):

        await init_db()
        self.db = get_pool()

        extensions = [
            "Commands.Inventory.inventory",
            "Commands.Cart.cart",
            "Commands.Orders.myorderscommand",
            "Commands.Orders.myordersview",
            "Commands.Admin.admincommands",
            "Commands.SellCards.sellcards",
            "Commands.BuyingGuide.buyingguide",
            "Commands.UpcomingShows.upcomingshows"
        ]

        print("\n=== EXTENSION LOAD REPORT ===")

        for ext in extensions:
            try:
                await self.load_extension(ext)
                print(f"[OK] Loaded: {ext}")
            except Exception as e:
                print(f"[FAIL] Could NOT load: {ext}")
                print(f"       Error: {e.__class__.__name__}: {e}")

        print("=== END OF REPORT ===\n")

        synced = await self.tree.sync()
        print(f"Synced {len(synced)} commands globally.")



bot = MyBot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


# ---------------------------------------------------------
#   WELCOME MESSAGE (UPDATED)
# ---------------------------------------------------------
@bot.event
async def on_member_join(member):
    WELCOME_CHANNEL_ID = 1532117357147848825

    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        await channel.send(
            f"Welcome to the server {member.mention}!\n\n"
            "There are a few commands you can use to buy or sell your cards to us:\n\n"
            "• **/inventory** – browse the cards we have available for sale and add them to your cart\n"
            "• **/cart** – submit and pay for your order\n"
            "• **/sellyourcards** – send us cards you'd like to offload\n"
            "• **/buyingguide** – view our current buying rates\n"
            "• **/myorders** – view your past orders\n"
            "• **/upcomingshows** – see what shows we are attending soon!\n\n"
            "To get a refresher about what commands the bot offers, use **/help**!"
        )


# ---------------------------------------------------------
#   HELP COMMAND
# ---------------------------------------------------------
@bot.tree.command(name="help", description="Shows all available commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📘 Bot Command Guide",
        description="Here’s everything you can do with the bot:",
        color=discord.Color.blue()
    )

    embed.add_field(name="🛒 /inventory", value="Browse cards and add to cart.", inline=False)
    embed.add_field(name="💳 /cart", value="Submit and pay for your order.", inline=False)
    embed.add_field(name="📤 /sellyourcards", value="Send us cards you'd like to offload.", inline=False)
    embed.add_field(name="📘 /buyingguide", value="View our current buying rates.", inline=False)
    embed.add_field(name="📦 /myorders", value="View your past orders.", inline=False)
    embed.add_field(name="🎪 /upcomingshows", value="See our upcoming shows.", inline=False)
    embed.add_field(name="ℹ️ /help", value="View this command list again.", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.run(TOKEN)
