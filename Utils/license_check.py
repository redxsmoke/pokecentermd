import discord

async def check_license(interaction: discord.Interaction):
    """Global license gate for ALL interactions."""

    guild_id = interaction.guild_id

    # Allow DMs
    if guild_id is None:
        return True

    # Fetch guild license status
    try:
        row = await interaction.client.db.fetchrow("""
            SELECT license_active
            FROM guild_settings
            WHERE guild_id = $1
        """, guild_id)
    except Exception as e:
        await _send_license_error(
            interaction,
            title="Database Error",
            description="Could not verify license status. Please contact support."
        )
        return False

    # No row found → guild not registered
    if row is None:
        await _send_license_error(
            interaction,
            title="Guild Not Registered",
            description="This guild is not registered to use the bot."
        )
        return False

    # Normalize license value
    license_value = row["license_active"]

    # Convert weird DB values into boolean
    inactive_values = {False, 0, "0", "false", "False", "inactive", None}

    if license_value in inactive_values:
        await _send_license_error(
            interaction,
            title="License Inactive",
            description=(
                "This bot is not licensed for this guild.\n"
                "Please contact the vendor to activate your license."
            )
        )
        return False

    # License active
    return True


async def _send_license_error(interaction: discord.Interaction, title: str, description: str):
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.red()
    )

    try:
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.InteractionResponded:
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception:
            pass
