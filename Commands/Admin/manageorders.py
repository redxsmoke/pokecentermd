import discord
from discord.ext import commands
import datetime


# =====================================================================
# HELPERS
# =====================================================================
async def fetch_orders_with_items(interaction: discord.Interaction, status: str):
    """
    Fetch orders by status, including joined order_items + inventory details.
    """
    async with interaction.client.db.acquire() as conn:
        orders = await conn.fetch(
            """
            SELECT
                o.order_id,
                o.user_id,
                o.subtotal,
                o.tax,
                o.fee,
                o.shipping_fee,
                o.total,
                o.payment_method,
                o.shipping_method,
                o.order_status,
                o.created_at,
                o.date_paid,
                o.estimated_delivery,
                o.date_shipped,
                o.tracking_number,
                o.reported_missing,
                o.date_received,
                o.cancelled_reason,
                o.buyer_name,
                o.shipping_address
            FROM orders o
            WHERE o.order_status = $1
            ORDER BY o.order_id DESC;
            """,
            status
        )

        results = []
        for o in orders:
            items = await conn.fetch(
                """
                SELECT
                    oi.inventory_id,
                    oi.quantity,
                    oi.price_each,
                    i.pokemon_name,
                    i.condition,
                    i.series,
                    i.set_name
                FROM order_items oi
                JOIN inventory i ON i.inventory_id = oi.inventory_id
                WHERE oi.order_id = $1
                ORDER BY i.pokemon_name ASC;
                """,
                o["order_id"]
            )
            o_dict = dict(o)
            o_dict["items"] = [dict(i) for i in items]
            results.append(o_dict)

    return results


def format_user_mention(user_id: int) -> str:
    return f"<@{user_id}>"


def format_items_list(items) -> str:
    if not items:
        return "No items found."
    lines = []
    for item in items:
        lines.append(
            f"• {item['pokemon_name']} — {item['series']} / {item['set_name']} "
            f"({item.get('condition', 'N/A')}) x{item['quantity']} @ ${item['price_each']:.2f}"
        )
    return "\n".join(lines)


# =====================================================================
# REFUND CONFIRMATION VIEW
# =====================================================================
class RefundConfirmView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, order: dict):
        super().__init__(timeout=60)
        self.interaction = interaction
        self.order = order

    @discord.ui.button(label="Yes, refund", style=discord.ButtonStyle.danger)
    async def yes_refund(self, inner: discord.Interaction, button: discord.ui.Button):
        async with inner.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET order_status = 'Cancelled',
                    cancelled_reason = 'Refunded'
                WHERE order_id = $1;
                """,
                self.order["order_id"]
            )

        try:
            buyer = await inner.client.fetch_user(self.order["user_id"])
            await buyer.send(
                embed=discord.Embed(
                    title="Order Refunded",
                    description=(
                        f"Your order #{self.order['order_id']} has been **refunded**.\n"
                        f"Reason: Refunded by admin."
                    ),
                    color=discord.Color.green()
                )
            )
        except Exception:
            pass

        refund_embed = discord.Embed(
            title=f"Order #{self.order['order_id']} Refunded",
            description=(
                f"Order #{self.order['order_id']} has been marked as **Cancelled (Refunded)**.\n\n"
                f"To complete the refund, send **${self.order['total']:.2f}** "
                f"to the buyer using your preferred refund method.\n\n"
                f"Remember to also update the quantity available for this/these item(s) "
                f"if planning to add them back into your inventory using `/admin manage_inventory`."
            ),
            color=discord.Color.green()
        )

        await inner.response.edit_message(
            embed=refund_embed,
            view=None
        )

    @discord.ui.button(label="No, keep order", style=discord.ButtonStyle.secondary)
    async def no_refund(self, inner: discord.Interaction, button: discord.ui.Button):
        cancel_embed = discord.Embed(
            title="Refund Cancelled",
            description="No changes were made to the order.",
            color=discord.Color.blue()
        )

        await inner.response.edit_message(
            embed=cancel_embed,
            view=None
        )


# =====================================================================
# TRACKING NUMBER MODAL (ADMIN)
# =====================================================================
class AdminTrackingModal(discord.ui.Modal, title="Add Tracking Number"):
    tracking_number = discord.ui.TextInput(
        label="Tracking Number",
        required=True,
        style=discord.TextStyle.short,
        max_length=100
    )

    def __init__(self, order: dict):
        super().__init__()
        self.order = order

    async def on_submit(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET tracking_number = $2
                WHERE order_id = $1;
                """,
                self.order["order_id"],
                self.tracking_number.value
            )

        try:
            buyer = await interaction.client.fetch_user(self.order["user_id"])
            await buyer.send(
                embed=discord.Embed(
                    title="Tracking Information Added",
                    description=(
                        f"Tracking information was added for your order #{self.order['order_id']}:\n"
                        f"**{self.tracking_number.value}**"
                    ),
                    color=discord.Color.green()
                )
            )
        except Exception:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Tracking Saved",
                description=(
                    f"Tracking number saved for order #{self.order['order_id']}.\n"
                    f"Buyer has been notified via DM."
                ),
                color=discord.Color.green()
            ),
            ephemeral=True
        )


# =====================================================================
# CANCEL ORDER MODAL (ADMIN)
# =====================================================================
class AdminCancelOrderModal(discord.ui.Modal, title="Cancel Order"):
    reason = discord.ui.TextInput(
        label="Cancellation Reason",
        required=True,
        style=discord.TextStyle.long,
        max_length=500
    )

    def __init__(self, order: dict):
        super().__init__()
        self.order = order

    async def on_submit(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET order_status = 'Cancelled',
                    cancelled_reason = $2
                WHERE order_id = $1;
                """,
                self.order["order_id"],
                self.reason.value
            )

        try:
            buyer = await interaction.client.fetch_user(self.order["user_id"])
            await buyer.send(
                embed=discord.Embed(
                    title="Order Cancelled",
                    description=(
                        f"Your order #{self.order['order_id']} has been **cancelled**.\n"
                        f"Reason: {self.reason.value}"
                    ),
                    color=discord.Color.red()
                )
            )
        except Exception:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Order Cancelled",
                description=(
                    f"Order #{self.order['order_id']} has been cancelled.\n"
                    f"Buyer has been notified via DM."
                ),
                color=discord.Color.green()
            ),
            ephemeral=True
        )


# =====================================================================
# MAIN ADMIN VIEW FOR /admin manage_orders
# =====================================================================
class ManageOrdersView(discord.ui.View):
    def __init__(
        self,
        interaction: discord.Interaction,
        shipped_orders,
        unpaid_orders,
        awaiting_orders,
        delivered_orders,
        cancelled_orders
    ):
        super().__init__(timeout=None)
        self.interaction = interaction

        self.shipped_orders = shipped_orders
        self.unpaid_orders = unpaid_orders
        self.awaiting_orders = awaiting_orders
        self.delivered_orders = delivered_orders
        self.cancelled_orders = cancelled_orders

        self.mode = "shipped"
        self.page = 0

        self.pages = self.shipped_orders

        self.add_item(self.StatusDropdown(self))

    # -----------------------------------------------------------------
    # DROPDOWN SELECTOR
    # -----------------------------------------------------------------
    class StatusDropdown(discord.ui.Select):
        def __init__(self, parent_view: "ManageOrdersView"):
            self.parent_view = parent_view

            options = [
                discord.SelectOption(
                    label="Shipped Orders",
                    description="View all shipped orders",
                    value="shipped"
                ),
                discord.SelectOption(
                    label="Unpaid Orders",
                    description="View all unpaid orders",
                    value="unpaid"
                ),
                discord.SelectOption(
                    label="Orders Awaiting Shipment",
                    description="Paid orders not yet shipped",
                    value="awaiting"
                ),
                discord.SelectOption(
                    label="Delivered Orders",
                    description="View all delivered orders",
                    value="delivered"
                ),
                discord.SelectOption(
                    label="Cancelled Orders",
                    description="View all cancelled orders",
                    value="cancelled"
                ),
            ]

            super().__init__(
                placeholder="Select order status...",
                min_values=1,
                max_values=1,
                options=options,
                row=0
            )

        async def callback(self, interaction: discord.Interaction):
            self.parent_view.mode = self.values[0]
            self.parent_view.page = 0
            await self.parent_view.update(interaction)

    # -----------------------------------------------------------------
    # EMBED BUILDER (UPDATED WITH BUYER NAME + ADDRESS)
    # -----------------------------------------------------------------
    def build_embed_for_order(self, order: dict) -> discord.Embed:
        mode = self.mode

        display_mode = (
            "Awaiting Shipment" if mode == "awaiting"
            else mode.capitalize()
        )

        embed = discord.Embed(
            title=f"Manage Orders — {display_mode}",
            color=discord.Color.blue()
        )

        user_mention = format_user_mention(order["user_id"])
        items_text = format_items_list(order["items"])

        buyer_name = order.get("buyer_name") or "Not Provided"
        shipping_address = order.get("shipping_address") or "Not Provided"

        embed.add_field(
            name="Order",
            value=(
                f"**Order ID:** {order['order_id']}\n"
                f"**Buyer:** {user_mention}\n"
                f"**Buyer Name:** {buyer_name}\n"
                f"**Shipping Address:** {shipping_address}\n"
                f"**Status:** {order['order_status']}\n"
            ),
            inline=False
        )
        if mode in ("shipped", "unpaid", "awaiting", "delivered"):
            embed.add_field(
                name="Financials",
                value=(
                    f"Subtotal: ${order['subtotal']:.2f}\n"
                    f"Tax: ${order['tax']:.2f}\n"
                    f"Fee: ${order['fee']:.2f}\n"
                    f"Shipping Fee: ${order['shipping_fee']:.2f}\n"
                    f"Total: ${order['total']:.2f}\n"
                ),
                inline=False
            )

        if mode == "awaiting":
            embed.add_field(
                name="Shipping",
                value=(
                    f"Shipping Method: {order['shipping_method']}\n"
                    f"Created At: {order['created_at']}\n"
                    f"Date Paid: {order['date_paid']}\n"
                    f"Payment Method: {order['payment_method']}\n"
                ),
                inline=False
            )

        elif mode == "unpaid":
            embed.add_field(
                name="Order Timing",
                value=f"Created At: {order['created_at']}\n",
                inline=False
            )

        elif mode == "shipped":
            embed.add_field(
                name="Shipping",
                value=(
                    f"Shipping Method: {order['shipping_method']}\n"
                    f"Tracking #: {order['tracking_number'] or 'None'}\n"
                    f"Created At: {order['created_at']}\n"
                    f"Date Paid: {order['date_paid']}\n"
                    f"Estimated Delivery: {order['estimated_delivery']}\n"
                    f"Date Shipped: {order['date_shipped']}\n"
                    f"Reported Missing: {order['reported_missing']}\n"
                    f"Payment Method: {order['payment_method']}\n"
                ),
                inline=False
            )

        elif mode == "delivered":
            embed.add_field(
                name="Shipping",
                value=(
                    f"Shipping Method: {order['shipping_method']}\n"
                    f"Tracking #: {order['tracking_number'] or 'None'}\n"
                    f"Created At: {order['created_at']}\n"
                    f"Payment Method: {order['payment_method']}\n"
                    f"Date Paid: {order['date_paid']}\n"
                    f"Estimated Delivery: {order['estimated_delivery']}\n"
                    f"Date Shipped: {order['date_shipped']}\n"
                    f"Date Received: {order['date_received']}\n"
                ),
                inline=False
            )

        elif mode == "cancelled":
            reason = order.get("cancelled_reason") or "None"
            total = order.get("total", 0)

            if reason.lower() == "refunded":
                amount_label = "Refunded Amount"
            else:
                amount_label = "Amount"

            embed.add_field(
                name="Cancellation",
                value=(
                    f"Cancelled Reason: {reason}\n"
                    f"{amount_label}: ${total:.2f}\n"
                ),
                inline=False
            )

        embed.add_field(
            name="Items",
            value=items_text,
            inline=False
        )

        return embed

    # -----------------------------------------------------------------
    # UPDATE VIEW (RESTORED)
    # -----------------------------------------------------------------
    async def update(self, interaction: discord.Interaction):
        if self.mode == "shipped":
            self.pages = self.shipped_orders
        elif self.mode == "unpaid":
            self.pages = self.unpaid_orders
        elif self.mode == "awaiting":
            self.pages = self.awaiting_orders
        elif self.mode == "delivered":
            self.pages = self.delivered_orders
        else:
            self.pages = self.cancelled_orders

        if not self.pages:
            display_mode = (
                "Awaiting Shipment" if self.mode == "awaiting"
                else self.mode.capitalize()
            )
            embed = discord.Embed(
                title=f"Manage Orders — {display_mode}",
                description=f"No {display_mode.lower()} orders found.",
                color=discord.Color.blue()
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return

        if self.page >= len(self.pages):
            self.page = 0

        order = self.pages[self.page]
        embed = self.build_embed_for_order(order)
        self.add_buttons_for_order(order)

        await interaction.response.edit_message(embed=embed, view=self)

    # -----------------------------------------------------------------
    # BUTTON MANAGEMENT
    # -----------------------------------------------------------------
    def clear_action_buttons(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Button) and child.custom_id in (
                "mark_delivered",
                "issue_refund",
                "add_tracking",
                "mark_paid",
                "mark_shipped",
                "cancel_order_admin",
                "next_order",
                "previous_order",
            ):
                self.remove_item(child)

    def add_buttons_for_order(self, order: dict):
        self.clear_action_buttons()

        mode = self.mode

        if mode == "shipped":
            self.add_item(MarkDeliveredButton(order))
            self.add_item(IssueRefundButton(order))
            self.add_item(AddTrackingButton(order))

        elif mode == "unpaid":
            self.add_item(MarkPaidButton(order))
            self.add_item(MarkShippedButton(order))
            self.add_item(AddTrackingButton(order))
            self.add_item(CancelOrderButton(order))

        elif mode == "awaiting":
            self.add_item(MarkShippedButton(order))
            self.add_item(AddTrackingButton(order))
            self.add_item(IssueRefundButton(order))

        elif mode == "delivered":
            self.add_item(IssueRefundButton(order))
        # cancelled: no buttons

        # -----------------------------------------------------------------
        # PAGINATION BUTTONS (NEW)
        # -----------------------------------------------------------------
        next_btn = NextOrderButton(self)
        prev_btn = PreviousOrderButton(self)

        if len(self.pages) <= 1:
            next_btn.disabled = True
            prev_btn.disabled = True
        else:
            prev_btn.disabled = (self.page == 0)
            next_btn.disabled = (self.page == len(self.pages) - 1)

        self.add_item(prev_btn)
        self.add_item(next_btn)


# -----------------------------------------------------------------
# PAGINATION BUTTON CLASSES (NEW)
# -----------------------------------------------------------------
class NextOrderButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="Next",
            style=discord.ButtonStyle.primary,
            custom_id="next_order",
            row=3
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.page < len(self.parent_view.pages) - 1:
            self.parent_view.page += 1
        await self.parent_view.update(interaction)


class PreviousOrderButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="Previous",
            style=discord.ButtonStyle.secondary,
            custom_id="previous_order",
            row=3
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.page > 0:
            self.parent_view.page -= 1
        await self.parent_view.update(interaction)


# =====================================================================
# ACTION BUTTON CLASSES
# =====================================================================
class NextOrderButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="Next",
            style=discord.ButtonStyle.primary,
            custom_id="next_order",
            row=3
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.page < len(self.parent_view.pages) - 1:
            self.parent_view.page += 1
        await self.parent_view.update(interaction)


class PreviousOrderButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="Previous",
            style=discord.ButtonStyle.secondary,
            custom_id="previous_order",
            row=3
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.page > 0:
            self.parent_view.page -= 1
        await self.parent_view.update(interaction)

class MarkDeliveredButton(discord.ui.Button):
    def __init__(self, order: dict):
        super().__init__(
            label="Mark as Delivered",
            style=discord.ButtonStyle.success,
            custom_id="mark_delivered",
            row=2
        )
        self.order = order

    async def callback(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET order_status = 'Delivered',
                    received = TRUE,
                    date_received = NOW()
                WHERE order_id = $1;
                """,
                self.order["order_id"]
            )

        try:
            buyer = await interaction.client.fetch_user(self.order["user_id"])
            await buyer.send(
                embed=discord.Embed(
                    title="Order Delivered",
                    description=f"Your order #{self.order['order_id']} has been marked as delivered.",
                    color=discord.Color.green()
                )
            )
        except Exception:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Order Updated",
                description=f"Order #{self.order['order_id']} marked as **Delivered**.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )


class IssueRefundButton(discord.ui.Button):
    def __init__(self, order: dict):
        super().__init__(
            label="Issue Refund",
            style=discord.ButtonStyle.danger,
            custom_id="issue_refund",
            row=2
        )
        self.order = order

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            content="Are you sure you want to refund this order?",
            view=RefundConfirmView(interaction, self.order),
            ephemeral=True
        )


class AddTrackingButton(discord.ui.Button):
    def __init__(self, order: dict):
        super().__init__(
            label="Add Tracking Number",
            style=discord.ButtonStyle.primary,
            custom_id="add_tracking",
            row=2
        )
        self.order = order

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AdminTrackingModal(self.order))


class MarkPaidButton(discord.ui.Button):
    def __init__(self, order: dict):
        super().__init__(
            label="Mark as Paid",
            style=discord.ButtonStyle.success,
            custom_id="mark_paid",
            row=2
        )
        self.order = order

    async def callback(self, interaction: discord.Interaction):
        estimated_delivery = datetime.date.today() + datetime.timedelta(days=14)

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET order_status = 'Paid',
                    date_paid = NOW(),
                    estimated_delivery = $2
                WHERE order_id = $1;
                """,
                self.order["order_id"],
                estimated_delivery
            )

        try:
            buyer = await interaction.client.fetch_user(self.order["user_id"])
            await buyer.send(
                embed=discord.Embed(
                    title="Payment Confirmed",
                    description=(
                        f"Your payment for order #{self.order['order_id']} has been confirmed.\n"
                        f"Estimated delivery: **{estimated_delivery.strftime('%Y-%m-%d')}**"
                    ),
                    color=discord.Color.green()
                )
            )
        except Exception:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Order Updated",
                description=f"Order #{self.order['order_id']} marked as **Paid**.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )


class MarkShippedButton(discord.ui.Button):
    def __init__(self, order: dict):
        super().__init__(
            label="Mark as Shipped",
            style=discord.ButtonStyle.primary,
            custom_id="mark_shipped",
            row=2
        )
        self.order = order

    async def callback(self, interaction: discord.Interaction):
        shipping_method = (self.order["shipping_method"] or "").lower()

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET order_status = 'Shipped',
                    date_shipped = NOW()
                WHERE order_id = $1;
                """,
                self.order["order_id"]
            )

            if "plain white envelope" in shipping_method:
                await conn.execute(
                    """
                    UPDATE orders
                    SET tracking_number = 'Shipped without tracking'
                    WHERE order_id = $1;
                    """,
                    self.order["order_id"]
                )

        try:
            buyer = await interaction.client.fetch_user(self.order["user_id"])
            await buyer.send(
                embed=discord.Embed(
                    title="Order Shipped",
                    description=f"Your order #{self.order['order_id']} has been marked as shipped. Buyer has been notified via DM",
                    color=discord.Color.green()
                )
            )
        except Exception:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Order Updated",
                description=f"Order #{self.order['order_id']} marked as **Shipped**.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )


class CancelOrderButton(discord.ui.Button):
    def __init__(self, order: dict):
        super().__init__(
            label="Cancel Order",
            style=discord.ButtonStyle.danger,
            custom_id="cancel_order_admin",
            row=2
        )
        self.order = order

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AdminCancelOrderModal(self.order))


# =====================================================================
# ENTRY FUNCTION FOR /admin manage_orders
# =====================================================================
async def start_manage_orders(interaction: discord.Interaction):
    shipped = await fetch_orders_with_items(interaction, "Shipped")
    unpaid = await fetch_orders_with_items(interaction, "Pending")
    awaiting = await fetch_orders_with_items(interaction, "Paid")
    delivered = await fetch_orders_with_items(interaction, "Delivered")
    cancelled = await fetch_orders_with_items(interaction, "Cancelled")

    view = ManageOrdersView(
        interaction,
        shipped_orders=shipped,
        unpaid_orders=unpaid,
        awaiting_orders=awaiting,
        delivered_orders=delivered,
        cancelled_orders=cancelled
    )

    if shipped:
        first_order = shipped[0]
        embed = view.build_embed_for_order(first_order)
        view.add_buttons_for_order(first_order)
    else:
        embed = discord.Embed(
            title="Manage Orders — Shipped",
            description="No shipped orders found.",
            color=discord.Color.blue()
        )

    await interaction.response.send_message(
        embed=embed,
        view=view,
        ephemeral=True
    )
