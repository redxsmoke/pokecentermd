import discord
from discord.ext import commands
import datetime

from .myordersview import (
    MyOrdersView,
    AdminOrderView,
    AdminNotReceivedView,
    AdminTrackingResponseModal
)


class MyOrders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_payment_settings(self, guild_id):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT admin_id, paypal_handle, venmo_handle, cashapp_handle
                FROM guild_settings
                WHERE guild_id = $1;
                """,
                guild_id
            )
        return row

    async def get_order_items(self, order_id):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT oi.inventory_id,
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
                order_id
            )
        return rows

    def build_order_embed(self, order, page, total_pages, mode):
        embed = discord.Embed(
            title=f"My Orders — Page {page}/{total_pages}",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="Order Summary",
            value=(
                f"**Order ID:** {order['order_id']}\n"
                f"**Status:** {order['order_status']}\n"
                f"**Total:** ${order['total']:.2f}\n"
                f"**Created:** {order['created_at'].date()}\n"
            ),
            inline=False
        )

        shipping_method = order["shipping_method"].lower()
        tracking_number = order.get("tracking_number")
        status = order["order_status"]

        if "plain white envelope" in shipping_method:
            tracking_display = "Shipped without tracking"
        else:
            if tracking_number is None:
                if status != "Shipped":
                    tracking_display = "Not yet shipped"
                else:
                    tracking_display = "Tracking number has not been provided"
            else:
                tracking_display = tracking_number

        embed.add_field(
            name="Tracking Information",
            value=tracking_display,
            inline=False
        )

        items_text = ""
        for item in order["items"]:
            items_text += (
                f"• {item['pokemon_name']} — x{item['quantity']} "
                f"@ ${item['price_each']:.2f}\n"
            )

        embed.add_field(
            name="Items",
            value=items_text or "No items found.",
            inline=False
        )

        return embed

    async def create_order(
        self,
        interaction,
        user_id,
        items,
        subtotal,
        tax,
        fee,
        shipping_fee,
        total,
        payment_method,
        shipping_method,
        name,
        address,
        admin_id
    ):
        async with interaction.client.db.acquire() as conn:

            row = await conn.fetchrow(
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
                    created_at,
                    order_status,
                    date_paid,
                    tracking_number,
                    estimated_delivery,
                    received,
                    date_received,
                    date_shipped,
                    cancelled_reason,
                    reported_missing
                )
                VALUES (
                    $1,$2,$3,$4,$5,$6,
                    $7,$8,
                    $9,$10,
                    $11,
                    NOW(),
                    'Pending',
                    NULL,
                    NULL,
                    NULL,
                    FALSE,
                    NULL,
                    NULL,
                    NULL,
                    FALSE
                )
                RETURNING order_id;
                """,
                user_id,
                interaction.guild.id,
                subtotal,
                tax,
                fee,
                shipping_fee,
                total,
                payment_method,
                shipping_method,
                name,
                address
            )

            order_id = row["order_id"]

            for i in items:
                await conn.execute(
                    """
                    INSERT INTO order_items (
                        order_id,
                        inventory_id,
                        quantity,
                        price_each
                    )
                    VALUES ($1,$2,$3,$4);
                    """,
                    order_id,
                    i["inventory_id"],
                    i["quantity"],
                    float(i["price"])
                )

        # ⭐ UPDATED: Correct claim-sale detection using inventory_id + user_id
        async with interaction.client.db.acquire() as conn:
            is_claim_sale = await conn.fetchval(
                """
                SELECT 1
                FROM claim_sale_orders
                WHERE inventory_id = $1
                AND user_id = $2
                LIMIT 1;
                """,
                items[0]["inventory_id"],
                user_id
            )

        if is_claim_sale:
            return order_id

        # ⭐ ORIGINAL DM CODE (unchanged)
        item_lines = "\n".join(
            f"• {i['pokemon_name']} — x{i['quantity']} @ ${float(i['price']):.2f}"
            for i in items
        )

        admin_embed = discord.Embed(
            title=f"New Order #{order_id}",
            description=(
                f"**Buyer:** {name}\n"
                f"**Address:**\n{address}\n\n"
                f"**Payment:** {payment_method.capitalize()}\n"
                f"**Shipping:** {shipping_method}\n"
                f"**Total:** ${total:.2f}\n\n"
                f"**Items:**\n{item_lines}\n\n"
                f"To manage this order (mark as **Paid**, **Shipped**, **Enter Tracking**, **Cancel**, etc.), "
                f"use the command:\n"
                f"**/admin manage_orders**\n\n"
                f"This DM is informational only. All actions must be done using the admin-manage_orders command."
            ),
            color=discord.Color.blue()
        )

        try:
            admin = await interaction.client.fetch_user(admin_id)
            await admin.send(
                embed=admin_embed,
                view=AdminOrderView(
                    self.bot,
                    order_id,
                    user_id,
                    items,
                    shipping_method,
                    admin_id
                )
            )
        except Exception as e:
            print("ADMIN DM ERROR:", e)

        return order_id

    @discord.app_commands.command(
        name="myorders",
        description="View your past orders and their status."
    )
    async def myorders(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Command Not Available in DMs",
                    description="This command cannot be used in DMs.\n\nPlease run this command within the server.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        user_id = interaction.user.id

        cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=30)

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT order_id, user_id, subtotal, tax, fee, shipping_fee, total,
                       payment_method, shipping_method, order_status,
                       created_at, date_paid, date_shipped,
                       tracking_number, estimated_delivery,
                       received, date_received, cancelled_reason,
                       reported_missing
                FROM orders
                WHERE user_id = $1
                AND created_at >= $2
                ORDER BY order_id DESC;
                """,
                user_id,
                cutoff_date
            )

        if not rows:
            embed = discord.Embed(
                title="My Orders",
                description="You have no orders in the past 30 days.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        orders = []
        for r in rows:
            r = dict(r)
            r["items"] = await self.get_order_items(r["order_id"])
            orders.append(r)

        config = await self.get_payment_settings(interaction.guild_id)
        admin_id = config["admin_id"]

        for o in orders:
            o["admin_id"] = admin_id

        active_orders = [
            o for o in orders
            if o["order_status"] in ("Pending", "Paid", "Shipped", "Not Received")
        ]

        archived_orders = [
            o for o in orders
            if o["order_status"] in ("Delivered", "Cancelled")
        ]

        view = MyOrdersView(
            self.bot,
            user_id,
            active_orders,
            archived_orders,
            None,
            admin_id
        )

        await interaction.response.send_message(
            content="Please select **Active Orders** or **Delivered Orders**.",
            view=view,
            ephemeral=True
        )



async def setup(bot):
    await bot.add_cog(MyOrders(bot))
