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

        # If a subscription already exists, disable Subscribe
        if self.subscription_id is not None:
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.label == "Subscribe":
                    item.disabled = True

    async def get_db(self):
        return await asyncpg.connect(DATABASE_URL)

    # -------------------------
    # SUBSCRIBE BUTTON
    # -------------------------
    @discord.ui.button(label="Subscribe", style=discord.ButtonStyle.green)
    async def subscribe(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Permission Denied",
                description="Only admins can subscribe.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # If subscription already exists, block re-subscribe
        if self.subscription_id is not None:
            embed = discord.Embed(
                title="Already Subscribed",
                description="You already have an active subscription for this server.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        guild_id = interaction.guild.id
        admin_id = interaction.user.id

        db = await self.get_db()

        # -------------------------
        # FETCH VENDOR OR CREATE NEW
        # -------------------------
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

        # -------------------------
        # FETCH PRICE ID FROM DB
        # -------------------------
        price_row = await db.fetchrow("""
            SELECT price_id
            FROM stripe_pricing_keys
            WHERE tier_name = $1
        """, "premium")

        if not price_row:
            await db.close()
            embed = discord.Embed(
                title="Pricing Error",
                description="Pricing configuration error: No price found for tier 'premium'.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        price_id = price_row["price_id"]

        # -------------------------
        # CREATE STRIPE CHECKOUT SESSION
        # -------------------------
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url="https://checkout.stripe.dev/success",
            cancel_url="https://checkout.stripe.dev/cancel",
            metadata={
                "guild_id": str(guild_id),
                "admin_id": str(admin_id),
                "vendor_id": str(vendor_id)
            }
        )

        await db.close()

        embed = discord.Embed(
            title="Subscribe",
            description=f"[Click here to subscribe]({session.url})",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -------------------------
    # UNSUBSCRIBE BUTTON
    # -------------------------
    @discord.ui.button(label="Unsubscribe", style=discord.ButtonStyle.red)
    async def unsubscribe(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Permission Denied",
                description="Only admins can unsubscribe.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if not self.stripe_subscription_id:
            embed = discord.Embed(
                title="No Active Subscription",
                description="There is no active subscription to cancel.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        stripe.Subscription.modify(
            self.stripe_subscription_id,
            cancel_at_period_end=True
        )

        embed = discord.Embed(
            title="Unsubscribe",
            description="Subscription will end at the end of the current billing period.",
            color=discord.Color.orange()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -------------------------
    # TURN ON AUTO RENEWAL
    # -------------------------
    @discord.ui.button(label="Turn On Auto Renewal", style=discord.ButtonStyle.blurple)
    async def auto_on(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Permission Denied",
                description="Only admins can modify auto-renewal.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if not self.stripe_subscription_id:
            embed = discord.Embed(
                title="No Subscription Found",
                description="Cannot enable auto-renewal without an active subscription.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        stripe.Subscription.modify(
            self.stripe_subscription_id,
            cancel_at_period_end=False
        )

        embed = discord.Embed(
            title="Auto-Renewal Enabled",
            description="Auto-renewal has been enabled for this subscription.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -------------------------
    # TURN OFF AUTO RENEWAL
    # -------------------------
    @discord.ui.button(label="Turn Off Auto Renewal", style=discord.ButtonStyle.gray)
    async def auto_off(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Permission Denied",
                description="Only admins can modify auto-renewal.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if not self.stripe_subscription_id:
            embed = discord.Embed(
                title="No Subscription Found",
                description="Cannot disable auto-renewal without an active subscription.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        stripe.Subscription.modify(
            self.stripe_subscription_id,
            cancel_at_period_end=True
        )

        embed = discord.Embed(
            title="Auto-Renewal Disabled",
            description="Auto-renewal has been disabled for this subscription.",
            color=discord.Color.orange()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# COG
# ============================================================
class AdminSubscription(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="manage_subscription",
        description="Manage your server's subscription"
    )
    @app_commands.default_permissions(administrator=True)
    async def manage_subscription(self, interaction: discord.Interaction):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Permission Denied",
                description="Only admins can manage subscriptions.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        db = await asyncpg.connect(DATABASE_URL)
        admin_id = interaction.user.id

        vendor = await db.fetchrow("""
            SELECT vendor_id
            FROM vendors
            WHERE admin_id = $1
        """, admin_id)

        if vendor:
            vendor_id = vendor["vendor_id"]
        else:
            vendor_id = None

        subscription = None
        stripe_subscription_id = None
        subscription_id = None

        if vendor_id is not None:
            subscription = await db.fetchrow("""
                SELECT subscription_id, stripe_subscription_id
                FROM subscriptions
                WHERE vendor_id = $1
                  AND guild_id = $2
                  AND status = 'active'
                ORDER BY subscription_id DESC
                LIMIT 1
            """, vendor_id, interaction.guild.id)

            if subscription:
                subscription_id = subscription["subscription_id"]
                stripe_subscription_id = subscription["stripe_subscription_id"]

        await db.close()

        view = SubscriptionButtons(
            vendor_id,
            subscription_id,
            stripe_subscription_id
        )

        if subscription is None:
            embed = discord.Embed(
                title="Subscription",
                description=(
                    "You do not currently have an active subscription.\n\n"
                    "Use the **Subscribe** button below to start a subscription."
                ),
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="Manage Subscription",
                description="Use the buttons below to manage your existing subscription.",
                color=discord.Color.green()
            )

        await interaction.followup.send(
            embed=embed,
            view=view,
            ephemeral=True
        )


# ============================================================
# BUTTON VIEW (UPDATED UNSUBSCRIBE INCLUDED)
# ============================================================
class SubscriptionButtons(discord.ui.View):
    def __init__(self, vendor_id, subscription_id, stripe_subscription_id):
        super().__init__(timeout=None)
        self.vendor_id = vendor_id
        self.subscription_id = subscription_id
        self.stripe_subscription_id = stripe_subscription_id

        # Disable Subscribe if already subscribed
        if self.subscription_id is not None:
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.label == "Subscribe":
                    item.disabled = True

    async def get_db(self):
        return await asyncpg.connect(DATABASE_URL)

    # -------------------------
    # SUBSCRIBE BUTTON
    # -------------------------
    @discord.ui.button(label="Subscribe", style=discord.ButtonStyle.green)
    async def subscribe(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Permission Denied",
                description="Only admins can subscribe.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if self.subscription_id is not None:
            embed = discord.Embed(
                title="Already Subscribed",
                description="You already have an active subscription for this server.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

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

        price_row = await db.fetchrow("""
            SELECT price_id
            FROM stripe_pricing_keys
            WHERE tier_name = $1
        """, "premium")

        if not price_row:
            await db.close()
            embed = discord.Embed(
                title="Pricing Error",
                description="Pricing configuration error: No price found for tier 'premium'.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        price_id = price_row["price_id"]

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url="https://checkout.stripe.dev/success",
            cancel_url="https://checkout.stripe.dev/cancel",
            metadata={
                "guild_id": str(guild_id),
                "admin_id": str(admin_id),
                "vendor_id": str(vendor_id)
            }
        )

        await db.close()

        embed = discord.Embed(
            title="Subscribe",
            description=f"[Click here to subscribe]({session.url})",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -------------------------
    # UPDATED UNSUBSCRIBE BUTTON
    # -------------------------
    @discord.ui.button(label="Unsubscribe", style=discord.ButtonStyle.red)
    async def unsubscribe(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Permission Denied",
                description="Only admins can unsubscribe.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if not self.stripe_subscription_id:
            embed = discord.Embed(
                title="No Active Subscription",
                description="There is no active subscription to cancel.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # Fetch subscription details
        sub = stripe.Subscription.retrieve(self.stripe_subscription_id)

        price_id = sub["items"]["data"][0]["price"]["id"]
        price = stripe.Price.retrieve(price_id)
        amount = price["unit_amount"]  # cents

        # Determine period end
        import datetime
        period_end = sub["current_period_end"]
        period_end_dt = datetime.datetime.fromtimestamp(period_end)
        period_end_str = period_end_dt.strftime("%B %d, %Y")

        # Confirmation dialog
        class ConfirmUnsubscribe(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)

            @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
            async def yes(self, yes_interaction: discord.Interaction, yes_button: discord.ui.Button):

                # FREE tier → delete
                if amount == 0:
                    stripe.Subscription.delete(self.stripe_subscription_id)
                else:
                    # PAID tier → cancel at period end
                    stripe.Subscription.modify(
                        self.stripe_subscription_id,
                        cancel_at_period_end=True
                    )

                # DB update
                db = await asyncpg.connect(DATABASE_URL)
                await db.execute("""
                    UPDATE subscriptions
                    SET status = 'canceled',
                        cancel_at_period_end = TRUE,
                        updated_at = NOW()
                    WHERE stripe_subscription_id = $1
                """, self.stripe_subscription_id)

                await db.execute("""
                    UPDATE guild_settings
                    SET license_active = FALSE,
                        license_last_checked = NOW()
                    WHERE subscription_id = $1
                """, self.subscription_id)

                await db.close()

                embed = discord.Embed(
                    title="Subscription Canceled",
                    description="Your subscription has been successfully canceled.",
                    color=discord.Color.green()
                )
                await yes_interaction.response.send_message(embed=embed, ephemeral=True)
                self.stop()

            @discord.ui.button(label="No", style=discord.ButtonStyle.red)
            async def no(self, no_interaction: discord.Interaction, no_button: discord.ui.Button):
                embed = discord.Embed(
                    title="No Changes Made",
                    description="Your subscription remains active.",
                    color=discord.Color.red()
                )
                await no_interaction.response.send_message(embed=embed, ephemeral=True)
                self.stop()

        # Send confirmation prompt
        embed = discord.Embed(
            title="Confirm Unsubscribe",
            description=(
                f"Are you sure you want to unsubscribe?\n\n"
                f"Your subscription will remain active until **{period_end_str}**.\n\n"
                "Choose **Yes** to cancel or **No** to keep your subscription."
            ),
            color=discord.Color.orange()
        )

        await interaction.response.send_message(
            embed=embed,
            view=ConfirmUnsubscribe(),
            ephemeral=True
        )

    # -------------------------
    # AUTO RENEW ON
    # -------------------------
    @discord.ui.button(label="Turn On Auto Renewal", style=discord.ButtonStyle.blurple)
    async def auto_on(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Permission Denied",
                description="Only admins can modify auto-renewal.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if not self.stripe_subscription_id:
            embed = discord.Embed(
                title="No Subscription Found",
                description="Cannot enable auto-renewal without an active subscription.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        stripe.Subscription.modify(
            self.stripe_subscription_id,
            cancel_at_period_end=False
        )

        embed = discord.Embed(
            title="Auto-Renewal Enabled",
            description="Auto-renewal has been enabled for this subscription.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -------------------------
    # AUTO RENEW OFF
    # -------------------------
    @discord.ui.button(label="Turn Off Auto Renewal", style=discord.ButtonStyle.gray)
    async def auto_off(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Permission Denied",
                description="Only admins can modify auto-renewal.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if not self.stripe_subscription_id:
            embed = discord.Embed(
                title="No Subscription Found",
                description="Cannot disable auto-renewal without an active subscription.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        stripe.Subscription.modify(
            self.stripe_subscription_id,
            cancel_at_period_end=True
        )

        embed = discord.Embed(
            title="Auto-Renewal Disabled",
            description="Auto-renewal has been disabled for this subscription.",
            color=discord.Color.orange()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# SETUP FUNCTION
# ============================================================
async def setup(bot):
    await bot.add_cog(AdminSubscription(bot))
