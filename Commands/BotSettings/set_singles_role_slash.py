import discord
from discord import app_commands

# ---------------------------------------------------------
# AUTOCOMPLETE — unlimited roles
# ---------------------------------------------------------
async def singles_role_autocomplete(interaction: discord.Interaction, current: str):
    roles = interaction.guild.roles

    filtered = [
        r for r in roles
        if current.lower() in r.name.lower()
    ][:25]

    return [
        app_commands.Choice(name=r.name, value=str(r.id))
        for r in filtered
    ]


# ---------------------------------------------------------
# SLASH COMMAND CALLBACK (standalone function)
# ---------------------------------------------------------
@app_commands.default_permissions(administrator=True)
async def set_singles_role_callback(interaction: discord.Interaction, role: str):

    # Extra safety check (Discord sometimes fails default_permissions)
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You must be an **Administrator** to use this command.",
            ephemeral=True
        )
        return

    role_obj = interaction.guild.get_role(int(role))
    if role_obj is None:
        await interaction.response.send_message(
            "❌ That role no longer exists.",
            ephemeral=True
        )
        return

    guild_id = interaction.guild.id

    # DB update — use interaction.client (the bot)
    bot = interaction.client

    async with bot.db.acquire() as conn:
        await conn.execute(
            """
            UPDATE guild_settings
            SET singles_role_id = $1
            WHERE guild_id = $2
            """,
            role_obj.id,
            guild_id
        )

    embed = discord.Embed(
        title="Singles Role Updated",
        description=f"Singles notifications will now be sent to members with the role: {role_obj.mention}",
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)
