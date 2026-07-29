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

class MyBot(commands.Bot):
    async def setup_hook(self):
        # Initialize database connection
        await init_db()
        self.db = get_pool()

        # Load inventory cog
        await self.load_extension("Commands.Inventory.inventory")
        await self.load_extension("Commands.Cart.cart")

        # Global sync for slash commands
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} slash commands")

bot = MyBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="ping", description="Replies with pong!")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong")

bot.run(TOKEN)
