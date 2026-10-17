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
            "Commands.Slots.slots",
            "Commands.DealorNoDeal.dealornodeal",
            "Commands.PokeMart.pokemart",	
            "Commands.VoltorbSweeper.voltorb_sweeper"

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

        add_command_sections(embed, detailed=True)

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

    # WELCOME AND RULES EMBED
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
            "Click **Agree** below to accept the rules and receive access. Failure to follow these rules will result in a ban. If you need a reminder of the list of commands, just type /help"
        ),
        color=discord.Color.blurple()
    )

    add_command_sections(embed, detailed=False)

    await channel.send(embed=embed, view=RulesAgreeView(member_role, member.id))


# ---------------------------------------------------------
#   HELP COMMAND
# ---------------------------------------------------------
# Centralized command directory, shared by /help and both welcome embeds.
# Keep this list updated as new public commands are added.
COMMAND_SECTIONS = (
    ("🛒 Shop Commands", (
        ("/shop sealed", "Browse sealed Pokémon products."),
        ("/shop singles", "Browse individual cards and add them to your cart."),
        ("/cart", "View your cart and check out."),
        ("/buyingguide", "See current card-buying rates."),
        ("/myorders", "View your previous orders."),
        ("/mywishlist", "Manage your card wishlist."),
        ("/myrewards", "View your available rewards."),
        ("/shippinginfo", "Save or update your shipping address."),
        ("/sellyourcards", "Submit cards you want to sell."),
        ("/singlesrole", "Opt in to new singles notifications."),
        ("/upcomingshows", "Find upcoming card shows."),
    )),
    ("🎮 Game Commands", (
        ("/unowncipher", "Solve the Unown cipher."),
        ("/catchpokemon", "Catch Pokémon and earn rewards."),
        ("/slots", "Play the slots game."),
        ("/dexdecoder", "Play Dex Decoder."),
        ("/dealornodeal", "Play Giovanni's Deal or No Deal."),
        ("/voltorbsweeper", "Play Voltorb Sweeper."),
        ("/pokemart", "Visit the Poké Mart.")

    )),
    ("🏆 Progress Commands", (
        ("/pokedex", "View Pokémon you've caught."),
        ("/daily", "Claim your daily reward."),
        ("/mybadges", "View your earned badges."),
        ("/userbadges", "View another member's badges."),
        ("/mylevel", "Check your level and experience."),
        ("/leaderboard", "View the server leaderboard."),
        ("/wallet", "View your wallet and currency."),
    )),
    ("🤖 Bot Commands", (
        ("/help", "Open this command guide."),
        ("/reportabug", "Report an issue to the developers."),
    )),
)


def add_command_sections(embed: discord.Embed, detailed: bool = True):
    """Add four organized command categories without exceeding embed field limits."""
    for heading, commands_list in COMMAND_SECTIONS:
        if detailed:
            value = "\n".join(f"**{command}** — {description}" for command, description in commands_list)
        else:
            value = " • ".join(f"`{command}`" for command, _ in commands_list)
        embed.add_field(name=heading, value=value, inline=False)


@bot.tree.command(name="help", description="Shows all available commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📘 Bot Command Guide",
        description="Explore the shop, play games, track your progress, and manage your account.",
        color=discord.Color.blue()
    )
    add_command_sections(embed, detailed=True)
    embed.add_field(
        name="🔧 Troubleshooting",
        value="If you receive an internal error, make sure you're running the command in the server rather than a direct message.",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.run(TOKEN)
