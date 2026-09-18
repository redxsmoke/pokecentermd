import math
import discord
from discord import app_commands
from discord.ext import commands

from db.connection import get_pool

PER_PAGE = 6

SortOption = (
    "most_caught",
    "least_caught",
    "region",
    "name",
    "most_progress",
    "least_progress",
)


class PokedexEntry:
    __slots__ = (
        "pokedex_id",
        "pokemon_name",
        "pokemon_region",
        "quantity",
        "catch_rate",
        "pokemon_image",
        "region_progress",
        "region_unique_caught",
        "region_total_unique",
    )

    def __init__(
        self,
        pokedex_id,
        pokemon_name,
        pokemon_region,
        quantity,
        catch_rate,
        pokemon_image,
        region_progress,
        region_unique_caught,
        region_total_unique,
    ):
        self.pokedex_id = pokedex_id
        self.pokemon_name = pokemon_name
        self.pokemon_region = pokemon_region
        self.quantity = quantity
        self.catch_rate = catch_rate
        self.pokemon_image = pokemon_image
        self.region_progress = region_progress
        self.region_unique_caught = region_unique_caught
        self.region_total_unique = region_total_unique


# ---------------------------------------------------------
# REGION PROGRESS
# ---------------------------------------------------------
async def fetch_region_progress_map(user_id: int, guild_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH total AS (
                SELECT pokemon_region, COUNT(DISTINCT pokedex_id) AS total_unique
                FROM cd_pokemon
                GROUP BY pokemon_region
            ),
            user_region AS (
                SELECT pokemon_region, COUNT(DISTINCT pokedex_id) AS unique_caught
                FROM user_pokemon
                WHERE user_id = $1 AND guild_id = $2
                GROUP BY pokemon_region
            )
            SELECT
                t.pokemon_region,
                COALESCE(u.unique_caught, 0) AS unique_caught,
                t.total_unique
            FROM total t
            LEFT JOIN user_region u
              ON u.pokemon_region = t.pokemon_region;
            """,
            user_id,
            guild_id,
        )

    result = {}
    for r in rows:
        result[r["pokemon_region"]] = {
            "unique_caught": r["unique_caught"],
            "total_unique": r["total_unique"],
        }
    return result


# ---------------------------------------------------------
# FETCH USER POKEMON
# ---------------------------------------------------------
async def fetch_user_pokedex_entries(
    user_id: int,
    guild_id: int,
    name_filter,
    region_filter,
    sort,
):
    pool = get_pool()
    async with pool.acquire() as conn:
        params = [user_id, guild_id]
        where = ["up.user_id = $1", "up.guild_id = $2"]
        idx = 3

        if name_filter:
            where.append(f"up.pokemon_name ILIKE ${idx}")
            params.append(f"%{name_filter}%")
            idx += 1

        if region_filter:
            where.append(f"up.pokemon_region = ${idx}")
            params.append(region_filter)
            idx += 1

        where_sql = " AND ".join(where)

        rows = await conn.fetch(
            f"""
            SELECT
                up.pokedex_id,
                up.pokemon_name,
                up.pokemon_region,
                up.quantity,
                cd.catch_rate,
                cd.pokemon_image
            FROM user_pokemon up
            JOIN cd_pokemon cd USING (pokedex_id)
            WHERE {where_sql};
            """,
            *params,
        )

    region_progress_map = await fetch_region_progress_map(user_id, guild_id)

    entries = []
    for r in rows:
        region = r["pokemon_region"]
        rp = region_progress_map.get(region, {"unique_caught": 0, "total_unique": 0})
        unique_caught = rp["unique_caught"]
        total_unique = rp["total_unique"]
        progress = unique_caught / total_unique if total_unique > 0 else 0.0

        entries.append(
            PokedexEntry(
                pokedex_id=r["pokedex_id"],
                pokemon_name=r["pokemon_name"],
                pokemon_region=region,
                quantity=r["quantity"],
                catch_rate=r["catch_rate"],
                pokemon_image=r["pokemon_image"],
                region_progress=progress,
                region_unique_caught=unique_caught,
                region_total_unique=total_unique,
            )
        )

    # Sorting
    if sort == "most_caught":
        entries.sort(key=lambda e: e.quantity, reverse=True)
    elif sort == "least_caught":
        entries.sort(key=lambda e: e.quantity)
    elif sort == "region":
        entries.sort(key=lambda e: (e.pokemon_region.lower(), e.pokemon_name.lower()))
    elif sort == "name":
        entries.sort(key=lambda e: e.pokemon_name.lower())
    elif sort == "most_progress":
        entries.sort(key=lambda e: e.region_progress, reverse=True)
    elif sort == "least_progress":
        entries.sort(key=lambda e: e.region_progress)
    else:
        entries.sort(key=lambda e: e.pokemon_name.lower())

    return entries


# ---------------------------------------------------------
# FETCH ALL REGIONS
# ---------------------------------------------------------
async def fetch_all_regions():
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT pokemon_region FROM cd_pokemon ORDER BY pokemon_region;"
        )
    return [r["pokemon_region"] for r in rows]


# ---------------------------------------------------------
# UI COMPONENTS
# ---------------------------------------------------------
class NameFilterModal(discord.ui.Modal, title="Filter by Pokémon Name"):
    name = discord.ui.TextInput(
        label="Pokémon Name",
        placeholder="Enter partial name",
        required=False,
        max_length=100,
    )

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view  # FIXED

    async def on_submit(self, interaction):
        self.parent_view.name_filter = self.name.value.strip() or None
        self.parent_view.current_page = 0
        await self.parent_view.refresh(interaction)


class RegionSelect(discord.ui.Select):
    def __init__(self, parent_view, regions):
        self.parent_view = parent_view  # FIXED

        options = [
            discord.SelectOption(
                label="All Regions",
                value="__all__",
                default=parent_view.region_filter is None,
            )
        ]

        for r in regions:
            options.append(
                discord.SelectOption(
                    label=r,
                    value=r,
                    default=parent_view.region_filter == r,
                )
            )

        super().__init__(
            placeholder="Select Region",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction):
        value = self.values[0]
        self.parent_view.region_filter = None if value == "__all__" else value
        self.parent_view.current_page = 0
        await self.parent_view.refresh(interaction)



class SortSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view  # FIXED

        options = [
            discord.SelectOption(label="Most Caught", value="most_caught"),
            discord.SelectOption(label="Least Caught", value="least_caught"),
            discord.SelectOption(label="Region", value="region"),
            discord.SelectOption(label="Pokémon Name", value="name"),
            discord.SelectOption(label="Most Progress (Region)", value="most_progress"),
            discord.SelectOption(label="Least Progress (Region)", value="least_progress"),
        ]

        super().__init__(
            placeholder="Sort By",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction):
        self.parent_view.sort = self.values[0]
        self.parent_view.current_page = 0
        await self.parent_view.refresh(interaction)

# ---------------------------------------------------------
# MAIN VIEW
# ---------------------------------------------------------
class PokedexView(discord.ui.View):
    def __init__(
        self,
        user,
        guild,
        entries,
        name_filter,
        region_filter,
        sort,
        regions,
    ):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.entries = entries
        self.name_filter = name_filter
        self.region_filter = region_filter
        self.sort = sort
        self.current_page = 0
        self.regions = regions

        self.add_item(RegionSelect(self, regions))
        self.add_item(SortSelect(self))

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction, button):
        if self.current_page > 0:
            self.current_page -= 1
        await self.refresh(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction, button):
        if self.current_page < self.max_page:
            self.current_page += 1
        await self.refresh(interaction)

    @discord.ui.button(label="Filter Name", style=discord.ButtonStyle.primary)
    async def filter_name_button(self, interaction, button):
        await interaction.response.send_modal(NameFilterModal(self))

    @property
    def max_page(self):
        if not self.entries:
            return 0
        return max(0, math.ceil(len(self.entries) / PER_PAGE) - 1)

    async def refresh(self, interaction):
        self.entries = await fetch_user_pokedex_entries(
            self.user.id,
            self.guild.id,
            self.name_filter,
            self.region_filter,
            self.sort,
        )

        if self.current_page > self.max_page:
            self.current_page = self.max_page

        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == self.max_page

        embeds = self.build_page_embeds()
        header = self.build_header_text()

        await interaction.response.edit_message(content=header, embeds=embeds, view=self)

    def build_header_text(self):
        total = len(self.entries)
        page_info = f"Page {self.current_page + 1}/{self.max_page + 1 if total else 1}"

        filters = []
        if self.name_filter:
            filters.append(f"Name: `{self.name_filter}`")
        if self.region_filter:
            filters.append(f"Region: `{self.region_filter}`")

        sort_label = {
            "most_caught": "Most Caught",
            "least_caught": "Least Caught",
            "region": "Region",
            "name": "Pokémon Name",
            "most_progress": "Most Progress (Region)",
            "least_progress": "Least Progress (Region)",
        }.get(self.sort, "Pokémon Name")

        filter_text = " | ".join(filters) if filters else "No filters"

        return (
            f"**Pokédex for {self.user.mention}**\n"
            f"{page_info} | Sort: **{sort_label}**\n"
            f"{filter_text}"
        )

    def build_page_embeds(self):
        embeds = []
        if not self.entries:
            embed = discord.Embed(
                title="Pokédex",
                description="You haven't caught any Pokémon yet.",
                color=discord.Color.red(),
            )
            embeds.append(embed)
            return embeds

        start = self.current_page * PER_PAGE
        end = start + PER_PAGE
        page_entries = self.entries[start:end]

        for e in page_entries:
            embed = discord.Embed(
                title=e.pokemon_name,
                color=discord.Color.blurple(),
            )

            embed.add_field(name="Region", value=e.pokemon_region, inline=True)
            embed.add_field(
                name="Region Progress",
                value=f"{e.region_unique_caught}/{e.region_total_unique}",
                inline=True,
            )
            embed.add_field(name="Caught", value=str(e.quantity), inline=True)
            embed.add_field(name="Catch Rate", value=f"{e.catch_rate}%", inline=True)

            embed.set_thumbnail(url=e.pokemon_image)

            embeds.append(embed)

        return embeds


# ---------------------------------------------------------
# COG
# ---------------------------------------------------------
class PokedexCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="pokedex", description="View your caught Pokémon")
    async def pokedex(self, interaction: discord.Interaction):
        user = interaction.user
        guild = interaction.guild

        regions = await fetch_all_regions()

        entries = await fetch_user_pokedex_entries(
            user.id,
            guild.id,
            name_filter=None,
            region_filter=None,
            sort="name",
        )

        view = PokedexView(
            user=user,
            guild=guild,
            entries=entries,
            name_filter=None,
            region_filter=None,
            sort="name",
            regions=regions,
        )

        await interaction.response.send_message(
            content=f"**Pokédex for {user.mention}**",
            embeds=view.build_page_embeds(),
            view=view,
        )


async def setup(bot):
    await bot.add_cog(PokedexCog(bot))
