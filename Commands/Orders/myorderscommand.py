# Commands/Orders/myorderscommand.py

import discord
from discord.ext import commands
import datetime

ADMIN_ID = 337773020770729985

from .myordersview import MyOrdersView  # use the buyer-facing view with buttons


class MyOrdersSlash(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="myorders",
        description="View your past orders and their status."
    )
    async def myorders(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        # Only show orders from the past 30 days
        cutoff_date = datetime.datetime.utcnow() - datetime.timedelta(days=30)

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

        orders_cog = interaction.client.get_cog("MyOrders")

        orders = []
        for r in rows:
            r = dict(r)
            r["items"] = await orders_cog.get_order_items(r["order_id"])
            orders.append(r)

        active_orders = [
            o for o in orders
            if o["order_status"] in ("Pending", "Paid", "Shipped", "Not Received")
        ]

        archived_orders = [
            o for o in orders
            if o["order_status"] in ("Delivered", "Cancelled")
        ]

        mode = "active" if active_orders else "archived"
        pages = active_orders if mode == "active" else archived_orders

        embed = orders_cog.build_order_embed(
            pages[0],
            1,
            len(pages),
            mode
        )

        view = MyOrdersView(
            self.bot,
            user_id,
            active_orders,
            archived_orders,
            mode
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(MyOrdersSlash(bot))