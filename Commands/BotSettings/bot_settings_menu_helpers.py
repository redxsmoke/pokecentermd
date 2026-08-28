import discord

# ---------------------------------------------------------
# UNIVERSAL CHANNEL SETTER VIEW
# ---------------------------------------------------------
class SetChannelView(discord.ui.View):
    def __init__(self, bot, guild_id, column_name, label):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.column_name = column_name
        self.label = label

        # Set button
        self.set_button = discord.ui.Button(
            label=f"Set This Channel as {label}",
            style=discord.ButtonStyle.primary
        )
        self.set_button.callback = self.set_channel
        self.add_item(self.set_button)

        # Cancel button
        self.cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger
        )
        self.cancel_button.callback = self.cancel
        self.add_item(self.cancel_button)

    async def set_channel(self, interaction: discord.Interaction):
        channel_id = interaction.channel.id

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO guild_settings (guild_id, {self.column_name})
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET {self.column_name} = EXCLUDED.{self.column_name}
                """,
                self.guild_id,
                channel_id
            )

        embed = discord.Embed(
            title=f"{self.label} Updated",
            description=f"This channel (**{interaction.channel.mention}**) is now set as the {self.label}.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cancel(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "❌ Channel update cancelled.",
            ephemeral=True
        )


# ---------------------------------------------------------
# HELPER WRAPPER
# ---------------------------------------------------------
async def _send_channel_setter(interaction, column_name, label, description):
    guild_id = interaction.guild.id

    embed = discord.Embed(
        title=f"Bot Settings — {label}",
        description=description,
        color=discord.Color.blurple()
    )

    view = SetChannelView(interaction.client, guild_id, column_name, label)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ---------------------------------------------------------
# SET ADMIN CHANNEL (UPDATED)
# ---------------------------------------------------------
async def set_admin_channel(interaction: discord.Interaction):
    await _send_channel_setter(
        interaction,
        column_name="admin_channel_id",
        label="Admin Channel",
        description="This channel is used for all administrative bot actions."
    )


# ---------------------------------------------------------
# SET WELCOME CHANNEL (UPDATED)
# ---------------------------------------------------------
async def set_welcome_channel(interaction: discord.Interaction):
    await _send_channel_setter(
        interaction,
        column_name="welcome_channel_id",
        label="Welcome Channel",
        description="This channel is used to greet new members."
    )


# ---------------------------------------------------------
# SET ANNOUNCEMENT CHANNEL (UPDATED)
# ---------------------------------------------------------
async def set_announcement_channel(interaction: discord.Interaction):
    await _send_channel_setter(
        interaction,
        column_name="announcement_channel_id",
        label="Announcement Channel",
        description="This channel receives bot announcements."
    )


# ---------------------------------------------------------
# SET PAYMENT INFO (UPDATED — NOW WORKS)
# ---------------------------------------------------------
async def set_payment_info(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None:
        embed = discord.Embed(
            title="Payment Settings",
            description="❌ This command cannot be used in DMs.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    from Commands.BotSettings.payment_settings import PaymentSettingsView

    embed = discord.Embed(
        title="Bot Settings — Payment Methods",
        description=(
            "Configure the payment handles used for checkout.\n\n"
            "**Supported methods:**\n"
            "• Venmo (must start with `@`)\n"
            "• CashApp (must start with `$`)\n"
            "• PayPal (any identifier)\n\n"
            "You may leave any field blank if you do not use that method.\n"
            "The guild owner will be stored as the administrator for these settings."
        ),
        color=discord.Color.blurple()
    )

    view = PaymentSettingsView(interaction.client, guild.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ---------------------------------------------------------
# SET SINGLES ROLE (UNCHANGED)
# ---------------------------------------------------------
async def set_singles_role(interaction: discord.Interaction, role: discord.Role):
    async with interaction.client.db.acquire() as conn:
        await conn.execute(
            """
            UPDATE guild_settings
            SET singles_role_id = $1
            WHERE guild_id = $2
            """,
            role.id,
            interaction.guild.id
        )

    embed = discord.Embed(
        title="Singles Role Updated",
        description=f"Singles notifications will now be sent to members with the role: {role.mention}",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
# SET SINGLES CHANNEL (NOW MATCHES WELCOME CHANNEL)
# ---------------------------------------------------------
async def set_singles_channel(interaction: discord.Interaction):
    await _send_channel_setter(
        interaction,
        column_name="singles_channel_id",
        label="Singles Notification Channel",
        description="This channel receives singles notifications."
    )


# ---------------------------------------------------------
# SET UPCOMING SHOWS CHANNEL (NOW MATCHES WELCOME CHANNEL)
# ---------------------------------------------------------
async def set_upcoming_shows_channel(interaction: discord.Interaction):
    await _send_channel_setter(
        interaction,
        column_name="upcoming_shows_channel_id",
        label="Upcoming Shows Channel",
        description="This channel receives upcoming show announcements."
    )


# ---------------------------------------------------------
# TOGGLE SINGLES NOTIFICATIONS (UNCHANGED)
# ---------------------------------------------------------
async def toggle_singles_notifications(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    async with interaction.client.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT singles_notifications_enabled
            FROM guild_settings
            WHERE guild_id = $1
            """,
            guild_id
        )

        current = row["singles_notifications_enabled"] if row else False
        new_value = not current

        await conn.execute(
            """
            UPDATE guild_settings
            SET singles_notifications_enabled = $1
            WHERE guild_id = $2
            """,
            new_value,
            guild_id
        )

    status_text = (
        "Singles notifications have been **enabled**."
        if new_value else
        "Singles notifications have been **disabled**."
    )

    embed = discord.Embed(
        title="Singles Notifications Updated",
        description=status_text,
        color=discord.Color.green() if new_value else discord.Color.red()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)
