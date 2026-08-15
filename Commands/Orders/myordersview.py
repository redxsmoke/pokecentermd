import discord
from discord.ext import commands
import datetime

# =====================================================================
# ADMIN ORDER VIEW
# =====================================================================
class AdminOrderView(discord.ui.View):
    def __init__(self, bot, order_id, user_id, items, shipping_method, admin_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id
        self.items = items
        self.shipping_method = shipping_method
        self.admin_id = admin_id

        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label in ("Mark Shipped", "Enter Tracking #"):
                child.disabled = True

    @discord.ui.button(label="Confirm Payment", style=discord.ButtonStyle.success)
    async def confirm_payment(self, interaction, button):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="Only the admin can confirm payment.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            status = await conn.fetchrow(
                "SELECT order_status FROM orders WHERE order_id = $1;",
                self.order_id
            )

        if status["order_status"] != "Pending":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Payment Already Confirmed",
                    description="Payment was already confirmed for this order.",
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )
            return

        estimated_delivery = datetime.date.today() + datetime.timedelta(days=14)

        async with self.bot.db.acquire() as conn:
            for item in self.items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET reserved = GREATEST(reserved - $1, 0),
                        quantity_available = GREATEST(quantity_available - $1, 0),
                        reserved_until = NULL
                    WHERE inventory_id = $2;
                    """,
                    item["quantity"],
                    item["inventory_id"]
                )

            await conn.execute(
                """
                UPDATE orders
                SET order_status = 'Paid',
                    date_paid = NOW(),
                    estimated_delivery = $2
                WHERE order_id = $1;
                """,
                self.order_id,
                estimated_delivery
            )

        button.disabled = True

        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Mark Shipped":
                child.disabled = False

        await interaction.message.edit(view=self)

        buyer = await interaction.client.fetch_user(self.user_id)
        try:
            await buyer.send(
                embed=discord.Embed(
                    title="Payment Confirmed",
                    description=f"Your payment for order #{self.order_id} has been confirmed.\n"
                                f"Estimated delivery: **{estimated_delivery.strftime('%Y-%m-%d')}**",
                    color=discord.Color.green()
                )
            )
        except:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Order Updated",
                description=f"Order #{self.order_id} marked as **Paid**.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

    @discord.ui.button(label="Mark Shipped", style=discord.ButtonStyle.primary)
    async def mark_shipped(self, interaction, button):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="Only the admin can mark orders as shipped.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            status = await conn.fetchrow(
                "SELECT order_status, shipping_method FROM orders WHERE order_id = $1;",
                self.order_id
            )

        if status["order_status"] == "Shipped":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Already Shipped",
                    description="Shipping was already confirmed for this order.",
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )
            return

        if status["order_status"] == "Cancelled":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Order Cancelled",
                    description="This order was cancelled. No further actions can be taken.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        shipping_method = status["shipping_method"].lower()

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET order_status = 'Shipped',
                    date_shipped = NOW()
                WHERE order_id = $1;
                """,
                self.order_id
            )

            if "plain white envelope" in shipping_method:
                await conn.execute(
                    """
                    UPDATE orders
                    SET tracking_number = 'Shipped without tracking'
                    WHERE order_id = $1;
                    """,
                    self.order_id
                )

        button.disabled = True

        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Enter Tracking #":
                child.disabled = ("plain white envelope" in shipping_method)

        await interaction.message.edit(view=self)

        buyer = await interaction.client.fetch_user(self.user_id)
        try:
            await buyer.send(
                embed=discord.Embed(
                    title="Order Shipped",
                    description=f"Your order #{self.order_id} has been marked as shipped.",
                    color=discord.Color.green()
                )
            )
        except:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Order Updated",
                description=f"Order #{self.order_id} marked as **Shipped**.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

    @discord.ui.button(label="Enter Tracking #", style=discord.ButtonStyle.secondary)
    async def enter_tracking(self, interaction, button):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="Only the admin can enter tracking numbers.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            status = await conn.fetchrow(
                "SELECT order_status, shipping_method FROM orders WHERE order_id = $1;",
                self.order_id
            )

        if status["order_status"] != "Shipped":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Not Shipped Yet",
                    description="You cannot enter a tracking number until the order is marked as shipped.",
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )
            return

        if "plain white envelope" in status["shipping_method"].lower():
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="No Tracking Required",
                    description="This order was shipped via PWE and does not have tracking.",
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            TrackingNumberModal(self.bot, self.order_id, self.user_id, self, self.admin_id)
        )

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction, button):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="Only the admin can cancel orders.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            CancelOrderModal(self.bot, self.order_id, self.user_id, self.items, self, self.admin_id)
        )

# =====================================================================
# TRACKING NUMBER MODAL
# =====================================================================
class TrackingNumberModal(discord.ui.Modal, title="Enter Tracking Number"):
    tracking = discord.ui.TextInput(
        label="Tracking Number",
        required=True,
        style=discord.TextStyle.short
    )

    def __init__(self, bot, order_id, user_id, admin_view, admin_id):
        super().__init__()
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id
        self.admin_view = admin_view
        self.admin_id = admin_id

    async def on_submit(self, interaction):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="Only the admin can enter tracking numbers.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET tracking_number = $2
                WHERE order_id = $1;
                """,
                self.order_id,
                self.tracking.value
            )

        for child in self.admin_view.children:
            if isinstance(child, discord.ui.Button) and child.label == "Enter Tracking #":
                child.disabled = True

        await interaction.message.edit(view=self.admin_view)

        buyer = await interaction.client.fetch_user(self.user_id)
        try:
            await buyer.send(
                embed=discord.Embed(
                    title="Tracking Number Added",
                    description=f"Your order #{self.order_id} now has tracking:\n**{self.tracking.value}**",
                    color=discord.Color.green()
                )
            )
        except:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Tracking Added",
                description=f"Tracking number saved for order #{self.order_id}.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

# =====================================================================
# CANCEL ORDER MODAL
# =====================================================================
class CancelOrderModal(discord.ui.Modal, title="Cancel Order"):
    reason = discord.ui.TextInput(
        label="Reason for cancellation",
        required=True,
        style=discord.TextStyle.long
    )

    def __init__(self, bot, order_id, user_id, items, admin_view, admin_id):
        super().__init__()
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id
        self.items = items
        self.admin_view = admin_view
        self.admin_id = admin_id

    async def on_submit(self, interaction):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="Only the admin can cancel orders.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            status = await conn.fetchrow(
                "SELECT order_status FROM orders WHERE order_id = $1;",
                self.order_id
            )

            if status["order_status"] == "Shipped":
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Cannot Cancel",
                        description="This order has already been shipped and cannot be cancelled.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                return

            for item in self.items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET quantity_available = quantity_available + $2,
                        reserved = 0,
                        reserved_until = NULL
                    WHERE inventory_id = $1;
                    """,
                    item["inventory_id"],
                    item["quantity"]
                )

            await conn.execute(
                """
                UPDATE orders
                SET order_status = 'Cancelled',
                    cancelled_reason = $2
                WHERE order_id = $1;
                """,
                self.order_id,
                self.reason.value
            )

        buyer = await interaction.client.fetch_user(self.user_id)
        try:
            await buyer.send(
                embed=discord.Embed(
                    title="Order Cancelled",
                    description=f"Your order #{self.order_id} has been cancelled.\nReason: {self.reason.value}",
                    color=discord.Color.red()
                )
            )
        except:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Order Cancelled",
                description=f"Order #{self.order_id} has been cancelled and inventory restored.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

        for child in self.admin_view.children:
            if isinstance(child, discord.ui.Button) and child.label == "Cancel Order":
                child.disabled = True

        await interaction.message.edit(view=self.admin_view)
# =====================================================================
# ADMIN TRACKING RESPONSE MODAL
# =====================================================================
class AdminTrackingResponseModal(discord.ui.Modal, title="Provide Status Update"):
    def __init__(self, bot, order_id, user_id):
        super().__init__()
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id

        self.message = discord.ui.TextInput(
            label="Status Update Message",
            placeholder="Type the update you want to send to the buyer...",
            style=discord.TextStyle.long,
            required=True,
            max_length=500
        )
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            buyer = await interaction.client.fetch_user(self.user_id)
        except Exception as e:
            await interaction.response.send_message(
                f"Error fetching buyer: {e}",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"Update on Order #{self.order_id}",
            description=self.message.value,
            color=discord.Color.blue()
        )

        try:
            await buyer.send(embed=embed)
        except Exception as e:
            await interaction.response.send_message(
                f"Could not DM buyer: {e}",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Status update sent to buyer for Order #{self.order_id}.",
            ephemeral=True
        )

# =====================================================================
# ADMIN NOT RECEIVED VIEW
# =====================================================================
class AdminNotReceivedView(discord.ui.View):
    def __init__(self, bot, order_id, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id

    @discord.ui.button(label="Mark as Delivered", style=discord.ButtonStyle.success)
    async def mark_delivered(self, interaction, button):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET received = TRUE,
                    date_received = NOW(),
                    order_status = 'Delivered'
                WHERE order_id = $1;
                """,
                self.order_id
            )

        buyer = await interaction.client.fetch_user(self.user_id)
        try:
            await buyer.send(
                embed=discord.Embed(
                    title="Order Updated",
                    description=f"Admin has marked your order #{self.order_id} as delivered.",
                    color=discord.Color.green()
                )
            )
        except:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Order Updated",
                description=f"Order #{self.order_id} marked as delivered.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

    @discord.ui.button(label="Provide Status Update", style=discord.ButtonStyle.primary)
    async def provide_update(self, interaction, button):
        await interaction.response.send_modal(
            AdminTrackingResponseModal(self.bot, self.order_id, self.user_id)
        )

# =====================================================================
# BUYER BUTTON — MARK RECEIVED
# =====================================================================
class MarkReceivedButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="Mark Received",
            style=discord.ButtonStyle.success,
            custom_id="mark_received"
        )
        self.parent_view = parent_view

    async def callback(self, interaction):
        order = self.parent_view.pages[self.parent_view.page]

        async with self.parent_view.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET received = TRUE,
                    date_received = NOW(),
                    order_status = 'Delivered'
                WHERE order_id = $1;
                """,
                order["order_id"]
            )

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Order Updated",
                description=f"Order #{order['order_id']} marked as **Received**.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

        # Rebuild lists and refresh view
        self.parent_view.refresh_order_lists()
        await self.parent_view.update(interaction)

# =====================================================================
# BUYER BUTTON — MARK NOT RECEIVED
# =====================================================================
class MarkNotReceivedButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="Mark Not Received",
            style=discord.ButtonStyle.danger,
            custom_id="mark_not_received"
        )
        self.parent_view = parent_view

    async def callback(self, interaction):
        order = self.parent_view.pages[self.parent_view.page]
        order_id = order["order_id"]
        estimated = order["estimated_delivery"]
        today = datetime.date.today()

        if order.get("reported_missing", False):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Already Reported",
                    description="You have already reported this order as not received.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        if estimated is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Order Not Yet Shipped",
                    description=(
                        "Your order has not yet been shipped.\n"
                        "All orders are shipped within **48 hours** of payment.\n\n"
                        f"If it has been more than 48 hours, contact <@{self.parent_view.admin_id}>."
                    ),
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )
            return

        if today < estimated:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Too Early to Report",
                    description=(
                        f"Your order is not expected until **{estimated.strftime('%Y-%m-%d')}**.\n"
                        "If you have not received it by then, please report again."
                    ),
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )
            return

        async with self.parent_view.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET received = FALSE,
                    date_received = NULL,
                    order_status = 'Not Received',
                    reported_missing = TRUE
                WHERE order_id = $1 AND user_id = $2;
                """,
                order_id,
                self.parent_view.user_id
            )

        order["reported_missing"] = True

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Package Not Received",
                description=(
                    f"Your report for order #{order_id} has been sent to the admin.\n"
                    "They will respond shortly."
                ),
                color=discord.Color.red()
            ),
            ephemeral=True
        )

        admin = await interaction.client.fetch_user(self.parent_view.admin_id)

        admin_embed = discord.Embed(
            title="Order Marked as NOT Received",
            description=(
                f"**Order ID:** {order_id}\n"
                f"**Buyer:** <@{self.parent_view.user_id}>\n"
                f"**Estimated Delivery:** {estimated.strftime('%Y-%m-%d')}\n"
                f"**Shipping Method:** {order['shipping_method']}\n"
                f"**Tracking #:** {order['tracking_number'] or 'None'}\n\n"
                "Buyer reports the package has **NOT** been received."
            ),
            color=discord.Color.red()
        )

        try:
            await admin.send(
                embed=admin_embed,
                view=AdminNotReceivedView(
                    self.parent_view.bot,
                    order_id,
                    self.parent_view.user_id
                )
            )
        except:
            pass

# =====================================================================
# BUYER BUTTON — PAY
# =====================================================================
class PayButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="Pay",
            style=discord.ButtonStyle.success,
            custom_id="pay_now"
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        order = self.parent_view.pages[self.parent_view.page]

        # Do not allow pay on cancelled orders
        if order["order_status"] == "Cancelled":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Order Cancelled",
                    description="This order has been cancelled and cannot be paid.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Load payment config
        async with self.parent_view.bot.db.acquire() as conn:
            config = await conn.fetchrow(
                """
                SELECT venmo_handle, cashapp_handle, paypal_handle
                FROM guild_settings
                WHERE guild_id = $1;
                """,
                interaction.guild_id
            )

        # ✅ Strip whitespace AND leading '@' from handles
        venmo = (config["venmo_handle"] or "").strip().lstrip("@")
        cashapp = (config["cashapp_handle"] or "").strip()
        paypal = (config["paypal_handle"] or "").strip()

        total = float(order["total"])
        method = (order["payment_method"] or "").lower()

        if method == "venmo" and venmo:
            # ✅ Correct Venmo URL format
            link = f"https://venmo.com/{venmo}?txn=pay&amount={total}"
            label = "Venmo Payment Link"
        elif method == "cashapp" and cashapp:
            link = f"https://cash.app/{cashapp}/{total}"
            label = "CashApp Payment Link"
        elif method == "paypal" and paypal:
            link = f"https://paypal.me/{paypal}/{total}"
            label = "PayPal Payment Link"
        else:
            link = None
            label = "Payment Not Configured"

        if not link:
            embed = discord.Embed(
                title="Payment Not Configured",
                description="This payment method is not configured for this guild.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="Complete Your Payment",
            description=(
                f"**Order ID:** {order['order_id']}\n"
                f"**Total Due:** ${total:.2f}\n"
                f"**Payment Method:** {order['payment_method'].capitalize()}\n\n"
                f"{label}:\n{link}"
            ),
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# =====================================================================
# BUYER-FACING VIEW — ACTIVE / DELIVERED DROPDOWN
# =====================================================================
class MyOrdersView(discord.ui.View):
    def __init__(self, bot, user_id, active_orders, delivered_orders, mode, admin_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.user_id = user_id
        self.active_orders = active_orders
        self.delivered_orders = delivered_orders
        self.admin_id = admin_id

        # Force default to ACTIVE mode
        self.mode = "active"
        self.page = 0

        # Current pages always derived from mode
        self.pages = self.active_orders

        # Dropdown (row 1)
        self.add_item(self.OrderTabDropdown(self))

        # Buyer buttons (row 2)
        self.add_buyer_buttons()

    # -----------------------------------------------------------------
    # DROPDOWN SELECTOR
    # -----------------------------------------------------------------
    class OrderTabDropdown(discord.ui.Select):
        def __init__(self, parent_view):
            self.parent_view = parent_view

            options = [
                discord.SelectOption(
                    label="Active Orders",
                    description="View all active orders",
                    value="active"
                ),
                discord.SelectOption(
                    label="Delivered Orders",
                    description="View all delivered orders",
                    value="delivered"
                )
            ]

            super().__init__(
                placeholder="Select order category...",
                min_values=1,
                max_values=1,
                options=options,
                row=1
            )

        async def callback(self, interaction):
            choice = self.values[0]

            if choice == "active":
                self.parent_view.mode = "active"
                self.parent_view.page = 0
            else:
                self.parent_view.mode = "delivered"
                self.parent_view.page = 0

            await self.parent_view.update(interaction)

    # -----------------------------------------------------------------
    # REFRESH ORDER LISTS AFTER STATUS CHANGE
    # -----------------------------------------------------------------
    def refresh_order_lists(self):
        new_active = []
        new_delivered = []

        for order in self.active_orders + self.delivered_orders:
            if order["order_status"] == "Delivered":
                new_delivered.append(order)
            else:
                new_active.append(order)

        self.active_orders = new_active
        self.delivered_orders = new_delivered

        # Re-derive pages from mode
        if self.mode == "active":
            self.pages = self.active_orders
        else:
            self.pages = self.delivered_orders

        if self.page >= len(self.pages):
            self.page = 0

    # -----------------------------------------------------------------
    # BUYER BUTTON LOGIC
    # -----------------------------------------------------------------
    def add_buyer_buttons(self):
        # Remove existing buyer buttons
        for child in list(self.children):
            if isinstance(child, (MarkReceivedButton, MarkNotReceivedButton, PayButton)):
                self.remove_item(child)

        # Only show buttons on active tab
        if self.mode != "active":
            return

        self.pages = self.active_orders

        if not self.pages:
            return

        order = self.pages[self.page]

        # Pay button first — only if unpaid and not cancelled
        if order.get("date_paid") is None and order["order_status"] != "Cancelled":
            self.add_item(PayButton(self))

        # If delivered, no received/not received buttons
        if order["order_status"] == "Delivered":
            return

        # Then Mark Received / Mark Not Received
        self.add_item(MarkReceivedButton(self))
        self.add_item(MarkNotReceivedButton(self))

    # -----------------------------------------------------------------
    # UPDATE VIEW
    # -----------------------------------------------------------------
    async def update(self, interaction):
        # Always derive pages from mode
        if self.mode == "active":
            self.pages = self.active_orders
        else:
            self.pages = self.delivered_orders

        # Empty states
        if not self.pages:
            if self.mode == "active":
                embed = discord.Embed(
                    title="Active Orders",
                    description="You don't currently have any active orders. Use /shop to place an order.",
                    color=discord.Color.blue()
                )
            else:
                embed = discord.Embed(
                    title="Delivered Orders",
                    description="You don't have any delivered orders yet.",
                    color=discord.Color.blue()
                )

            await interaction.response.edit_message(embed=embed, view=self)
            return

        # Clamp page
        if self.page >= len(self.pages):
            self.page = 0

        embed = interaction.client.get_cog("MyOrders").build_order_embed(
            self.pages[self.page],
            self.page + 1,
            len(self.pages),
            self.mode
        )

        if self.mode == "active":
            embed.set_footer(text="Only active orders (orders that have not been delivered) are displayed.")
        else:
            embed.set_footer(text="Delivered orders are shown here.")

        self.add_buyer_buttons()

        await interaction.response.edit_message(embed=embed, view=self)

    # -----------------------------------------------------------------
    # PAGINATION BUTTONS
    # -----------------------------------------------------------------
    @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.primary, row=0)
    async def previous(self, interaction, button):
        if self.mode == "active":
            self.pages = self.active_orders
        else:
            self.pages = self.delivered_orders

        if self.page > 0:
            self.page -= 1
        await self.update(interaction)

    @discord.ui.button(label="Next ➡", style=discord.ButtonStyle.primary, row=0)
    async def next(self, interaction, button):
        if self.mode == "active":
            self.pages = self.active_orders
        else:
            self.pages = self.delivered_orders

        if self.page < len(self.pages) - 1:
            self.page += 1
        await self.update(interaction)


async def setup(bot):
    pass

