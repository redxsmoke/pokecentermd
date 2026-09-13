import discord
from discord import app_commands
from discord.ext import commands

import shop_state
from Commands.Inventory.inventory import Inventory
from Commands.Cart.cart import CheckoutStartView


class RecentlyAdded(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="recentlyadded",
        description="Browse cards added Today, Past 7 Days, or Past 30 Days."
    )
    async def recentlyadded(self, interaction: discord.Interaction):

        # ---------------------------------------------------------
        # SHOP BLOCK CHECKS — EXACTLY MATCHING /shop
        # ---------------------------------------------------------
        runtime = interaction.client.get_cog("ClaimSaleRuntime")
        if runtime and await runtime.is_shop_blocked(interaction.guild.id):
            embed = discord.Embed(
                title="🚫 Shop Temporarily Closed",
                description=(
                    "A **claim sale** is starting shortly or is currently in progress.\n\n"
                    "The shop is closed during claim sales. Please try again after the claim sale ends."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not shop_state.SHOP_OPEN:
            if shop_state.SHOP_CLOSE_REASON == "show":
                desc = (
                    "We are currently **at a show**, and the shop is temporarily closed.\n\n"
                    "Please check back after the event!"
                )
            else:
                desc = (
                    "The shop is currently **undergoing maintenance**.\n\n"
                    "Please try again later."
                )

            embed = discord.Embed(
                title="🚫 Shop Closed",
                description=desc,
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # ---------------------------------------------------------
        # STEP 1 — Ask user to pick a time range
        # ---------------------------------------------------------
        options = [
            discord.SelectOption(label="Today", value="today"),
            discord.SelectOption(label="Past 7 Days", value="past_7"),
            discord.SelectOption(label="Past 30 Days", value="past_30"),
        ]

        select = discord.ui.Select(
            placeholder="Select a Recently Added time range",
            min_values=1,
            max_values=1,
            options=options
        )

        view = discord.ui.View()
        view.add_item(select)

        embed = discord.Embed(
            title="Recently Added",
            description=(
                "Select a time range to view newly added cards.\n\n"
                "[Click here to view our inventory online]"
                "(https://app.dextcg.com/folders/99d3ec14-0435-419e-bf51-331a37821152"
                "?screenTitle=Inventory&type=standard_v2&initial=false)"
            ),
            color=discord.Color.blue()
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # ---------------------------------------------------------
        # CALLBACK — Build query + use InventoryView (same as /shop)
        # ---------------------------------------------------------
        async def callback(inter: discord.Interaction):
            range_value = select.values[0]

            # Build WHERE clause
            where_clauses = ["quantity_available >= 1"]
            params = []

            where_clauses.append(f"guild_id = ${len(params)+1}")
            params.append(inter.guild.id)

            if range_value == "today":
                where_clauses.append("date_added::date = NOW()::date")
            elif range_value == "past_7":
                where_clauses.append("date_added >= NOW() - INTERVAL '7 days'")
            elif range_value == "past_30":
                where_clauses.append("date_added >= NOW() - INTERVAL '30 days'")

            query = f"""
                SELECT inventory_id, pokemon_name, series, set_name,
                       card_number, variant, rarity, price,
                       quantity_available, condition, illustrator, image_link
                FROM inventory
                WHERE {' AND '.join(where_clauses)}
                ORDER BY price ASC;
            """

            async with self.bot.db.acquire() as conn:
                rows = await conn.fetch(query, *params)

            if not rows:
                embed = discord.Embed(
                    title="Recently Added",
                    description=(
                        "No cards found for the selected time range.\n\n"
                        "[Click here to view our inventory online]"
                        "(https://app.dextcg.com/folders/99d3ec14-0435-419e-bf51-331a37821152"
                        "?screenTitle=Inventory&type=standard_v2&initial=false)"
                    ),
                    color=discord.Color.red()
                )
                await inter.response.edit_message(embed=embed, view=None)
                return

            # ---------------------------------------------------------
            # USE INVENTORY COG — EXACT SAME FLOW AS /shop
            # ---------------------------------------------------------
            inventory_cog = self.bot.get_cog("Inventory")

            pages, inventory_ids = inventory_cog.build_gallery_pages(rows)

            # Filter options identical to /shop
            conditions = await inventory_cog.get_distinct_values("condition", inter.guild.id)
            series_list = await inventory_cog.get_distinct_values("series", inter.guild.id)
            variants = await inventory_cog.get_distinct_values("variant", inter.guild.id)
            rarities = await inventory_cog.get_distinct_values("rarity", inter.guild.id)
            illustrators = await inventory_cog.get_distinct_values("illustrator", inter.guild.id)

            filter_options = {
                "condition": conditions,
                "series": series_list,
                "variant": variants,
                "rarity": rarities,
                "illustrator": illustrators,
            }

            # Build InventoryView — EXACT SAME UI AS /shop
            view2 = inventory_cog.InventoryView(
                bot=self.bot,
                base_pokemon_name=None,
                base_set_name=None,
                filters={"recently_added": True, "recent_range": range_value},
                pages=pages,
                inventory_ids=inventory_ids,
                filter_options=filter_options
            )

            embeds, files = pages[0]
            discord_files = [
                discord.File(path, filename=filename)
                for path, filename in files
            ]

            await inter.response.edit_message(
                embeds=embeds,
                attachments=discord_files,
                view=view2
            )

        select.callback = callback


async def setup(bot):
    print("RECENTLY ADDED COG LOADED")
    await bot.add_cog(RecentlyAdded(bot))
