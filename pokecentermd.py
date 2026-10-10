from dotenv import load_dotenv
load_dotenv()

import os
import discord
import logging
from discord.ext import commands
from dotenv import load_dotenv
from Commands.BotSettings.admin_channel_helpers import get_singles_role
from Utils.daily_license_expiration import daily_license_expiration_task

# DB imports
from db.connection import init_db, get_pool

# BADGE SYSTEM IMPORT
from Users.upsertuser import BadgeDB

SHOP_OPEN = True
SHOP_CLOSE_REASON = None

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

        self.badgedb = BadgeDB(self.db)

        extensions = [
            "Commands.Inventory.inventory",
            "Commands.Inventory.inventory_sealed",
            "Commands.Inventory.inventory_grouped",
            "Commands.Cart.cart",
            "Commands.Orders.myorderscommand",
            "Commands.Orders.myordersview",
            "Commands.Admin.claim_sale_wizard",
            "Commands.Admin.claim_sale_runtime",
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
            "Commands.RecentlyAdded.recentlyadded",
            "Commands.ShippingInfo.shipping_info",
            "Commands.PokeTrivia.poketrivia",
            "Commands.UserLevel.userlevel",
            "Commands.Leaderboard.leaderboard",
            "Commands.MyRewards.my_rewards",
            "Commands.ReportBug.report_a_bug",
            "Commands.OwnerCommands.manage_bugs",
            "Commands.Pokedex.pokedex",
            "Commands.Admin.subscribe",
            "Commands.UnownCipher.unowncipher",
            "Commands.Admin.set_member_role",
            "Commands.Wallet.wallet",
            "Commands.Dexdecoder.dexdecoder",
            "Commands.Slots.slots"
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

        # REGISTER PERSISTENT VIEW
        self.add_view(RulesAgreeView(None, None))

        self.loop.create_task(daily_license_expiration_task(self))
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} commands globally.")


bot = MyBot(command_prefix="!", intents=intents)

from Utils.license_check import check_license

original_call = bot.tree._call

async def patched_call(interaction: discord.Interaction):
    allowed = await check_license(interaction)
    if not allowed:
        return
    return await original_call(interaction)

bot.tree._call = patched_call


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    logger.error(
        f"[APP COMMAND ERROR] Command={interaction.command.name if interaction.command else 'None'} "
        f"User={interaction.user.id} "
        f"Error={error.__class__.__name__}: {error}",
        exc_info=True
    )

    embed = discord.Embed(
        title="⚠️ Internal Error",
        description="An internal error occurred while processing this command.",
        color=discord.Color.red()
    )

    try:
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    except discord.InteractionResponded:
        pass
    except discord.NotFound:
        pass

    try:
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception:
        logger.error("[ERROR HANDLER] Could not send error message (interaction invalid).")


@bot.event
async def on_interaction(interaction: discord.Interaction):
    logger.debug(
        f"[INTERACTION] type={interaction.type} id={interaction.id} data={interaction.data}"
    )

    async with bot.db.acquire() as conn:
        created = await bot.badgedb.ensure_user_exists(interaction.user, interaction.guild.id)

        if created:
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

                badge = await conn.fetchrow("""
                    SELECT name, emoji_name, emoji_id, description
                    FROM badges
                    WHERE LOWER(name) = 'first partner';
                """)

                embed = discord.Embed(
                    title="🎉 Badge Awarded!",
                    description=f"You’ve earned the **{badge['name']}** badge!",
                    color=discord.Color.gold()
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

                embed.set_thumbnail(
                    url=f"https://cdn.discordapp.com/emojis/{badge['emoji_id']}.png?size=96&quality=lossless"
                )

                try:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                except discord.InteractionResponded:
                    pass


# ---------------------------------------------------------
#   PERSISTENT RULES AGREEMENT BUTTON
# ---------------------------------------------------------
class RulesAgreeView(discord.ui.View):
    def __init__(self, member_role, allowed_user_id):
        super().__init__(timeout=None)
        self.member_role = member_role
        self.allowed_user_id = allowed_user_id

    @discord.ui.button(
        label="Agree",
        style=discord.ButtonStyle.green,
        custom_id="rules_agree_button"
    )
    async def agree_button(self, interaction: discord.Interaction, button: discord.ui.Button):

        # Only the joining user can click
        if self.allowed_user_id is not None and interaction.user.id != self.allowed_user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⚠️ Not Allowed",
                    description="This button is not for you.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Role missing
        if self.member_role is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⚠️ No Member Role",
                    description="No Member role is configured. Please contact an admin.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        await interaction.user.add_roles(self.member_role)

        # SEND COMMAND LIST HERE (embed)
        embed = discord.Embed(
            title="✅ Rules Accepted",
            description=(
                f"You have agreed to the rules and have been granted the **{self.member_role.name}** role!"
            ),
            color=discord.Color.green()
        )

        embed.add_field(
            name="📘 Commands You Can Use",
            value=(
                "**/shop sealed** – browse sealed products\n"
                "**/shop singles** – browse singles\n"
                "**/cart** – submit and pay for your order\n"
                "**/sellyourcards** – offload cards\n"
                "**/buyingguide** – view buying rates\n"
                "**/myorders** – view past orders\n"
                "**/mywishlist** – manage your wishlist\n"
                "**/catchpokemon** – catch Pokémon for rewards\n"
                "**/unowncipher** – play the unown cipher game\n"
                "**/pokedex** – view caught Pokémon\n"
                "**/daily** – daily check‑in rewards\n"
                "**/mybadges** – view your badges\n"
                "**/userbadges** – view others’ badges\n"
                "**/mylevel** – view your level\n"
                "**/leaderboard** – server leaderboard\n"
                "**/shippinginfo** – save shipping address\n"
                "**/reportabug** – report issues\n"
                "**/help** – view all commands\n"
            ),
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
#   WELCOME MESSAGE (RULES ONLY)
# ---------------------------------------------------------
@bot.event
async def on_member_join(member: discord.Member):
    print(f"[DEBUG] Member joined: {member} (ID: {member.id}) in guild {member.guild.name}")

    await bot.badgedb.ensure_user_exists(member, member.guild.id)

    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT welcome_channel_id, member_role_id FROM guild_settings WHERE guild_id = $1",
            member.guild.id
        )

    if not row or not row["welcome_channel_id"]:
        return

    welcome_channel_id = row["welcome_channel_id"]
    configured_role_id = row["member_role_id"]

    channel = member.guild.get_channel(welcome_channel_id)
    if channel is None:
        return

    # 1. Try configured role
    member_role = None
    if configured_role_id:
        member_role = member.guild.get_role(configured_role_id)

        # If not found, refresh role cache
        if member_role is None:
            print(f"[WARN] Role {configured_role_id} not found in cache. Refreshing...")
            await member.guild.fetch_roles()
            member_role = member.guild.get_role(configured_role_id)

        # Check bot permissions
        if member_role is not None:
            bot_member = member.guild.get_member(bot.user.id)
            if member_role.position >= bot_member.top_role.position:
                print("[ERROR] Bot cannot assign Member role due to role hierarchy.")
                member_role = None

    # 2. Fallback to role named "Member"
    if member_role is None:
        member_role = discord.utils.get(member.guild.roles, name="Member")

    # 3. If still missing → notify admins
    if member_role is None:
        await channel.send(
            embed=discord.Embed(
                title="⚠️ Admin Action Required",
                description=(
                    "This server does not have a configured Member role.\n"
                    "Please run **/setmemberrole** to enable onboarding."
                ),
                color=discord.Color.red()
            )
        )

    # RULES ONLY EMBED
    embed = discord.Embed(
        title=f"👋 Welcome {member.display_name}!",
        description=(
            "**Before you can access the server, please review the rules below:**\n\n"
            "📌 **Server Rules**\n"
            "• Be respectful to all members\n"
            "• No harassment, politics, or hate speech\n"
            "• No spamming or advertising\n"
            "• Users who abuse the system may be banned at the admin's discretion\n"
            "• Follow Discord’s Terms of Service\n\n"
            "Click **Agree** below to accept the rules and receive access. Failure to follow these rules will result in a ban"
        ),
        color=discord.Color.blurple()
    )

    await channel.send(embed=embed, view=RulesAgreeView(member_role, member.id))


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

    embed.add_field(name="🛒📦 /shop sealed", value="Browse sealed collection and add to cart.", inline=False)
    embed.add_field(name="🛒 /shop singles", value="Browse cards and add to cart.", inline=False)
    embed.add_field(name="💳 /cart", value="Submit and pay for your order.", inline=False)
    embed.add_field(name="📤 /sellyourcards", value="Send us cards you'd like to offload.", inline=False)
    embed.add_field(name="📘 /buyingguide", value="View our current buying rates.", inline=False)
    embed.add_field(name="📦 /myorders", value="View your past orders.", inline=False)
    embed.add_field(name="🎪 /upcomingshows", value="See our upcoming shows.", inline=False)
    embed.add_field(name="✨ /mywishlist", value="Add, view, and remove items to your wish list.", inline=False)
    embed.add_field(name="🏅 /catchpokemon", value="Earn rewards by catching pokemon!", inline=False)
    embed.add_field(name="🔡 /unowncipher", value="Play the unown cipher game!", inline=False)
    embed.add_field(name="✅ /pokedex", value="View pokemon you've caught using /catchpokemon", inline=False)
    embed.add_field(name="📆 /daily", value="Earn rewards by checking in daily", inline=False)
    embed.add_field(name="⭐ /mybadges", value="View your badges", inline=False)
    embed.add_field(name="👤 /userbadges", value="View other server members' badges", inline=False)
    embed.add_field(name="🎚️ /mylevel", value="View your current level and EXP progress", inline=False)
    embed.add_field(name="👑 /leaderboard", value="View level and number of pokemon caught leaderboard", inline=False)
    embed.add_field(name="✉️ /shippinginfo", value="Add a saved shipping aderss for faster checkout", inline=False)
    embed.add_field(name="🐛 /reportabug", value="Report an issue with the bot to the developers!", inline=False)
    embed.add_field(name="ℹ️ /help", value="View this command list again.", inline=False)

    embed.add_field(
        name="**Troubleshooting:**",
        value="If you receive this error ⚠️ **An internal error occurred while processing this command**, make sure you are **not running the command inside a direct message**.",
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.run(TOKEN)
