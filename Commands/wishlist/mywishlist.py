import discord
from discord.ext import commands
from discord import ui, app_commands

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
        }

        self.step = WishlistStep.MODAL
        self.message: discord.Message | None = None

    async def start(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Add Wishlist Filter",
            description="Click **Next** to begin.",
            color=discord.Color.blurple()
        )

        msg = await interaction.channel.send(embed=embed, view=self)
        self.message = msg

        await interaction.response.defer(ephemeral=True)

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
                description="All fields are optional, but **at least one must be entered** to save.\n\nClick **Next** to enter Pokémon name, variant, price, and notes.",
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
    async def back_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.step == WishlistStep.MODAL:
            await interaction.response.defer()
            return

        self.step -= 1
        await interaction.response.defer()
        await self.update()

    @ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.step == WishlistStep.MODAL:
            await interaction.response.send_modal(WishlistModal(self))
            return

        if self.step == WishlistStep.CONDITION:
            self.step = WishlistStep.SERIES_PROMPT
            await interaction.response.defer()
            await self.update()
            return

        if self.step == WishlistStep.SERIES_PROMPT:
            await interaction.response.defer()
            return

        if self.step == WishlistStep.SERIES:
            await interaction.response.defer()
            return

        if self.step == WishlistStep.SET:
            await interaction.response.defer()
            return

        if self.step == WishlistStep.CONFIRM:
            await self.finish(interaction)
            return

    @ui.button(label="Finish", style=discord.ButtonStyle.success, disabled=True)
    async def finish_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.finish(interaction)

    async def add_series_dropdown(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT series FROM expansion_list ORDER BY series"
            )

        options = [
            discord.SelectOption(label=row["series"], value=row["series"])
            for row in rows
        ]

        self.add_item(SeriesSelect(self, options))

    async def add_set_dropdown(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT set_name FROM expansion_list WHERE series = $1 ORDER BY set_name",
                self.state["series"]
            )

        options = [
            discord.SelectOption(label=row["set_name"], value=row["set_name"])
            for row in rows
        ]

        self.add_item(SetSelect(self, options))

    async def finish(self, interaction: discord.Interaction):
        if interaction.guild is None:
            embed = discord.Embed(
                title="Command Not Allowed",
                description="This command can't be used in DMs.\n\nPlease run it inside a server channel.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if (
            not self.state["pokemon_name"]
            and not self.state["variant"]
            and not self.state["price"]
            and not self.state["condition"]
            and not self.state["series"]
            and not self.state["set_name"]
            and not self.state["notes"]
        ):
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
                    variant, condition, price, notes
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
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
            )

        embed = discord.Embed(
            title="Wishlist Saved",
            description="Your wishlist filter has been saved.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
        self.stop()

class WishlistModal(ui.Modal, title="Wishlist Filters"):
    pokemon_name = ui.TextInput(label="Pokémon Name", required=False)
    variant = ui.TextInput(label="Variant", required=False)
    price = ui.TextInput(label="Max Price", required=False)
    notes = ui.TextInput(label="Notes", required=False)

    def __init__(self, wizard: WishlistWizardView):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        self.wizard.state["pokemon_name"] = self.pokemon_name.value.strip() or None
        self.wizard.state["variant"] = self.variant.value.strip() or None
        self.wizard.state["notes"] = self.notes.value.strip() or None

        raw = self.price.value.strip()
        if raw:
            try:
                raw = raw.replace("$", "").replace(",", "")
                self.wizard.state["price"] = float(raw)
            except:
                await interaction.response.send_message(
                    "Price must be a number.",
                    ephemeral=True
                )
                return

        self.wizard.step = WishlistStep.CONDITION
        await interaction.response.defer()
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

        await interaction.response.defer()
        await self.wizard.update()

class SeriesPromptYes(ui.Button):
    def __init__(self, wizard: WishlistWizardView):
        super().__init__(label="Yes", style=discord.ButtonStyle.success)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.step = WishlistStep.SERIES
        await interaction.response.defer()
        await self.wizard.update()

class SeriesPromptNo(ui.Button):
    def __init__(self, wizard: WishlistWizardView):
        super().__init__(label="No", style=discord.ButtonStyle.secondary)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.step = WishlistStep.CONFIRM
        await interaction.response.defer()
        await self.wizard.update()

class SeriesSelect(ui.Select):
    def __init__(self, wizard: WishlistWizardView, options: list[discord.SelectOption]):
        super().__init__(placeholder="Select Series", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.state["series"] = self.values[0]
        self.wizard.step = WishlistStep.SET
        await interaction.response.defer()
        await self.wizard.update()

class SetSelect(ui.Select):
    def __init__(self, wizard: WishlistWizardView, options: list[discord.SelectOption]):
        super().__init__(placeholder="Select Set", options=options)
        self.wizard = wizard

    async def callback(self, interaction: discord.Interaction):
        self.wizard.state["set_name"] = self.values[0]
        self.wizard.step = WishlistStep.CONFIRM
        await interaction.response.defer()
        await self.wizard.update()

class Wishlist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    mywishlist = app_commands.Group(
        name="mywishlist",
        description="Manage wishlist filters"
    )

    @mywishlist.command(name="add", description="Add a wishlist filter.")
    async def mywishlist_add(self, interaction: discord.Interaction):
        view = WishlistWizardView(self.bot, interaction.user)
        await view.start(interaction)

    @mywishlist.command(name="list", description="List your wishlist filters.")
    async def mywishlist_list(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT wishlist_id, pokemon_name, series, set_name,
                       variant, condition, price, notes
                FROM user_wishlist
                WHERE guild_id = $1 AND user_id = $2
                ORDER BY wishlist_id ASC
                """,
                interaction.guild.id,
                interaction.user.id
            )

        if not rows:
            await interaction.response.send_message(
                "You have no wishlist filters.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Your Wishlist Filters",
            color=discord.Color.blurple()
        )

        for row in rows:
            # Dynamic title (priority)
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
            else:
                title = "Wishlist Filter"

            # Build body
            parts = []

            if row["pokemon_name"]:
                parts.append(f"★ Name: {row['pokemon_name']}")

            if row["price"] is not None:
                parts.append(f"★ Price: < ${row['price']:.2f}")

            if row["condition"]:
                parts.append(f"★ Condition: {row['condition']}")

            if row["set_name"]:
                parts.append(f"★ Set: {row['set_name']}")

            if row["series"]:
                parts.append(f"★ Series: {row['series']}")

            body = "```text\n" + "\n".join(parts) + "\n```"

            embed.add_field(
                name=title,
                value=body,
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @mywishlist.command(name="remove", description="Remove a wishlist filter.")
    async def mywishlist_remove(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT wishlist_id, pokemon_name, price, condition, set_name, series
                FROM user_wishlist
                WHERE guild_id = $1 AND user_id = $2
                ORDER BY wishlist_id ASC
                """,
                interaction.guild.id,
                interaction.user.id
            )

        if not rows:
            await interaction.response.send_message(
                "You have no wishlist filters.",
                ephemeral=True
            )
            return

        options = []

        for row in rows:
            parts = []

            if row["pokemon_name"]:
                parts.append(f"★ {row['pokemon_name']}")

            if row["price"] is not None:
                parts.append(f"Less than ${row['price']:.2f}")

            if row["condition"]:
                parts.append(f"Condition: {row['condition']}")

            if row["set_name"]:
                parts.append(f"Set: {row['set_name']}")

            if row["series"]:
                parts.append(f"Series: {row['series']}")

            label = " – ".join(parts)

            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(row["wishlist_id"])
                )
            )

        class RemoveSelect(ui.Select):
            def __init__(self):
                super().__init__(placeholder="Select a filter to remove", options=options)

            async def callback(self, inner_interaction):
                wid = int(self.values[0])

                async with inner_interaction.client.db.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT pokemon_name, price, condition, set_name, series
                        FROM user_wishlist
                        WHERE wishlist_id = $1 AND guild_id = $2 AND user_id = $3
                        """,
                        wid,
                        interaction.guild.id,
                        interaction.user.id
                    )

                    await conn.execute(
                        """
                        DELETE FROM user_wishlist
                        WHERE wishlist_id = $1 AND guild_id = $2 AND user_id = $3
                        """,
                        wid,
                        interaction.guild.id,
                        interaction.user.id
                    )

                parts = []

                if row["pokemon_name"]:
                    parts.append(f"★ {row['pokemon_name']}")

                if row["price"] is not None:
                    parts.append(f"Less than ${row['price']:.2f}")

                if row["condition"]:
                    parts.append(f"Condition: {row['condition']}")

                if row["set_name"]:
                    parts.append(f"Set: {row['set_name']}")

                if row["series"]:
                    parts.append(f"Series: {row['series']}")

                label = " – ".join(parts)

                embed = discord.Embed(
                    title="Wishlist Filter Removed",
                    description=label,
                    color=discord.Color.red()
                )

                await inner_interaction.response.send_message(embed=embed, ephemeral=True)

        view = ui.View()
        view.add_item(RemoveSelect())

        await interaction.response.send_message(
            "Select a wishlist filter to remove:",
            view=view,
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(Wishlist(bot))
