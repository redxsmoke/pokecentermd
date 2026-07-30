import discord
from discord.ext import commands
import datetime

ADMIN_ID = 337773020770729985
VENMO = "@aevans9560"
CASHAPP = "$andrew9560"
PAYPAL = "swemd"


class MyOrders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # =====================================================================
    # ORDER CREATION (ROUNDING FIXED)
    # =====================================================================
    async def create_order(
        self,
        interaction,
        user_id,
        items,
        subtotal,
        tax,
        paypal_fee,
        shipping_fee,
        total,
        grand_total,
        name,
        address,
        shipping_method,
        payment_method
    ):
        subtotal = round(float(subtotal), 2)
        tax = round(float(tax), 2)
        paypal_fee = round(float(paypal_fee), 2)
        shipping_fee = round(float(shipping_fee), 2)
        total = round(float(total), 2)

        async with self.bot.db.acquire() as conn:
            order = await conn.fetchrow(
                """
                INSERT INTO orders (
                    user_id, subtotal, tax, fee, shipping_fee, total,
                    payment_method, shipping_method, order_status
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'Pending')
                RETURNING order_id;
                """,
                user_id,
                subtotal,
                tax,
                paypal_fee,
                shipping_fee,
                total,
                payment_method,
                shipping_method
            )

            order_id = order["order_id"]

            for i in items:
                price_each = round(float(i["price"]), 2)
                await conn.execute(
                    """
                    INSERT INTO order_items (order_id, inventory_id, quantity, price_each)
                    VALUES ($1, $2, $3, $4);
                    """,
                    order_id, i["inventory_id"], i["quantity"], price_each
                )

        amount = f"{grand_total:.2f}"

        if payment_method == "venmo":
            payment_text = (
                f"**Venmo Payment:**\n"
                f"https://venmo.com/{VENMO.replace('@', '')}\n"
                f"Send **${amount}**"
            )
        elif payment_method == "cashapp":
            payment_text = (
                f"**CashApp Payment:**\n"
                f"https://cash.app/{CASHAPP}\n"
                f"Send **${amount}**"
            )
        else:
            payment_text = (
                f"**PayPal Payment:**\n"
                f"https://paypal.me/{PAYPAL}/{amount}\n"
                f"Send **${amount}** (Goods & Services)"
            )

        embed = discord.Embed(
            title="Order Submitted",
            description=f"Your order has been submitted!\n\nPlease complete payment:\n\n{payment_text}",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        await self.send_admin_order_dm(
            interaction.client,
            order_id,
            user_id,
            items,
            subtotal,
            tax,
            paypal_fee,
            shipping_fee,
            grand_total,
            name,
            address,
            shipping_method,
            payment_method
        )

    # =====================================================================
    # ADMIN DM
    # =====================================================================
    async def send_admin_order_dm(
        self,
        client,
        order_id,
        user_id,
        items,
        subtotal,
        tax,
        paypal_fee,
        shipping_fee,
        grand_total,
        name,
        address,
        shipping_method,
        payment_method
    ):
        try:
            admin = await client.fetch_user(ADMIN_ID)

            items_desc = "\n".join(
                f"#{i['inventory_id']} — {i['pokemon_name']} x{i['quantity']} @ ${float(i['price']):.2f}"
                for i in items
            )

            embed = discord.Embed(
                title=f"New Order Submitted — Order #{order_id}",
                color=discord.Color.orange()
            )
            embed.description = (
                f"**Buyer Name:** {name}\n"
                f"**Shipping Address:** {address}\n"
                f"**Shipping Method:** {shipping_method}\n"
                f"**Payment Method:** {payment_method.capitalize()}\n\n"
                f"**Subtotal:** ${float(subtotal):.2f}\n"
                f"**Tax:** ${float(tax):.2f}\n"
                f"**PayPal Fee:** ${float(paypal_fee):.2f}\n"
                f"**Shipping Fee:** ${float(shipping_fee):.2f}\n"
                f"**Grand Total:** ${float(grand_total):.2f}\n\n"
                f"**Items Ordered:**\n{items_desc}"
            )

            view = AdminOrderView(
                self.bot,
                order_id,
                user_id,
                items,
                shipping_method
            )

            await admin.send(embed=embed, view=view)

        except discord.Forbidden:
            pass

    # =====================================================================
    # /myorders EMBED
    # =====================================================================
    def build_order_embed(self, order, page_num, total_pages):
        embed = discord.Embed(
            title=f"My Orders — Page {page_num}/{total_pages}",
            color=discord.Color.blue()
        )

        embed.description = (
            f"**Order ID:** `{order['order_id']}`\n"
            f"**Status:** {order['order_status']}\n"
            f"**Placed:** {order['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
            f"**Paid:** {order['date_paid'].strftime('%Y-%m-%d %H:%M') if order['date_paid'] else 'Not Paid'}\n"
            f"**Shipped:** {order['date_shipped'].strftime('%Y-%m-%d %H:%M') if order['date_shipped'] else 'Not Shipped'}\n\n"
            f"**Shipping Method:** {order['shipping_method']}\n"
            f"**Tracking #:** {order['tracking_number'] or 'Not Provided'}\n"
            f"**Estimated Delivery:** {order['estimated_delivery'].strftime('%Y-%m-%d') if order['estimated_delivery'] else 'Not Set'}\n"
            f"**Received:** {'Yes' if order['received'] else 'No'}\n\n"
            f"**Subtotal:** ${float(order['subtotal']):.2f}\n"
            f"**Tax:** ${float(order['tax']):.2f}\n"
            f"**PayPal Fee:** ${float(order['fee']):.2f}\n"
            f"**Shipping Fee:** ${float(order['shipping_fee']):.2f}\n"
            f"**Total:** ${float(order['total']):.2f}\n"
            f"**Cancelled Reason:** {order['cancelled_reason'] or 'N/A'}\n"
        )

        return embed

    @discord.app_commands.command(name="myorders", description="View your past orders and their status.")
    async def myorders(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT order_id, user_id, subtotal, tax, fee, shipping_fee, total,
                       payment_method, shipping_method, order_status,
                       created_at, date_paid, date_shipped,
                       tracking_number, estimated_delivery,
                       received, date_received, cancelled_reason
                FROM orders
                WHERE user_id = $1
                ORDER BY order_id DESC;
                """,
                user_id
            )

        if not rows:
            embed = discord.Embed(
                title="My Orders",
                description="You have no orders yet.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        pages = list(rows)
        view = MyOrdersView(self.bot, interaction.user.id, pages)
        embed = self.build_order_embed(pages[0], 1, len(pages))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# =====================================================================
# MY ORDERS VIEW (USER)
# =====================================================================
class MyOrdersView(discord.ui.View):
    def __init__(self, bot, user_id, pages):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.pages = pages
        self.page = 0

        # Remove "Mark Not Received" for PWE orders
        first_order = pages[0]
        if first_order["shipping_method"].lower().startswith("plain white envelope"):
            for child in list(self.children):
                if isinstance(child, discord.ui.Button) and child.label == "Mark Not Received":
                    self.remove_item(child)

    async def update(self, interaction):
        cog = interaction.client.get_cog("MyOrders")
        embed = cog.build_order_embed(
            self.pages[self.page],
            self.page + 1,
            len(self.pages)
        )

        view = MyOrdersView(self.bot, self.user_id, self.pages)
        view.page = self.page

        await interaction.response.edit_message(embed=embed, view=view)

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

    @discord.ui.button(label="Mark Received", style=discord.ButtonStyle.success)
    async def mark_received(self, interaction, button):
        order = self.pages[self.page]
        order_id = order["order_id"]

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET received = TRUE,
                    date_received = NOW()
                WHERE order_id = $1 AND user_id = $2;
                """,
                order_id,
                self.user_id
            )

        embed = discord.Embed(
            title="Order Updated",
            description=f"Order #{order_id} marked as **Received**.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Mark Not Received", style=discord.ButtonStyle.danger)
    async def mark_not_received(self, interaction, button):
        order = self.pages[self.page]
        order_id = order["order_id"]

        estimated = order["estimated_delivery"]
        today = datetime.date.today()

        # Not shipped yet
        if estimated is None:
            embed = discord.Embed(
                title="Order Not Yet Shipped",
                description=(
                    "Your order has not yet been shipped.\n"
                    "All orders are shipped within **48 hours** of payment.\n\n"
                    f"If it has been more than 48 hours, please contact the admin:\n"
                    f"<@{ADMIN_ID}>"
                ),
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Too early to report
        if today < estimated:
            embed = discord.Embed(
                title="Too Early to Report",
                description=(
                    f"Your order is not expected until **{estimated.strftime('%Y-%m-%d')}**.\n"
                    "If you have not received your order by then, please let us know."
                ),
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Mark as not received
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET received = FALSE,
                    date_received = NULL
                WHERE order_id = $1 AND user_id = $2;
                """,
                order_id,
                self.user_id
            )

        # Notify buyer
        buyer_embed = discord.Embed(
            title="Package Not Received",
            description=(
                f"Your report for order #{order_id} has been sent to the admin.\n"
                "They will review your case and respond shortly."
            ),
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=buyer_embed, ephemeral=True)

        # Notify admin
        admin = await interaction.client.fetch_user(ADMIN_ID)

        admin_embed = discord.Embed(
            title="Order Marked as NOT Received",
            description=(
                f"**Order ID:** {order_id}\n"
                f"**Buyer:** <@{self.user_id}>\n"
                f"**Estimated Delivery:** {estimated.strftime('%Y-%m-%d')}\n"
                f"**Shipping Method:** {order['shipping_method']}\n"
                f"**Tracking #:** {order['tracking_number'] or 'None'}\n\n"
                f"Buyer reports the package has **NOT** been received."
            ),
            color=discord.Color.red()
        )

        admin_view = AdminNotReceivedView(
            self.bot,
            order_id,
            self.user_id
        )

        try:
            await admin.send(embed=admin_embed, view=admin_view)
        except:
            pass


class AdminNotReceivedView(discord.ui.View):
    def __init__(self, bot, order_id, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id

    @discord.ui.button(label="Provide Updated Tracking Information", style=discord.ButtonStyle.primary)
    async def provide_info(self, interaction, button):
        await interaction.response.send_modal(
            AdminTrackingResponseModal(self.bot, self.order_id, self.user_id)
        )


class AdminTrackingResponseModal(discord.ui.Modal, title="Send Message to Buyer"):
    message = discord.ui.TextInput(
        label="Message to Buyer",
        style=discord.TextStyle.long,
        required=True
    )

    def __init__(self, bot, order_id, user_id):
        super().__init__()
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id

    async def on_submit(self, interaction):
        buyer = await interaction.client.fetch_user(self.user_id)

        # Send message to buyer
        try:
            await buyer.send(
                embed=discord.Embed(
                    title=f"Update regarding your order #{self.order_id} reported as Not Received",
                    description=self.message.value,
                    color=discord.Color.blue()
                )
            )
        except:
            pass

        # Confirm to admin
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Message Sent",
                description=f"Your message has been sent to <@{self.user_id}>.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )
# =====================================================================
# ADMIN VIEW — PAYMENT, SHIPPING, TRACKING, CANCEL
# =====================================================================
class AdminOrderView(discord.ui.View):
    def __init__(self, bot, order_id, user_id, items, shipping_method):
        super().__init__(timeout=None)
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id
        self.items = items
        self.shipping_method = shipping_method

        # Mark Shipped starts disabled until payment is confirmed
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Mark Shipped":
                child.disabled = True

        # Tracking button starts disabled until shipped
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Enter Tracking #":
                child.disabled = True

    @discord.ui.button(label="Confirm Payment", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        if interaction.user.id != ADMIN_ID:
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
            status_row = await conn.fetchrow(
                "SELECT order_status FROM orders WHERE order_id = $1;",
                self.order_id
            )

        if status_row["order_status"] != "Pending":
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
            for i in self.items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET reserved = GREATEST(reserved - $1, 0),
                        quantity_available = GREATEST(quantity_available - $1, 0),
                        reserved_until = NULL
                    WHERE inventory_id = $2;
                    """,
                    i["quantity"],
                    i["inventory_id"]
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
        if interaction.user.id != ADMIN_ID:
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
            status_row = await conn.fetchrow(
                "SELECT order_status, shipping_method FROM orders WHERE order_id = $1;",
                self.order_id
            )

        if status_row["order_status"] == "Shipped":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Already Shipped",
                    description="Shipping was already confirmed for this order.",
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )
            return

        if status_row["order_status"] == "Cancelled":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Order Cancelled",
                    description="This order was cancelled. No further actions can be taken.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        shipping_method = status_row["shipping_method"].lower()

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
        if interaction.user.id != ADMIN_ID:
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
            status_row = await conn.fetchrow(
                "SELECT order_status, shipping_method FROM orders WHERE order_id = $1;",
                self.order_id
            )

        if status_row["order_status"] != "Shipped":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Not Shipped Yet",
                    description="You cannot enter a tracking number until the order is marked as shipped.",
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )
            return

        if "plain white envelope" in status_row["shipping_method"].lower():
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
            TrackingNumberModal(self.bot, self.order_id, self.user_id, self)
        )

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        if interaction.user.id != ADMIN_ID:
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
            CancelOrderModal(self.bot, self.order_id, self.user_id, self.items, self)
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

    def __init__(self, bot, order_id, user_id, admin_view):
        super().__init__()
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id
        self.admin_view = admin_view

    async def on_submit(self, interaction):
        if interaction.user.id != ADMIN_ID:
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

        # Disable tracking button after entry
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

    def __init__(self, bot, order_id, user_id, items, admin_view):
        super().__init__()
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id
        self.items = items
        self.admin_view = admin_view

    async def on_submit(self, interaction):
        if interaction.user.id != ADMIN_ID:
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

            #
            # ⭐ FIXED CANCEL LOGIC
            # - Restore ONLY what was reserved
            # - Never restore more than reserved
            # - Never inflate quantity_available
            # - Never leave reserved NULL
            #
            for i in self.items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET quantity_available = quantity_available + COALESCE(reserved, 0),
                        reserved = 0,
                        reserved_until = NULL
                    WHERE inventory_id = $1;
                    """,
                    i["inventory_id"]
                )

            # Update order status
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
# SETUP
# =====================================================================
async def setup(bot):
    await bot.add_cog(MyOrders(bot))
