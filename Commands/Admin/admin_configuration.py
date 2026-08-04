import discord
from discord import ui


class SetAdminChannelView(ui.View):
    def __init__(self, bot, guild_id, current_admin_channel_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

        # Dynamic label
        if current_admin_channel_id is None:
            label = "Set This Channel as Admin Channel"
        else:
            label = "Update Admin Channel to This Channel"

        # Create dynamic button
        self.button = ui.Button(
            label=label,
            style=discord.ButtonStyle.primary
        )
        self.button.callback = self.set_channel
        self.add_item(self.button)

    async def set_channel(self, interaction: discord.Interaction):
        channel_id = interaction.channel.id

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO guild_settings (guild_id, admin_channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET admin_channel_id = EXCLUDED.admin_channel_id
                """,
                self.guild_id,
                channel_id
            )

        embed = discord.Embed(
            title="Admin Channel Updated",
            description=f"This channel (**{interaction.channel.mention}**) is now set as the admin channel.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def bot_settings(interaction: discord.Interaction):
    """This function will be registered by admincommands.py"""

    guild_id = interaction.guild.id

    # Fetch current admin channel
    async with interaction.client.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT admin_channel_id FROM guild_settings WHERE guild_id = $1",
            guild_id
        )

    current_admin_channel_id = row["admin_channel_id"] if row else None

    embed = discord.Embed(
        title="Bot Settings — Admin Configuration",
        description=(
            "**Admin Channel Requirement**\n"
            "This bot requires an **Admin Channel** for inventory management.\n\n"
            "The admin channel is used for:\n"
            "• Running the Add Single Wizard\n"
            "• Uploading card images\n"
            "• Logging inventory actions\n\n"
            "**Important:**\n"
            "The admin channel **must be restricted** to:\n"
            "• Server administrators\n"
            "• The bot\n\n"
            "This prevents regular users from interfering with inventory operations. If this is not the channel you would like to be the admin channel, please navigate to the correct channel and run this command again"
        ),
        color=discord.Color.blurple()
    )

    view = SetAdminChannelView(interaction.client, guild_id, current_admin_channel_id)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
