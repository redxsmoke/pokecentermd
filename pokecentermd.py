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

        # Existing users default to FALSE; this migration is safe on restarts.
        async with self.db.acquire() as conn:
            await conn.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS welcome_bonus_received BOOLEAN NOT NULL DEFAULT FALSE
            """)

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
            "Commands.VoltorbSweeper.voltorb_sweeper",
            "Commands.Admin.VendorCalculator.vendorcalculator",
            "Commands.Admin.SalesReport.salesreport"

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
        self.add_view(RulesAgreeView())
        self.add_view(GettingStartedView())

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
#   ONBOARDING: PERSISTENT RULES + SHOPPING SHORTCUTS
# ---------------------------------------------------------
WELCOME_BONUS = 100_000


async def award_welcome_bonus(user_id: int, guild_id: int) -> bool:
    """One atomic credit per user per guild, even under simultaneous clicks."""
    async with bot.db.acquire() as conn:
        credited = await conn.fetchval("""
            UPDATE users
            SET coin_balance = COALESCE(coin_balance, 0) + $3,
                welcome_bonus_received = TRUE
            WHERE user_id = $1
              AND guild_id = $2
              AND welcome_bonus_received = FALSE
            RETURNING welcome_bonus_received
        """, user_id, guild_id, WELCOME_BONUS)
    return credited is True


class GettingStartedView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Browse Pokémon Cards", emoji="🛒",
                       style=discord.ButtonStyle.primary, custom_id="welcome_browse_singles")
    async def browse(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_license(interaction):
            return
        # Use the existing shop command implementation, not a duplicate storefront.
        cog = interaction.client.get_cog("InventoryGrouped")
        if cog is None:
            await interaction.response.send_message(
                "The shop is temporarily unavailable. Try `/shop singles`.", ephemeral=True)
            return
        try:
            await cog.shop_singles.callback(cog, interaction)
        except Exception:
            logger.exception("Welcome shop shortcut failed")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Unable to open the shop right now. Try `/shop singles`.", ephemeral=True)
            else:
                await interaction.followup.send(
                    "Unable to open the shop right now. Try `/shop singles`.", ephemeral=True)

    @discord.ui.button(label="Create a Wishlist", emoji="💖",
                       style=discord.ButtonStyle.secondary, custom_id="welcome_open_wishlist")
    async def wishlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_license(interaction):
            return
        command = interaction.client.tree.get_command("mywishlist")
        if command is None:
            await interaction.response.send_message(
                "Wishlist is temporarily unavailable. Try `/mywishlist`.", ephemeral=True)
            return
        try:
            # The callback is reused so the shortcut stays in sync with /mywishlist.
            if command.binding is not None:
                await command.callback(command.binding, interaction)
            else:
                await command.callback(interaction)
        except Exception:
            logger.exception("Welcome wishlist shortcut failed")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Unable to open your wishlist right now. Try `/mywishlist`.", ephemeral=True)
            else:
                await interaction.followup.send(
                    "Unable to open your wishlist right now. Try `/mywishlist`.", ephemeral=True)


class RulesAgreeView(discord.ui.View):
    def __init__(self, member_role=None, allowed_user_id=None):
        super().__init__(timeout=None)
        self.member_role = member_role
        self.allowed_user_id = allowed_user_id

    @discord.ui.button(label="Agree", style=discord.ButtonStyle.green,
                       custom_id="rules_agree_button")
    async def agree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Please use this button in the server.", ephemeral=True)
            return

        # A persistent view has no original per-user context after a restart.
        # Enforce the correct member and role using the current server state.
        if self.allowed_user_id is not None and interaction.user.id != self.allowed_user_id:
            await interaction.response.send_message("This welcome button belongs to another member.", ephemeral=True)
            return

        member = interaction.user
        async with bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT member_role_id FROM guild_settings WHERE guild_id = $1",
                interaction.guild.id)
        role = interaction.guild.get_role(row["member_role_id"]) if row and row["member_role_id"] else None
        if role is None:
            role = discord.utils.get(interaction.guild.roles, name="Member")
        if role is None:
            await interaction.response.send_message(
                "No Member role is configured. Please contact an admin.", ephemeral=True)
            return

        if role not in member.roles:
            try:
                await member.add_roles(role, reason="Accepted server rules")
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Failed to grant member role")
                await interaction.response.send_message(
                    "I couldn't grant your Member role. Please contact an admin.", ephemeral=True)
                return

        # Ensure the user row exists, then credit once (never on join alone).
        await bot.badgedb.ensure_user_exists(member, interaction.guild.id)
        try:
            bonus_awarded = await award_welcome_bonus(member.id, interaction.guild.id)
        except Exception:
            logger.exception("Welcome bonus failed for user=%s guild=%s", member.id, interaction.guild.id)
            await interaction.response.send_message(
                "Rules accepted, but your welcome coins could not be processed. "
                "Please try Agree again or contact an admin.", ephemeral=True)
            return

        description = (
            f"You've accepted the rules and received the **{role.name}** role!\n\n"
            + (f"🎁 **Welcome bonus: +{WELCOME_BONUS:,} coins!**\n\n"
               if bonus_awarded else "")
            + "Ready to find your next Pokémon card? Choose an option below."
        )
        embed = discord.Embed(title="🎉 Welcome to the Shop!",
                              description=description, color=discord.Color.green())
        embed.set_footer(text="For all commands, use /help")
        await interaction.response.send_message(embed=embed, view=GettingStartedView(), ephemeral=True)


@bot.event
async def on_member_join(member: discord.Member):
    logger.info("Member joined: %s (%s) in %s", member, member.id, member.guild.name)
    # Check whether this user was already recorded BEFORE creating their row.
    async with bot.db.acquire() as conn:
        existing_user = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM users WHERE user_id = $1 AND guild_id = $2)",
            member.id, member.guild.id)

    await bot.badgedb.ensure_user_exists(member, member.guild.id)

    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT welcome_channel_id FROM guild_settings WHERE guild_id = $1",
            member.guild.id)
    if not row or not row["welcome_channel_id"]:
        return
    channel = member.guild.get_channel(row["welcome_channel_id"])
    if channel is None:
        return

    embed = discord.Embed(
        title=f"👋 Welcome {member.display_name}!",
        description=(
            "**Please review the rules before accessing the server:**\n\n"
            "📌 **Server Rules**\n"
            "• Be respectful to all members\n"
            "• No harassment, politics, or hate speech\n"
            "• No spamming or advertising\n"
            "• Users who abuse the system may be banned at the admin's discretion\n"
            "• Follow Discord's Terms of Service\n\n"
            + (f"🎁 **New member gift: {WELCOME_BONUS:,} coins!**\n"
               if not existing_user else "")
            + "Click **Agree** to accept the rules and unlock the server."
        ),
        color=discord.Color.blurple()
    )
    await channel.send(embed=embed, view=RulesAgreeView(allowed_user_id=member.id))


# ---------------------------------------------------------
#   HELP COMMAND
# ---------------------------------------------------------
# Centralized command directory for /help.
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
