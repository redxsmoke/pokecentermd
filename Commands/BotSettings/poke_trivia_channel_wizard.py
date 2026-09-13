# poke_trivia_channel_wizard.py

import discord

async def start_poke_trivia_wizard(interaction: discord.Interaction):
    """Enable/Disable Poké Trivia with a wizard for channel selection."""

    # Fetch current settings
    async with interaction.client.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT poke_trivia_enabled, poke_trivia_channel_id
            FROM guild_settings
            WHERE guild_id = $1
            """,
            interaction.guild.id,
        )

        if row is None:
            await conn.execute(
                """
                INSERT INTO guild_settings (guild_id, poke_trivia_enabled, poke_trivia_channel_id)
                VALUES ($1, FALSE, NULL)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                interaction.guild.id,
            )
            poke_trivia_enabled = False
            poke_trivia_channel_id = None
        else:
            poke_trivia_enabled = row["poke_trivia_enabled"]
            poke_trivia_channel_id = row["poke_trivia_channel_id"]

    # ============================================================
    #   DISABLE FLOW
    # ============================================================
    if poke_trivia_enabled:
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE guild_settings
                SET poke_trivia_enabled = FALSE
                WHERE guild_id = $1
                """,
                interaction.guild.id,
            )

        embed = discord.Embed(
            title="Poké Trivia Disabled",
            description="Poké Trivia has been **disabled** for this server.",
            color=discord.Color.red(),
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # ============================================================
    #   ENABLE FLOW — CATEGORY SELECT
    # ============================================================
    class CategorySelect(discord.ui.Select):
        def __init__(self):
            options = []
            categories = interaction.guild.categories[:25]

            if not categories:
                options.append(
                    discord.SelectOption(
                        label="No categories available",
                        value="none",
                        description="Create a category first.",
                    )
                )
            else:
                for category in categories:
                    options.append(
                        discord.SelectOption(
                            label=category.name,
                            value=str(category.id),
                        )
                    )

            super().__init__(
                placeholder="Select a category for Poké Trivia",
                options=options,
            )

        async def callback(self, category_interaction: discord.Interaction):
            if self.values[0] == "none":
                await category_interaction.response.send_message(
                    embed=discord.Embed(
                        title="No Categories Found",
                        description="This server has no categories. Please create one and try again.",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True,
                )
                return

            category_id = int(self.values[0])
            category = category_interaction.guild.get_channel(category_id)

            # ============================================================
            #   CHANNEL SELECT
            # ============================================================
            class ChannelSelect(discord.ui.Select):
                def __init__(self, target_category: discord.CategoryChannel):
                    channels = [
                        ch for ch in target_category.channels
                        if isinstance(ch, discord.TextChannel)
                        and ch.permissions_for(category_interaction.guild.me).send_messages
                    ]

                    options = []
                    if not channels:
                        options.append(
                            discord.SelectOption(
                                label="No text channels available",
                                value="none",
                                description="Create a text channel in this category.",
                            )
                        )
                    else:
                        for ch in channels[:25]:
                            options.append(
                                discord.SelectOption(
                                    label=f"#{ch.name}",
                                    value=str(ch.id),
                                )
                            )

                    super().__init__(
                        placeholder="Select the channel for Poké Trivia",
                        options=options,
                    )

                async def callback(self, channel_interaction: discord.Interaction):
                    if self.values[0] == "none":
                        await channel_interaction.response.send_message(
                            embed=discord.Embed(
                                title="No Channels Found",
                                description="This category has no usable text channels.",
                                color=discord.Color.red(),
                            ),
                            ephemeral=True,
                        )
                        return

                    channel_id = int(self.values[0])
                    channel = channel_interaction.guild.get_channel(channel_id)

                    # Save to DB
                    async with channel_interaction.client.db.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE guild_settings
                            SET poke_trivia_enabled = TRUE,
                                poke_trivia_channel_id = $1
                            WHERE guild_id = $2
                            """,
                            channel.id,
                            channel_interaction.guild.id,
                        )

                    embed = discord.Embed(
                        title="Poké Trivia Enabled",
                        description=(
                            f"Poké Trivia was **enabled successfully**.\n\n"
                            f"Questions will be posted in {channel.mention}.\n\n"
                            "If that channel becomes unavailable, trivia will fall back to a general text channel."
                        ),
                        color=discord.Color.green(),
                    )

                    await channel_interaction.response.send_message(
                        embed=embed,
                        ephemeral=True,
                    )

            class ChannelSelectView(discord.ui.View):
                def __init__(self, target_category):
                    super().__init__(timeout=300)
                    self.add_item(ChannelSelect(target_category))

            channel_embed = discord.Embed(
                title="Select Poké Trivia Channel",
                description=(
                    f"Category selected: **{category.name}**\n\n"
                    "Now choose which text channel in this category should receive Poké Trivia questions."
                ),
                color=discord.Color.blurple(),
            )

            await category_interaction.response.send_message(
                embed=channel_embed,
                view=ChannelSelectView(category),
                ephemeral=True,
            )

    class CategorySelectView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(CategorySelect())

    embed = discord.Embed(
        title="Enable Poké Trivia",
        description=(
            "Poké Trivia is currently **disabled**.\n\n"
            "To enable it, please select the **category** where your trivia channel lives.\n"
            "You'll then choose the specific text channel for trivia posts."
        ),
        color=discord.Color.blurple(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=CategorySelectView(),
        ephemeral=True,
    )
