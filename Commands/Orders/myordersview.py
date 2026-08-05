import discord
from discord.ext import commands
import datetime

class MyOrders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # =====================================================================
    # FETCH PAYMENT SETTINGS FROM DB
    # =====================================================================
    async def get_payment_settings(self, guild_id):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT venmo_handle, cashapp_handle, paypal_handle, admin_id
                FROM guild_settings
                WHERE guild_id = $1;
                """,
                guild_id
            )
        return row

    # =====================================================================
    # FETCH ITEMS FOR /MYORDERS
    # =====================================================================
    async def get_order_items(self, order_id: int):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT oi.inventory_id,
                       oi.quantity,
                       i.pokemon_name,
                       i.price,
                       i.condition,
                       i.series,
                       i.set_name
                FROM order_items oi
                JOIN inventory i ON i.inventory_id = oi.inventory_id
                WHERE oi.order_id = $1
                ORDER BY i.pokemon_name ASC;
                """,
                order_id
            )
        return rows

    # =====================================================================
    # EMBED BUILDER
    # =====================================================================
    def build_order_embed(self, order, page_num: int, total_pages: int, mode: str):
        title_text = f"📦 Order #{order['order_id']} — {order['order_status']}"
        if mode == "archived":
            title_text += " (Orders from the past 30 days)"

        embed = discord.Embed(
            title=title_text,
            color=discord.Color.blue()
        )

        embed.set_footer(text=f"Order {page_num}/{total_pages}")

        timeline = [
            f"**Placed:** {order['created_at']:%Y-%m-%d}",
            f"**Paid:** {order['date_paid']:%Y-%m-%d}" if order["date_paid"] else "**Paid:** —",
            f"**Shipped:** {order['date_shipped']:%Y-%m-%d}" if order["date_shipped"] else "**Shipped:** —",
            f"**Est. Delivery:** {order['estimated_delivery']:%Y-%m-%d}" if order["estimated_delivery"] else "**Est. Delivery:** —",
            f"**Delivered:** {order['date_received']:%Y-%m-%d}" if order["date_received"] else "**Delivered:** —",
        ]
        embed.add_field(name="🗓️ Timeline", value="\n".join(timeline), inline=False)

        shipping = [
            f"**Method:** {order['shipping_method']}",
            f"**Tracking:** {order['tracking_number'] or 'None'}",
        ]
        embed.add_field(name="🚚 Shipping", value="\n".join(shipping), inline=False)

        item_lines = []
        for i in order["items"]:
            price_each = float(i["price"])
            qty = i["quantity"]
            total = round(price_each * qty, 2)
            item_lines.append(
                f"• {i['pokemon_name']} — x{qty} (${price_each:.2f} ea, ${total:.2f} total)"
            )

        embed.add_field(name="🃏 Items", value="\n".join(item_lines), inline=False)

        payment = [
            f"**Subtotal:** ${order['subtotal']:.2f}",
            f"**Tax:** ${order['tax']:.22f}",
            f"**PayPal Fee:** ${order['fee']:.2f}",
            f"**Shipping:** ${order['shipping_fee']:.2f}",
            f"**Total:** ${order['total']:.2f}",
            f"**Method:** {order['payment_method'].capitalize()}",
        ]
        embed.add_field(name="💰 Payment", value="\n".join(payment), inline=False)

        status = [
            f"**Received:** {'Yes' if order['received'] else 'No'}",
            f"**Cancelled Reason:** {order['cancelled_reason'] or '—'}",
        ]
        embed.add_field(name="📌 Status", value="\n".join(status), inline=False)

        return embed
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

        # Disable shipping buttons until payment is confirmed
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
            # Deduct reserved inventory
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

        # Disable payment button
        button.disabled = True

        # Enable shipping buttons
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Mark Shipped":
                child.disabled = False

        await interaction.message.edit(view=self)

        # Notify buyer
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

        # Enable tracking button only if not PWE
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Enter Tracking #":
                child.disabled = ("plain white envelope" in shipping_method)

        await interaction.message.edit(view=self)

        # Notify buyer
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

        # Disable tracking button
        for child in self.admin_view.children:
            if isinstance(child, discord.ui.Button) and child.label == "Enter Tracking #":
                child.disabled = True

        await interaction.message.edit(view=self.admin_view)

        # Notify buyer
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

            # Restore inventory
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

        # Notify buyer
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

        # Disable cancel button
        for child in self.admin_view.children:
            if isinstance(child, discord.ui.Button) and child.label == "Cancel Order":
                child.disabled = True

        await interaction.message.edit(view=self.admin_view)


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

        # Notify buyer
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

        # Already reported?
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

        # Not shipped yet
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

        # Too early
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

        # Update DB
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

        # Notify admin
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
# USER ORDER VIEW (Buyer-facing view)
# =====================================================================
class MyOrdersView(discord.ui.View):
    def __init__(self, bot, user_id, active_orders, archived_orders, mode="active", admin_id=None):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id

        self.active_orders = active_orders
        self.archived_orders = archived_orders
        self.mode = mode

        # Pages for pagination
        self.pages = active_orders if mode == "active" else archived_orders
        self.page = 0

        # Dynamic admin ID
        self.admin_id = admin_id

        # Dropdown selector
        self.add_item(OrderCategoryDropdown(self))

        # Add buyer buttons
        self.refresh_buttons()

    def refresh_buttons(self):
        """Adds or removes buyer buttons depending on mode and order status."""
        # Remove old buttons
        for child in list(self.children):
            if isinstance(child, discord.ui.Button) and child.custom_id in ("mark_received", "mark_not_received"):
                self.remove_item(child)

        # Only show buttons on active orders
        if self.mode != "active":
            return

        if not self.pages:
            return

        order = self.pages[self.page]

        # Delivered or Cancelled → no buttons
        if order["order_status"] in ("Delivered", "Cancelled"):
            return

        # Add Mark Received
        self.add_item(MarkReceivedButton(self))

        # Add Mark Not Received (unless PWE)
        if "plain white envelope" not in order["shipping_method"].lower():
            self.add_item(MarkNotReceivedButton(self))

    async def update(self, interaction):
        """Refreshes the embed + buttons when user changes page or category."""
        if not self.pages:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="No Orders",
                    description="There are no orders in this category.",
                    color=discord.Color.orange()
                ),
                view=self
            )
            return

        cog = interaction.client.get_cog("MyOrders")

        embed = cog.build_order_embed(
            self.pages[self.page],
            self.page + 1,
            len(self.pages),
            self.mode
        )

        # Refresh buyer buttons
        self.refresh_buttons()

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.primary)
    async def previous(self, interaction, button):
        if self.page > 0:
            self.page -= 1
        await self.update(interaction)

    @discord.ui.button(label="Next ➡", style=discord.ButtonStyle.primary)
    async def next(self, interaction, button):
        if self.page < len(self.pages) - 1:
            self.page += 1
        await self.update(interaction)


# =====================================================================
# DROPDOWN SELECTOR
# =====================================================================
class OrderCategoryDropdown(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view

        options = [
            discord.SelectOption(
                label="Active Orders",
                description="Pending, Paid, Shipped, Not Received",
                value="active"
            ),
            discord.SelectOption(
                label="Archived Orders",
                description="Delivered or Cancelled (Past 30 Days)",
                value="archived"
            )
        ]

        super().__init__(
            placeholder="Select Order Category...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction):
        mode = self.values[0]
        self.parent_view.mode = mode

        if mode == "active":
            self.parent_view.pages = self.parent_view.active_orders
        else:
            self.parent_view.pages = self.parent_view.archived_orders

        self.parent_view.page = 0
        await self.parent_view.update(interaction)


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
        order_id = order["order_id"]

        # Update DB
        async with self.parent_view.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET received = TRUE,
                    date_received = NOW(),
                    order_status = 'Delivered'
                WHERE order_id = $1;
                """,
                order_id
            )

        # Buyer confirmation
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Order Updated",
                description=f"Order #{order_id} marked as **Received**.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

        # Notify admin
        try:
            admin = await interaction.client.fetch_user(self.parent_view.admin_id)
            await admin.send(
                embed=discord.Embed(
                    title="Order Marked as Received",
                    description=(
                        f"**Order ID:** {order_id}\n"
                        f"**Buyer:** <@{self.parent_view.user_id}>\n"
                        f"**Date:** {datetime.date.today().strftime('%Y-%m-%d')}\n\n"
                        "The buyer has marked their order as **Received**."
                    ),
                    color=discord.Color.green()
                )
            )
        except:
            pass

        await self.parent_view.update(interaction)


# =====================================================================
# SETUP — REGISTER ONLY THE MyOrders COG (NOT the slash command)
# =====================================================================
async def setup(bot):
    await bot.add_cog(MyOrders(bot))

