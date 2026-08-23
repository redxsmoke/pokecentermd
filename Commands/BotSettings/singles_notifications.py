import discord
from discord.ext import commands

async def set_singles_role(interaction: discord.Interaction, role: discord.Role):
    """Admin command to set the Singles role."""
    guild_id = interaction.guild.id

    async with interaction.client.db.acquire() as conn:
        await conn.execute(
            """
            UPDATE guild_settings
            SET singles_role_id = $1
            WHERE guild_id = $2
            """,
            role.id,
            guild_id
        )

    embed = discord.Embed(
        title="Singles Role Updated",
        description=f"The Singles role has been set to: {role.mention}",
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


async def toggle_singles_notifications(interaction: discord.Interaction):
    """Admin command to enable/disable Singles notifications."""
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

        current = row["singles_notifications_enabled"] if row else True
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

    status = "ENABLED" if new_value else "DISABLED"
    color = discord.Color.green() if new_value else discord.Color.red()

    embed = discord.Embed(
        title="Singles Notifications Updated",
        description=f"Singles notifications are now **{status}**.",
        color=color
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)
