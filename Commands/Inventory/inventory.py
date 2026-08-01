import discord
from discord import app_commands
from discord.ext import commands
import os

import shop_state

from Commands.Cart.cart import CheckoutStartView

GALLERY_PAGE_SIZE = 6  # Number of cards per page


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

        # ----------------------------------------------------
        # SHOP CLOSED CHECK
        # ----------------------------------------------------
        if not shop_state.SHOP_OPEN:
            if shop_state.SHOP_CLOSE_REASON == "show":
                desc = (
                    "We are currently **at a show**, and the shop is temporarily closed to "
                    "prevent orders of items that may be sold at the event.\n\n"
                    "Please check back after the show to see what's available and view new items!"
                )
            else:
                desc = (
                    "The shop is currently **undergoing maintenance**.\n\n"
                    "Please try again later once improvements are complete."
                )

            embed = discord.Embed(
                title="🚫 Shop Closed",
                description=desc,
                color=discord.Color.red()
            )

            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        # ----------------------------------------------------

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

        pages, inventory_ids = self.build_gallery_pages(rows)

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
            inventory_ids=inventory_ids,
            filter_options=filter_options
        )

        embeds, files = pages[0]

        discord_files = [
            discord.File(path, filename=filename)
            for path, filename in files
        ]

        await interaction.followup.send(
            embeds=embeds,
            files=discord_files,
            view=view,
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

        # -----------------------------
        # FILTER LOGIC (UPDATED)
        # -----------------------------
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

            if filters.get("set_name"):
                where_clauses.append(f"set_name = ${len(params)+1}")
                params.append(filters["set_name"])

            # -----------------------------
            # NEW FILTERS: SET LIST A–L
            # -----------------------------
            if filters.get("set_bucket_AL"):
                where_clauses.append("""
                    (
                        LEFT(set_name, 1) ~* '^[A-L]'
                    )
                """)

            # -----------------------------
            # NEW FILTERS: SET LIST M–Z (INCLUDES 151)
            # -----------------------------
            if filters.get("set_bucket_MZ"):
                where_clauses.append("""
                    (
                        LEFT(set_name, 1) ~* '^[M-Z]'
                        OR set_name = '151'
                    )
                """)

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

    # ------------------------------------------------------------
    # GALLERY PAGE BUILDER (LOCAL PNG/JPG SUPPORT + 151 PATCH)
    # ------------------------------------------------------------
    def build_gallery_pages(self, rows):
        pages = []
        inventory_ids = []

        current_page_embeds = []
        current_page_files = []

        for index, row in enumerate(rows):
            inventory_ids.append(row["inventory_id"])

            card_number = row["card_number"] or "—"

            # -----------------------------
            # SPECIAL DISPLAY PATCH FOR SET "151"
            # -----------------------------
            set_display = row["set_name"]
            if set_display == "151":
                set_display = "Mew 151"

            title = f"{row['pokemon_name']} #{card_number} — {set_display}"

            embed = discord.Embed(
                title=title,
                color=discord.Color.gold()
            )

            # LOCAL IMAGE SUPPORT
            img = row["image_link"]
            if img and isinstance(img, str):
                local_path = img.replace("\\", "/")
                if os.path.exists(local_path):
                    filename = f"card_{index}.jpg"
                    embed.set_thumbnail(url=f"attachment://{filename}")
                    current_page_files.append((local_path, filename))

            graded_text = "Yes" if row["graded"] else "No"

            details = "__**Card Details**__\n\n"
            details += f"**Price:** ${row['price']}\n"
            details += f"**Condition:** {row['condition'] or 'Near Mint'}\n"
            details += f"**Graded:** {graded_text}\n"

            embed.description = details
            embed.set_footer(text=f"Inventory ID: {row['inventory_id']}")

            current_page_embeds.append(embed)

            if len(current_page_embeds) == GALLERY_PAGE_SIZE:
                pages.append((current_page_embeds, current_page_files))
                current_page_embeds = []
                current_page_files = []

        if current_page_embeds:
            pages.append((current_page_embeds, current_page_files))

        return pages, inventory_ids
    # ------------------------------------------------------------
    # UPDATED VIEW — 4 ROWS (ERROR-FREE)
    # ------------------------------------------------------------
    class InventoryView(discord.ui.View):
        def __init__(self, bot, base_pokemon_name, base_set_name, filters, pages, inventory_ids, filter_options):
            super().__init__(timeout=180)
            self.bot = bot
            self.base_pokemon_name = base_pokemon_name
            self.base_set_name = base_set_name
            self.filters = filters
            self.pages = pages
            self.inventory_ids = inventory_ids
            self.page = 0
            self.filter_options = filter_options

            self.build_dropdowns()

        def build_dropdowns(self):
            """Build dropdowns for Add to Cart + More Info."""
            self.clear_items()

            embeds, _ = self.pages[self.page]
            start_index = self.page * GALLERY_PAGE_SIZE

            # Build dropdown options
            options = []
            for i, embed in enumerate(embeds):
                inv_id = self.inventory_ids[start_index + i]
                label = embed.title
                options.append(
                    discord.SelectOption(
                        label=label,
                        value=str(inv_id)
                    )
                )

            # -----------------------------
            # ROW 0 — NAVIGATION BUTTONS
            # -----------------------------
            self.previous.row = 0
            self.next.row = 0
            self.add_item(self.previous)
            self.add_item(self.next)

            # -----------------------------
            # ROW 1 — ADD TO CART DROPDOWN
            # -----------------------------
            add_to_cart_dropdown = discord.ui.Select(
                placeholder="Add to Cart — Select a Card",
                min_values=1,
                max_values=1,
                options=options,
                row=1
            )

            async def add_to_cart_callback(interaction: discord.Interaction):
                inv_id = int(add_to_cart_dropdown.values[0])
                await self.add_to_cart(interaction, inv_id)

            add_to_cart_dropdown.callback = add_to_cart_callback
            self.add_item(add_to_cart_dropdown)

            # -----------------------------
            # ROW 2 — MORE INFO DROPDOWN
            # -----------------------------
            more_info_dropdown = discord.ui.Select(
                placeholder="View More Info — Select a Card",
                min_values=1,
                max_values=1,
                options=options,
                row=2
            )

            async def more_info_callback(interaction: discord.Interaction):
                inv_id = int(more_info_dropdown.values[0])
                await self.view_more_info(interaction, inv_id)

            more_info_dropdown.callback = more_info_callback
            self.add_item(more_info_dropdown)

            # -----------------------------
            # ROW 3 — FILTER BUTTONS
            # -----------------------------
            self.filters_button.row = 3
            self.clear_filters.row = 3

            self.add_item(self.filters_button)
            self.add_item(self.clear_filters)

        async def update(self, interaction):
            """Update embeds + attachments + rebuild dropdowns."""
            embeds, files = self.pages[self.page]

            discord_files = [
                discord.File(path, filename=filename)
                for path, filename in files
            ]

            self.build_dropdowns()

            await interaction.response.edit_message(
                embeds=embeds,
                attachments=discord_files,
                view=self
            )

        # -------------------------
        # NAVIGATION BUTTONS (ROW 0)
        # -------------------------
        @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.primary, row=0)
        async def previous(self, interaction, button):
            if self.page > 0:
                self.page -= 1
            await self.update(interaction)

        @discord.ui.button(label="Next ➡", style=discord.ButtonStyle.primary, row=0)
        async def next(self, interaction, button):
            if self.page < len(self.pages) - 1:
                self.page += 1
            await self.update(interaction)

        # -------------------------
        # FILTER BUTTONS (ROW 3)
        # -------------------------
        @discord.ui.button(label="Filters", style=discord.ButtonStyle.secondary, row=3)
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
                inventory_ids=self.inventory_ids,
                current_page=self.page,
                filter_options=self.filter_options,
                filter_type_select=filter_type_select
            )

            embeds, files = self.pages[self.page]
            discord_files = [
                discord.File(path, filename=filename)
                for path, filename in files
            ]

            await interaction.response.edit_message(
                embeds=embeds,
                attachments=discord_files,
                view=view
            )

        @discord.ui.button(label="🧹 Clear Filters", style=discord.ButtonStyle.secondary, row=3)
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

            self.pages, self.inventory_ids = self.bot.get_cog("Inventory").build_gallery_pages(rows)
            self.page = 0
            await self.update(interaction)

        # -------------------------
        # ADD TO CART CALLBACK
        # -------------------------
        async def add_to_cart(self, interaction, inventory_id):
            await interaction.response.defer(ephemeral=True)

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

        # -------------------------
        # MORE INFO CALLBACK
        # -------------------------
        async def view_more_info(self, interaction, inventory_id):
            async with self.bot.db.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT series, set_name, variant, rarity
                    FROM inventory
                    WHERE inventory_id = $1;
                    """,
                    inventory_id
                )

            embed = discord.Embed(
                title="More Information",
                color=discord.Color.blue()
            )

            embed.description = (
                f"**Expansion:** {row['series']}\n"
                f"**Set:** {row['set_name']}\n"
                f"**Variant:** {row['variant'] or '—'}\n"
                f"**Rarity:** {row['rarity'] or '—'}\n"
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------
    # FILTER TYPE VIEW — WITH SERIES → SET FILTER
    # ------------------------------------------------------------
    class FilterTypeView(discord.ui.View):
        def __init__(
            self,
            bot,
            base_pokemon_name,
            base_set_name,
            filters,
            pages,
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

            # Pokémon name buckets
            if filter_type == "pokemon_name":
                options = [
                    discord.SelectOption(label="A–F", value="AF"),
                    discord.SelectOption(label="G–M", value="GM"),
                    discord.SelectOption(label="N–S", value="NS"),
                    discord.SelectOption(label="T–Z", value="TZ"),
                ]

            # SERIES → SET FILTER
            elif filter_type == "series":
                # Get all distinct series
                series_list = self.filter_options.get("series", [])
                options = [
                    discord.SelectOption(label=str(s), value=str(s))
                    for s in series_list
                ]

            # Standard filters
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

                # Pokémon name bucket
                if filter_type == "pokemon_name":
                    self.filters["pokemon_name_bucket"] = value

                # SERIES → SET (Step 1: Series chosen)
                elif filter_type == "series":
                    self.filters["series"] = value

                    # Fetch sets inside this series
                    async with self.bot.db.acquire() as conn:
                        rows = await conn.fetch(
                            """
                            SELECT DISTINCT set_name
                            FROM inventory
                            WHERE series = $1
                            ORDER BY set_name ASC;
                            """,
                            value
                        )

                    set_options = []
                    for r in rows:
                        set_name = r["set_name"]
                        if set_name == "151":
                            set_name_display = "Mew 151"
                        else:
                            set_name_display = set_name

                        set_options.append(
                            discord.SelectOption(
                                label=set_name_display,
                                value=set_name
                            )
                        )

                    # Build second dropdown for sets
                    set_select = discord.ui.Select(
                        placeholder="Select a Set",
                        min_values=1,
                        max_values=1,
                        options=set_options
                    )

                    async def set_select_callback(inter2: discord.Interaction):
                        chosen_set = set_select.values[0]
                        self.filters["set_name"] = chosen_set

                        rows2 = await self.bot.get_cog("Inventory").run_query(
                            pokemon_name=self.base_pokemon_name,
                            set_name=self.base_set_name,
                            filters=self.filters
                        )

                        if not rows2:
                            embed = discord.Embed(
                                title="Filters",
                                description="No results with that filter.",
                                color=discord.Color.gold()
                            )
                            await inter2.response.send_message(embed=embed, ephemeral=True)
                            return

                        self.pages, self.inventory_ids = (
                            self.bot.get_cog("Inventory").build_gallery_pages(rows2)
                        )
                        self.page = 0

                        main_view = Inventory.InventoryView(
                            bot=self.bot,
                            base_pokemon_name=self.base_pokemon_name,
                            base_set_name=self.base_set_name,
                            filters=self.filters,
                            pages=self.pages,
                            inventory_ids=self.inventory_ids,
                            filter_options=self.filter_options
                        )

                        embeds, files = self.pages[self.page]
                        discord_files = [
                            discord.File(path, filename=filename)
                            for path, filename in files
                        ]

                        await inter2.response.edit_message(
                            embeds=embeds,
                            attachments=discord_files,
                            view=main_view
                        )

                    set_select.callback = set_select_callback

                    view2 = discord.ui.View(timeout=180)
                    view2.add_item(set_select)

                    embed2 = discord.Embed(
                        title="Select Set",
                        description=f"Choose a set inside **{value}**.",
                        color=discord.Color.blue()
                    )

                    await inter.response.edit_message(
                        embed=embed2,
                        view=view2
                    )
                    return

                # Standard filters
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

                self.pages, self.inventory_ids = (
                    self.bot.get_cog("Inventory").build_gallery_pages(rows)
                )
                self.page = 0

                main_view = Inventory.InventoryView(
                    bot=self.bot,
                    base_pokemon_name=self.base_pokemon_name,
                    base_set_name=self.base_set_name,
                    filters=self.filters,
                    pages=self.pages,
                    inventory_ids=self.inventory_ids,
                    filter_options=self.filter_options
                )

                embeds, files = self.pages[self.page]
                discord_files = [
                    discord.File(path, filename=filename)
                    for path, filename in files
                ]

                await inter.response.edit_message(
                    embeds=embeds,
                    attachments=discord_files,
                    view=main_view
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

