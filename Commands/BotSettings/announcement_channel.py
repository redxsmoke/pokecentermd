import discord
from discord import ui

GREEN = discord.Color.green()


class SetAnnouncementChannelView(ui.View):
    def __init__(self, bot, guild_id, current_announcement_channel_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

        label = (
            "Set This Channel as Announcement Channel"
            if current_announcement_channel_id is None
            else "Update Announcement Channel to This Channel"
        )

        self.button = ui.Button(label=label, style=discord.ButtonStyle.primary)
        self.button.callback = self.set_channel
        self.add_item(self.button)

    async def set_channel(self, interaction: discord.Interaction):
        channel_id = interaction.channel.id

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO guild_settings (guild_id, announcement_channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET announcement_channel_id = EXCLUDED.announcement_channel_id
                """,
                self.guild_id,
                channel_id
            )

        embed = discord.Embed(
            title="Announcement Channel Updated",
            description=f"This channel (**{interaction.channel.mention}**) is now set as the announcement channel.",
            color=GREEN
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def set_announcement_channel(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    async with interaction.client.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT announcement_channel_id FROM guild_settings WHERE guild_id = $1",
            guild_id
        )

    current_announcement_channel_id = row["announcement_channel_id"] if row else None

    embed = discord.Embed(
        title="Bot Settings — Announcement Channel",
        description=(
            "**Announcement Channel Requirement**\n"
            "This bot uses an **Announcement Channel** to send release notes and update notifications.\n\n"
            "The announcement channel is used for:\n"
            "• Release notes\n"
            "• Update notifications\n"
            "• System-wide announcements\n\n"
            "**Important:**\n"
            "The announcement channel should be a channel where:\n"
            "• Server administrators can read\n"
            "• The bot has permission to send messages\n\n"
            "If this is not the channel you want to use, navigate to the correct channel and run this command again."
        ),
        color=GREEN
    )

    view = SetAnnouncementChannelView(interaction.client, guild_id, current_announcement_channel_id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
