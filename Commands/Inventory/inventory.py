import discord
from discord import app_commands
from discord.ext import commands
import os

from Commands.Cart.cart import CheckoutStartView  # ✅ needed for Checkout button


class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="inventory",
        description="Browse the inventory. Apply filters after results appear."
    )
    @app_commands.describe(
        pokemon_name="Search by Pokémon name",
        set_name="Search by set name"
    )
    async def inventory(
        self,
        interaction: discord.Interaction,
        pokemon_name: str = None,
        set_name: str = None
    ):
        await interaction.response.defer(ephemeral=True)

        filters = {}
        rows = await self.run_query(
            pokemon_name=pokemon_name,
            set_name=set_name,
            filters=filters
        )

        if not rows:
            embed = discord.Embed(
                title="Inventory",
                description="No available cards found.",
                color=discord.Color.gold()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        pages, page_files, inventory_ids = self.build_pages(rows)

        conditions = await self.get_distinct_values("condition")
        series_list = await self.get_distinct_values("series")
        variants = await self.get_distinct_values("variant")
        rarities = await self.get_distinct_values("rarity")

        filter_options = {
            "condition": conditions,
            "series": series_list,
            "variant": variants,
            "rarity": rarities,
        }

        view = self.InventoryView(
            bot=self.bot,
            base_pokemon_name=pokemon_name,
            base_set_name=set_name,
            filters=filters,
            pages=pages,
            page_files=page_files,
            inventory_ids=inventory_ids,
            filter_options=filter_options
        )

        first_page = pages[0]
        first_page.set_footer(text=f"Result 1/{len(pages)}")

        files = []
        if page_files[0]:
            files = [discord.File(page_files[0], filename="card.jpg")]
            first_page.set_image(url="attachment://card.jpg")

        await interaction.followup.send(
            embed=first_page,
            view=view,
            files=files,
            ephemeral=True
        )

    async def run_query(self, pokemon_name=None, set_name=None, filters=None):
        where_clauses = ["quantity_available >= 1"]
        params = []

        if pokemon_name:
            where_clauses.append(f"pokemon_name ILIKE ${len(params)+1}")
            params.append(f"%{pokemon_name}%")

        if set_name:
            where_clauses.append(f"set_name ILIKE ${len(params)+1}")
            params.append(f"%{set_name}%")

        if filters:
            bucket = filters.get("pokemon_name_bucket")
            if bucket == "AF":
                where_clauses.append("pokemon_name ~* '^[A-F]'")
            elif bucket == "GM":
                where_clauses.append("pokemon_name ~* '^[G-M]'")
            elif bucket == "NS":
                where_clauses.append("pokemon_name ~* '^[N-S]'")
            elif bucket == "TZ":
                where_clauses.append("pokemon_name ~* '^[T-Z]'")

            if filters.get("condition"):
                where_clauses.append(f"condition = ${len(params)+1}")
                params.append(filters["condition"])

            if filters.get("series"):
                where_clauses.append(f"series = ${len(params)+1}")
                params.append(filters["series"])

            if filters.get("variant"):
                where_clauses.append(f"variant = ${len(params)+1}")
                params.append(filters["variant"])

            if filters.get("rarity"):
                where_clauses.append(f"rarity = ${len(params)+1}")
                params.append(filters["rarity"])

        query = f"""
            SELECT inventory_id, csv_id, pokemon_name, series, set_name,
                   card_number, variant, price, rarity,
                   graded, grading_company, grade,
                   quantity_available, image_link, condition
            FROM inventory
            WHERE {' AND '.join(where_clauses)}
            ORDER BY pokemon_name ASC;
        """

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return rows

    async def get_distinct_values(self, column_name: str):
        query = f"""
            SELECT DISTINCT {column_name}
            FROM inventory
            WHERE quantity_available >= 1
              AND {column_name} IS NOT NULL
            ORDER BY {column_name} ASC;
        """
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(query)
        return [r[column_name] for r in rows]

    def build_pages(self, rows):
        pages = []
        page_files = []
        inventory_ids = []

        for row in rows:
            inventory_ids.append(row["inventory_id"])

            embed = discord.Embed(
                title=f"{row['pokemon_name']} — {row['set_name']}",
                color=discord.Color.gold()
            )

            image_path = None
            if row["image_link"]:
                if row["image_link"].startswith(("http://", "https://")):
                    embed.set_image(url=row["image_link"])
                else:
                    local_path = row["image_link"].replace("\\", "/")
                    if os.path.exists(local_path):
                        image_path = local_path
                        embed.set_image(url="attachment://card.jpg")

            graded_text = "Yes" if row["graded"] else "No"

            details = f"**Card Details**\n\n"
            details += f"• **Expansion:** {row['series']}\n"
            details += f"• **Set:** {row['set_name']}\n"
            details += f"• **Condition:** {row['condition'] or 'Near Mint'}\n"
            details += f"• **Price:** ${row['price']}\n"
            details += f"• **Card #:** {row['card_number'] or '—'}\n"
            details += f"• **Variant:** {row['variant'] or '—'}\n"
            details += f"• **Rarity:** {row['rarity'] or '—'}\n"
            details += f"• **Graded:** {graded_text}\n"

            if row["graded"]:
                details += f"• **Grading Company:** {row['grading_company']}\n"
                details += f"• **Grade:** {row['grade']}\n"

            details += "\n\n[Click Here](https://dextcg.com/users/redxsmoke/folders/99d3ec14-0435-419e-bf51-331a37821152?type=standard_v2) to view our inventory online."

            embed.description = details
            embed.set_footer(text=f"Inventory ID: {row['inventory_id']}")

            pages.append(embed)
            page_files.append(image_path)

        return pages, page_files, inventory_ids
    class InventoryView(discord.ui.View):
        def __init__(self, bot, base_pokemon_name, base_set_name, filters, pages, page_files, inventory_ids, filter_options):
            super().__init__(timeout=180)
            self.bot = bot
            self.base_pokemon_name = base_pokemon_name
            self.base_set_name = base_set_name
            self.filters = filters
            self.pages = pages
            self.page_files = page_files
            self.inventory_ids = inventory_ids
            self.page = 0
            self.filter_options = filter_options

        async def update(self, interaction):
            embed = self.pages[self.page]
            embed.set_footer(text=f"Result {self.page+1}/{len(self.pages)}")

            files = []
            image_path = self.page_files[self.page]

            if image_path:
                try:
                    files = [discord.File(image_path, filename="card.jpg")]
                    embed.set_image(url="attachment://card.jpg")
                except Exception as e:
                    print(f"Image reload failed: {e}")

            await interaction.response.edit_message(
                embed=embed,
                view=self,
                attachments=files
            )

        @discord.ui.button(label="Filters", style=discord.ButtonStyle.primary)
        async def filters_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            options = [
                discord.SelectOption(label="Pokémon Name", value="pokemon_name"),
                discord.SelectOption(label="Condition", value="condition"),
                discord.SelectOption(label="Series", value="series"),
                discord.SelectOption(label="Variant", value="variant"),
                discord.SelectOption(label="Rarity", value="rarity"),
            ]

            filter_type_select = discord.ui.Select(
                placeholder="Select a filter",
                min_values=1,
                max_values=1,
                options=options
            )

            view = Inventory.FilterTypeView(
                bot=self.bot,
                base_pokemon_name=self.base_pokemon_name,
                base_set_name=self.base_set_name,
                filters=self.filters,
                pages=self.pages,
                page_files=self.page_files,
                inventory_ids=self.inventory_ids,
                current_page=self.page,
                filter_options=self.filter_options,
                filter_type_select=filter_type_select
            )

            embed = self.pages[self.page]
            embed.set_footer(text=f"Result {self.page+1}/{len(self.pages)}")

            files = []
            image_path = self.page_files[self.page]
            if image_path:
                try:
                    files = [discord.File(image_path, filename="card.jpg")]
                    embed.set_image(url="attachment://card.jpg")
                except Exception as e:
                    print(f"Image reload failed: {e}")

            await interaction.response.edit_message(
                embed=embed,
                view=view,
                attachments=files
            )

        @discord.ui.button(label="🧹 Clear Filters", style=discord.ButtonStyle.secondary)
        async def clear_filters(self, interaction, button):
            self.filters.clear()
            rows = await self.bot.get_cog("Inventory").run_query(
                pokemon_name=self.base_pokemon_name,
                set_name=self.base_set_name,
                filters=self.filters
            )
            if not rows:
                embed = discord.Embed(
                    title="Filters",
                    description="No results after clearing filters.",
                    color=discord.Color.gold()
                )
                await interaction.response.send_message(
                    embed=embed,
                    ephemeral=True
                )
                return

            self.pages, self.page_files, self.inventory_ids = self.bot.get_cog("Inventory").build_pages(rows)
            self.page = 0
            await self.update(interaction)

        @discord.ui.button(label="🛒 Add to Cart", style=discord.ButtonStyle.success)
        async def add_to_cart(self, interaction, button):
            await interaction.response.defer(ephemeral=True)

            inventory_id = self.inventory_ids[self.page]

            async with self.bot.db.acquire() as conn:
                inv = await conn.fetchrow(
                    """
                    SELECT quantity_available, pokemon_name, set_name
                    FROM inventory
                    WHERE inventory_id = $1;
                    """,
                    inventory_id
                )

                cart = await conn.fetchrow(
                    """
                    SELECT quantity
                    FROM cart_items
                    WHERE user_id = $1 AND inventory_id = $2;
                    """,
                    interaction.user.id,
                    inventory_id
                )

            if not inv:
                await interaction.followup.send("Item no longer exists.", ephemeral=True)
                return

            available = inv["quantity_available"]
            already = cart["quantity"] if cart else 0

            if already >= available:
                await interaction.followup.send(
                    f"You already have **{already}** of this item in your cart.\n"
                    f"Only **{available}** are available.",
                    ephemeral=True
                )
                return

            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO cart_items (user_id, inventory_id, quantity)
                    VALUES ($1, $2, 1)
                    ON CONFLICT (user_id, inventory_id)
                    DO UPDATE SET quantity = cart_items.quantity + 1;
                    """,
                    interaction.user.id,
                    inventory_id
                )

            embed = discord.Embed(
                title="Cart Updated",
                description=f"**{inv['pokemon_name']} — {inv['set_name']}** has been added to your cart.",
                color=discord.Color.green()
            )

            view = discord.ui.View()

            checkout_button = discord.ui.Button(
                label="Checkout",
                style=discord.ButtonStyle.success
            )

            async def checkout_callback(inner_interaction: discord.Interaction):
                cart_view = CheckoutStartView(self.bot, inner_interaction.user.id)
                embed_checkout = discord.Embed(
                    title="Checkout",
                    description="Select shipping and payment method:",
                    color=discord.Color.blue()
                )
                await inner_interaction.response.send_message(embed=embed_checkout, view=cart_view, ephemeral=True)

            checkout_button.callback = checkout_callback
            view.add_item(checkout_button)

            view_cart_button = discord.ui.Button(
                label="View Cart",
                style=discord.ButtonStyle.primary
            )

            async def view_cart_callback(inner_interaction: discord.Interaction):
                cart_cog = inner_interaction.client.get_cog("Cart")
                await cart_cog.open_cart(inner_interaction)

            view_cart_button.callback = view_cart_callback
            view.add_item(view_cart_button)

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

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
    class FilterTypeView(discord.ui.View):
        def __init__(
            self,
            bot,
            base_pokemon_name,
            base_set_name,
            filters,
            pages,
            page_files,
            inventory_ids,
            current_page,
            filter_options,
            filter_type_select: discord.ui.Select
        ):
            super().__init__(timeout=180)
            self.bot = bot
            self.base_pokemon_name = base_pokemon_name
            self.base_set_name = base_set_name
            self.filters = filters
            self.pages = pages
            self.page_files = page_files
            self.inventory_ids = inventory_ids
            self.page = current_page
            self.filter_options = filter_options
            self.filter_type_select = filter_type_select

            async def filter_type_callback(inter: discord.Interaction):
                filter_type = self.filter_type_select.values[0]
                await self.show_filter_options(inter, filter_type)

            self.filter_type_select.callback = filter_type_callback
            self.add_item(self.filter_type_select)

        async def show_filter_options(self, interaction: discord.Interaction, filter_type: str):
            if filter_type == "pokemon_name":
                options = [
                    discord.SelectOption(label="A–F", value="AF"),
                    discord.SelectOption(label="G–M", value="GM"),
                    discord.SelectOption(label="N–S", value="NS"),
                    discord.SelectOption(label="T–Z", value="TZ"),
                ]
            else:
                values = self.filter_options.get(filter_type, [])
                options = [
                    discord.SelectOption(label=str(v), value=str(v))
                    for v in values
                ]

            filter_value_select = discord.ui.Select(
                placeholder="Select filter value",
                min_values=1,
                max_values=1,
                options=options
            )

            async def filter_value_callback(inter: discord.Interaction):
                value = filter_value_select.values[0]

                if filter_type == "pokemon_name":
                    self.filters["pokemon_name_bucket"] = value
                else:
                    self.filters[filter_type] = value

                rows = await self.bot.get_cog("Inventory").run_query(
                    pokemon_name=self.base_pokemon_name,
                    set_name=self.base_set_name,
                    filters=self.filters
                )

                if not rows:
                    embed = discord.Embed(
                        title="Filters",
                        description="No results with that filter.",
                        color=discord.Color.gold()
                    )
                    await inter.response.send_message(embed=embed, ephemeral=True)
                    return

                self.pages, self.page_files, self.inventory_ids = (
                    self.bot.get_cog("Inventory").build_pages(rows)
                )
                self.page = 0

                main_view = Inventory.InventoryView(
                    bot=self.bot,
                    base_pokemon_name=self.base_pokemon_name,
                    base_set_name=self.base_set_name,
                    filters=self.filters,
                    pages=self.pages,
                    page_files=self.page_files,
                    inventory_ids=self.inventory_ids,
                    filter_options=self.filter_options
                )

                embed = self.pages[self.page]
                embed.set_footer(text=f"Result {self.page+1}/{len(self.pages)}")

                files = []
                image_path = self.page_files[self.page]
                if image_path:
                    try:
                        files = [discord.File(image_path, filename="card.jpg")]
                        embed.set_image(url="attachment://card.jpg")
                    except Exception as e:
                        print(f"Image reload failed: {e}")

                await inter.response.edit_message(
                    embed=embed,
                    view=main_view,
                    attachments=files
                )

            filter_value_select.callback = filter_value_callback

            view = discord.ui.View(timeout=180)
            view.add_item(filter_value_select)

            embed = discord.Embed(
                title="Select Filter Value",
                description="Choose a value for your selected filter.",
                color=discord.Color.blue()
            )

            await interaction.response.edit_message(
                embed=embed,
                view=view
            )
async def setup(bot):
    await bot.add_cog(Inventory(bot))


