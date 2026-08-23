import asyncpg
import discord

# ---------------------------------------------------------
# GET ADMIN CHANNEL
# ---------------------------------------------------------
async def get_admin_channel(bot, guild_id: int):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT admin_channel_id
            FROM guild_settings
            WHERE guild_id = $1
            """,
            guild_id
        )

    if not row or not row["admin_channel_id"]:
        return None

    channel_id = row["admin_channel_id"]
    guild = bot.get_guild(guild_id)

    if guild is None:
        return None

    return guild.get_channel(channel_id)


# ---------------------------------------------------------
# GET SINGLES ROLE
# ---------------------------------------------------------
async def get_singles_role(bot, guild_id: int):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT singles_role_id
            FROM guild_settings
            WHERE guild_id = $1
            """,
            guild_id
        )

    if not row or not row["singles_role_id"]:
        return None

    role_id = row["singles_role_id"]
    guild = bot.get_guild(guild_id)

    if guild is None:
        return None

    return guild.get_role(role_id)


# ---------------------------------------------------------
# GET SINGLES NOTIFICATIONS ENABLED
# ---------------------------------------------------------
async def get_singles_notifications_enabled(bot, guild_id: int):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT singles_notifications_enabled
            FROM guild_settings
            WHERE guild_id = $1
            """,
            guild_id
        )

    # Default to TRUE if missing
    if not row:
        return True

    return row["singles_notifications_enabled"]


# ---------------------------------------------------------
# GET SINGLES NOTIFICATION CHANNEL  (NEW)
# ---------------------------------------------------------
async def get_singles_channel(bot, guild_id: int):
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT singles_channel_id
            FROM guild_settings
            WHERE guild_id = $1
            """,
            guild_id
        )

    if not row or not row["singles_channel_id"]:
        return None

    channel_id = row["singles_channel_id"]
    guild = bot.get_guild(guild_id)

    if guild is None:
        return None

    return guild.get_channel(channel_id)


# ---------------------------------------------------------
# SET SINGLES NOTIFICATION CHANNEL  (NEW)
# ---------------------------------------------------------
async def set_singles_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id = interaction.guild.id

    async with interaction.client.db.acquire() as conn:
        await conn.execute(
            """
            UPDATE guild_settings
            SET singles_channel_id = $1
            WHERE guild_id = $2
            """,
            channel.id,
            guild_id
        )

    embed = discord.Embed(
        title="Singles Notification Channel Updated",
        description=f"Singles notifications will now be sent in: {channel.mention}",
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------------------------------------------------------
# SET SINGLES ROLE  (REQUIRED)
# ---------------------------------------------------------
async def set_singles_role(interaction: discord.Interaction, role: discord.Role):
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
        description=f"Singles notifications will now be sent to members with the role: {role.mention}",
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

