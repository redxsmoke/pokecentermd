import discord
from discord.ext import commands
import datetime

ADMIN_ID = 337773020770729985

VENMO = "@aevans9560"
CASHAPP = "$andrew9560"
PAYPAL = "swemd"


class Cart(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="cart", description="View your shopping cart.")
    async def cart(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET quantity_available = quantity_available + reserved,
                    reserved = 0,
                    reserved_until = NULL
                WHERE reserved_until IS NOT NULL
                  AND reserved_until < NOW();
                """
            )

            rows = await conn.fetch(
                """
                SELECT c.inventory_id, c.quantity,
                       i.pokemon_name, i.price, i.condition,
                       i.series, i.set_name, i.rarity
                FROM cart_items c
                JOIN inventory i ON i.inventory_id = c.inventory_id
                WHERE c.user_id = $1
                ORDER BY i.pokemon_name ASC;
                """,
                user_id
            )

        if not rows:
            embed = discord.Embed(
                title="Your Cart",
                description="Your cart is empty.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        pages = []
        chunk = []

        for r in rows:
            chunk.append(r)
            if len(chunk) == 10:
                pages.append(chunk)
                chunk = []

        if chunk:
            pages.append(chunk)

        view = CartView(self.bot, interaction.user.id, pages)
        embed = self.build_page_embed(pages[0], 1, len(pages))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def build_page_embed(self, items, page_num, total_pages):
        embed = discord.Embed(
            title=f"Your Cart — Page {page_num}/{total_pages}",
            color=discord.Color.green()
        )

        desc = ""
        for r in items:
            desc += (
                f"**#{r['inventory_id']} — {r['pokemon_name']}**\n"
                f"Price: ${r['price']} — Condition: {r['condition']}\n"
                f"{r['series']} — {r['set_name']} — {r['rarity']}\n"
                f"Qty: {r['quantity']}\n\n"
            )

        subtotal = sum(r["price"] * r["quantity"] for r in items)
        tax = round(subtotal * 0.06, 2)
        paypal_fee = round((subtotal + tax) * 0.04, 2)

        desc += (
            f"**Subtotal (this page):** ${subtotal:.2f}\n"
            f"**Tax (est):** ${tax:.2f}\n"
            f"**Shipping:** PWE $1.50 or Tracked $4.95\n"
            f"**PayPal Fee (est):** ${paypal_fee:.2f}\n"
            f"**Total (est, before shipping):** ${round(subtotal + tax, 2):.2f}\n"
            f"_Final total shown at checkout based on chosen shipping and payment method._\n"
        )

        embed.description = desc
        return embed


class RemoveItemButton(discord.ui.Button):
    def __init__(self, bot, user_id, inventory_id, quantity):
        super().__init__(label=f"Remove #{inventory_id}", style=discord.ButtonStyle.danger)
        self.bot = bot
        self.user_id = user_id
        self.inventory_id = inventory_id
        self.quantity = quantity

    async def callback(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:

            await conn.execute(
                "DELETE FROM cart_items WHERE user_id = $1 AND inventory_id = $2;",
                self.user_id, self.inventory_id
            )

            row = await conn.fetchrow(
                """
                SELECT reserved
                FROM inventory
                WHERE inventory_id = $1;
                """,
                self.inventory_id
            )

            reserved = row["reserved"]

            if reserved > 0:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET reserved = reserved - $1,
                        quantity_available = quantity_available + $1,
                        reserved_until = CASE
                            WHEN reserved - $1 <= 0 THEN NULL
                            ELSE reserved_until
                        END
                    WHERE inventory_id = $2;
                    """,
                    self.quantity,
                    self.inventory_id
                )

        embed = discord.Embed(
            title="Item Removed",
            description=f"Removed item #{self.inventory_id} from your cart.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class CartView(discord.ui.View):
    def __init__(self, bot, user_id, pages):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.pages = pages
        self.page = 0

        for r in pages[0]:
            self.add_item(RemoveItemButton(bot, user_id, r["inventory_id"], r["quantity"]))

    async def update(self, interaction):
        embed = interaction.client.get_cog("Cart").build_page_embed(
            self.pages[self.page],
            self.page + 1,
            len(self.pages)
        )

        view = CartView(self.bot, self.user_id, self.pages)
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

    @discord.ui.button(label="Checkout", style=discord.ButtonStyle.success)
    async def checkout(self, interaction, button):
        view = CheckoutStartView(self.bot, self.user_id)
        embed = discord.Embed(
            title="Checkout",
            description="Select shipping and payment method:",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=view)
class CheckoutStartView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id

        self.shipping_method = None
        self.payment_method = None

        self.shipping_select = discord.ui.Select(
            placeholder="Select Shipping Method",
            options=[
                discord.SelectOption(label="PWE ($1.50)", value="pwe"),
                discord.SelectOption(label="Tracked ($4.95)", value="tracked")
            ]
        )
        self.shipping_select.callback = self.shipping_callback
        self.add_item(self.shipping_select)

        self.payment_select = discord.ui.Select(
            placeholder="Select Payment Method",
            options=[
                discord.SelectOption(label="Venmo", value="venmo"),
                discord.SelectOption(label="CashApp", value="cashapp"),
                discord.SelectOption(label="PayPal", value="paypal")
            ]
        )
        self.payment_select.callback = self.payment_callback
        self.add_item(self.payment_select)

    async def shipping_callback(self, interaction: discord.Interaction):
        self.shipping_method = self.shipping_select.values[0]
        await interaction.response.defer()

    async def payment_callback(self, interaction: discord.Interaction):
        self.payment_method = self.payment_select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success)
    async def continue_btn(self, interaction, button):
        if not self.shipping_method or not self.payment_method:
            embed = discord.Embed(
                title="Missing Selection",
                description="Please select both shipping and payment method.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        modal = CheckoutModal(
            self.bot,
            self.user_id,
            self.shipping_method,
            self.payment_method
        )
        await interaction.response.send_modal(modal)


class RemoveUnavailableItemsButton(discord.ui.Button):
    def __init__(self, bot, user_id, unavailable_ids):
        super().__init__(label="Remove unavailable items", style=discord.ButtonStyle.danger)
        self.bot = bot
        self.user_id = user_id
        self.unavailable_ids = unavailable_ids

    async def callback(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM cart_items
                WHERE user_id = $1
                  AND inventory_id = ANY($2);
                """,
                self.user_id,
                self.unavailable_ids
            )

        embed = discord.Embed(
            title="Items Removed",
            description="Unavailable items were removed from your cart.\nYou may restart checkout.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class UnavailableItemsView(discord.ui.View):
    def __init__(self, bot, user_id, unavailable_items):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id

        unavailable_ids = [i["inventory_id"] for i in unavailable_items]
        self.add_item(RemoveUnavailableItemsButton(bot, user_id, unavailable_ids))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button):
        embed = discord.Embed(
            title="Checkout Cancelled",
            description="You cancelled checkout.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
class CheckoutModal(discord.ui.Modal, title="Shipping Information"):
    name = discord.ui.TextInput(label="Full Name", required=True)
    address = discord.ui.TextInput(label="Shipping Address", required=True)

    def __init__(self, bot, user_id, shipping_method, payment_method):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.shipping_method = shipping_method
        self.payment_method = payment_method
        self.items = None

    async def on_submit(self, interaction: discord.Interaction):

        if self.shipping_method == "pwe":
            shipping_cost = 1.50
            shipping_label = "Plain White Envelope (Buyer Risk)"
        else:
            shipping_cost = 4.95
            shipping_label = "Tracked Shipping"

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET quantity_available = quantity_available + reserved,
                    reserved = 0,
                    reserved_until = NULL
                WHERE reserved_until IS NOT NULL
                  AND reserved_until < NOW();
                """
            )

            items = await conn.fetch(
                """
                SELECT c.inventory_id, c.quantity,
                       i.pokemon_name, i.price, i.condition,
                       i.series, i.set_name, i.rarity,
                       i.quantity_available, i.reserved
                FROM cart_items c
                JOIN inventory i ON i.inventory_id = c.inventory_id
                WHERE c.user_id = $1;
                """,
                self.user_id
            )

        if not items:
            embed = discord.Embed(
                title="Cart Empty",
                description="Your cart is empty.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        unavailable = []

        for i in items:
            if i["quantity"] > i["quantity_available"]:
                unavailable.append(i)

        if unavailable:
            desc = (
                "The following items are no longer available:\n\n" +
                "\n".join(
                    f"**#{i['inventory_id']} — {i['pokemon_name']}** "
                    f"(Requested {i['quantity']}, Available {i['quantity_available']})"
                    for i in unavailable
                ) +
                "\n\nYou may remove these items and continue."
            )

            embed = discord.Embed(
                title="Unavailable Items",
                description=desc,
                color=discord.Color.red()
            )

            view = UnavailableItemsView(self.bot, self.user_id, unavailable)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return

        expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=30)

        async with self.bot.db.acquire() as conn:
            for i in items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET reserved = reserved + $1,
                        quantity_available = quantity_available - $1,
                        reserved_until = $2
                    WHERE inventory_id = $3
                      AND quantity_available >= $1;
                    """,
                    i["quantity"],
                    expires_at,
                    i["inventory_id"]
                )

        self.items = items

        subtotal = sum(i["price"] * i["quantity"] for i in items)
        tax = round(subtotal * 0.06, 2)
        total_before_shipping = subtotal + tax
        total = round(total_before_shipping + shipping_cost, 2)

        if self.payment_method == "paypal":
            paypal_fee = round(total_before_shipping * 0.04, 2)
            grand_total = round(total + paypal_fee, 2)
        else:
            paypal_fee = 0
            grand_total = total

        reservation_msg = (
            "**Your cards are now reserved for 30 minutes — "
            "if you do not submit your order, the items will be released.**"
        )

        embed = discord.Embed(
            title="Confirm Your Order",
            color=discord.Color.green()
        )

        embed.description = (
            f"**Name:** {self.name.value}\n"
            f"**Address:** {self.address.value}\n"
            f"**Shipping:** {shipping_label}\n"
            f"**Payment Method:** {self.payment_method.capitalize()}\n\n"
            f"**Subtotal:** ${subtotal:.2f}\n"
            f"**Tax:** ${tax:.2f}\n"
            f"**Shipping:** ${shipping_cost:.2f}\n"
            f"**PayPal Fee:** ${paypal_fee:.2f}\n"
            f"**Grand Total:** ${grand_total:.2f}\n\n"
            f"{reservation_msg}\n"
        )

        view = FinalizeOrderView(
            self.bot,
            self.user_id,
            items,
            subtotal,
            tax,
            shipping_cost,
            shipping_label,
            self.payment_method,
            self.name.value,
            self.address.value
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class FinalizeOrderView(discord.ui.View):
    def __init__(
        self, bot, user_id, items,
        subtotal, tax, shipping_cost, shipping_label,
        payment_method, name, address
    ):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.items = items
        self.subtotal = subtotal
        self.tax = tax
        self.shipping_cost = shipping_cost
        self.shipping_label = shipping_label
        self.payment_method = payment_method
        self.name = name
        self.address = address

        self.total_before_shipping = subtotal + tax
        self.total = round(self.total_before_shipping + shipping_cost, 2)

        if payment_method == "paypal":
            self.paypal_fee = round(self.total_before_shipping * 0.04, 2)
            self.grand_total = round(self.total + self.paypal_fee, 2)
        else:
            self.paypal_fee = 0
            self.grand_total = self.total

    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit(self, interaction, button):

        async with self.bot.db.acquire() as conn:
            order = await conn.fetchrow(
                """
                INSERT INTO orders (user_id, subtotal, tax, fee, total, payment_method)
                VALUES ($1, $2, $3, $4, $5, 'Pending')
                RETURNING order_id;
                """,
                self.user_id,
                self.subtotal,
                self.tax,
                self.paypal_fee,
                self.total
            )

            order_id = order["order_id"]

            for i in self.items:
                await conn.execute(
                    """
                    INSERT INTO order_items (order_id, inventory_id, quantity, price_each)
                    VALUES ($1, $2, $3, $4);
                    """,
                    order_id, i["inventory_id"], i["quantity"], i["price"]
                )

        amount = f"{self.grand_total:.2f}"

        if self.payment_method == "venmo":
            payment_text = (
                f"**Venmo Payment:**\n"
                f"https://venmo.com/{VENMO.replace('@', '')}\n"
                f"Send **${amount}**"
            )
        elif self.payment_method == "cashapp":
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
class AdminOrderView(discord.ui.View):
    def __init__(
        self, bot, order_id, user_id,
        total, grand_total, items,
        name, address, shipping_label
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id
        self.total = total
        self.grand_total = grand_total
        self.items = items
        self.name = name
        self.address = address
        self.shipping_label = shipping_label

    @discord.ui.button(label="Confirm Payment", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button):

        if interaction.user.id != ADMIN_ID:
            embed = discord.Embed(
                title="Access Denied",
                description="Only the admin can confirm payment.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        async with self.bot.db.acquire() as conn:

            # Deduct reserved inventory permanently
            for i in self.items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET reserved = GREATEST(reserved - $1, 0),
                        reserved_until = NULL
                    WHERE inventory_id = $2;
                    """,
                    i["quantity"],
                    i["inventory_id"]
                )

            await conn.execute(
                """
                UPDATE orders
                SET payment_method = 'Paid'
                WHERE order_id = $1;
                """,
                self.order_id
            )

        user = await interaction.client.fetch_user(self.user_id)

        try:
            embed = discord.Embed(
                title="Payment Confirmed",
                description=(
                    f"Your payment for order #{self.order_id} has been confirmed!\n"
                    f"Your cards will be shipped via **{self.shipping_label}**."
                ),
                color=discord.Color.green()
            )
            await user.send(embed=embed)
        except discord.Forbidden:
            pass

        embed = discord.Embed(
            title="Payment Confirmed",
            description=f"Order #{self.order_id} marked as **Paid**.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button):

        if interaction.user.id != ADMIN_ID:
            embed = discord.Embed(
                title="Access Denied",
                description="Only the admin can cancel orders.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        modal = CancelOrderModal(
            self.bot,
            self.order_id,
            self.user_id,
            self.items
        )
        await interaction.response.send_modal(modal)


class CancelOrderModal(discord.ui.Modal, title="Cancel Order"):
    reason = discord.ui.TextInput(
        label="Reason for cancellation",
        required=True,
        style=discord.TextStyle.long
    )

    def __init__(self, bot, order_id, user_id, items):
        super().__init__()
        self.bot = bot
        self.order_id = order_id
        self.user_id = user_id
        self.items = items

    async def on_submit(self, interaction: discord.Interaction):

        if interaction.user.id != ADMIN_ID:
            embed = discord.Embed(
                title="Access Denied",
                description="Only the admin can cancel orders.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        async with self.bot.db.acquire() as conn:

            # Release reserved inventory
            for i in self.items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET reserved = GREATEST(reserved - $1, 0),
                        quantity_available = quantity_available + $1,
                        reserved_until = NULL
                    WHERE inventory_id = $2;
                    """,
                    i["quantity"],
                    i["inventory_id"]
                )

            await conn.execute(
                """
                UPDATE orders
                SET payment_method = 'Cancelled'
                WHERE order_id = $1;
                """,
                self.order_id
            )

        user = await interaction.client.fetch_user(self.user_id)

        try:
            embed = discord.Embed(
                title="Order Cancelled",
                description=(
                    f"Your order #{self.order_id} has been cancelled.\n"
                    f"**Reason:** {self.reason.value}"
                ),
                color=discord.Color.red()
            )
            await user.send(embed=embed)
        except discord.Forbidden:
            pass

        embed = discord.Embed(
            title="Order Cancelled",
            description="Order cancelled and inventory released.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Cart(bot))


