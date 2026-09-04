import asyncio
import datetime
from typing import Dict, Set, List

import discord
from discord.ext import commands, tasks
import pytz


# ============================================================
# CLAIM SALE CARD VIEW
# ============================================================
class ClaimSaleCardView(discord.ui.View):
    def __init__(self, bot, sale_row, card_row, index, total, claimed_users, order_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.sale_row = sale_row
        self.card_row = card_row
        self.index = index
        self.total = total
        self.claimed = False
        self.highest_declined_offer = None
        self.claimed_users = claimed_users
        self.order_id = order_id
        self.message = None

        self.claim_btn = discord.ui.Button(label="Claim", style=discord.ButtonStyle.success)
        self.offer_btn = discord.ui.Button(label="Make Offer", style=discord.ButtonStyle.primary)

        self.claim_btn.callback = self.claim
        self.offer_btn.callback = self.make_offer

        self.add_item(self.claim_btn)
        self.add_item(self.offer_btn)

    async def claim(self, interaction: discord.Interaction):
        if self.claimed:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Already Claimed",
                    description="This card has already been claimed.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        self.claimed = True
        inventory_id = self.card_row["inventory_id"]
        user_id = interaction.user.id
        sale_id = self.sale_row["claim_sale_id"]
        guild_id = self.sale_row["guild_id"]

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO claim_sale_orders (
                    sale_id, user_id, inventory_id,
                    pokemon_name, condition, series, set_name,
                    quantity, original_price, sold_price, method,
                    created_at, guild_id, order_id
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,1,$8,$9,'claim',NOW(),$10,NULL)
                """,
                sale_id,
                user_id,
                inventory_id,
                self.card_row["pokemon_name"],
                self.card_row["condition"],
                self.card_row["series"],
                self.card_row["set_name"],
                self.card_row["price"],
                self.card_row["price"],
                guild_id
            )

            await conn.execute(
                """
                UPDATE inventory
                SET quantity_available = quantity_available - 1
                WHERE inventory_id = $1
                """,
                inventory_id
            )

        self.claimed_users.add(user_id)

        self.disable_all()
        if self.message:
            await self.message.edit(view=self)

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Card Claimed",
                description="You claimed this card in the claim sale.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

    async def make_offer(self, interaction: discord.Interaction):
        class OfferModal(discord.ui.Modal, title="Make an Offer"):
            offer_input = discord.ui.TextInput(
                label="Offer Amount (USD)",
                placeholder="e.g. 25",
                required=True
            )

            def __init__(self, parent_view):
                super().__init__()
                self.parent_view = parent_view

            async def on_submit(self, inner_interaction):

                # Card already claimed (claim or accepted offer)
                if self.parent_view.claimed:
                    await inner_interaction.response.send_message(
                        embed=discord.Embed(
                            title="Card Already Claimed",
                            description="This card has already been claimed. Your offer cannot be submitted.",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )
                    return

                # Buttons disabled (admin accepted offer)
                for item in self.parent_view.children:
                    if item.disabled:
                        await inner_interaction.response.send_message(
                            embed=discord.Embed(
                                title="Offer Closed",
                                description="An offer has already been accepted for this card.",
                                color=discord.Color.red()
                            ),
                            ephemeral=True
                        )
                        return

                try:
                    amount = int(self.offer_input.value.strip())
                    if amount <= 0:
                        raise ValueError
                except ValueError:
                    await inner_interaction.response.send_message(
                        embed=discord.Embed(
                            title="Invalid Amount",
                            description="Please enter a valid positive number.",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )
                    return

                if self.parent_view.highest_declined_offer is not None:
                    if amount <= self.parent_view.highest_declined_offer:
                        await inner_interaction.response.send_message(
                            embed=discord.Embed(
                                title="Offer Too Low",
                                description=f"Your offer must be higher than ${self.parent_view.highest_declined_offer}.",
                                color=discord.Color.red()
                            ),
                            ephemeral=True
                        )
                        return

                await self.parent_view.send_offer_to_admin(inner_interaction, amount)

        await interaction.response.send_modal(OfferModal(self))

    async def send_offer_to_admin(self, interaction, offer_amount):
        admin_id = self.sale_row["admin_id"]
        guild = self.bot.get_guild(self.sale_row["guild_id"])
        channel = guild.get_channel(self.sale_row["claim_sale_channel_id"])

        embed = discord.Embed(
            title="New Offer Submitted",
            description=f"Offer submitted for **{self.card_row['pokemon_name']}**",
            color=discord.Color.blue()
        )
        embed.add_field(name="Offer Amount", value=f"${offer_amount}", inline=False)
        embed.add_field(name="Offered By", value=f"<@{interaction.user.id}>", inline=False)
        embed.add_field(name="Inventory ID", value=str(self.card_row["inventory_id"]), inline=False)

        admin_view = self.build_admin_offer_view(offer_amount, interaction.user.id)

        await channel.send(
            content=f"<@{admin_id}>",
            embed=embed,
            view=admin_view
        )

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Offer Submitted",
                description=f"Your offer of **${offer_amount}** has been sent to the admin.",
                color=discord.Color.blue()
            ),
            ephemeral=True
        )

    def build_admin_offer_view(self, offer_amount, offer_user_id):
        bot = self.bot
        inventory_id = self.card_row["inventory_id"]
        sale_id = self.sale_row["claim_sale_id"]
        admin_id = self.sale_row["admin_id"]
        guild_id = self.sale_row["guild_id"]

        class OfferAdminView(discord.ui.View):
            def __init__(self, parent_view):
                super().__init__(timeout=None)
                self.parent_view = parent_view
                self.admin_id = admin_id

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                if interaction.user.id != self.admin_id:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Admin Only",
                            description="Only the admin can accept or decline offers.",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )
                    return False
                return True

            @discord.ui.button(label="Accept Offer", style=discord.ButtonStyle.success)
            async def accept_offer(self, interaction: discord.Interaction, button: discord.ui.Button):

                if interaction.user.id != self.admin_id:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Admin Only",
                            description="Only the admin can accept offers.",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )
                    return

                # Card already claimed before admin tried to accept
                if self.parent_view.claimed:
                    # Notify admin
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Cannot Accept Offer",
                            description="This card was already claimed. The offer cannot be accepted.",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )

                    # Notify offer user
                    user = await bot.fetch_user(offer_user_id)
                    if user:
                        try:
                            await user.send(
                                embed=discord.Embed(
                                    title="Offer Not Accepted",
                                    description=(
                                        "Someone claimed this card before your offer was accepted.\n\n"
                                        "Claims take priority over offers."
                                    ),
                                    color=discord.Color.red()
                                )
                            )
                        except Exception as e:
                            print(f"[CLAIM SALE][WARN] DM to user {offer_user_id} failed: {e}")

                    return

                self.parent_view.claimed = True

                async with bot.db.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO claim_sale_orders (
                            sale_id, user_id, inventory_id,
                            pokemon_name, condition, series, set_name,
                            quantity, original_price, sold_price, method,
                            created_at, guild_id, order_id
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7,1,$8,$9,'offer',NOW(),$10,NULL)
                        """,
                        sale_id,
                        offer_user_id,
                        inventory_id,
                        self.parent_view.card_row["pokemon_name"],
                        self.parent_view.card_row["condition"],
                        self.parent_view.card_row["series"],
                        self.parent_view.card_row["set_name"],
                        self.parent_view.card_row["price"],
                        offer_amount,
                        guild_id
                    )

                self.parent_view.disable_all()
                if self.parent_view.message:
                    await self.parent_view.message.edit(view=self.parent_view)

                user = await bot.fetch_user(offer_user_id)
                if user:
                    await user.send(
                        embed=discord.Embed(
                            title="Offer Accepted",
                            description="Your offer was accepted and the item was placed in your claim sale order.",
                            color=discord.Color.green()
                        )
                    )

                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Offer Accepted",
                        description=f"Offer of **${offer_amount}** accepted.",
                        color=discord.Color.green()
                    ),
                    ephemeral=True
                )

            @discord.ui.button(label="Decline Offer", style=discord.ButtonStyle.danger)
            async def decline_offer(self, interaction: discord.Interaction, button: discord.ui.Button):

                if interaction.user.id != self.admin_id:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Admin Only",
                            description="Only the admin can decline offers.",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )
                    return

                if (
                    self.parent_view.highest_declined_offer is None
                    or offer_amount > self.parent_view.highest_declined_offer
                ):
                    self.parent_view.highest_declined_offer = offer_amount

                user = await bot.fetch_user(offer_user_id)
                if user:
                    try:
                        await user.send(
                            embed=discord.Embed(
                                title="Offer Declined",
                                description=(
                                    f"Your offer of **${offer_amount}** for "
                                    f"**{self.parent_view.card_row['pokemon_name']}** was declined."
                                ),
                                color=discord.Color.red()
                            )
                        )
                    except Exception as e:
                        print(f"[CLAIM SALE][WARN] DM to user {offer_user_id} failed: {e}")

                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Offer Declined",
                        description=f"Offer of **${offer_amount}** was declined.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )

        return OfferAdminView(self)

    def disable_all(self):
        for item in self.children:
            item.disabled = True

    async def on_message(self, message: discord.Message):
        self.message = message

# ============================================================
# CLAIM SALE RUNTIME
# ============================================================
class ClaimSaleRuntime(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.est = pytz.timezone("America/New_York")

        self.pending_sales: Dict[int, Dict] = {}
        self.claimed_users_by_guild: Dict[int, Set[int]] = {}

        self.claim_sale_task = self.check_claim_sales

    # ============================================================
    # ENSURE LOOP STARTS ON READY (Railway sometimes misses this)
    # ============================================================
    @commands.Cog.listener()
    async def on_ready(self):
        try:
            if not self.claim_sale_task.is_running():
                print("[CLAIM SALE] Starting claim sale task loop...", flush=True)
                self.claim_sale_task.start()
        except Exception as e:
            print("[CLAIM SALE][ERROR] Failed to start loop on_ready:", e, flush=True)

    # ============================================================
    # ENSURE LOOP RESTARTS AFTER DISCORD RECONNECT (Railway issue)
    # ============================================================
    @commands.Cog.listener()
    async def on_resumed(self):
        try:
            if not self.claim_sale_task.is_running():
                print("[CLAIM SALE] Resumed — restarting claim sale loop...", flush=True)
                self.claim_sale_task.start()
        except Exception as e:
            print("[CLAIM SALE][ERROR] Failed to restart loop on_resumed:", e, flush=True)

    # ============================================================
    # MAIN CLAIM SALE LOOP
    # ============================================================
    @tasks.loop(minutes=1)
    async def check_claim_sales(self):
        try:
            now = datetime.datetime.now(self.est)
            print(f"[CLAIM SALE LOOP] Tick at {now}", flush=True)

            async with self.bot.db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT *
                    FROM claim_sales
                    WHERE is_ran = FALSE
                    """
                )

            for sale in rows:
                sale_id = sale["claim_sale_id"]

                naive_dt = datetime.datetime.combine(
                    sale["sale_date"],
                    sale["sale_time"]
                )
                start_dt = self.est.localize(naive_dt)
                delta = start_dt - now
                print(f"[CLAIM SALE] sale_id={sale_id} start={start_dt} delta={delta}", flush=True)

                if sale_id not in self.pending_sales:
                    self.pending_sales[sale_id] = {
                        "start_dt": start_dt,
                        "one_hour_sent": False,
                        "ten_min_sent": False,
                        "started": False
                    }

                cached = self.pending_sales[sale_id]

                if cached["start_dt"] != start_dt:
                    cached["start_dt"] = start_dt
                    cached["one_hour_sent"] = False
                    cached["ten_min_sent"] = False
                    cached["started"] = False

                if datetime.timedelta(minutes=0) < delta <= datetime.timedelta(hours=1):
                    if not cached["one_hour_sent"]:
                        print(f"[CLAIM SALE] sending 1 hour warning for sale_id={sale_id}", flush=True)
                        await self.send_warning_embed(sale, start_dt, "1 hour")
                        cached["one_hour_sent"] = True

                if datetime.timedelta(minutes=0) < delta <= datetime.timedelta(minutes=10):
                    if not cached["ten_min_sent"]:
                        print(f"[CLAIM SALE] sending 10 minute warning for sale_id={sale_id}", flush=True)
                        await self.send_warning_embed(sale, start_dt, "10 minutes")
                        cached["ten_min_sent"] = True

                if delta <= datetime.timedelta(seconds=0):
                    if not cached["started"]:
                        print(f"[CLAIM SALE] starting claim sale sale_id={sale_id}", flush=True)
                        cached["started"] = True
                        await self.start_claim_sale(sale)

        except Exception as e:
            print("[CLAIM SALE LOOP ERROR]", e, flush=True)

    # ============================================================
    # WARNING EMBED
    # ============================================================
    async def send_warning_embed(self, sale_row, start_dt, window_label):
        guild = self.bot.get_guild(sale_row["guild_id"])
        if not guild:
            print(f"[WARN] Guild {sale_row['guild_id']} not found for warning embed", flush=True)
            return

        channel = guild.get_channel(sale_row["claim_sale_channel_id"])
        if not channel:
            print(f"[WARN] Channel {sale_row['claim_sale_channel_id']} not found for warning embed", flush=True)
            return

        number_of_cards = sale_row["number_of_cards"]
        min_price = sale_row["min_price_value"]
        max_price = sale_row["max_price_value"]

        conditions = sale_row["conditions"]
        if "All Conditions" in conditions:
            conditions_list = [
                "Near Mint",
                "Lightly Played",
                "Moderately Played",
                "Heavily Played",
                "Damaged"
            ]
        else:
            conditions_list = conditions

        embed = discord.Embed(
            title="Claim Sale Starting Soon",
            color=discord.Color.gold()
        )

        embed.add_field(
            name="Scheduled Start",
            value=start_dt.strftime("%B %d, %Y at %I:%M %p"),
            inline=False
        )

        embed.add_field(
            name="Time Remaining",
            value=f"Starts in **{window_label}**",
            inline=False
        )

        embed.add_field(
            name="Cards Included",
            value=f"{number_of_cards} cards ranging from **${min_price}** to **${max_price}**",
            inline=False
        )

        embed.add_field(
            name="Conditions Included",
            value=", ".join(conditions_list),
            inline=False
        )

        print(f"[CLAIM SALE] sending warning embed to channel {channel.id} for sale {sale_row['claim_sale_id']}", flush=True)

        try:
            await channel.send(embed=embed)
        except Exception as e:
            print("[CLAIM SALE][ERROR] Failed to send warning embed:", e, flush=True)

    # ============================================================
    # START CLAIM SALE
    # ============================================================
    async def start_claim_sale(self, sale_row):
        guild_id = sale_row["guild_id"]
        channel_id = sale_row["claim_sale_channel_id"]
        payment_hours = sale_row["payment_hours"]

        print(f"[CLAIM SALE] start_claim_sale() guild_id={guild_id} channel_id={channel_id} payment_hours={payment_hours}", flush=True)

        guild = self.bot.get_guild(guild_id)
        if not guild:
            print(f"[ERROR] Guild {guild_id} not found in start_claim_sale", flush=True)
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            print(f"[ERROR] Channel {channel_id} not found in start_claim_sale", flush=True)
            return

        async with self.bot.db.acquire() as conn:
            try:
                print("[CLAIM SALE] fetching inventory rows for sale", flush=True)

                if "All Conditions" in sale_row["conditions"]:
                    inv_rows = await conn.fetch(
                        """
                        SELECT *
                        FROM inventory
                        WHERE guild_id = $1
                          AND is_active = TRUE
                          AND quantity_available >= 1
                          AND ($2::int IS NULL OR price <= $2)
                        ORDER BY price ASC
                        """,
                        guild_id,
                        sale_row["max_price_value"],
                    )
                else:
                    inv_rows = await conn.fetch(
                        """
                        SELECT *
                        FROM inventory
                        WHERE guild_id = $1
                          AND is_active = TRUE
                          AND quantity_available >= 1
                          AND ($3::int IS NULL OR price <= $3)
                          AND condition = ANY($2::text[])
                        ORDER BY price ASC
                        """,
                        guild_id,
                        sale_row["conditions"],
                        sale_row["max_price_value"],
                    )
            except Exception as e:
                print(f"[CLAIM SALE][ERROR] inventory fetch failed: {e}", flush=True)
                raise


        expanded_rows = []
        for row in inv_rows:
            qty = row["quantity_available"]
            for _ in range(qty):
                expanded_rows.append(row)

        inv_rows = expanded_rows

        total = len(inv_rows)
        print(f"[CLAIM SALE] total inventory rows for sale: {total}")

        if total == 0:
            await channel.send("No matching cards found for this claim sale.")
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "UPDATE claim_sales SET is_ran = TRUE WHERE claim_sale_id = $1",
                    sale_row["claim_sale_id"]
                )
            return

        if guild_id not in self.claimed_users_by_guild:
            self.claimed_users_by_guild[guild_id] = set()
        claimed_users = self.claimed_users_by_guild[guild_id]

        placeholder_order_id = 0

        for idx, card in enumerate(inv_rows, start=1):
            embed = self.build_card_embed(card, idx, total)

            view = ClaimSaleCardView(
                self.bot,
                sale_row,
                card,
                idx,
                total,
                claimed_users,
                placeholder_order_id
            )

            print(f"[CLAIM SALE] posting card {idx}/{total} inventory_id={card['inventory_id']}")
            msg = await channel.send(embed=embed, view=view)
            await view.on_message(msg)

            await asyncio.sleep(30)

        print("[CLAIM SALE] sale finished — waiting 30 seconds before creating orders...")
        await asyncio.sleep(30)

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id,
                       inventory_id,
                       pokemon_name,
                       condition,
                       series,
                       set_name,
                       quantity,
                       sold_price
                FROM claim_sale_orders
                WHERE sale_id = $1
                ORDER BY user_id, pokemon_name;
                """,
                sale_row["claim_sale_id"]
            )

        users = {}
        if rows:
            for r in rows:
                r = dict(r)
                users.setdefault(r["user_id"], []).append(r)

            myorders_cog = self.bot.get_cog("MyOrders")

            # ⭐ admin_id MUST be fetched BEFORE DummyInteraction uses it
            async with self.bot.db.acquire() as conn:
                admin_id = await conn.fetchval(
                    "SELECT admin_id FROM guild_settings WHERE guild_id = $1",
                    guild_id
                )

            # ⭐ FIXED DummyInteraction — now valid
            DummyInteraction = type(
                "DummyInteraction",
                (),
                {
                    "client": self.bot,
                    "guild": self.bot.get_guild(guild_id),
                    "user": self.bot.get_guild(guild_id).get_member(admin_id),
                    "channel": channel,
                    "response": type(
                        "DummyResponse",
                        (),
                        {"send_message": lambda *args, **kwargs: None}
                    )(),
                }
            )

            created_orders = {}

            for user_id, items in users.items():
                subtotal = sum(float(i["sold_price"]) * i["quantity"] for i in items)
                tax = round(subtotal * 0.06, 2)
                fee = 0.0
                shipping_fee = 0.0
                total = round(subtotal + tax + shipping_fee + fee, 2)

                order_items = []
                for i in items:
                    order_items.append(
                        {
                            "inventory_id": i["inventory_id"],
                            "quantity": i["quantity"],
                            "pokemon_name": i["pokemon_name"],
                            "condition": i["condition"],
                            "series": i["series"],
                            "set_name": i["set_name"],
                            "price": float(i["sold_price"])
                        }
                    )

                try:
                    order_id = await myorders_cog.create_order(
                        DummyInteraction(),
                        user_id,
                        order_items,
                        subtotal,
                        tax,
                        fee,
                        shipping_fee,
                        total,
                        "Not Selected",
                        "Not Selected",
                        "Not Provided",
                        "Not Provided",
                        admin_id
                    )
                    print(f"[CLAIM SALE] created order {order_id} for user {user_id}")
                    created_orders[user_id] = order_id
                except Exception as e:
                    print(f"[CLAIM SALE][ERROR] failed to create order for user {user_id}: {e}")
                    continue

                async with self.bot.db.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE claim_sale_orders
                        SET order_id = $1
                        WHERE sale_id = $2
                          AND user_id = $3;
                        """,
                        order_id,
                        sale_row["claim_sale_id"],
                        user_id
                    )

                    for i in items:
                        await conn.execute(
                            """
                            UPDATE inventory
                            SET quantity_available = quantity_available - $2
                            WHERE inventory_id = $1;
                            """,
                            i["inventory_id"],
                            i["quantity"]
                        )

                card_lines = []
                for i in items:
                    price_each = float(i["sold_price"])
                    qty = i["quantity"]
                    line_total = round(price_each * qty, 2)
                    card_lines.append(
                        f"• {i['pokemon_name']} — x{qty} @ ${price_each:.2f} = ${line_total:.2f}\n"
                        f"  Condition: {i['condition']}\n"
                        f"  Series: {i['series']}\n"
                        f"  Set: {i['set_name']}\n"
                    )

                card_text = "\n".join(card_lines)

                user = await self.bot.fetch_user(user_id)
                if user:
                    try:
                        embed = discord.Embed(
                            title=f"Claim Sale Summary — Order #{order_id}",
                            description=(
                                "You participated in a claim sale and have claimed the following cards.\n\n"
                                f"{card_text}\n"
                                f"**Subtotal:** ${subtotal:.2f}\n"
                                f"**Tax (6%):** ${tax:.2f}\n"
                                f"**Total:** ${total:.2f}\n\n"
                                f"To complete this purchase, please run **/myorders** and select **Pay**.\n"
                                f"Payments not received within **{payment_hours} hours** are subject to cancellation.\n"
                                f"/myorders must be ran from a server channel."
                            ),
                            color=discord.Color.green()
                        )
                        await user.send(embed=embed)
                    except Exception as e:
                        print(f"[CLAIM SALE][WARN] DM to user {user_id} failed: {e}")

        summary_lines = []

        for user_id, items in users.items():
            subtotal = sum(float(i["sold_price"]) * i["quantity"] for i in items)
            tax = round(subtotal * 0.06, 2)
            total = round(subtotal + tax, 2)

            order_id = created_orders.get(user_id, "ERROR")

            summary_lines.append(
                f"<@{user_id}> | {len(items)} cards | ${total:.2f} | Order #{order_id}"
            )

        summary_text = "\n".join(summary_lines)

        admin_embed = discord.Embed(
            title="Claim Sale Summary — All Buyers",
            description=(
                "Here is the summary of all orders created from this claim sale:\n\n"
                f"{summary_text}\n\n"
                "Buyers will provide name & address when they run **/myorders** and complete checkout."
            ),
            color=discord.Color.blue()
        )

        admin_user = await self.bot.fetch_user(admin_id)
        if admin_user:
            try:
                await admin_user.send(embed=admin_embed)
            except Exception as e:
                print(f"[CLAIM SALE][WARN] Failed to DM admin summary: {e}")

        try:
            await channel.purge(limit=None)
            print("[CLAIM SALE] channel purge completed")
        except Exception as e:
            print(f"[CLAIM SALE][ERROR] purge failed: {e}")

        final_embed = discord.Embed(
            title="Claim Sale Concluded",
            description=(
                f"This concludes the claim sale.\n\n"
                f"Orders have been created for all buyers based on their claimed cards.\n"
                f"Payment is due within **{payment_hours} hours**.\n\n"
                "Payments not received by this time are subject to cancellation."
            ),
            color=discord.Color.gold()
        )

        await channel.send(embed=final_embed)

        async with self.bot.db.acquire() as conn:

            num_claims = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM claim_sale_orders
                WHERE sale_id = $1;
                """,
                sale_row["claim_sale_id"]
            )

            await conn.execute(
                """
                UPDATE claim_sales
                SET is_ran = TRUE,
                    number_of_claims = $2
                WHERE claim_sale_id = $1;
                """,
                sale_row["claim_sale_id"],
                num_claims
            )

        self.claimed_users_by_guild[guild_id].clear()
        print(f"[CLAIM SALE] cleared claimed_users for guild {guild_id}")

    def build_card_embed(self, card_row, index: int, total: int) -> discord.Embed:
        embed = discord.Embed(
            title=card_row["pokemon_name"],
            description="Claim this card or make an offer.",
            color=discord.Color.gold()
        )

        embed.add_field(name="Price", value=f"${card_row['price']}", inline=True)
        embed.add_field(name="Condition", value=card_row["condition"], inline=True)
        embed.add_field(name="Variant", value=card_row["variant"] or "N/A", inline=True)
        embed.add_field(name="Rarity", value=card_row["rarity"] or "N/A", inline=True)
        embed.add_field(name="Series", value=card_row["series"] or "N/A", inline=True)
        embed.add_field(name="Set", value=card_row["set_name"] or "N/A", inline=True)
        embed.add_field(name="Inventory ID", value=str(card_row["inventory_id"]), inline=True)

        if card_row["graded"]:
            embed.add_field(name="Grading Company", value=card_row["grading_company"] or "N/A", inline=True)
            embed.add_field(name="Grade", value=card_row["grade"] or "N/A", inline=True)

        if card_row["image_link"]:
            embed.set_thumbnail(url=card_row["image_link"])

        remaining = total - index
        embed.set_footer(text=f"Card {index}/{total} - {remaining} cards remaining")

        return embed

    async def send_end_of_sale_message(self, channel: discord.TextChannel, payment_hours: int):
        pass

    async def is_shop_blocked(self, guild_id: int) -> bool:

        now = datetime.datetime.now(self.est)
        print(f"[CLAIM SALE] is_shop_blocked check guild_id={guild_id} now={now}")

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT sale_date, sale_time, is_ran
                FROM claim_sales
                WHERE guild_id = $1
                """,
                guild_id
            )

        for row in rows:
            if row["is_ran"]:
                continue

            naive_dt = datetime.datetime.combine(row["sale_date"], row["sale_time"])
            start_dt = self.est.localize(naive_dt)

            block_start = start_dt - datetime.timedelta(minutes=10)

            if block_start <= now <= start_dt:
                print("[CLAIM SALE] shop is blocked (within 10-minute pre-sale window)")
                return True

            if now >= start_dt and not row["is_ran"]:
                print("[CLAIM SALE] shop is blocked (sale in progress)")
                return True

        print("[CLAIM SALE] shop is not blocked")
        return False


async def setup(bot: commands.Bot):
    await bot.add_cog(ClaimSaleRuntime(bot))
