import discord
from discord import ui


class SetWelcomeChannelView(ui.View):
    def __init__(self, bot, guild_id, current_welcome_channel_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

        # Dynamic label
        if current_welcome_channel_id is None:
            label = "Set This Channel as Welcome Channel"
        else:
            label = "Update Welcome Channel to This Channel"

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
                INSERT INTO guild_settings (guild_id, welcome_channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET welcome_channel_id = EXCLUDED.welcome_channel_id
                """,
                self.guild_id,
                channel_id
            )

        embed = discord.Embed(
            title="Welcome Channel Updated",
            description=f"This channel (**{interaction.channel.mention}**) is now set as the welcome channel.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def set_welcome_channel(interaction: discord.Interaction):
    """This function will be registered by admincommands.py"""

    guild_id = interaction.guild.id

    # Fetch current welcome channel
    async with interaction.client.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT welcome_channel_id FROM guild_settings WHERE guild_id = $1",
            guild_id
        )

    current_welcome_channel_id = row["welcome_channel_id"] if row else None

    embed = discord.Embed(
        title="Bot Settings — Welcome Channel",
        description=(
            "**Welcome Channel Purpose**\n"
            "This bot will automatically greet new members when they join your server.\n\n"
            "The welcome channel is used for:\n"
            "• Sending a friendly welcome message\n"
            "• Showing new users the list of **available user commands**\n"
            "• Helping new members understand how to interact with the bot\n\n"
            "**Important:**\n"
            "The welcome channel should be visible to:\n"
            "• All members\n"
            "• The bot\n\n"
            "If this is not the correct channel, navigate to the correct one and run this command again."
        ),
        color=discord.Color.blurple()
    )

    view = SetWelcomeChannelView(interaction.client, guild_id, current_welcome_channel_id)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
