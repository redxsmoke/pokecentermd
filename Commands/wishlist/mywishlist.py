import discord
from discord.ext import commands
from discord import ui, app_commands

PAGE_SIZE = 20

class WishlistStep:
    MODAL = 1
    CONDITION = 2
    SERIES_PROMPT = 3
    SERIES = 4
    SET = 5
    CONFIRM = 6

class WishlistWizardView(ui.View):
    def __init__(self, bot, user):
        super().__init__(timeout=1200)
        self.bot = bot
        self.user = user

        self.state = {
            "pokemon_name": None,
            "variant": None,
            "price": None,
            "condition": None,
            "series": None,
            "set_name": None,
            "notes": None,
            "illustrator": None,
        }

        self.step = WishlistStep.MODAL
        self.message = None

    async def start(self, interaction):
        embed = discord.Embed(
            title="Add Wishlist Filter",
            description="Click **Next** to begin.",
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
        self.message = await interaction.original_response()

    async def update(self):
        self.clear_items()

        if self.step == WishlistStep.SERIES_PROMPT:
            self.add_item(SeriesPromptYes(self))
            self.add_item(SeriesPromptNo(self))
        else:
            self.add_item(self.back_button)
            self.add_item(self.next_button)

        if self.step == WishlistStep.CONDITION:
            self.add_item(ConditionSelect(self))

        if self.step == WishlistStep.SERIES:
            await self.add_series_dropdown()

        if self.step == WishlistStep.SET:
            await self.add_set_dropdown()

        self.finish_button.disabled = (self.step != WishlistStep.CONFIRM)
        self.add_item(self.finish_button)

        embed = self.build_embed()
        await self.message.edit(embed=embed, view=self)

    def build_embed(self):
        if self.step == WishlistStep.MODAL:
            return discord.Embed(
                title="Step 1 — Basic Filters",
                description="All fields optional, but at least one must be entered.\n\n"
                            "Click **Next** to enter Pokémon name, variant, price, illustrator, and notes.",
                color=discord.Color.blurple()
            )

        if self.step == WishlistStep.CONDITION:
            return discord.Embed(
                title="Step 2 — Condition",
                description="Select the card condition.",
                color=discord.Color.blurple()
            )

        if self.step == WishlistStep.SERIES_PROMPT:
            return discord.Embed(
                title="Step 3 — Series + Set?",
                description="Would you like to add Series + Set filters?",
                color=discord.Color.blurple()
            )

        if self.step == WishlistStep.SERIES:
            return discord.Embed(
                title="Step 4 — Series",
                description="Select a Series.",
                color=discord.Color.blurple()
            )

        if self.step == WishlistStep.SET:
            return discord.Embed(
                title="Step 5 — Set",
                description="Select a Set.",
                color=discord.Color.blurple()
            )

        if self.step == WishlistStep.CONFIRM:
            embed = discord.Embed(
                title="Step 6 — Confirm",
                description="Review your wishlist filter.",
                color=discord.Color.green()
            )
            for key, value in self.state.items():
                if key == "price" and value is not None:
                    value = f"${value:.2f}"
                embed.add_field(
                    name=key.replace("_", " ").title(),
                    value=value or "Any",
                    inline=False
                )
            return embed

    @ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction, button):
        if self.step == WishlistStep.MODAL:
            await interaction.response.defer(ephemeral=True)
            return
        self.step -= 1
        await interaction.response.defer(ephemeral=True)
        await self.update()

    @ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction, button):
        if self.step == WishlistStep.MODAL:
            await interaction.response.send_modal(WishlistModal(self))
            return

        if self.step == WishlistStep.CONDITION:
            self.step = WishlistStep.SERIES_PROMPT
            await interaction.response.defer(ephemeral=True)
            await self.update()
            return

        if self.step in (WishlistStep.SERIES_PROMPT, WishlistStep.SERIES, WishlistStep.SET):
            await interaction.response.defer(ephemeral=True)
            return

        if self.step == WishlistStep.CONFIRM:
            await self.finish(interaction)
            return

    @ui.button(label="Finish", style=discord.ButtonStyle.success, disabled=True)
    async def finish_button(self, interaction, button):
        await self.finish(interaction)

    async def add_series_dropdown(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("SELECT DISTINCT series FROM expansion_list ORDER BY series")
        options = [discord.SelectOption(label=r["series"], value=r["series"]) for r in rows]
        self.add_item(SeriesSelect(self, options))

    async def add_set_dropdown(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT set_name FROM expansion_list WHERE series = $1 ORDER BY set_name",
                self.state["series"]
            )
        options = [discord.SelectOption(label=r["set_name"], value=r["set_name"]) for r in rows]
        self.add_item(SetSelect(self, options))

    async def finish(self, interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Command Not Allowed",
                    description="This command must be used in a server.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        if not any(self.state.values()):
            await interaction.response.send_message(
                "You must enter at least one field.",
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_wishlist (
                    guild_id, user_id,
                    pokemon_name, series, set_name,
                    variant, condition, price, notes, illustrator
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                interaction.guild.id,
                self.user.id,
                self.state["pokemon_name"],
                self.state["series"],
                self.state["set_name"],
                self.state["variant"],
                self.state["condition"],
                self.state["price"],
                self.state["notes"],
                self.state["illustrator"],
            )

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Wishlist Saved",
                description="Your wishlist filter has been saved.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )
        self.stop()
class WishlistModal(ui.Modal, title="Wishlist Filters"):
    pokemon_name = ui.TextInput(label="Pokémon Name", required=False)
    variant = ui.TextInput(label="Variant", required=False)
    price = ui.TextInput(label="Max Price", required=False)
    illustrator = ui.TextInput(label="Illustrator", required=False)
    notes = ui.TextInput(label="Notes", required=False)

    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction):
        self.wizard.state["pokemon_name"] = self.pokemon_name.value.strip() or None
        self.wizard.state["variant"] = self.variant.value.strip() or None
        self.wizard.state["notes"] = self.notes.value.strip() or None
        self.wizard.state["illustrator"] = self.illustrator.value.strip() or None

        raw = self.price.value.strip()
        if raw:
            try:
                raw = raw.replace("$", "").replace(",", "")
                self.wizard.state["price"] = float(raw)
            except:
                await interaction.response.send_message(
                    "Price must be a valid number.",
                    ephemeral=True
                )
                return

        self.wizard.step = WishlistStep.CONDITION
        await interaction.response.defer(ephemeral=True)
        await self.wizard.update()

class ConditionSelect(ui.Select):
    def __init__(self, wizard: WishlistWizardView):
        options = [
            discord.SelectOption(label="Any", value="Any"),
            discord.SelectOption(label="Near Mint", value="Near Mint"),
            discord.SelectOption(label="Lightly Played", value="Lightly Played"),
            discord.SelectOption(label="Moderately Played", value="Moderately Played"),
            discord.SelectOption(label="Heavily Played", value="Heavily Played"),
            discord.SelectOption(label="Damaged", value="Damaged"),
            discord.SelectOption(label="Graded", value="Graded"),
        ]
        super().__init__(placeholder="Select Condition", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        self.wizard.state["condition"] = None if val == "Any" else val
        self.wizard.step = WishlistStep.SERIES_PROMPT
        await interaction.response.defer(ephemeral=True)
        await self.wizard.update()

class SeriesPromptYes(ui.Button):
    def __init__(self, wizard: WishlistWizardView):
        super().__init__(label="Yes", style=discord.ButtonStyle.success)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.step = WishlistStep.SERIES
        await interaction.response.defer(ephemeral=True)
        await self.wizard.update()


class SeriesPromptNo(ui.Button):
    def __init__(self, wizard: WishlistWizardView):
        super().__init__(label="No", style=discord.ButtonStyle.secondary)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.step = WishlistStep.CONFIRM
        await interaction.response.defer(ephemeral=True)
        await self.wizard.update()


class SeriesSelect(ui.Select):
    def __init__(self, wizard: WishlistWizardView, options: list[discord.SelectOption]):
        super().__init__(placeholder="Select Series", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.state["series"] = self.values[0]
        self.wizard.step = WishlistStep.SET
        await interaction.response.defer(ephemeral=True)
        await self.wizard.update()


class SetSelect(ui.Select):
    def __init__(self, wizard: WishlistWizardView, options: list[discord.SelectOption]):
        super().__init__(placeholder="Select Set", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.state["set_name"] = self.values[0]
        self.wizard.step = WishlistStep.CONFIRM
        await interaction.response.defer(ephemeral=True)
        await self.wizard.update()


class WishlistListView(ui.View):
    def __init__(self, rows, guild_id, user_id):
        super().__init__(timeout=1200)
        self.rows = rows
        self.guild_id = guild_id
        self.user_id = user_id
        self.page = 0
        self.message = None
        self.remove_mode = False
        self.remove_select = None

    @property
    def total_pages(self):
        if not self.rows:
            return 1
        return (len(self.rows) - 1) // PAGE_SIZE + 1

    def _page_slice(self):
        start = self.page * PAGE_SIZE
        end = start + PAGE_SIZE
        return self.rows[start:end]

    def build_list_embed(self):
        embed = discord.Embed(
            title=f"Your Wishlist Filters (Page {self.page + 1}/{self.total_pages})",
            color=discord.Color.blurple()
        )

        page_rows = self._page_slice()
        description_parts = []

        for row in page_rows:
            title = "Wishlist Filter"

            if row["pokemon_name"]:
                title = f"{row['pokemon_name']} Filter"
            elif row["price"] is not None:
                title = f"< ${row['price']:.2f} Filter"
            elif row["condition"]:
                title = f"{row['condition']} Filter"
            elif row["set_name"]:
                title = f"{row['set_name']} Filter"
            elif row["series"]:
                title = f"{row['series']} Filter"
            elif row.get("illustrator"):
                title = f"{row['illustrator']} Filter"

            parts = []

            if row["pokemon_name"]:
                parts.append(f"★ Name: {row['pokemon_name']}")

            if row["variant"]:
                parts.append(f"★ Variant: {row['variant']}")

            if row["price"] is not None:
                parts.append(f"★ Price: < ${row['price']:.2f}")

            if row["condition"]:
                parts.append(f"★ Condition: {row['condition']}")

            if row["series"]:
                parts.append(f"★ Series: {row['series']}")

            if row["set_name"]:
                parts.append(f"★ Set: {row['set_name']}")

            if row.get("illustrator"):
                parts.append(f"★ Illustrator: {row['illustrator']}")

            if row["notes"]:
                parts.append(f"★ Notes: {row['notes']}")

            body = "```text\n" + "\n".join(parts) + "\n```"
            description_parts.append(f"**{title}**\n{body}")

        embed.description = "\n\n".join(description_parts) if description_parts else "No filters on this page."
        return embed

    def build_remove_embed(self):
        embed = discord.Embed(
            title=f"Remove Wishlist Item (Page {self.page + 1}/{self.total_pages})",
            color=discord.Color.red()
        )

        page_rows = self._page_slice()
        lines = []

        for row in page_rows:
            parts = []

            if row["pokemon_name"]:
                parts.append(f"{row['pokemon_name']}")

            if row["condition"]:
                parts.append(f"Condition: {row['condition']}")

            if row["set_name"]:
                parts.append(f"Set: {row['set_name']}")

            if row["price"] is not None:
                parts.append(f"< ${row['price']:.2f}")

            if row.get("illustrator"):
                parts.append(f"Illustrator: {row['illustrator']}")

            label = " – ".join(parts) if parts else "Wishlist Filter"
            if len(label) > 100:
                label = label[:97] + "..."

            lines.append(f"• {label}")

        embed.description = (
            "Select a wishlist filter to remove:\n\n" + "\n".join(lines)
            if lines else "No filters on this page."
        )

        return embed

    def update_buttons(self):
        if self.remove_mode:
            return

        self.prev_button.disabled = (self.page == 0 or self.total_pages <= 1)
        self.next_button.disabled = (self.page >= self.total_pages - 1 or self.total_pages <= 1)
        self.remove_button.disabled = (len(self.rows) == 0)

    async def refresh(self):
        if self.message is None:
            return

        self.clear_items()

        if self.remove_mode:
            self.build_remove_select()
            self.add_item(self.remove_prev_button)
            self.add_item(self.remove_next_button)
            self.add_item(self.cancel_button)

            self.remove_prev_button.disabled = (self.page == 0 or self.total_pages <= 1)
            self.remove_next_button.disabled = (self.page >= self.total_pages - 1 or self.total_pages <= 1)

            embed = self.build_remove_embed()
            await self.message.edit(embed=embed, view=self)
        else:
            self.add_item(self.prev_button)
            self.add_item(self.next_button)
            self.add_item(self.add_button)
            self.add_item(self.remove_button)

            self.update_buttons()

            embed = self.build_list_embed()
            await self.message.edit(embed=embed, view=self)

    async def on_timeout(self):
        if self.message:
            await self.message.edit(view=None)

    def build_remove_select(self):
        page_rows = self._page_slice()
        options = []

        for row in page_rows:
            parts = []

            if row["pokemon_name"]:
                parts.append(row["pokemon_name"])

            if row["condition"]:
                parts.append(f"Condition: {row['condition']}")

            if row["set_name"]:
                parts.append(f"Set: {row['set_name']}")

            if row["price"] is not None:
                parts.append(f"< ${row['price']:.2f}")

            if row.get("illustrator"):
                parts.append(f"Illustrator: {row['illustrator']}")

            label = " – ".join(parts) if parts else "Wishlist Filter"
            if len(label) > 100:
                label = label[:97] + "..."

            options.append(discord.SelectOption(label=label, value=str(row["wishlist_id"])))

        if self.remove_select:
            self.remove_item(self.remove_select)

        class RemoveSelect(ui.Select):
            def __init__(self, parent, opts):
                super().__init__(placeholder="Select a wishlist filter to remove", options=opts)
                self.owner = parent

            async def callback(self_inner, interaction):
                wid = int(self_inner.values[0])

                async with interaction.client.db.acquire() as conn:
                    await conn.execute(
                        """
                        DELETE FROM user_wishlist
                        WHERE wishlist_id = $1 AND guild_id = $2 AND user_id = $3
                        """,
                        wid,
                        self_inner.owner.guild_id,
                        self_inner.owner.user_id
                    )

                self_inner.owner.rows = [
                    r for r in self_inner.owner.rows if r["wishlist_id"] != wid
                ]

                if not self_inner.owner.rows:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Wishlist Filter Removed",
                            description="The wishlist filter was removed successfully.",
                            color=discord.Color.green()
                        ),
                        ephemeral=True
                    )
                    if self_inner.owner.message:
                        await self_inner.owner.message.edit(view=None)
                    self_inner.owner.stop()
                    return

                if self_inner.owner.page >= self_inner.owner.total_pages:
                    self_inner.owner.page = max(0, self_inner.owner.total_pages - 1)

                self_inner.owner.remove_mode = False

                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Wishlist Filter Removed",
                        description="The wishlist filter was removed successfully.",
                        color=discord.Color.green()
                    ),
                    ephemeral=True
                )

                await self_inner.owner.refresh()

        self.remove_select = RemoveSelect(self, options)
        self.add_item(self.remove_select)

    @ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction, button):
        if self.page > 0:
            self.page -= 1
        await interaction.response.defer()
        await self.refresh()

    @ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction, button):
        if self.page < self.total_pages - 1:
            self.page += 1
        await interaction.response.defer()
        await self.refresh()

    @ui.button(label="➕ Add wishlist item", style=discord.ButtonStyle.success)
    async def add_button(self, interaction, button):
        wizard = WishlistWizardView(interaction.client, interaction.user)
        await wizard.start(interaction)

    @ui.button(label="🗑️ Remove wishlist item", style=discord.ButtonStyle.danger)
    async def remove_button(self, interaction, button):
        if not self.rows:
            await interaction.response.defer()
            return
        self.remove_mode = True
        await interaction.response.defer()
        await self.refresh()

    @ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def remove_prev_button(self, interaction, button):
        if self.page > 0:
            self.page -= 1
        await interaction.response.defer()
        await self.refresh()

    @ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def remove_next_button(self, interaction, button):
        if self.page < self.total_pages - 1:
            self.page += 1
        await interaction.response.defer()
        await self.refresh()

    @ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction, button):
        await interaction.response.send_message("Changes cancelled.", ephemeral=True)
        if self.message:
            await self.message.edit(view=None)
        self.stop()
class Wishlist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="mywishlist",
        description="View and manage your wishlist filters."
    )
    async def mywishlist(self, interaction: discord.Interaction):

        # ⭐ Updated SQL to include illustrator
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT wishlist_id,
                       pokemon_name,
                       series,
                       set_name,
                       variant,
                       condition,
                       price,
                       notes,
                       illustrator
                FROM user_wishlist
                WHERE guild_id = $1 AND user_id = $2
                ORDER BY wishlist_id ASC
                """,
                interaction.guild.id,
                interaction.user.id
            )

        # ⭐ FIX: If user has no wishlist items, still show Add button
        if not rows:
            view = WishlistListView([], interaction.guild.id, interaction.user.id)

            embed = discord.Embed(
                title="Your Wishlist Filters",
                description="You have no wishlist filters.",
                color=discord.Color.blurple()
            )

            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()
            await view.refresh()
            return

        # ⭐ Normal case: user has wishlist items
        view = WishlistListView(rows, interaction.guild.id, interaction.user.id)
        embed = view.build_list_embed()

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()
        await view.refresh()


async def setup(bot: commands.Bot):
    await bot.add_cog(Wishlist(bot))



