import discord
from discord import app_commands
from discord.ext import commands
import logging

import shop_state
from Commands.Cart.cart import CheckoutStartView
from Commands.Inventory.inventory_filter import FilterTypeView

GALLERY_PAGE_SIZE = 6
log = logging.getLogger("inventory")

class PokemonSearchModal(discord.ui.Modal, title="Search Pokémon"):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
        self.pokemon_name = discord.ui.TextInput(
            label="Pokémon Name",
            required=True,
            max_length=100
        )
        self.add_item(self.pokemon_name)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.pokemon_name.value.strip()
        inventory_cog = self.parent_view.bot.get_cog("Inventory")

        if not inventory_cog:
            await interaction.response.send_message(
                "Inventory system is not available.",
                ephemeral=True
            )
            return

        rows = await inventory_cog.run_query(
            pokemon_name=name,
            set_name=self.parent_view.base_set_name,
            filters=self.parent_view.filters,
            guild_id=interaction.guild.id
        )

        if not rows:
            await interaction.response.send_message(
                f"No results found for **{name}**.",
                ephemeral=True
            )
            return

        self.parent_view.pages, self.parent_view.inventory_ids = inventory_cog.build_gallery_pages(rows)
        self.parent_view.page = 0

        embeds, files = self.parent_view.pages[0]
        discord_files = [
            discord.File(path, filename=filename)
            for path, filename in files
        ]

        # IMPORTANT FIX: rebuild dropdowns so add-to-cart updates
        self.parent_view.build_dropdowns()

        await interaction.response.edit_message(
            embeds=embeds,
            attachments=discord_files,
            view=self.parent_view
        )
class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="shop",
        description="Browse the Shop! Apply filters after results appear."
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
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            log.error(f"defer() failed: {e}")
            await interaction.followup.send("❌ Failed to start inventory.", ephemeral=True)
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
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        filters = {}
        rows = await self.run_query(
            pokemon_name=pokemon_name,
            set_name=set_name,
            filters=filters,
            guild_id=interaction.guild.id
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

        conditions = await self.get_distinct_values("condition", interaction.guild.id)
        series_list = await self.get_distinct_values("series", interaction.guild.id)
        variants = await self.get_distinct_values("variant", interaction.guild.id)
        rarities = await self.get_distinct_values("rarity", interaction.guild.id)

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

    async def run_query(self, pokemon_name=None, set_name=None, filters=None, guild_id=None):
        where_clauses = ["quantity_available >= 1"]
        params = []

        if guild_id is not None:
            where_clauses.append(f"guild_id = ${len(params)+1}")
            params.append(guild_id)

        if pokemon_name:
            where_clauses.append(f"pokemon_name ILIKE ${len(params)+1}")
            params.append(f"%{pokemon_name}%")

        if set_name:
            where_clauses.append(f"set_name ILIKE ${len(params)+1}")
            params.append(f"%{set_name}%")

        if filters:
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

            if filters.get("set_bucket_AL"):
                where_clauses.append("LEFT(set_name, 1) ~* '^[A-L]'")

            if filters.get("set_bucket_MZ"):
                where_clauses.append("(LEFT(set_name, 1) ~* '^[M-Z]' OR set_name = '151')")

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
            return await conn.fetch(query, *params)

    async def get_distinct_values(self, column_name: str, guild_id: int):
        query = f"""
            SELECT DISTINCT {column_name}
            FROM inventory
            WHERE quantity_available >= 1
              AND {column_name} IS NOT NULL
              AND guild_id = $1
            ORDER BY {column_name} ASC;
        """
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(query, guild_id)
        return [r[column_name] for r in rows]

    def build_gallery_pages(self, rows):
        pages = []
        inventory_ids = []
        current_embeds = []
        current_files = []

        for row in rows:
            inventory_ids.append(row["inventory_id"])

            card_number = row["card_number"] or "—"
            set_display = "Mew 151" if row["set_name"] == "151" else row["set_name"]

            title = f"{row['pokemon_name']} #{card_number} — {set_display}"

            embed = discord.Embed(title=title, color=discord.Color.gold())
            if row["image_link"]:
                embed.set_thumbnail(url=row["image_link"])

            graded_text = "Yes" if row["graded"] else "No"

            embed.description = (
                "__**Card Details**__\n\n"
                f"**Price:** ${row['price']}\n"
                f"**Condition:** {row['condition'] or 'Near Mint'}\n"
                f"**Graded:** {graded_text}\n"
            )
            embed.set_footer(text=f"Inventory ID: {row['inventory_id']}")

            current_embeds.append(embed)

            if len(current_embeds) == GALLERY_PAGE_SIZE:
                pages.append((current_embeds, current_files))
                current_embeds = []
                current_files = []

        if current_embeds:
            pages.append((current_embeds, current_files))

        return pages, inventory_ids

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

            self.previous.row = 0
            self.next.row = 0
            self.add_item(self.previous)
            self.add_item(self.next)

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

            self.filters_button.row = 3
            self.clear_filters.row = 3
            self.add_item(self.filters_button)
            self.add_item(self.clear_filters)

        async def update(self, interaction: discord.Interaction):
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

        @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.primary, row=0)
        async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page > 0:
                self.page -= 1
            await self.update(interaction)

        @discord.ui.button(label="Next ➡", style=discord.ButtonStyle.primary, row=0)
        async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page < len(self.pages) - 1:
                self.page += 1
            await self.update(interaction)

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

            async def filter_type_callback(interaction: discord.Interaction):
                selected = filter_type_select.values[0]

                if selected == "pokemon_name":
                    await interaction.response.send_modal(PokemonSearchModal(self))
                    return

                view = FilterTypeView(
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

            filter_type_select.callback = filter_type_callback

            embeds, files = self.pages[self.page]
            discord_files = [
                discord.File(path, filename=filename)
                for path, filename in files
            ]

            view = discord.ui.View()
            view.add_item(filter_type_select)
            await interaction.response.edit_message(
                embeds=embeds,
                attachments=discord_files,
                view=view
            )

        @discord.ui.button(label="🧹 Clear Filters", style=discord.ButtonStyle.secondary, row=3)
        async def clear_filters(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.filters.clear()

            inventory_cog = self.bot.get_cog("Inventory")
            rows = await inventory_cog.run_query(
                pokemon_name=self.base_pokemon_name,
                set_name=self.base_set_name,
                filters=self.filters,
                guild_id=interaction.guild.id
            )

            if not rows:
                embed = discord.Embed(
                    title="Filters",
                    description="No results after clearing filters.",
                    color=discord.Color.gold()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            self.pages, self.inventory_ids = inventory_cog.build_gallery_pages(rows)
            self.page = 0
            self.build_dropdowns()
            await self.update(interaction)

        async def add_to_cart(self, interaction: discord.Interaction, inventory_id: int):
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
                    f"You already have **{already}** of this item.\n"
                    f"Only **{available}** available.",
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
                description=f"**{inv['pokemon_name']} — {inv['set_name']}** added to your cart.",
                color=discord.Color.green()
            )

            view = discord.ui.View()

            checkout_button = discord.ui.Button(
                label="Checkout",
                style=discord.ButtonStyle.success
            )

            async def checkout_callback(interaction: discord.Interaction):
                checkout_view = CheckoutStartView(self.bot, interaction.user.id)
                ok = await checkout_view.async_init(interaction)
                if ok is False:
                    return

                embed2 = discord.Embed(
                    title="Checkout",
                    description="Select shipping and payment method:",
                    color=discord.Color.blue()
                )

                await interaction.response.edit_message(embed=embed2, view=checkout_view)

            checkout_button.callback = checkout_callback
            view.add_item(checkout_button)

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        async def view_more_info(self, interaction: discord.Interaction, inventory_id: int):
            async with self.bot.db.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT series, set_name, variant, rarity
                    FROM inventory
                    WHERE inventory_id = $1;
                    """,
                    inventory_id
                )

            if not row:
                await interaction.response.send_message("Item no longer exists.", ephemeral=True)
                return

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

async def setup(bot):
    print("INVENTORY COG LOADED")
<<<<<<< HEAD
    await bot.add_cog(Inventory(bot))




async def setup(bot):
    print("INVENTORY COG LOADED")
    await bot.add_cog(Inventory(bot))

