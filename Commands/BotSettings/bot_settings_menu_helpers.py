import discord

# ---------------------------------------------------------
# SET ADMIN CHANNEL
# ---------------------------------------------------------
async def set_admin_channel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Admin Channel Updated",
        description="The admin channel has been successfully updated.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
# SET WELCOME CHANNEL
# ---------------------------------------------------------
async def set_welcome_channel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Welcome Channel Updated",
        description="The welcome channel has been successfully updated.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
# SET ANNOUNCEMENT CHANNEL
# ---------------------------------------------------------
async def set_announcement_channel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Announcement Channel Updated",
        description="The announcement channel has been successfully updated.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
# SET PAYMENT INFO
# ---------------------------------------------------------
async def set_payment_info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Payment Info Updated",
        description="Payment information has been successfully updated.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
# SET SINGLES ROLE
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
# SET SINGLES CHANNEL
# ---------------------------------------------------------
async def set_singles_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    async with interaction.client.db.acquire() as conn:
        await conn.execute(
            """
            UPDATE guild_settings
            SET singles_channel_id = $1
            WHERE guild_id = $2
            """,
            channel.id,
            interaction.guild.id
        )

    embed = discord.Embed(
        title="Singles Notification Channel Updated",
        description=f"Singles notifications will now be sent in: {channel.mention}",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
# TOGGLE SINGLES NOTIFICATIONS
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
        "Singles notifications have been **enabled**. Members will now receive Singles alerts."
        if new_value else
        "Singles notifications have been **disabled**. Members will no longer receive Singles alerts."
    )

    embed = discord.Embed(
        title="Singles Notifications Updated",
        description=status_text,
        color=discord.Color.green() if new_value else discord.Color.red()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)
