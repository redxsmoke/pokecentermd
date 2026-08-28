import os
import discord
import logging
from discord.ext import commands
from dotenv import load_dotenv
from Commands.BotSettings.admin_channel_helpers import get_singles_role


# DB imports
from db.connection import init_db, get_pool

# BADGE SYSTEM IMPORT
from Users.upsertuser import BadgeDB

# -------------------------
#   SHOP STATE VARIABLES
# -------------------------
SHOP_OPEN = True
SHOP_CLOSE_REASON = None

# -------------------------
#   LOGGING SETUP
# -------------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("bot")

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class MyBot(commands.Bot):
    async def setup_hook(self):

        await init_db()
        self.db = get_pool()

        # Initialize badge system
        self.badgedb = BadgeDB(self.db)

        extensions = [
            "Commands.Inventory.inventory",
            "Commands.Cart.cart",
            "Commands.Orders.myorderscommand",
            "Commands.Orders.myordersview",
            "Commands.Admin.admincommands",
            "Commands.Admin.inventory_csv_import",
            "Commands.SellCards.sellcards",
            "Commands.BuyingGuide.buyingguide",
            "Commands.UpcomingShows.upcomingshows",
            "Commands.BotSettings.releasenotesannouncement",
            "Commands.Badges.mybadges",
            "Commands.Badges.userbadges",
            "Commands.CatchPokemon.catchpokemoncommand",
            "Commands.Daily.dailycommand",
            "Commands.wishlist.mywishlist",
            "Commands.SinglesRole.singlesrole",
            "Commands.RecentlyAdded.recentlyadded" 
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


# ---------------------------------------------------------
#   GLOBAL APP COMMAND ERROR LOGGER (SAFE)
# ---------------------------------------------------------
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    logger.error(
        f"[APP COMMAND ERROR] Command={interaction.command.name if interaction.command else 'None'} "
        f"User={interaction.user.id} "
        f"Error={error.__class__.__name__}: {error}",
        exc_info=True
    )

    try:
        await interaction.response.send_message(
            "⚠️ An internal error occurred while processing this command.",
            ephemeral=True
        )
        return
    except discord.InteractionResponded:
        pass
    except discord.NotFound:
        pass

    try:
        await interaction.followup.send(
        "⚠️ An internal error occurred while processing this command.",
        ephemeral=True
        )
    except Exception:
        logger.error("[ERROR HANDLER] Could not send error message (interaction invalid).")


# ---------------------------------------------------------
#   SAFE INTERACTION LOGGER + BADGE SYSTEM HOOK
# ---------------------------------------------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    logger.debug(
        f"[INTERACTION] type={interaction.type} id={interaction.id} data={interaction.data}"
    )

    # --- Badge System User Tracking ---
    async with bot.db.acquire() as conn:
        created = await bot.badgedb.ensure_user_exists(interaction.user, interaction.guild.id)

        # Award First Partner badge ONLY if user is new AND does NOT already have it
        if created:

            # Check if user already has the badge
            has_badge = await conn.fetchval("""
                SELECT 1
                FROM user_badges ub
                JOIN badges b ON b.badge_id = ub.badge_id
                WHERE ub.user_id = $1
                AND LOWER(b.name) = 'first partner'
                LIMIT 1;
            """, interaction.user.id)

            if not has_badge:
                await bot.badgedb.auto_award_first_partner(interaction.user.id)

                # Fetch badge info
                badge = await conn.fetchrow("""
                    SELECT name, emoji_name, emoji_id, description
                    FROM badges
                    WHERE LOWER(name) = 'first partner';
                """)

                # Build embed
                embed = discord.Embed(
                    title="🎉 Badge Awarded!",
                    description=f"You’ve earned the **{badge['name']}** badge!",
                    color=discord.Color.gold()
                )

                # Render badge emoji exactly like your Items bot
                badge_emoji = (
                    f"<:{badge['emoji_name']}:{badge['emoji_id']}>"
                    if badge["emoji_id"] else "⬜"
                )

                embed.add_field(
                    name="Badge Description:",
                    value=badge["description"],
                    inline=False
                )

                embed.add_field(
                    name="Next Steps",
                    value=(
                        "Run **/mybadges** to view all your badges.\n"
                        "Run **/userbadges @user** to view other users' badges."
                    ),
                    inline=False
                )

                # Thumbnail uses the badge emoji image
                embed.set_thumbnail(
                    url=f"https://cdn.discordapp.com/emojis/{badge['emoji_id']}.png?size=96&quality=lossless"
                )

                try:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                except discord.InteractionResponded:
                    pass


# ---------------------------------------------------------
#   WELCOME MESSAGE (DB-DRIVEN WELCOME CHANNEL)
# ---------------------------------------------------------
@bot.event
async def on_member_join(member: discord.Member):
    print(f"[DEBUG] Member joined: {member} (ID: {member.id}) in guild {member.guild.name}")

    # --- FIX ADDED HERE ---
    await bot.badgedb.ensure_user_exists(member, member.guild.id)

    # Fetch welcome channel from DB
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT welcome_channel_id FROM guild_settings WHERE guild_id = $1",
            member.guild.id
        )

    if not row or not row["welcome_channel_id"]:
        print("[DEBUG] No welcome channel set for this guild.")
        return

    welcome_channel_id = row["welcome_channel_id"]
    channel = member.guild.get_channel(welcome_channel_id)

    if channel is None:
        print(f"[DEBUG] Welcome channel ID {welcome_channel_id} not found in guild.")
        return

    await channel.send(
        f"Welcome to the server {member.mention}!\n\n"
        "There are a few commands you can use to buy or sell your cards to us:\n\n"
        "• **/shop** – browse the cards we have available for sale and add them to your cart\n"
        "• **/cart** – submit and pay for your order\n"
        "• **/sellyourcards** – send us cards you'd like to offload\n"
        "• **/buyingguide** – view our current buying rates\n"
        "• **/myorders** – view your past orders\n"
        "• **/mywishlist** – Add, view, and remove items to your wish list. Get alerts for new singles that match your wish list!\n"
        "• **/catchpokemon** – Earn rewards by catching pokemon!\n"
        "• **/daily** – Earn rewards by checking in daily\n"
        "• **/mybadges** – View your badges\n"
        "• **/userbadges** – View other server members badges\n"
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

    embed.add_field(name="🛒 /shop", value="Browse cards and add to cart.", inline=False)
    embed.add_field(name="💳 /cart", value="Submit and pay for your order.", inline=False)
    embed.add_field(name="📤 /sellyourcards", value="Send us cards you'd like to offload.", inline=False)
    embed.add_field(name="📘 /buyingguide", value="View our current buying rates.", inline=False)
    embed.add_field(name="📦 /myorders", value="View your past orders.", inline=False)
    embed.add_field(name="🎪 /upcomingshows", value="See our upcoming shows.", inline=False)
    embed.add_field(name="✨ /mywishlist", value="Add, view, and remove items to your wish list. Get alerts for new singles that match your wish list!", inline=False)
    embed.add_field(name="🏅 /catchpokemon", value="Earn rewards by catching pokemon!", inline=False)
    embed.add_field(name="📆 /daily", value="Earn rewards by checking in daily", inline=False)
    embed.add_field(name="⭐ /mybadges", value="View your badges", inline=False)
    embed.add_field(name="👤 /userbadges", value="View other server members' badges", inline=False)
    embed.add_field(name="ℹ️ /help", value="View this command list again.", inline=False)

    embed.add_field(
        name="**Troubleshooting:**",
        value="If you receive this error ⚠️ **An internal error occurred while processing this command**, make sure you are **not running the command inside a direct message**. Run it again inside the Discord server.",
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)



bot.run(TOKEN)