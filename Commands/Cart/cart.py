import discord
from discord.ext import commands
from discord import app_commands
from Commands.Admin.rewards_evaluator import (
    fetch_active_rewards,
    reward_is_eligible,
    apply_reward_action,
    track_reward_usage,
    apply_rewards
)

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

    @app_commands.command(name="cart", description="View your shopping cart.")
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
            f"**Total (est, before shipping):** "
            f"${round(subtotal + tax + paypal_fee, 2):.2f}\n"
            f"_Final total shown at checkout based on chosen shipping and payment method._\n"
        )

        embed.description = desc
        return embed

class CartView(discord.ui.View):
    def __init__(self, bot, user_id, pages):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.pages = pages
        self.page_index = 0

        # Core controls
        self.add_item(RemoveItemSelect(bot, user_id, pages[0]))
        self.add_item(ClearCartButton(bot, user_id))
        self.add_item(CheckoutButton(bot, user_id, self))

        # Pagination
        if len(pages) > 1:
            self.add_item(PrevPageButton(self))
            self.add_item(NextPageButton(self))


class PrevPageButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="Previous Page", style=discord.ButtonStyle.secondary)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.page_index > 0:
            self.parent_view.page_index -= 1

        items = self.parent_view.pages[self.parent_view.page_index]
        embed = self.parent_view.bot.get_cog("Cart").build_page_embed(
            items,
            self.parent_view.page_index + 1,
            len(self.parent_view.pages)
        )

        # Rebuild remove select for current page
        self.parent_view.clear_items()
        self.parent_view.add_item(
            RemoveItemSelect(self.parent_view.bot, self.parent_view.user_id, items)
        )
        self.parent_view.add_item(ClearCartButton(self.parent_view.bot, self.parent_view.user_id))
        self.parent_view.add_item(CheckoutButton(self.parent_view.bot, self.parent_view.user_id, self.parent_view))
        if len(self.parent_view.pages) > 1:
            self.parent_view.add_item(PrevPageButton(self.parent_view))
            self.parent_view.add_item(NextPageButton(self.parent_view))

        await interaction.response.edit_message(embed=embed, view=self.parent_view)


class NextPageButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="Next Page", style=discord.ButtonStyle.primary)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.page_index < len(self.parent_view.pages) - 1:
            self.parent_view.page_index += 1

        items = self.parent_view.pages[self.parent_view.page_index]
        embed = self.parent_view.bot.get_cog("Cart").build_page_embed(
            items,
            self.parent_view.page_index + 1,
            len(self.parent_view.pages)
        )

        # Rebuild remove select for current page
        self.parent_view.clear_items()
        self.parent_view.add_item(
            RemoveItemSelect(self.parent_view.bot, self.parent_view.user_id, items)
        )
        self.parent_view.add_item(ClearCartButton(self.parent_view.bot, self.parent_view.user_id))
        self.parent_view.add_item(CheckoutButton(self.parent_view.bot, self.parent_view.user_id, self.parent_view))
        if len(self.parent_view.pages) > 1:
            self.parent_view.add_item(PrevPageButton(self.parent_view))
            self.parent_view.add_item(NextPageButton(self.parent_view))

        await interaction.response.edit_message(embed=embed, view=self.parent_view)


class CheckoutButton(discord.ui.Button):
    def __init__(self, bot, user_id, parent_view):
        super().__init__(label="Checkout", style=discord.ButtonStyle.success)
        self.bot = bot
        self.user_id = user_id
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        start_view = CheckoutStartView(self.bot, self.user_id)
        ok = await start_view.async_init(interaction)
        if not ok:
            return

        embed = discord.Embed(
            title="Checkout — Step 1",
            description="Select your shipping and payment method to continue.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=start_view)


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


async def get_user_level(bot, user_id, guild_id):
    async with bot.db.acquire() as conn:
        lvl = await conn.fetchval(
            "SELECT level FROM users WHERE user_id = $1 AND guild_id = $2",
            user_id,
            guild_id
        )
    return lvl or 0
async def process_checkout(
    bot,
    interaction,
    user_id,
    shipping_method,
    payment_method,
    full_name,
    street,
    city,
    state,
    zip
):
    # -----------------------------
    # SHIPPING COST
    # -----------------------------
    if shipping_method == "pwe":
        shipping_cost = 1.50
        shipping_label = "Plain White Envelope (Not refunded if lost)"
    else:
        shipping_cost = 4.95
        shipping_label = "Tracked Shipping"

    # -----------------------------
    # FETCH CART ITEMS
    # -----------------------------
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

    # -----------------------------
    # CHECK AVAILABILITY
    # -----------------------------
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

    # -----------------------------
    # BASE MATH
    # -----------------------------
    subtotal = sum(i["price"] * i["quantity"] for i in items)
    tax = round(subtotal * 0.06, 2)
    total_before_shipping = subtotal + tax

    # -----------------------------
    # REWARD SYSTEM DISABLED HERE
    # (Manual reward buttons will handle discounts)
    # -----------------------------
    final_total = total_before_shipping
    discounted_shipping = shipping_cost
    applied_reward = None

    # -----------------------------
    # FINAL TOTAL BEFORE PAYMENT FEE
    # -----------------------------
    base_total_before_fee = final_total + discounted_shipping

    # -----------------------------
    # PAYPAL FEE
    # -----------------------------
    paypal_fee = round(base_total_before_fee * 0.04, 2) if payment_method == "paypal" else 0

    # -----------------------------
    # FINAL TOTAL
    # -----------------------------
    total = round(base_total_before_fee + paypal_fee, 2)

    # -----------------------------
    # ITEM LIST
    # -----------------------------
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

    # -----------------------------
    # EMBED
    # -----------------------------
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

    reward_text = applied_reward["name"] if applied_reward else "None"

    embed.add_field(
        name="🚚 Payment & Shipping Information",
        value=(
            f"**Shipping:** {shipping_label}\n"
            f"**Payment Method:** {payment_method.capitalize()}\n\n"
            f"**Subtotal:** ${subtotal:.2f}\n"
            f"**Tax:** ${tax:.2f}\n"
            f"**Reward Applied:** {reward_text}\n"
            f"**Shipping After Reward:** ${discounted_shipping:.2f}\n"
            f"**PayPal Fee:** ${paypal_fee:.2f}\n"
            f"**Total:** ${total:.2f}"
        ),
        inline=False
    )

    # -----------------------------
    # FINALIZE VIEW
    # -----------------------------
    view = FinalizeOrderView(
        bot,
        user_id,
        items,
        subtotal,
        tax,
        discounted_shipping,
        shipping_label,
        payment_method,
        full_name,
        f"{street}\n{city}, {state} {zip}"
    )

    view.applied_reward = applied_reward
    view.discounted_total = total

    # -----------------------------
    # REWARD BUTTONS
    # -----------------------------
    reward_view = RewardApplyView(
        bot,
        user_id,
        subtotal,
        tax,
        discounted_shipping,
        payment_method,
        view
    )

    has_rewards = await reward_view.async_init(interaction.guild.id)

    if has_rewards:
        combined_view = discord.ui.View(timeout=900)

        # Add reward buttons first
        for item in reward_view.children:
            combined_view.add_item(item)

        # Add checkout buttons
        for item in view.children:
            combined_view.add_item(item)

        final_view = combined_view
    else:
        final_view = view

    await interaction.response.send_message(embed=embed, view=final_view, ephemeral=True)


# =====================================================================
# CHECKOUT START VIEW
# =====================================================================
# =====================================================================
# CHECKOUT START VIEW
# =====================================================================
class CheckoutStartView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id

        self.shipping_method = None
        self.payment_method = None

        # SHIPPING SELECT
        self.shipping_select = discord.ui.Select(
            placeholder="Select Shipping Method",
            options=[
                discord.SelectOption(label="PWE ($1.50)", value="pwe"),
                discord.SelectOption(label="Tracked ($4.95)", value="tracked")
            ]
        )
        self.shipping_select.callback = self.shipping_callback
        self.add_item(self.shipping_select)

        # PAYMENT SELECT (added in async_init)
        self.payment_select = None

    async def async_init(self, interaction):
        guild_id = interaction.guild_id or interaction.user.guild.id

        config = await get_guild_payment_config(self.bot, guild_id)
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
                description=f"Payment options have not been configured for this guild.\nPlease contact <@{admin_id}>.",
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

        return True

    async def shipping_callback(self, interaction: discord.Interaction):
        self.shipping_method = self.shipping_select.values[0]
        await interaction.response.defer()

    async def payment_callback(self, interaction: discord.Interaction):
        self.payment_method = self.payment_select.values[0]
        await interaction.response.defer()

    # =====================================================================
    # CONTINUE → MANUAL ADDRESS ENTRY (CheckoutModal)
    # =====================================================================
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

    # =====================================================================
    # USE SAVED ADDRESS BUTTON (RESTORED)
    # =====================================================================
    @discord.ui.button(label="Use Saved Shipping Address", style=discord.ButtonStyle.primary)
    async def use_saved_btn(self, interaction: discord.Interaction, button):
        guild_id = interaction.guild_id or interaction.user.guild.id

        async with self.bot.db.acquire() as conn:
            saved = await conn.fetchrow(
                """
                SELECT full_name, street_address, city, state, zip
                FROM user_shipping_info
                WHERE user_id = $1 AND guild_id = $2;
                """,
                self.user_id,
                guild_id
            )

        if not saved:
            embed = discord.Embed(
                title="No Saved Address",
                description="You do not have a saved shipping address.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Call checkout using saved address
        await process_checkout(
            self.bot,
            interaction,
            self.user_id,
            self.shipping_method,
            self.payment_method,
            saved["full_name"],
            saved["street_address"],
            saved["city"],
            saved["state"],
            saved["zip"]
        )


# =====================================================================
# CHECKOUT MODAL — VERSION C (Address + Shipping + Payment Confirmation)
# =====================================================================
class CheckoutModal(discord.ui.Modal, title="Enter Shipping Information"):
    full_name = discord.ui.TextInput(label="Full Name", required=True)
    street = discord.ui.TextInput(label="Street Address", required=True)
    city = discord.ui.TextInput(label="City", required=True)
    state = discord.ui.TextInput(label="State", required=True)
    zip = discord.ui.TextInput(label="ZIP Code", required=True)

    def __init__(self, bot, user_id, shipping_method, payment_method):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.shipping_method = shipping_method
        self.payment_method = payment_method

    async def on_submit(self, interaction: discord.Interaction):
        await process_checkout(
            self.bot,
            interaction,
            self.user_id,
            self.shipping_method,
            self.payment_method,
            self.full_name.value,
            self.street.value,
            self.city.value,
            self.state.value,
            self.zip.value
        )


# =====================================================================
# CHECKOUT MODAL — VERSION C (Address + Shipping + Payment Confirmation)
# =====================================================================
class CheckoutModal(discord.ui.Modal, title="Enter Shipping Information"):
    full_name = discord.ui.TextInput(label="Full Name", required=True)
    street = discord.ui.TextInput(label="Street Address", required=True)
    city = discord.ui.TextInput(label="City", required=True)
    state = discord.ui.TextInput(label="State", required=True)
    zip = discord.ui.TextInput(label="ZIP Code", required=True)

    def __init__(self, bot, user_id, shipping_method, payment_method):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.shipping_method = shipping_method
        self.payment_method = payment_method

    async def on_submit(self, interaction: discord.Interaction):
        await process_checkout(
            self.bot,
            interaction,
            self.user_id,
            self.shipping_method,
            self.payment_method,
            self.full_name.value,
            self.street.value,
            self.city.value,
            self.state.value,
            self.zip.value
        )
# =====================================================================
# REWARD APPLY VIEW
# =====================================================================
class RewardApplyView(discord.ui.View):
    def __init__(self, bot, user_id, subtotal, tax, shipping_cost, payment_method, finalize_view):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id

        # Store original values for display
        self.original_subtotal = subtotal
        self.original_tax = tax
        self.original_shipping = shipping_cost

        # Working values (may be discounted)
        self.subtotal = subtotal
        self.tax = tax
        self.shipping_cost = shipping_cost
        self.payment_method = payment_method
        self.finalize_view = finalize_view

        self.selected_reward = None
        self.discounted_total = subtotal + tax
        self.discounted_shipping = shipping_cost
        self.applied_reward = None

    async def async_init(self, guild_id):
        user_level = await get_user_level(self.bot, self.user_id, guild_id)
        rewards = await fetch_active_rewards(self.bot.db, guild_id)

        eligible = []
        for r in rewards:
            ok = await reward_is_eligible(
                self.bot.db,
                r,
                self.user_id,
                guild_id,
                user_level,
                self.original_subtotal + self.original_tax
            )
            if ok:

                if r["category"] == "limited_use":
                    async with self.bot.db.acquire() as conn:
                        row = await conn.fetchrow(
                            """
                            SELECT times_used
                            FROM user_rewards
                            WHERE user_id = $1 AND guild_id = $2 AND reward_id = $3
                            """,
                            self.user_id,
                            guild_id,
                            r["reward_id"]
                        )

                    used = row["times_used"] if row else 0

                    r = dict(r)
                    r["remaining_uses"] = r["max_uses"] - used

                else:
                    r = dict(r)

                eligible.append(r)

        for reward in eligible:
            self.add_item(RewardButton(self.bot, reward, self))

        return len(eligible) > 0

    async def apply_selected_reward(self, interaction: discord.Interaction):
        # ---------------------------------------------------------
        # PREVENT REWARD STACKING
        # ---------------------------------------------------------
        if self.applied_reward is not None:
            embed = discord.Embed(
                title="Reward Already Applied",
                description=(
                    f"You already applied **{self.applied_reward['name']}**.\n\n"
                    "Only **one reward** can be used per order."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        reward = self.selected_reward
        if not reward:
            return

        reward = dict(reward)

        # ---------------------------------------------------------
        # APPLY THE SELECTED REWARD
        # ---------------------------------------------------------
        result = await apply_rewards(
            self.bot.db,
            interaction.guild_id,
            self.user_id,
            await get_user_level(self.bot, self.user_id, interaction.guild_id),
            self.subtotal + self.tax,
            self.shipping_cost,
            self.subtotal,
            reward
        )

        # result["final_total"] is discounted SUBTOTAL
        discounted_subtotal = result["final_total"]
        discounted_tax = round(discounted_subtotal * 0.06, 2)

        # Update working values
        self.subtotal = discounted_subtotal
        self.tax = discounted_tax
        self.discounted_shipping = result["final_shipping"]
        self.applied_reward = reward

        # ---------------------------------------------------------
        # DISABLE ALL OTHER REWARD BUTTONS
        # ---------------------------------------------------------
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        # ---------------------------------------------------------
        # UPDATE FINALIZE VIEW
        # ---------------------------------------------------------
        new_total_for_finalize = self.subtotal + self.tax + self.discounted_shipping
        self.finalize_view.applied_reward = reward
        self.finalize_view.discounted_total = new_total_for_finalize
        self.finalize_view.shipping_cost = self.discounted_shipping

        embed = self.build_updated_embed()

        await interaction.response.edit_message(
            embed=embed,
            view=self.finalize_view
        )

    async def restore_if_applied(self):
        if self.applied_reward:
            reward = dict(self.applied_reward)
            await restore_reward_usage(self.bot.db, reward, self.user_id)

    def build_updated_embed(self):
        original_total = self.original_subtotal + self.original_tax + self.original_shipping
        new_total = self.subtotal + self.tax + self.discounted_shipping

        embed = discord.Embed(
            title="Reward Applied",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Original Breakdown",
            value=(
                f"Subtotal: ${self.original_subtotal:.2f}\n"
                f"Tax: ${self.original_tax:.2f}\n"
                f"Shipping: ${self.original_shipping:.2f}\n"
                f"**Original Total: ${original_total:.2f}**"
            ),
            inline=False
        )

        if self.applied_reward:
            r = self.applied_reward
            r_type = r["type"]
            val = r["value"]

            if r_type == "percent_off":
                reward_text = f"{val}% off"
            elif r_type == "flat_off":
                reward_text = f"${val} off"
            elif r_type == "free_shipping":
                reward_text = "Free Shipping"
            else:
                reward_text = r["name"]

            embed.add_field(
                name="Applied Reward",
                value=reward_text,
                inline=False
            )

        embed.add_field(
            name="New Breakdown",
            value=(
                f"Subtotal: ${self.subtotal:.2f}\n"
                f"Tax: ${self.tax:.2f}\n"
                f"Shipping: ${self.discounted_shipping:.2f}\n"
                f"**New Total: ${new_total:.2f}**"
            ),
            inline=False
        )

        return embed

# =====================================================================
# REWARD BUTTON
# =====================================================================
class RewardButton(discord.ui.Button):
    def __init__(self, bot, reward, parent_view):
        label = self.format_label(reward)
        super().__init__(label=label, style=discord.ButtonStyle.primary)

        self.bot = bot
        self.reward = reward
        self.parent_view = parent_view

    @staticmethod
    def format_label(reward):
        r_type = reward["type"]
        value = reward["value"]

        # ⭐ Correct limited_use formatting
        if reward["category"] == "limited_use":
            remaining = reward.get("remaining_uses")

            # Build base label depending on reward type
            if r_type == "percent_off":
                base = f"Apply {value}% off"
            elif r_type == "flat_off":
                base = f"Apply ${value} off"
            elif r_type == "free_shipping":
                base = "Apply Free Shipping"
            else:
                base = f"Apply {reward['name']}"

            # Append remaining uses
            if remaining is not None:
                return f"{base} — {remaining} use(s) left"

            return base

        # Normal reward types
        if r_type == "percent_off":
            return f"Apply {value}% off"

        if r_type == "flat_off":
            return f"Apply ${value} off"

        if r_type == "free_shipping":
            return "Apply Free Shipping"

        return f"Apply {reward['name']}"

    async def callback(self, interaction: discord.Interaction):
        # Store selected reward
        self.parent_view.selected_reward = self.reward

        # Apply reward and return to FinalizeOrderView
        await self.parent_view.apply_selected_reward(interaction)
# =====================================================================
# FINALIZE ORDER VIEW
# =====================================================================
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

        self.applied_reward = None
        self.message = None

        # Buttons
        self.add_item(ConfirmOrderButton(self))
        self.add_item(CancelOrderButton(self))


class ConfirmOrderButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="Confirm Order",
            style=discord.ButtonStyle.success
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        view = self.parent_view
        guild_id = interaction.guild_id
        user_id = view.user_id

        # -----------------------------
        # FEE (PayPal only)
        # -----------------------------
        if view.payment_method == "paypal":
            fee = round((view.subtotal + view.tax) * 0.04, 2)
        else:
            fee = 0

        async with view.bot.db.acquire() as conn:

            # -----------------------------
            # CREATE ORDER (FIXED + RESTORED)
            # -----------------------------
            order_row = await conn.fetchrow(
                """
                INSERT INTO orders (
                    user_id,
                    guild_id,
                    subtotal,
                    tax,
                    fee,
                    shipping_fee,
                    total,
                    payment_method,
                    shipping_method,
                    buyer_name,
                    shipping_address,
                    applied_reward,
                    order_status,
                    created_at
                )
                VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'Unpaid',NOW()
                )
                RETURNING order_id;
                """,
                user_id,
                guild_id,
                view.subtotal,
                view.tax,
                fee,
                view.shipping_cost,
                view.total,
                view.payment_method,
                view.shipping_label,
                view.name,
                view.address,
                view.applied_reward["name"] if view.applied_reward else None
            )

            order_id = order_row["order_id"]

            # -----------------------------
            # INSERT ORDER ITEMS
            # -----------------------------
            for item in view.items:
                await conn.execute(
                    """
                    INSERT INTO order_items (
                        order_id, inventory_id, quantity, price_each
                    )
                    VALUES ($1,$2,$3,$4);
                    """,
                    order_id,
                    item["inventory_id"],
                    item["quantity"],
                    item["price"]
                )

                await conn.execute(
                    """
                    UPDATE inventory
                    SET quantity_available = quantity_available - $2
                    WHERE inventory_id = $1;
                    """,
                    item["inventory_id"],
                    item["quantity"]
                )

            # -----------------------------
            # CLEAR CART
            # -----------------------------
            await conn.execute(
                "DELETE FROM cart_items WHERE user_id = $1;",
                user_id
            )

        # -----------------------------
        # PAYMENT LINK RESTORED
        # -----------------------------
        async with view.bot.db.acquire() as conn:
            config = await conn.fetchrow(
                """
                SELECT venmo_handle, cashapp_handle, paypal_handle, admin_id
                FROM guild_settings
                WHERE guild_id = $1;
                """,
                guild_id
            )

        venmo = (config["venmo_handle"] or "").strip().lstrip("@")
        cashapp = (config["cashapp_handle"] or "").strip()
        paypal = (config["paypal_handle"] or "").strip()
        admin_id = config["admin_id"]

        total = float(view.total)
        method = view.payment_method.lower()

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

        # -----------------------------
        # DM ADMIN RESTORED
        # -----------------------------
        try:
            admin_user = await view.bot.fetch_user(admin_id)
            await admin_user.send(
                embed=discord.Embed(
                    title=f"New Order #{order_id}",
                    description=(
                        f"**Buyer:** {view.name}\n"
                        f"**Address:**\n{view.address}\n\n"
                        f"**Payment:** {view.payment_method.capitalize()}\n"
                        f"**Shipping:** {view.shipping_label}\n"
                        f"**Total:** ${total:.2f}\n\n"
                        f"**Items:**\n" +
                        "\n".join(
                            f"• {i['pokemon_name']} — x{i['quantity']}"
                            for i in sorted(view.items, key=lambda x: x["pokemon_name"].lower())
                        ) +
                        "\n\nUse **/admin manage_orders** to mark Paid, Shipped, add Tracking, etc."
                    ),
                    color=discord.Color.blue()
                )
            )
        except Exception:
            pass

        # -----------------------------
        # CONFIRMATION EMBED (RESTORED)
        # -----------------------------
        embed = discord.Embed(
            title="Order Created",
            description=(
                f"Your order has been created!\n"
                f"**Order ID:** {order_id}\n\n"
                f"{label}:\n{link}"
            ),
            color=discord.Color.green()
        )

        await interaction.response.edit_message(embed=embed, view=None)


class CancelOrderButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="Cancel",
            style=discord.ButtonStyle.danger
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        # ==============================
        # RESTORE REWARD USAGE IF APPLIED
        # ==============================
        reward = getattr(self.parent_view, "applied_reward", None)

        if reward:
            reward_id = reward["reward_id"]
            user_id = self.parent_view.user_id
            guild_id = interaction.guild_id

            async with self.parent_view.bot.db.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE user_rewards
                    SET times_used = GREATEST(times_used - 1, 0)
                    WHERE user_id = $1
                      AND guild_id = $2
                      AND reward_id = $3;
                    """,
                    user_id,
                    guild_id,
                    reward_id
                )

        # ==============================
        # CANCEL CHECKOUT MESSAGE
        # ==============================
        embed = discord.Embed(
            title="Checkout Cancelled",
            description="You cancelled checkout.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

# =====================================================================
# REWARD USAGE RESTORE HELPER
# =====================================================================
async def restore_reward_usage(db, reward, user_id):
    """
    Decrements usage for limited_use rewards when an order is cancelled or refunded.
    Ensures times_used never goes below zero.
    Uses new tables: guild_rewards + user_rewards.
    """
    # Only limited_use rewards track usage
    if reward.get("category") != "limited_use":
        return

    reward_id = reward["reward_id"]
    guild_id = reward["guild_id"]

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE user_rewards
            SET times_used = GREATEST(times_used - 1, 0)
            WHERE user_id = $1 AND guild_id = $2 AND reward_id = $3
            """,
            user_id,
            guild_id,
            reward_id
        )


# =====================================================================
# COG SETUP
# =====================================================================
async def setup(bot):
    await bot.add_cog(Cart(bot))




