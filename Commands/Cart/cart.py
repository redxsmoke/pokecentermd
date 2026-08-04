import discord
from discord.ext import commands
from discord import app_commands
import datetime

ADMIN_ID = 337773020770729985

VENMO = "@aevans9560"
CASHAPP = "$andrew9560"
PAYPAL = "swemd"


class Cart(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def open_cart(self, interaction: discord.Interaction):
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

    @discord.app_commands.command(name="cart", description="View your shopping cart.")
    async def cart(self, interaction: discord.Interaction):
        await self.open_cart(interaction)

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


class RemoveItemSelect(discord.ui.Select):
    def __init__(self, bot, user_id, items):
        options = [
            discord.SelectOption(label="🗑️ Remove All Cards", value="clear_all")
        ]

        for r in items:
            options.append(
                discord.SelectOption(
                    label=f"Remove #{r['inventory_id']} — {r['pokemon_name']}",
                    value=str(r["inventory_id"])
                )
            )

        super().__init__(
            placeholder="Remove Card(s)...",
            min_values=1,
            max_values=1,
            options=options
        )

        self.bot = bot
        self.user_id = user_id
        self.items = items

    async def callback(self, interaction: discord.Interaction):

        choice = self.values[0]

        async with self.bot.db.acquire() as conn:

            # CLEAR ALL
            if choice == "clear_all":
                await conn.execute(
                    """
                    UPDATE inventory
                    SET quantity_available = quantity_available + reserved,
                        reserved = 0,
                        reserved_until = NULL
                    WHERE inventory_id IN (
                        SELECT inventory_id FROM cart_items WHERE user_id = $1
                    );
                    """,
                    self.user_id
                )

                await conn.execute(
                    "DELETE FROM cart_items WHERE user_id = $1;",
                    self.user_id
                )

                embed = discord.Embed(
                    title="Cart Cleared",
                    description="All items have been removed from your cart.",
                    color=discord.Color.green()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # REMOVE SINGLE ITEM
            inventory_id = int(choice)

            # Get quantity for proper release
            qty_row = await conn.fetchrow(
                """
                SELECT quantity FROM cart_items
                WHERE user_id = $1 AND inventory_id = $2;
                """,
                self.user_id,
                inventory_id
            )

            if qty_row:
                qty = qty_row["quantity"]

                await conn.execute(
                    "DELETE FROM cart_items WHERE user_id = $1 AND inventory_id = $2;",
                    self.user_id,
                    inventory_id
                )

                await conn.execute(
                    """
                    UPDATE inventory
                    SET reserved = GREATEST(reserved - $1, 0),
                        quantity_available = quantity_available + $1,
                        reserved_until = NULL
                    WHERE inventory_id = $2;
                    """,
                    qty,
                    inventory_id
                )

            embed = discord.Embed(
                title="Item Removed",
                description=f"Removed item #{inventory_id} from your cart.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

class ClearCartButton(discord.ui.Button):
    def __init__(self, bot, user_id):
        super().__init__(label="Clear All", style=discord.ButtonStyle.danger)
        self.bot = bot
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:

            await conn.execute(
                """
                UPDATE inventory
                SET quantity_available = quantity_available + reserved,
                    reserved = 0,
                    reserved_until = NULL
                WHERE inventory_id IN (
                    SELECT inventory_id FROM cart_items WHERE user_id = $1
                );
                """,
                self.user_id
            )

            await conn.execute(
                """
                DELETE FROM cart_items
                WHERE user_id = $1;
                """,
                self.user_id
            )

        embed = discord.Embed(
            title="Cart Cleared",
            description="All items have been removed from your cart.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


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
                    SET reserved = COALESCE(reserved, 0) + $1,
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
            self.paypal_fee = paypal_fee
            grand_total = round(total + paypal_fee, 2)
        else:
            paypal_fee = 0
            self.paypal_fee = 0
            grand_total = total

        reservation_msg = (
            "Your cards are now reserved for 15 minutes — "
            "if you do not submit your order, the items will be released."
        )

        # Build card list (sorted alphabetically)
        sorted_items = sorted(items, key=lambda x: x["pokemon_name"].lower())

        card_lines = []
        for i in sorted_items:
            price_each = float(i["price"])
            qty = i["quantity"]
            line_total = round(price_each * qty, 2)

            card_lines.append(
                f"• {i['pokemon_name']} — x{qty} @ ${price_each:.2f} = ${line_total:.2f}\n"
                f"  Condition: {i['condition']}\n"
                f"  Series: {i['series']}\n"
                f"  Set: {i['set_name']}\n"
            )

        card_list_text = "\n".join(card_lines)

        embed = discord.Embed(
            title="Review Your Order",
            color=discord.Color.green()
        )

        embed.add_field(
            name="🧍 Customer Information",
            value=f"**Name:** {self.name.value}\n**Address:** {self.address.value}",
            inline=False
        )

        embed.add_field(
            name="🛒 Order Information",
            value=card_list_text,
            inline=False
        )

        embed.add_field(
            name="🚚 Payment & Shipping Information",
            value=(
                f"**Shipping:** {shipping_label}\n"
                f"**Payment Method:** {self.payment_method.capitalize()}\n\n"
                f"**Subtotal:** ${subtotal:.2f}\n"
                f"**Tax:** ${tax:.2f}\n"
                f"**Shipping:** ${shipping_cost:.2f}\n"
                f"**PayPal Fee:** ${paypal_fee:.2f}\n"
                f"**Grand Total:** ${grand_total:.2f}"
            ),
            inline=False
        )

        embed.add_field(
            name="⏳ Reservation Notice",
            value=reservation_msg,
            inline=False
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

        async with self.bot.db.acquire() as conn:
            subtotal_row = await conn.fetchrow(
                """
                SELECT SUM(i.price * c.quantity) AS subtotal
                FROM cart_items c
                JOIN inventory i ON i.inventory_id = c.inventory_id
                WHERE c.user_id = $1;
                """,
                self.user_id
            )

        subtotal = float(subtotal_row["subtotal"])
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

        modal = CheckoutModal(
            self.bot,
            self.user_id,
            self.shipping_method,
            self.payment_method
        )
        await interaction.response.send_modal(modal)


class CartView(discord.ui.View):
    def __init__(self, bot, user_id, pages):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.pages = pages
        self.page = 0

        # Add dropdown instead of many remove buttons
        self.add_item(RemoveItemSelect(bot, user_id, pages[0]))

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

class FinalizeOrderView(discord.ui.View):
    def __init__(
        self, bot, user_id, items,
        subtotal, tax, shipping_cost, shipping_label,
        payment_method, name, address
    ):
        super().__init__(timeout=900)  # 15 minutes
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
            paypal_fee = round(self.total_before_shipping * 0.04, 2)
            self.paypal_fee = paypal_fee
            self.grand_total = round(self.total + paypal_fee, 2)
        else:
            self.paypal_fee = 0
            self.grand_total = self.total

        self.message = None


    async def on_timeout(self):
        async with self.bot.db.acquire() as conn:

            # Release inventory
            for i in self.items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET quantity_available = quantity_available + $2,
                        reserved = GREATEST(reserved - $2, 0),
                        reserved_until = NULL
                    WHERE inventory_id = $1;
                    """,
                    i["inventory_id"],
                    i["quantity"]
                )

            # Clear cart
            await conn.execute(
                "DELETE FROM cart_items WHERE user_id = $1;",
                self.user_id
            )

        # Disable buttons
        for child in self.children:
            child.disabled = True

        # Edit original message
        if self.message:
            try:
                await self.message.edit(
                    content="⏰ **Order timed out** — items were released.",
                    view=self
                )
            except:
                pass

        # DM user
        try:
            user = await self.bot.fetch_user(self.user_id)

            card_lines = [
                f"• {i['pokemon_name']} — x{i['quantity']}"
                for i in sorted(self.items, key=lambda x: x["pokemon_name"].lower())
            ]
            card_text = "\n".join(card_lines)

            await user.send(
                embed=discord.Embed(
                    title="Order Cancelled",
                    description=(
                        "**Your checkout session expired before the order was submitted.**\n\n"
                        "The following items were released:\n\n"
                        f"{card_text}\n\n"
                        "If you still want these items, please add them to your cart again."
                    ),
                    color=discord.Color.red()
                )
            )
        except:
            pass


    # =====================================================================
    # SUBMIT ORDER BUTTON
    # =====================================================================
    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):

        self.stop()  

        self.message = interaction.message
        button.disabled = True
        self.children[1].disabled = True  # Cancel button

        # Update message
        if interaction.response.is_done():
            await interaction.followup.edit_message(view=self)
        else:
            await interaction.response.edit_message(view=self)

        # Create order (does NOT touch inventory)
        await interaction.client.get_cog("MyOrders").create_order(
            interaction,
            self.user_id,
            self.items,
            self.subtotal,
            self.tax,
            self.paypal_fee,
            self.shipping_cost,
            self.total,
            self.grand_total,
            self.name,
            self.address,
            self.shipping_label,
            self.payment_method
        )

        # Clear cart ONLY
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                "DELETE FROM cart_items WHERE user_id = $1;",
                self.user_id
            )

        await interaction.followup.send(
            "Order submitted! Your cart has been cleared.",
            ephemeral=True
        )


    # =====================================================================
    # CANCEL ORDER BUTTON
    # =====================================================================
    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):

        self.stop()  

        self.message = interaction.message

        # Release inventory + clear cart
        async with self.bot.db.acquire() as conn:
            for i in self.items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET quantity_available = quantity_available + $2,
                        reserved = GREATEST(reserved - $2, 0),
                        reserved_until = NULL
                    WHERE inventory_id = $1;
                    """,
                    i["inventory_id"],
                    i["quantity"]
                )

            await conn.execute(
                "DELETE FROM cart_items WHERE user_id = $1;",
                self.user_id
            )

        # Disable buttons
        for child in self.children:
            child.disabled = True

        # Build card list
        sorted_items = sorted(self.items, key=lambda x: x["pokemon_name"].lower())
        card_text = "\n".join(
            f"• {i['pokemon_name']} — x{i['quantity']}" for i in sorted_items
        )

        # DM user
        try:
            user = await self.bot.fetch_user(self.user_id)
            await user.send(
                embed=discord.Embed(
                    title="Order Cancelled",
                    description=(
                        "You cancelled your order.\n\n"
                        "The following items were released:\n\n"
                        f"{card_text}\n\n"
                        "If you still want these items, please add them to your cart again."
                    ),
                    color=discord.Color.red()
                )
            )
        except:
            pass

        # Update original message
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Order Cancelled",
                description="Your order was cancelled and all items were released.",
                color=discord.Color.red()
            ),
            view=self
        )


    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):

        self.message = interaction.message

        async with self.bot.db.acquire() as conn:
            for i in self.items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET quantity_available = quantity_available + $2,
                        reserved = GREATEST(reserved - $2, 0),
                        reserved_until = NULL
                    WHERE inventory_id = $1;
                    """,
                    i["inventory_id"],
                    i["quantity"]
                )

            await conn.execute(
                """
                DELETE FROM cart_items
                WHERE user_id = $1;
                """,
                self.user_id
            )

        for child in self.children:
            child.disabled = True

        sorted_items = sorted(self.items, key=lambda x: x["pokemon_name"].lower())
        card_text = "\n".join(
            f"• {i['pokemon_name']} — x{i['quantity']}" for i in sorted_items
        )

        try:
            user = await self.bot.fetch_user(self.user_id)
            await user.send(
                embed=discord.Embed(
                    title="Order Cancelled",
                    description=(
                        "You cancelled your order.\n\n"
                        "The following items were released:\n\n"
                        f"{card_text}\n\n"
                        "If you still want these items, please add them to your cart again."
                    ),
                    color=discord.Color.red()
                )
            )
        except:
            pass

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Order Cancelled",
                description="Your order was cancelled and all items were released.",
                color=discord.Color.red()
            ),
            view=self
        )
async def setup(bot):
    await bot.add_cog(Cart(bot))