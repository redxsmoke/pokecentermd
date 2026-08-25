import discord

# ---------------------------------------------------------
# Wishlist Dashboard View
# ---------------------------------------------------------
class WishlistDashboardView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.page = 0
        self.embed = None
        self.total_count = 0
        self.current_page_rows = []  # rows for dropdown

        # Buttons
        self.add_item(ViewDetailsButton(self))
        self.add_item(MostRequestedButton(self))

    async def load_page(self):
        async with self.interaction.client.db.acquire() as conn:

            # Count total wishlist entries
            self.total_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM user_wishlist
                WHERE guild_id = $1
                """,
                self.interaction.guild.id
            )

            rows = await conn.fetch(
                """
                SELECT wishlist_id,
                       user_id,
                       pokemon_name,
                       series,
                       set_name,
                       condition,
                       created_at
                FROM user_wishlist
                WHERE guild_id = $1
                ORDER BY wishlist_id ASC
                LIMIT 20 OFFSET $2
                """,
                self.interaction.guild.id,
                self.page * 20
            )

        self.current_page_rows = rows

        # Build page text
        if not rows:
            desc = "No wishlist entries found."
        else:
            blocks = []
            for r in rows:
                username = await self._resolve_username(r["user_id"])
                pokemon = r["pokemon_name"] or "(Any Pokémon)"
                series = r["series"] or "(Any Series)"
                set_name = r["set_name"] or "(Any Set)"
                condition = r["condition"] or "(Any Condition)"

                block = (
                    f"**{username}**\n"
                    f"- **ID:** {r['wishlist_id']}\n"
                    f"- **Pokémon:** {pokemon}\n"
                    f"- **Set:** {set_name}\n"
                    f"- **Series:** {series}\n"
                    f"- **Condition:** {condition}\n"
                )
                blocks.append(block)

            desc = "\n".join(blocks)

        # Build embed
        self.embed = discord.Embed(
            title=f"Wishlist Dashboard — Page {self.page + 1}",
            description=desc,
            color=discord.Color.blurple()
        )

        # Update button states
        self._update_buttons()

    def _update_buttons(self):
        total_pages = max(1, (self.total_count + 19) // 20)

        if total_pages == 1:
            self.prev_page.disabled = True
            self.next_page.disabled = True
            return

        self.prev_page.disabled = (self.page == 0)
        self.next_page.disabled = (self.page >= total_pages - 1)

    async def _resolve_username(self, user_id: int):
        user = self.interaction.guild.get_member(user_id)
        if user:
            return user.display_name
        return f"User {user_id}"

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        await self.load_page()
        await interaction.response.edit_message(embed=self.embed, view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self.load_page()
        await interaction.response.edit_message(embed=self.embed, view=self)


# ---------------------------------------------------------
# Button: View More Details (opens dropdown)
# ---------------------------------------------------------
class ViewDetailsButton(discord.ui.Button):
    def __init__(self, parent_view: WishlistDashboardView):
        super().__init__(label="View More Details", style=discord.ButtonStyle.primary)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        view = WishlistDetailsSelectView(interaction, self.parent_view.current_page_rows)
        await view.populate()
        await interaction.response.send_message(
            "Select an entry to view details:",
            view=view,
            ephemeral=True
        )


# ---------------------------------------------------------
# Button: Most Requested Pokémon
# ---------------------------------------------------------
class MostRequestedButton(discord.ui.Button):
    def __init__(self, parent_view: WishlistDashboardView):
        super().__init__(label="Most Requested Pokémon", style=discord.ButtonStyle.success)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):

        async with interaction.client.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT pokemon_name,
                       COUNT(*) AS count,
                       MIN(series) AS series,
                       MIN(set_name) AS set_name
                FROM user_wishlist
                WHERE guild_id = $1
                GROUP BY pokemon_name
                ORDER BY count DESC
                LIMIT 5
                """,
                interaction.guild.id
            )

        if not rows:
            await interaction.response.send_message(
                "No Pokémon requests found.",
                ephemeral=True
            )
            return

        bullets = []
        for r in rows:
            pokemon = r["pokemon_name"]
            count = r["count"]

            # NEW RULE:
            # If pokemon_name is NULL → treat as Any Pokémon and show series + set
            if pokemon is None:
                series = r["series"] or "(Any Series)"
                set_name = r["set_name"] or "(Any Set)"

                bullets.append(
                    f"- **(Any Pokémon)** — {count} requests\n"
                    f"  • **Series:** {series}\n"
                    f"  • **Set:** {set_name}"
                )
            else:
                bullets.append(f"- **{pokemon}** — {count} requests")

        desc = "\n".join(bullets)

        embed = discord.Embed(
            title="Top 5 Most Requested Pokémon",
            description=desc,
            color=discord.Color.gold()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
# Dropdown View (uses current page rows)
# ---------------------------------------------------------
class WishlistDetailsSelectView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, page_rows):
        super().__init__(timeout=120)
        self.interaction = interaction
        self.page_rows = page_rows

        self.select = WishlistDetailsSelect()
        self.add_item(self.select)

    async def populate(self):
        rows = self.page_rows

        # Sort by wishlist_id ASC
        rows = sorted(rows, key=lambda r: r["wishlist_id"])

        if not rows:
            self.select.options = [
                discord.SelectOption(label="No entries on this page", value="none")
            ]
            return

        options = []
        for r in rows[:25]:  # Discord max 25 options
            user = self.interaction.guild.get_member(r["user_id"])
            username = user.display_name if user else f"User {r['user_id']}"

            pokemon = r["pokemon_name"] or "(Any Pokémon)"

            label = f"{username} — {pokemon} (ID {r['wishlist_id']})"

            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(r["wishlist_id"])
                )
            )

        self.select.options = options


# ---------------------------------------------------------
# Dropdown
# ---------------------------------------------------------
class WishlistDetailsSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Select an entry",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="Loading…", value="loading")]
        )

    async def callback(self, interaction: discord.Interaction):
        wid = self.values[0]

        if wid == "none":
            await interaction.response.send_message("No entries available on this page.", ephemeral=True)
            return

        await send_wishlist_details(interaction, int(wid))


# ---------------------------------------------------------
# Helper: Send Details (clean bulleted list)
# ---------------------------------------------------------
async def send_wishlist_details(interaction: discord.Interaction, wishlist_id: int):
    async with interaction.client.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM user_wishlist
            WHERE wishlist_id = $1
            """,
            wishlist_id
        )

    if not row:
        await interaction.response.send_message("Wishlist entry not found.", ephemeral=True)
        return

    username = interaction.guild.get_member(row["user_id"])
    username = username.display_name if username else f"User {row['user_id']}"

    pokemon = row["pokemon_name"] or "(Any Pokémon)"
    series = row["series"] or "(Any Series)"
    set_name = row["set_name"] or "(Any Set)"
    condition = row["condition"] or "(Any Condition)"
    price = str(row["price"]) if row["price"] else "(Any Price)"
    notes = row["notes"] or "None"

    desc = (
        f"**{username}**\n"
        f"- **Pokémon:** {pokemon}\n"
        f"- **Series:** {series}\n"
        f"- **Set:** {set_name}\n"
        f"- **Condition:** {condition}\n"
        f"- **Price:** {price}\n"
        f"- **Notes:** {notes}\n"
    )

    embed = discord.Embed(
        title=f"Wishlist Details — ID {wishlist_id}",
        description=desc,
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)
