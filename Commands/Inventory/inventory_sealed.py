import discord
from discord.ext import commands
from discord import app_commands
import logging

from Commands.Cart.cart import CheckoutStartView

log = logging.getLogger("inventory_sealed")

GALLERY_PAGE_SIZE = 6

# Price filter mapping
PRICE_FILTERS = {
    "Less than $10": 10,
    "Less than $25": 25,
    "Less than $50": 50,
    "Less than $100": 100,
    "Less than $200": 200,
    "Less than $500": 500,
    "Less than $1,000": 1000,
    "Less than $5,000": 5000,
}


class InventorySealed(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------------------------------------------------------
    # RUN SEALED QUERY
    # ---------------------------------------------------------
    async def run_sealed_query(self, filters, guild_id):
        """
        Pull ONLY sealed products using csv_id = 'sealed_add'
        """

        query = """
            SELECT
                inventory_id,
                pokemon_name,        -- Sealed Product Type
                series,
                set_name,
                price,
                quantity_available,
                condition,
                image_link
            FROM inventory
            WHERE guild_id = $1
              AND is_active = TRUE
              AND quantity_available >= 1
              AND csv_id = 'sealed_add'
        """

        params = [guild_id]

        # Apply filters
        if filters:
            for key, value in filters.items():

                # Sealed Product Type (now matches product_name)
                if key == "pokemon_name":
                    query += f" AND pokemon_name = ${len(params)+1}"
                    params.append(value)
                    continue

                # Series
                if key == "series":
                    query += f" AND series = ${len(params)+1}"
                    params.append(value)
                    continue

                # Set
                if key == "set_name":
                    query += f" AND set_name = ${len(params)+1}"
                    params.append(value)
                    continue

                # Price
                if key == "price_max":
                    query += f" AND price < ${len(params)+1}"
                    params.append(value)
                    continue

        query += " ORDER BY price ASC"

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return rows

    # ---------------------------------------------------------
    # DISTINCT VALUES FOR FILTERS
    # ---------------------------------------------------------
    async def get_distinct_sealed_product_types(self, guild_id):
        """
        Return ONLY sealed product types that actually exist in inventory.
        (i.e., sealed_product_id is not null)
        """
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT sp.product_name
                FROM inventory i
                JOIN sealed_product_list sp
                  ON sp.product_id = i.sealed_product_id
                WHERE i.guild_id = $1
                  AND i.csv_id = 'sealed_add'
                  AND i.quantity_available >= 1
                  AND i.sealed_product_id IS NOT NULL
                ORDER BY sp.product_name ASC;
            """, guild_id)

        return [r["product_name"] for r in rows]

    async def get_distinct_series(self, guild_id):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT series
                FROM inventory
                WHERE guild_id = $1
                  AND csv_id = 'sealed_add'
                  AND quantity_available >= 1
                ORDER BY series ASC;
            """, guild_id)

        return [r["series"] for r in rows]

    async def get_distinct_sets(self, guild_id, series):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT set_name
                FROM inventory
                WHERE guild_id = $1
                  AND csv_id = 'sealed_add'
                  AND series = $2
                  AND quantity_available >= 1
                ORDER BY set_name ASC;
            """, guild_id, series)

        return [r["set_name"] for r in rows]

    # ---------------------------------------------------------
    # BUILD SEALED GALLERY PAGES
    # ---------------------------------------------------------
    def build_sealed_gallery_pages(self, rows):
        pages = []
        inventory_ids = []
        current_embeds = []

        for row in rows:
            embed = discord.Embed(
                title=row["pokemon_name"],  # Sealed Product Type
                description=f"{row['series']} — {row['set_name']}",
                color=discord.Color.blue()
            )

            embed.add_field(name="Price", value=f"${row['price']}")
            embed.add_field(name="Condition", value=row["condition"])
            embed.add_field(name="Quantity Available", value=row["quantity_available"])
            embed.add_field(name="Sealed Product Type", value=row["pokemon_name"], inline=False)

            if row["image_link"]:
                embed.set_image(url=row["image_link"])

            current_embeds.append(embed)
            inventory_ids.append(row["inventory_id"])

            if len(current_embeds) == GALLERY_PAGE_SIZE:
                pages.append((current_embeds, []))
                current_embeds = []

        if current_embeds:
            pages.append((current_embeds, []))

        return pages, inventory_ids

    # ---------------------------------------------------------
    # PUBLIC ENTRYPOINT CALLED BY /shop sealed
    # ---------------------------------------------------------
    async def start_sealed_inventory(self, interaction):
        filters = {}

        rows = await self.run_sealed_query(filters, interaction.guild.id)

        if not rows:
            embed = discord.Embed(
                title="Sealed Inventory",
                description="No sealed products found.",
                color=discord.Color.gold()
            )
            await interaction.followup.send(embed=embed)
            return

        pages, inventory_ids = self.build_sealed_gallery_pages(rows)

        # Build filter options
        sealed_types = await self.get_distinct_sealed_product_types(interaction.guild.id)
        series_list = await self.get_distinct_series(interaction.guild.id)

        filter_options = {
            "sealed_product_type": sealed_types,
            "series": series_list,
            "price": list(PRICE_FILTERS.keys()),
        }

        view = SealedInventoryView(
            bot=self.bot,
            filters=filters,
            pages=pages,
            inventory_ids=inventory_ids,
            filter_options=filter_options
        )

        embeds, _ = pages[0]

        await interaction.followup.send(
            embeds=embeds,
            view=view
        )


# ---------------------------------------------------------
# SEALED INVENTORY VIEW
# ---------------------------------------------------------
class SealedInventoryView(discord.ui.View):
    def __init__(self, bot, filters, pages, inventory_ids, filter_options):
        super().__init__(timeout=180)
        self.bot = bot
        self.filters = filters
        self.pages = pages
        self.inventory_ids = inventory_ids
        self.page = 0
        self.filter_options = filter_options

        self.build_dropdowns()

    # ---------------------------------------------------------
    # BUILD DROPDOWNS
    # ---------------------------------------------------------
    def build_dropdowns(self):
        self.clear_items()

        embeds, _ = self.pages[self.page]
        start_index = self.page * GALLERY_PAGE_SIZE

        options = [
            discord.SelectOption(
                label=embed.title,
                value=str(self.inventory_ids[start_index + i])
            )
            for i, embed in enumerate(embeds)
        ]

        # Pagination buttons
        self.add_item(self.previous)
        self.add_item(self.next)

        # Add to cart
        add_to_cart_dropdown = discord.ui.Select(
            placeholder="Add to Cart — Select a Sealed Product",
            min_values=1,
            max_values=1,
            options=options,
            row=1
        )

        async def add_to_cart_callback(interaction):
            inv_id = int(add_to_cart_dropdown.values[0])
            await self.add_to_cart(interaction, inv_id)

        add_to_cart_dropdown.callback = add_to_cart_callback
        self.add_item(add_to_cart_dropdown)

        # Filters
        self.add_item(self.filters_button)
        self.add_item(self.clear_filters)

    # ---------------------------------------------------------
    # UPDATE PAGE
    # ---------------------------------------------------------
    async def update(self, interaction):
        embeds, _ = self.pages[self.page]
        self.build_dropdowns()

        await interaction.response.edit_message(
            embeds=embeds,
            view=self
        )

    # ---------------------------------------------------------
    # PAGINATION BUTTONS
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # FILTERS BUTTON
    # ---------------------------------------------------------
    @discord.ui.button(label="Filters", style=discord.ButtonStyle.secondary)
    async def filters_button(self, interaction, button):
        options = [
            discord.SelectOption(label="Sealed Product Type", value="sealed_product_type"),
            discord.SelectOption(label="Series", value="series"),
            discord.SelectOption(label="Set", value="set_name"),
            discord.SelectOption(label="Price", value="price"),
        ]

        filter_type_select = discord.ui.Select(
            placeholder="Select a filter",
            min_values=1,
            max_values=1,
            options=options
        )

        async def filter_type_callback(interaction2):
            selected = filter_type_select.values[0]
            sealed_cog = self.bot.get_cog("InventorySealed")

            # Sealed Product Type
            if selected == "sealed_product_type":
                values = self.filter_options["sealed_product_type"]
                opts = [discord.SelectOption(label=v, value=v) for v in values]

                value_select = discord.ui.Select(
                    placeholder="Select Sealed Product Type",
                    min_values=1,
                    max_values=1,
                    options=opts
                )

                async def value_cb(inter3):
                    chosen = value_select.values[0]
                    self.filters["pokemon_name"] = chosen

                    rows = await sealed_cog.run_sealed_query(self.filters, inter3.guild.id)
                    if not rows:
                        await inter3.response.send_message("No sealed products found.", ephemeral=True)
                        return

                    self.pages, self.inventory_ids = sealed_cog.build_sealed_gallery_pages(rows)
                    self.page = 0
                    await self.update(inter3)

                value_select.callback = value_cb

                v = discord.ui.View()
                v.add_item(value_select)

                embeds, _ = self.pages[self.page]
                await interaction2.response.edit_message(embeds=embeds, view=v)
                return

            # Series
            if selected == "series":
                values = self.filter_options["series"]
                opts = [discord.SelectOption(label=v, value=v) for v in values]

                series_select = discord.ui.Select(
                    placeholder="Select Series",
                    min_values=1,
                    max_values=1,
                    options=opts
                )

                async def series_cb(inter3):
                    chosen_series = series_select.values[0]
                    self.filters["series"] = chosen_series

                    sets = await sealed_cog.get_distinct_sets(inter3.guild.id, chosen_series)
                    set_opts = [discord.SelectOption(label=s, value=s) for s in sets]

                    set_select = discord.ui.Select(
                        placeholder="Select Set",
                        min_values=1,
                        max_values=1,
                        options=set_opts
                    )

                    async def set_cb(inter4):
                        chosen_set = set_select.values[0]
                        self.filters["set_name"] = chosen_set

                        rows = await sealed_cog.run_sealed_query(self.filters, inter4.guild.id)
                        if not rows:
                            await inter4.response.send_message("No sealed products found.", ephemeral=True)
                            return

                        self.pages, self.inventory_ids = sealed_cog.build_sealed_gallery_pages(rows)
                        self.page = 0
                        await self.update(inter4)

                    set_select.callback = set_cb

                    v2 = discord.ui.View()
                    v2.add_item(set_select)

                    embeds, _ = self.pages[self.page]
                    await inter3.response.edit_message(embeds=embeds, view=v2)

                series_select.callback = series_cb

                v = discord.ui.View()
                v.add_item(series_select)

                embeds, _ = self.pages[self.page]
                await interaction2.response.edit_message(embeds=embeds, view=v)
                return

            # Price
            if selected == "price":
                values = self.filter_options["price"]
                opts = [discord.SelectOption(label=v, value=v) for v in values]

                price_select = discord.ui.Select(
                    placeholder="Select Price Filter",
                    min_values=1,
                    max_values=1,
                    options=opts
                )

                async def price_cb(inter3):
                    chosen_label = price_select.values[0]
                    max_price = PRICE_FILTERS[chosen_label]
                    self.filters["price_max"] = max_price

                    rows = await sealed_cog.run_sealed_query(self.filters, inter3.guild.id)
                    if not rows:
                        await inter3.response.send_message("No sealed products found.", ephemeral=True)
                        return

                    self.pages, self.inventory_ids = sealed_cog.build_sealed_gallery_pages(rows)
                    self.page = 0
                    await self.update(inter3)

                price_select.callback = price_cb

                v = discord.ui.View()
                v.add_item(price_select)

                embeds, _ = self.pages[self.page]
                await interaction2.response.edit_message(embeds=embeds, view=v)
                return

        filter_type_select.callback = filter_type_callback

        v = discord.ui.View()
        v.add_item(filter_type_select)

        embeds, _ = self.pages[self.page]
        await interaction.response.edit_message(embeds=embeds, view=v)

    # ---------------------------------------------------------
    # CLEAR FILTERS
    # ---------------------------------------------------------
    @discord.ui.button(label="🧹 Clear Filters", style=discord.ButtonStyle.secondary)
    async def clear_filters(self, interaction, button):
        self.filters.clear()

        sealed_cog = self.bot.get_cog("InventorySealed")
        rows = await sealed_cog.run_sealed_query(self.filters, interaction.guild.id)

        if not rows:
            await interaction.response.send_message("No sealed products found.", ephemeral=True)
            return

        self.pages, self.inventory_ids = sealed_cog.build_sealed_gallery_pages(rows)
        self.page = 0
        await self.update(interaction)

    # ---------------------------------------------------------
    # ADD TO CART
    # ---------------------------------------------------------
    async def add_to_cart(self, interaction, inventory_id):
        await interaction.response.defer(ephemeral=True)

        async with self.bot.db.acquire() as conn:
            inv = await conn.fetchrow("""
                SELECT quantity_available, pokemon_name, set_name
                FROM inventory
                WHERE inventory_id = $1;
            """, inventory_id)

            cart = await conn.fetchrow("""
                SELECT quantity
                FROM cart_items
                WHERE user_id = $1 AND inventory_id = $2;
            """, interaction.user.id, inventory_id)

        if not inv:
            await interaction.followup.send("Item no longer exists.", ephemeral=True)
            return

        available = inv["quantity_available"]
        already = cart["quantity"] if cart else 0

        if already >= available:
            await interaction.followup.send(
                f"You already have **{already}** of this item.\n"
                f"Only **{available}** available.",
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO cart_items (user_id, inventory_id, quantity)
                VALUES ($1, $2, 1)
                ON CONFLICT (user_id, inventory_id)
                DO UPDATE SET quantity = cart_items.quantity + 1;
            """, interaction.user.id, inventory_id)

        embed = discord.Embed(
            title="Cart Updated",
            description=f"**{inv['pokemon_name']} — {inv['set_name']}** added to your cart.",
            color=discord.Color.green()
        )

        view = discord.ui.View()

        checkout_button = discord.ui.Button(
            label="Checkout",
            style=discord.ButtonStyle.success
        )

        async def checkout_callback(interaction2):
            checkout_view = CheckoutStartView(self.bot, interaction.user.id)
            ok = await checkout_view.async_init(interaction2)
            if ok is False:
                return

            embed2 = discord.Embed(
                title="Checkout",
                description="Select shipping and payment method:",
                color=discord.Color.blue()
            )

            await interaction2.response.edit_message(embed=embed2, view=checkout_view)

        checkout_button.callback = checkout_callback
        view.add_item(checkout_button)

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    print("INVENTORY SEALED COG LOADED")
    await bot.add_cog(InventorySealed(bot))
