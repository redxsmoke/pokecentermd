import discord
from discord.ext import commands
from discord import app_commands
import datetime

async def get_guild_payment_config(bot, guild_id):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT venmo_handle, cashapp_handle, paypal_handle, admin_id
            FROM guild_settings
            WHERE guild_id = $1;
            """,
            guild_id
        )
    return row


class Cart(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def open_cart(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        async with self.bot.db.acquire() as conn:
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
            f"**Total (est, before shipping):** ${round(subtotal + tax + paypal_fee, 2):.2f}\n"
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

            if choice == "clear_all":
                await conn.execute(
                    """
                    UPDATE inventory
                    SET quantity_available = quantity_available + c.quantity
                    FROM cart_items c
                    WHERE c.user_id = $1
                      AND inventory.inventory_id = c.inventory_id;
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

            inventory_id = int(choice)

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
                    SET quantity_available = quantity_available + $1
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
                SET quantity_available = quantity_available + c.quantity
                FROM cart_items c
                WHERE c.user_id = $1
                  AND inventory.inventory_id = c.inventory_id;
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


async def process_checkout(
    bot,
    interaction,
    user_id,
    shipping_method,
    payment_method,
    full_name=None,
    street=None,
    city=None,
    state=None,
    zip=None,
    use_saved=False
):
    if shipping_method == "pwe":
        shipping_cost = 1.50
        shipping_label = "Plain White Envelope (Buyer Risk)"
    else:
        shipping_cost = 4.95
        shipping_label = "Tracked Shipping"

    async with bot.db.acquire() as conn:
        items = await conn.fetch(
            """
            SELECT c.inventory_id, c.quantity,
                   i.pokemon_name, i.price, i.condition,
                   i.series, i.set_name, i.rarity,
                   i.quantity_available
            FROM cart_items c
            JOIN inventory i ON i.inventory_id = c.inventory_id
            WHERE c.user_id = $1;
            """,
            user_id
        )

    if not items:
        embed = discord.Embed(
            title="Cart Empty",
            description="Your cart is empty.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    unavailable = [
        i for i in items if i["quantity"] > i["quantity_available"]
    ]

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

        view = UnavailableItemsView(bot, user_id, unavailable)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    subtotal = sum(i["price"] * i["quantity"] for i in items)
    tax = round(subtotal * 0.06, 2)
    total_before_shipping = subtotal + tax

    config = await get_guild_payment_config(bot, interaction.guild.id)

    paypal_fee = round(total_before_shipping * 0.04, 2) if payment_method == "paypal" else 0
    total = round(total_before_shipping + shipping_cost + paypal_fee, 2)

    if use_saved:
        async with bot.db.acquire() as conn:
            saved = await conn.fetchrow(
                """
                SELECT full_name, street_address, city, state, zip
                FROM user_shipping_info
                WHERE user_id = $1 AND guild_id = $2;
                """,
                user_id,
                interaction.guild.id
            )

        if not saved:
            embed = discord.Embed(
                title="No Saved Shipping Address",
                description="You do not have a saved shipping address.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        full_name = saved["full_name"]
        street = saved["street_address"]
        city = saved["city"]
        state = saved["state"]
        zip = saved["zip"]

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
        value=(
            f"**Name:** {full_name}\n"
            f"**Address:** {street}\n"
            f"{city}, {state} {zip}"
        ),
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
            f"**Payment Method:** {payment_method.capitalize()}\n\n"
            f"**Subtotal:** ${subtotal:.2f}\n"
            f"**Tax:** ${tax:.2f}\n"
            f"**Shipping:** ${shipping_cost:.2f}\n"
            f"**PayPal Fee:** ${paypal_fee:.2f}\n"
            f"**Total:** ${total:.2f}"
        ),
        inline=False
    )

    view = FinalizeOrderView(
        bot,
        user_id,
        items,
        subtotal,
        tax,
        shipping_cost,
        shipping_label,
        payment_method,
        full_name,
        f"{street}\n{city}, {state} {zip}"
    )

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
class CheckoutModal(discord.ui.Modal, title="Enter Shipping Information"):
    full_name = discord.ui.TextInput(label="Full Name", required=True)
    street = discord.ui.TextInput(label="Street Address", required=True)
    city = discord.ui.TextInput(label="City", required=True)
    state = discord.ui.TextInput(label="State", required=True)
    zip_code = discord.ui.TextInput(label="Zip Code", required=True)

    def __init__(self, bot, user_id, shipping_method, payment_method):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.shipping_method = shipping_method
        self.payment_method = payment_method
        self.items = None

    async def on_submit(self, interaction: discord.Interaction):
        await process_checkout(
            bot=self.bot,
            interaction=interaction,
            user_id=self.user_id,
            shipping_method=self.shipping_method,
            payment_method=self.payment_method,
            full_name=self.full_name.value,
            street=self.street.value,
            city=self.city.value,
            state=self.state.value,
            zip=self.zip_code.value,
            use_saved=False
        )


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

        self.payment_select = None

    async def async_init(self, interaction):
        guild_id = interaction.guild.id

        config = await get_guild_payment_config(self.bot, guild_id)
        if config is None:
            embed = discord.Embed(
                title="Payment Configuration Missing",
                description=(
                    "Payment settings have not been configured for this server.\n"
                    "Please contact an administrator."
                ),
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return False

        venmo = (config["venmo_handle"] or "").strip()
        cashapp = (config["cashapp_handle"] or "").strip()
        paypal = (config["paypal_handle"] or "").strip()
        admin_id = config["admin_id"]

        payment_options = []
        if venmo:
            payment_options.append(discord.SelectOption(label="Venmo", value="venmo"))
        if cashapp:
            payment_options.append(discord.SelectOption(label="CashApp", value="cashapp"))
        if paypal:
            payment_options.append(discord.SelectOption(label="PayPal", value="paypal"))

        if not payment_options:
            embed = discord.Embed(
                title="Payment Not Configured",
                description=f"Payment options have not been configured.\nContact <@{admin_id}>.",
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return False

        self.payment_select = discord.ui.Select(
            placeholder="Select Payment Method",
            options=payment_options
        )
        self.payment_select.callback = self.payment_callback
        self.add_item(self.payment_select)

        manual_btn = discord.ui.Button(
            label="Enter Name & Shipping Info",
            style=discord.ButtonStyle.success
        )
        manual_btn.callback = self.enter_manual
        self.add_item(manual_btn)

        saved_btn = discord.ui.Button(
            label="Use Saved Shipping Address",
            style=discord.ButtonStyle.primary
        )
        saved_btn.callback = self.use_saved
        self.add_item(saved_btn)

        return True

    async def shipping_callback(self, interaction: discord.Interaction):
        self.shipping_method = self.shipping_select.values[0]
        await interaction.response.defer()

    async def payment_callback(self, interaction: discord.Interaction):
        self.payment_method = self.payment_select.values[0]
        await interaction.response.defer()

    async def enter_manual(self, interaction: discord.Interaction):
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

    async def use_saved(self, interaction: discord.Interaction):
        if not self.shipping_method or not self.payment_method:
            embed = discord.Embed(
                title="Missing Selection",
                description="Please select both shipping and payment method.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await process_checkout(
            bot=self.bot,
            interaction=interaction,
            user_id=self.user_id,
            shipping_method=self.shipping_method,
            payment_method=self.payment_method,
            use_saved=True
        )


class CartView(discord.ui.View):
    def __init__(self, bot, user_id, pages):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.pages = pages
        self.page = 0

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
        ok = await view.async_init(interaction)
        if not ok:
            return

        embed = discord.Embed(
            title="Checkout",
            description="Select shipping and payment method:",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=view)


@discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):

    self.stop()

    self.message = interaction.message
    button.disabled = True
    self.children[1].disabled = True

    if interaction.response.is_done():
        await interaction.followup.edit_message(view=self)
    else:
        await interaction.response.edit_message(view=self)

    config = await get_guild_payment_config(self.bot, interaction.guild_id)
    admin_id = config["admin_id"]

    order_id = await interaction.client.get_cog("MyOrders").create_order(
        interaction,
        self.user_id,
        self.items,
        self.subtotal,
        self.tax,
        self.paypal_fee,
        self.shipping_cost,
        self.total,
        self.payment_method,
        self.shipping_label,
        self.name,
        self.address,
        admin_id
    )

    async with interaction.client.db.acquire() as conn:
        for i in self.items:
            await conn.execute(
                """
                UPDATE inventory
                SET quantity_available = quantity_available - $2
                WHERE inventory_id = $1;
                """,
                i["inventory_id"],
                i["quantity"]
            )

        await conn.execute(
            "DELETE FROM cart_items WHERE user_id = $1;",
            self.user_id
        )

    async with self.bot.db.acquire() as conn:
        config = await conn.fetchrow(
            """
            SELECT venmo_handle, cashapp_handle, paypal_handle
            FROM guild_settings
            WHERE guild_id = $1;
            """,
            interaction.guild_id
        )

    venmo = (config["venmo_handle"] or "").strip().lstrip("@")
    cashapp = (config["cashapp_handle"] or "").strip()
    paypal = (config["paypal_handle"] or "").strip()

    total = float(self.total)
    method = self.payment_method.lower()

    if method == "venmo" and venmo:
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

    confirm_embed = discord.Embed(
        title="Order Confirmed. Please complete your payment",
        description=(
            f"**Order ID:** {order_id}\n"
            f"**Total Due:** ${total:.2f}\n"
            f"**Payment Method:** {self.payment_method.capitalize()}\n\n"
            f"{label}:\n{link}"
        ),
        color=discord.Color.green()
    )

    await interaction.followup.send(embed=confirm_embed, ephemeral=True)


@discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):

    self.stop()

    self.message = interaction.message

    async with self.bot.db.acquire() as conn:
        for i in self.items:
            await conn.execute(
                """
                UPDATE inventory
                SET quantity_available = quantity_available + $2
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
class FinalizeOrderView(discord.ui.View):
    def __init__(
        self, bot, user_id, items,
        subtotal, tax, shipping_cost, shipping_label,
        payment_method, name, address
    ):
        super().__init__(timeout=900)
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

        if payment_method == "paypal":
            paypal_fee = round(self.total_before_shipping * 0.04, 2)
        else:
            paypal_fee = 0

        self.total = round(self.total_before_shipping + shipping_cost + paypal_fee, 2)
        self.paypal_fee = paypal_fee

        self.message = None

    async def on_timeout(self):
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

        for child in self.children:
            child.disabled = True

        if self.message:
            try:
                await self.message.edit(
                    content="⏰ **Order timed out** — items were released.",
                    view=self
                )
            except:
                pass

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

    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):

        self.stop()

        self.message = interaction.message
        button.disabled = True
        self.children[1].disabled = True

        if interaction.response.is_done():
            await interaction.followup.edit_message(view=self)
        else:
            await interaction.response.edit_message(view=self)

        config = await get_guild_payment_config(self.bot, interaction.guild_id)
        admin_id = config["admin_id"]

        # ============================================================
        # UPDATED: buyer_name + shipping_address now passed to create_order
        # ============================================================
        order_id = await interaction.client.get_cog("MyOrders").create_order(
            interaction,
            self.user_id,
            self.items,
            self.subtotal,
            self.tax,
            self.paypal_fee,
            self.shipping_cost,
            self.total,
            self.payment_method,
            self.shipping_label,
            self.name,
            self.address,
            admin_id
        )

        #
        # ⭐ DM ADMIN — New Order Placed
        #
        try:
            admin = await self.bot.fetch_user(admin_id)

            item_lines = []
            for item in self.items:
                item_lines.append(
                    f"• {item['pokemon_name']} — {item['series']} / {item['set_name']} "
                    f"({item.get('condition', 'N/A')}) x{item['quantity']} @ ${item['price']:.2f}"
                )
            items_text = "\n".join(item_lines)

            admin_embed = discord.Embed(
                title=f"🛒 New Order Placed — #{order_id}",
                description=(
                    f"A new order has been placed.\n\n"
                    f"**Buyer:** <@{self.user_id}>\n"
                    f"**Shipping Method:** {self.shipping_label}\n\n"
                    f"**Items:**\n{items_text}\n\n"
                    f"To manage this order (mark as **Paid**, **Shipped**, enter **Tracking**, cancel, etc.), "
                    f"use the command:\n"
                    f"**/admin manage_orders**\n\n"
                    f"All actions must be done using the admin command. This DM is informational only."
                ),
                color=discord.Color.blue()
            )

            await admin.send(embed=admin_embed)

        except Exception as e:
            print("ADMIN DM ERROR:", e)

        #
        # Delete cart items
        #
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                "DELETE FROM cart_items WHERE user_id = $1;",
                self.user_id
            )

        #
        # Payment link generation
        #
        async with self.bot.db.acquire() as conn:
            config = await conn.fetchrow(
                """
                SELECT venmo_handle, cashapp_handle, paypal_handle
                FROM guild_settings
                WHERE guild_id = $1;
                """,
                interaction.guild_id
            )

        venmo = (config["venmo_handle"] or "").strip().lstrip("@")
        cashapp = (config["cashapp_handle"] or "").strip()
        paypal = (config["paypal_handle"] or "").strip()

        total = float(self.total)
        method = self.payment_method.lower()

        if method == "venmo" and venmo:
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

        #
        # ⭐ UPDATED — Add bold admin notification message under payment link
        #
        confirm_embed = discord.Embed(
            title="Order Confirmed. Please complete your payment",
            description=(
                f"**Order ID:** {order_id}\n"
                f"**Total Due:** ${total:.2f}\n"
                f"**Payment Method:** {self.payment_method.capitalize()}\n\n"
                f"{label}:\n{link}\n\n"
                f"**A message has been sent to the admin letting them know you placed an order. "
                f"Once you pay for the order, the admin must confirm payment. If you do not get a notification that your order was marked as paid after a few days, "
                f"please reach out to the admin.You can check your order status anytime by running /myorders**"
            ),
            color=discord.Color.green()
        )

        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

        #
        # ⭐ NEW — After sending the payment link, update quantity_available -= quantity
        #
        async with self.bot.db.acquire() as conn:
            for item in self.items:
                await conn.execute(
                    """
                    UPDATE inventory
                    SET quantity_available = quantity_available - $2
                    WHERE inventory_id = $1;
                    """,
                    item["inventory_id"],
                    item["quantity"]
                )

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):

        self.stop()

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

