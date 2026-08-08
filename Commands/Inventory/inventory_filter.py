import discord
import logging

log = logging.getLogger("inventory")


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
            log.info(f"[INV] FilterTypeView.filter_type_callback filter_type={filter_type}")
            await self.show_filter_options(inter, filter_type)

        self.filter_type_select.callback = filter_type_callback
        self.add_item(self.filter_type_select)

    async def show_filter_options(self, interaction: discord.Interaction, filter_type: str):
        log.info(f"[INV] show_filter_options() filter_type={filter_type}")

        #
        # Pokémon-name filter removed — autocomplete handles it
        #
        if filter_type == "pokemon_name":
            embed = discord.Embed(
                title="Pokémon Name Filter",
                description="Use the autocomplete search in the /inventory command.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        #
        # Build dropdown options
        #
        if filter_type == "series":
            values = self.filter_options.get("series", [])
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
            log.info(f"[INV] filter_value_callback filter_type={filter_type} value={value}")

            #
            # SERIES → requires second dropdown for set selection
            #
            if filter_type == "series":
                self.filters["series"] = value

                async with self.bot.db.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT DISTINCT set_name
                        FROM inventory
                        WHERE series = $1
                          AND quantity_available >= 1
                          AND guild_id = $2
                        ORDER BY set_name ASC;
                        """,
                        value,
                        inter.guild.id
                    )

                set_options = []
                for r in rows:
                    set_name = r["set_name"]
                    set_display = "Mew 151" if set_name == "151" else set_name

                    set_options.append(
                        discord.SelectOption(
                            label=set_display,
                            value=set_name
                        )
                    )

                set_select = discord.ui.Select(
                    placeholder="Select a Set",
                    min_values=1,
                    max_values=1,
                    options=set_options
                )

                async def set_select_callback(inter2: discord.Interaction):
                    chosen_set = set_select.values[0]
                    log.info(f"[INV] set_select_callback chosen_set={chosen_set}")

                    self.filters["set_name"] = chosen_set

                    inventory_cog = self.bot.get_cog("Inventory")
                    rows2 = await inventory_cog.run_query(
                        pokemon_name=self.base_pokemon_name,
                        set_name=self.base_set_name,
                        filters=self.filters,
                        guild_id=inter2.guild.id
                    )

                    if not rows2:
                        embed = discord.Embed(
                            title="Filters",
                            description="No results with that filter.",
                            color=discord.Color.gold()
                        )
                        await inter2.response.send_message(embed=embed, ephemeral=True)
                        return

                    self.pages, self.inventory_ids = inventory_cog.build_gallery_pages(rows2)
                    self.page = 0

                    main_view = inventory_cog.InventoryView(
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

            #
            # NON-SERIES FILTERS
            #
            self.filters[filter_type] = value

            inventory_cog = self.bot.get_cog("Inventory")
            rows2 = await inventory_cog.run_query(
                pokemon_name=self.base_pokemon_name,
                set_name=self.base_set_name,
                filters=self.filters,
                guild_id=inter.guild.id
            )

            if not rows2:
                embed = discord.Embed(
                    title="Filters",
                    description="No results with that filter.",
                    color=discord.Color.gold()
                )
                await inter.response.send_message(embed=embed, ephemeral=True)
                return

            self.pages, self.inventory_ids = inventory_cog.build_gallery_pages(rows2)
            self.page = 0

            main_view = inventory_cog.InventoryView(
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

        view2 = discord.ui.View(timeout=180)
        view2.add_item(filter_value_select)

        embed = discord.Embed(
            title="Select Filter Value",
            description="Choose a value for the selected filter.",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=view2
        )