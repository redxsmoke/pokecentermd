import discord
import stripe
import asyncpg
import os
from discord.ext import commands
from discord import app_commands

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")


# ============================================================
# BUTTON VIEW
# ============================================================
class SubscriptionButtons(discord.ui.View):
    def __init__(self, vendor_id, subscription_id, stripe_subscription_id):
        super().__init__(timeout=None)
        self.vendor_id = vendor_id
        self.subscription_id = subscription_id
        self.stripe_subscription_id = stripe_subscription_id

    async def get_db(self):
        return await asyncpg.connect(DATABASE_URL)

    # -------------------------
    # SUBSCRIBE BUTTON
    # -------------------------
    @discord.ui.button(label="Subscribe", style=discord.ButtonStyle.green)
    async def subscribe(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Only admins can subscribe.",
                ephemeral=True
            )

        guild_id = interaction.guild.id
        admin_id = interaction.user.id

        db = await self.get_db()

        vendor = await db.fetchrow("""
            SELECT vendor_id, stripe_customer_id
            FROM vendors
            WHERE admin_id = $1
        """, admin_id)

        if vendor:
            vendor_id = vendor["vendor_id"]
            stripe_customer_id = vendor["stripe_customer_id"]
        else:
            vendor = await db.fetchrow("""
                INSERT INTO vendors (name, email, admin_id)
                VALUES ($1, $2, $3)
                RETURNING vendor_id
            """, interaction.user.name, f"user-{admin_id}@example.com", admin_id)

            vendor_id = vendor["vendor_id"]

            customer = stripe.Customer.create(
                email=f"user-{admin_id}@example.com",
                metadata={
                    "vendor_id": vendor_id,
                    "admin_id": admin_id,
                    "guild_id": guild_id
                }
            )

            stripe_customer_id = customer.id

            await db.execute("""
                UPDATE vendors
                SET stripe_customer_id = $1
                WHERE vendor_id = $2
            """, stripe_customer_id, vendor_id)

        price_id = "price_12345"

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url="https://yourdomain.com/success",
            cancel_url="https://yourdomain.com/cancel",
            metadata={
                "guild_id": str(guild_id),
                "admin_id": str(admin_id),
                "vendor_id": str(vendor_id)
            }
        )

        await db.close()

        await interaction.response.send_message(
            f"Click here to subscribe:\n{session.url}",
            ephemeral=True
        )

    # -------------------------
    # UNSUBSCRIBE BUTTON
    # -------------------------
    @discord.ui.button(label="Unsubscribe", style=discord.ButtonStyle.red)
    async def unsubscribe(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Only admins can unsubscribe.",
                ephemeral=True
            )

        stripe.Subscription.modify(
            self.stripe_subscription_id,
            cancel_at_period_end=True
        )

        await interaction.response.send_message(
            "Subscription will end at the end of the billing period.",
            ephemeral=True
        )

    # -------------------------
    # TURN ON AUTO RENEWAL
    # -------------------------
    @discord.ui.button(label="Turn On Auto Renewal", style=discord.ButtonStyle.blurple)
    async def auto_on(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Only admins can modify auto-renewal.",
                ephemeral=True
            )

        stripe.Subscription.modify(
            self.stripe_subscription_id,
            cancel_at_period_end=False
        )

        await interaction.response.send_message(
            "Auto-renewal enabled.",
            ephemeral=True
        )

    # -------------------------
    # TURN OFF AUTO RENEWAL
    # -------------------------
    @discord.ui.button(label="Turn Off Auto Renewal", style=discord.ButtonStyle.gray)
    async def auto_off(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Only admins can modify auto-renewal.",
                ephemeral=True
            )

        stripe.Subscription.modify(
            self.stripe_subscription_id,
            cancel_at_period_end=True
        )

        await interaction.response.send_message(
            "Auto-renewal disabled.",
            ephemeral=True
        )


# ============================================================
# COG (THIS WAS MISSING)
# ============================================================
class AdminSubscription(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="manage_subscription", description="Manage your server's subscription")
    @app_commands.default_permissions(administrator=True)
    async def manage_subscription(self, interaction: discord.Interaction):

        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Only admins can manage subscriptions.",
                ephemeral=True
            )

        # You will later fetch these from DB
        vendor_id = 1
        subscription_id = 1
        stripe_subscription_id = "sub_12345"

        view = SubscriptionButtons(vendor_id, subscription_id, stripe_subscription_id)

        await interaction.response.send_message(
            "Manage your subscription:",
            view=view,
            ephemeral=True
        )


# ============================================================
# SETUP FUNCTION (NOW CORRECT)
# ============================================================
async def setup(bot):
    await bot.add_cog(AdminSubscription(bot))
