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

        # REMOVE ALL BUTTONS
        for child in list(self.children):
            self.remove_item(child)

    async def send_admin_notification(self, interaction):
        """
        Sends a DM to the admin notifying them of a new order.
        No buttons. No actions. Just instructions.
        """

        # ⭐ DO NOT SEND DM IF THIS ORDER IS A CLAIM SALE
        async with self.bot.db.acquire() as conn:
            exists = await conn.fetchval(
                """
                SELECT 1
                FROM claim_sale_orders
                WHERE order_id = $1
                LIMIT 1;
                """,
                self.order_id
            )

        if exists:
            return  # <-- STOP. Claim sale order → DO NOT SEND DM.

        admin = await interaction.client.fetch_user(self.admin_id)

        # Build item list
        item_lines = []
        for item in self.items:
            item_lines.append(
                f"• {item['pokemon_name']} — {item['series']} / {item['set_name']} "
                f"({item.get('condition', 'N/A')}) x{item['quantity']} @ ${item['price_each']:.2f}"
            )
        items_text = "\n".join(item_lines)

        embed = discord.Embed(
            title=f"🛒 New Order Placed — #{self.order_id}",
            description=(
                f"A new order has been placed.\n\n"
                f"**Buyer:** <@{self.user_id}>\n"
                f"**Shipping Method:** {self.shipping_method}\n\n"
                f"**Items:**\n{items_text}\n\n"
                f"To manage this order (mark as **Paid**, **Shipped**, enter **Tracking**, cancel, etc.), "
                f"use the command:\n"
                f"**/admin manage_orders**\n\n"
                f"All actions must be done using the admin command. This DM Is informational only."
            ),
            color=discord.Color.blue()
        )

        try:
            await admin.send(embed=embed)
        except Exception as e:
            print("ADMIN DM ERROR:", e)



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
                description=f"Order #{self.order_id} has been cancelled.",
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
# PAY CHECKOUT VIEW
# =====================================================================
class PayCheckoutView(discord.ui.View):
    def __init__(self, bot, order, config):
        super().__init__(timeout=900)
        self.bot = bot
        self.order = order
        self.config = config
        self.order["admin_id"] = config["admin_id"]

        self.payment_method = None
        self.shipping_method = None

        # Payment options: venmo, cashapp, paypal
        options = []
        venmo = (config["venmo_handle"] or "").strip().lstrip("@")
        cashapp = (config["cashapp_handle"] or "").strip()
        paypal = (config["paypal_handle"] or "").strip()

        if venmo:
            options.append(discord.SelectOption(label="Venmo", value="venmo"))
        if cashapp:
            options.append(discord.SelectOption(label="CashApp", value="cashapp"))
        if paypal:
            options.append(discord.SelectOption(label="PayPal", value="paypal"))

        self.payment_select = discord.ui.Select(
            placeholder="Select Payment Method",
            options=options,
            min_values=1,
            max_values=1
        )
        self.payment_select.callback = self.payment_callback

        self.shipping_select = discord.ui.Select(
            placeholder="Select Shipping Method",
            options=[
                discord.SelectOption(label="PWE ($1.50)", value="pwe"),
                discord.SelectOption(label="Tracked ($4.95)", value="tracked")
            ],
            min_values=1,
            max_values=1
        )
        self.shipping_select.callback = self.shipping_callback

        self.add_item(self.payment_select)
        self.add_item(self.shipping_select)

        # Existing button
        confirm_btn = discord.ui.Button(
            label="Enter Name & Shipping Address",
            style=discord.ButtonStyle.success
        )
        confirm_btn.callback = self.confirm
        self.add_item(confirm_btn)

        # ⭐ NEW BUTTON — Use Saved Shipping Address
        saved_btn = discord.ui.Button(
            label="Use Saved Shipping Address",
            style=discord.ButtonStyle.primary
        )
        saved_btn.callback = self.use_saved_shipping
        self.add_item(saved_btn)

    async def payment_callback(self, interaction: discord.Interaction):
        self.payment_method = self.payment_select.values[0]
        await interaction.response.defer()

    async def shipping_callback(self, interaction: discord.Interaction):
        self.shipping_method = self.shipping_select.values[0]
        await interaction.response.defer()

    # ============================================================
    # ⭐ NEW METHOD — Use Saved Shipping Address
    # ============================================================
    async def use_saved_shipping(self, interaction: discord.Interaction):

        # ⭐ REQUIRE PAYMENT + SHIPPING METHOD FIRST
        if not self.payment_method or not self.shipping_method:
            embed = discord.Embed(
                title="Missing Required Selections",
                description=(
                    "Please select both a **payment method** and a **shipping method** "
                    "before using your saved shipping address."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Fetch saved shipping info
        async with self.bot.db.acquire() as conn:
            record = await conn.fetchrow(
                """
                SELECT full_name, street_address, city, state, zip
                FROM user_shipping_info
                WHERE user_id = $1 AND guild_id = $2;
                """,
                interaction.user.id,
                interaction.guild.id
            )

        if record is None:
            embed = discord.Embed(
                title="No Saved Shipping Address",
                description=(
                    "You do not have a saved shipping address.\n\n"
                    "Run the **/shippinginfo** command to provide one."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Build full address
        full_address = (
            f"{record['street_address']}\n"
            f"{record['city']}, {record['state']} {record['zip']}"
        )

        # Recalculate totals
        subtotal = float(self.order["subtotal"])
        tax = round(subtotal * 0.06, 2)
        total_before_shipping = subtotal + tax

        # Enforce tracked shipping rule
        if total_before_shipping > 15 and self.shipping_method == "pwe":
            embed = discord.Embed(
                title="Tracked Shipping Required",
                description=(
                    "Orders over **$15.00** require tracked shipping.\n"
                    "Please select the **Tracked ($4.95)** shipping option to continue."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Shipping cost
        if self.shipping_method == "pwe":
            shipping_cost = 1.50
            shipping_label = "Plain White Envelope (Buyer Risk)"
        else:
            shipping_cost = 4.95
            shipping_label = "Tracked Shipping"

        # PayPal fee
        fee = round(total_before_shipping * 0.03, 2) if self.payment_method == "paypal" else 0.0

        total = round(total_before_shipping + shipping_cost + fee, 2)

        # Payment link
        venmo = (self.config["venmo_handle"] or "").strip().lstrip("@")
        cashapp = (self.config["cashapp_handle"] or "").strip()
        paypal = (self.config["paypal_handle"] or "").strip()

        method = self.payment_method.lower()
        link = None

        if method == "venmo" and venmo:
            link = f"https://venmo.com/{venmo}?txn=pay&amount={total}"
        elif method == "cashapp" and cashapp:
            link = f"https://cash.app/{cashapp}/{total}"
        elif method == "paypal" and paypal:
            link = f"https://paypal.me/{paypal}/{total}"

        # Final embed to buyer
        final_embed = discord.Embed(
            title="Claim Sale Order Payment",
            description=(
                f"**Order ID:** {self.order['order_id']}\n"
                f"**Subtotal:** ${subtotal:.2f}\n"
                f"**Tax (6%):** ${tax:.2f}\n"
                f"**Fee:** ${fee:.2f}\n"
                f"**Shipping:** ${shipping_cost:.2f} — {shipping_label}\n"
                f"**Total Due:** ${total:.2f}\n\n"
                f"**Name:** {record['full_name']}\n"
                f"**Address:**\n{full_address}\n\n"
                f"**Payment Link:**\n{link or 'No payment link available.'}"
            ),
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=final_embed, ephemeral=True)

        # Admin DM
        admin_id = self.order.get("admin_id")
        if admin_id:
            try:
                admin = await interaction.client.fetch_user(admin_id)

                admin_embed = discord.Embed(
                    title="Buyer Submitted Payment Information",
                    description=(
                        f"**Buyer:** <@{self.order['user_id']}>\n"
                        f"**Buyer Name:** {record['full_name']}\n"
                        f"**Shipping Address:**\n{full_address}\n\n"
                        f"**Payment Method:** {self.payment_method.capitalize()}\n"
                        f"**Total Paid:** ${total:.2f}\n\n"
                        f"**Next Steps:**\n"
                        f"• Verify payment on **{self.payment_method.capitalize()}**.\n"
                        f"• Mark the order as **Paid** using `/admin manage_orders`.\n"
                        f"• Once shipped, mark as **Shipped** and enter tracking.\n"
                    ),
                    color=discord.Color.blue()
                )

                await admin.send(embed=admin_embed)

            except Exception as e:
                print(f"[CLAIM SALE][WARN] Failed to DM admin payment notice: {e}")

    # ============================================================
    # EXISTING confirm() METHOD (unchanged)
    # ============================================================
    async def confirm(self, interaction: discord.Interaction):
        if not self.payment_method or not self.shipping_method:
            await interaction.response.send_message(
                "Please select both payment and shipping methods.",
                ephemeral=True
            )
            return

        subtotal = float(self.order["subtotal"])
        tax = round(subtotal * 0.06, 2)
        total_before_shipping = subtotal + tax

        if total_before_shipping > 15 and self.shipping_method == "pwe":
            embed = discord.Embed(
                title="Tracked Shipping Required",
                description=(
                    "Orders over **$15.00** require tracked shipping.\n"
                    "Please select the **Tracked ($4.95)** shipping option to continue."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if self.shipping_method == "pwe":
            shipping_cost = 1.50
            shipping_label = "Plain White Envelope (Buyer Risk)"
        else:
            shipping_cost = 4.95
            shipping_label = "Tracked Shipping"

        fee = round(total_before_shipping * 0.03, 2) if self.payment_method == "paypal" else 0.0
        total = round(total_before_shipping + shipping_cost + fee, 2)

        venmo = (self.config["venmo_handle"] or "").strip().lstrip("@")
        cashapp = (self.config["cashapp_handle"] or "").strip()
        paypal = (self.config["paypal_handle"] or "").strip()

        method = self.payment_method.lower()
        link = None

        if method == "venmo" and venmo:
            link = f"https://venmo.com/{venmo}?txn=pay&amount={total}"
        elif method == "cashapp" and cashapp:
            link = f"https://cash.app/{cashapp}/{total}"
        elif method == "paypal" and paypal:
            link = f"https://paypal.me/{paypal}/{total}"

        self.payment_link = link
        self.shipping_label = shipping_label
        self.total = total

        await interaction.response.send_modal(
            ShippingInfoModal(
                self.bot,
                self.order,
                total,
                self.payment_method,
                shipping_label,
                link
            )
        )

# =====================================================================
# PAY CHECKOUT VIEW
# =====================================================================
class ShippingInfoModal(discord.ui.Modal, title="Enter Shipping Information"):
    name = discord.ui.TextInput(label="Full Name", required=True)
    street = discord.ui.TextInput(label="Street Address", required=True)
    city = discord.ui.TextInput(label="City", required=True)
    state = discord.ui.TextInput(label="State", required=True)
    zip_code = discord.ui.TextInput(label="Zip Code", required=True)

    def __init__(self, bot, order, total, payment_method, shipping_label, payment_link):
        super().__init__()
        self.bot = bot
        self.order = order
        self.total = total
        self.payment_method = payment_method
        self.shipping_label = shipping_label
        self.payment_link = payment_link

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name.value
        street = self.street.value
        city = self.city.value
        state = self.state.value
        zip_code = self.zip_code.value

        full_address = f"{street}\n{city}, {state} {zip_code}"

        # ⭐ Save buyer name + shipping info into DB
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET buyer_name = $2,
                    shipping_address = $3,
                    shipping_method = $4,
                    payment_method = $5
                WHERE order_id = $1;
                """,
                self.order["order_id"],
                name,
                full_address,
                self.shipping_label,
                self.payment_method
            )

        # ⭐ Update order dict for immediate UI refresh
        self.order["buyer_name"] = name
        self.order["shipping_address"] = full_address
        self.order["shipping_method"] = self.shipping_label
        self.order["payment_method"] = self.payment_method

        subtotal = float(self.order["subtotal"])
        tax = round(subtotal * 0.06, 2)
        fee = round(subtotal * 0.03, 2) if self.payment_method == "paypal" else 0.0
        shipping_cost = 4.95 if self.shipping_label.startswith("Tracked") else 1.50

        final_embed = discord.Embed(
            title="Claim Sale Order Payment",
            description=(
                f"**Order ID:** {self.order['order_id']}\n"
                f"**Subtotal:** ${subtotal:.2f}\n"
                f"**Tax (6%):** ${tax:.2f}\n"
                f"**Fee:** ${fee:.2f}\n"
                f"**Shipping:** ${shipping_cost:.2f} — {self.shipping_label}\n"
                f"**Total Due:** ${self.total:.2f}\n\n"
                f"**Name:** {name}\n"
                f"**Address:**\n{full_address}\n\n"
                f"**Payment Link - CLICK HERE TO MAKE PAYMENT:**\n{self.payment_link or 'No payment link available.'}"
            ),
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=final_embed, ephemeral=True)

        # ⭐ ADMIN PAYMENT NOTIFICATION (now includes buyer name + address)
        admin_id = self.order.get("admin_id")
        if admin_id:
            try:
                admin = await interaction.client.fetch_user(admin_id)

                admin_embed = discord.Embed(
                    title="Buyer Submitted Payment Information",
                    description=(
                        f"**Buyer:** <@{self.order['user_id']}>\n"
                        f"**Buyer Name:** {name}\n"
                        f"**Shipping Address:**\n{full_address}\n\n"
                        f"**Payment Method:** {self.payment_method.capitalize()}\n"
                        f"**Total Paid:** ${self.total:.2f}\n\n"
                        f"**Next Steps:**\n"
                        f"• Verify payment on **{self.payment_method.capitalize()}**.\n"
                        f"• If payment is confirmed, mark the order as **Paid** using `/admin manage_orders`.\n"
                        f"• Once shipped, mark the order as **Shipped** and enter the tracking number.\n"
                    ),
                    color=discord.Color.blue()
                )

                await admin.send(embed=admin_embed)

            except Exception as e:
                print(f"[CLAIM SALE][WARN] Failed to DM admin payment notice: {e}")

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

        # Refresh lists and update view
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
                SELECT admin_id, venmo_handle, cashapp_handle, paypal_handle
                FROM guild_settings
                WHERE guild_id = $1;
                """,
                interaction.guild_id
            )

        # If no methods configured, bail
        if not any([
            (config["venmo_handle"] or "").strip(),
            (config["cashapp_handle"] or "").strip(),
            (config["paypal_handle"] or "").strip()
        ]):
            embed = discord.Embed(
                title="Payment Not Configured",
                description="No payment methods are configured for this guild.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        view = PayCheckoutView(self.parent_view.bot, order, config)

        await interaction.response.send_message(
            content="Select payment and shipping, then preview your total and payment link.",
            view=view,
            ephemeral=True
        )

# =====================================================================
# BUYER-FACING VIEW — ACTIVE / DELIVERED DROPDOWN
# =====================================================================
class MyOrdersView(discord.ui.View):
    def __init__(self, bot, user_id, active_orders, delivered_orders, mode, admin_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.user_id = user_id
        self.active_orders = active_orders

        # ⭐ Filter delivered orders to last 60 days
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=60)
        self.delivered_orders = [
            o for o in delivered_orders
            if o["created_at"] >= cutoff
        ]

        self.admin_id = admin_id

        # Force default to NO MODE SELECTED
        self.mode = None
        self.page = 0
        self.pages = []

        # Dropdown only at start
        self.add_item(self.OrderTabDropdown(self))

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
                    description="View delivered orders from the past 60 days",
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
            self.parent_view.mode = choice
            self.parent_view.page = 0
            await self.parent_view.update(interaction)

    # -----------------------------------------------------------------
    # REFRESH ORDER LISTS AFTER STATUS CHANGE
    # -----------------------------------------------------------------
    def refresh_order_lists(self):
        new_active = []
        new_delivered = []

        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=60)

        for order in self.active_orders + self.delivered_orders:
            if order["order_status"] == "Delivered":
                if order["created_at"] >= cutoff:
                    new_delivered.append(order)
            else:
                new_active.append(order)

        self.active_orders = new_active
        self.delivered_orders = new_delivered

        if self.mode == "active":
            self.pages = self.active_orders
        elif self.mode == "delivered":
            self.pages = self.delivered_orders
        else:
            self.pages = []

    # -----------------------------------------------------------------
    # BUYER BUTTON LOGIC
    # -----------------------------------------------------------------
    def add_buyer_buttons(self):
        # Remove old buyer buttons
        for child in list(self.children):
            if isinstance(child, (MarkReceivedButton, MarkNotReceivedButton, PayButton)):
                self.remove_item(child)

        # Only active orders get buyer buttons
        if self.mode != "active":
            return

        if not self.pages:
            return

        order = self.pages[self.page]

        # Show Pay button only if unpaid and not cancelled
        if order.get("date_paid") is None and order["order_status"] != "Cancelled":
            self.add_item(PayButton(self))

        # Delivered orders do not get received/not received buttons
        if order["order_status"] == "Delivered":
            return

        # Add received/not received buttons
        self.add_item(MarkReceivedButton(self))
        self.add_item(MarkNotReceivedButton(self))
    # -----------------------------------------------------------------
    # UPDATE VIEW
    # -----------------------------------------------------------------
    async def update(self, interaction):

        # ⭐ REQUIRED FIX — user MUST select a category first
        if self.mode is None:
            embed = discord.Embed(
                title="Select Order Category",
                description="Please choose **Active Orders** or **Delivered Orders**.",
                color=discord.Color.blue()
            )

            # Remove everything except dropdown
            for child in list(self.children):
                if not isinstance(child, self.OrderTabDropdown):
                    self.remove_item(child)

            await interaction.response.edit_message(embed=embed, view=self)
            return

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
                    description="You don't currently have any active orders.",
                    color=discord.Color.blue()
                )
            else:
                embed = discord.Embed(
                    title="Delivered Orders",
                    description="You have no delivered orders in the past 60 days.",
                    color=discord.Color.blue()
                )
                embed.set_footer(text="Only orders from the past 60 days are shown.")

            # Remove everything except dropdown
            for child in list(self.children):
                if not isinstance(child, self.OrderTabDropdown):
                    self.remove_item(child)

            await interaction.response.edit_message(embed=embed, view=self)
            return

        # Clamp page
        if self.page >= len(self.pages):
            self.page = 0

        # Build embed using MyOrders cog builder
        embed = interaction.client.get_cog("MyOrders").build_order_embed(
            self.pages[self.page],
            self.page + 1,
            len(self.pages),
            self.mode
        )

        # ⭐ Add footer for delivered orders
        if self.mode == "delivered":
            embed.set_footer(text="Only orders from the past 60 days are shown.")
        else:
            embed.set_footer(text="Only active orders are displayed.")

        # Rebuild buttons
        self.clear_items()

        # Dropdown always first
        self.add_item(self.OrderTabDropdown(self))

        # Pagination buttons
        self.add_pagination_buttons()

        # Buyer buttons
        self.add_buyer_buttons()

        await interaction.response.edit_message(embed=embed, view=self)

    # -----------------------------------------------------------------
    # PAGINATION BUTTONS (DYNAMIC)
    # -----------------------------------------------------------------
    def add_pagination_buttons(self):

        # Remove old pagination buttons
        for child in list(self.children):
            if isinstance(child, discord.ui.Button) and child.custom_id in ("previous", "next"):
                self.remove_item(child)

        prev = discord.ui.Button(
            label="Previous",
            style=discord.ButtonStyle.primary,
            custom_id="previous",
            row=0
        )
        next = discord.ui.Button(
            label="Next",
            style=discord.ButtonStyle.primary,
            custom_id="next",
            row=0
        )

        async def prev_callback(interaction):
            if self.page > 0:
                self.page -= 1
            await self.update(interaction)

        async def next_callback(interaction):
            if self.page < len(self.pages) - 1:
                self.page += 1
            await self.update(interaction)

        prev.callback = prev_callback
        next.callback = next_callback

        prev.disabled = (self.page == 0 or len(self.pages) <= 1)
        next.disabled = (self.page >= len(self.pages) - 1 or len(self.pages) <= 1)

        self.add_item(prev)
        self.add_item(next)


# =====================================================================
# SETUP
# =====================================================================
async def setup(bot):
    pass


