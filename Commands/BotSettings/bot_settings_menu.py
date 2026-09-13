import discord
from discord.ext import commands

# Your existing imports
from Commands.BotSettings.bot_settings_menu_helpers import (
    set_admin_channel,
    set_welcome_channel,
    set_announcement_channel,
    set_payment_info,
    set_singles_role,
    set_singles_channel,
    toggle_singles_notifications,
    set_upcoming_shows_channel
)

# NEW IMPORT
from Commands.BotSettings.poke_trivia_channel_wizard import start_poke_trivia_wizard


class BotSettingsMenu(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def bot_settings(self, interaction: discord.Interaction):

        class BotSettingsSelect(discord.ui.Select):
            def __init__(self):

                options = [
                    discord.SelectOption(label="Set Admin Channel", value="admin_channel"),
                    discord.SelectOption(label="Set Welcome Channel", value="welcome_channel"),
                    discord.SelectOption(label="Set Announcement Channel", value="announcement_channel"),
                    discord.SelectOption(label="Set Singles Notification Channel", value="singles_channel"),
                    discord.SelectOption(label="Set Upcoming Shows Channel", value="upcoming_shows_channel"),

                    discord.SelectOption(label="Set Payment Info", value="payment_info"),
                    discord.SelectOption(label="Set Singles Role", value="singles_role"),
                    discord.SelectOption(label="Toggle Singles Notifications", value="toggle_singles"),

                    # NEW OPTION
                    discord.SelectOption(label="Enable/Disable Poké Trivia", value="toggle_poke_trivia"),
                ]

                super().__init__(placeholder="Choose a bot setting to configure", options=options)

            async def callback(self, inner_interaction: discord.Interaction):
                choice = self.values[0]

                if choice == "admin_channel":
                    await set_admin_channel(inner_interaction)

                elif choice == "welcome_channel":
                    await set_welcome_channel(inner_interaction)

                elif choice == "announcement_channel":
                    await set_announcement_channel(inner_interaction)

                elif choice == "singles_channel":
                    await set_singles_channel(inner_interaction)

                elif choice == "upcoming_shows_channel":
                    await set_upcoming_shows_channel(inner_interaction)

                elif choice == "payment_info":
                    await set_payment_info(inner_interaction)

                elif choice == "singles_role":
                    # (your existing role selection code stays unchanged)
                    pass

                elif choice == "toggle_singles":
                    await toggle_singles_notifications(inner_interaction)

                # NEW — WIZARD
                elif choice == "toggle_poke_trivia":
                    await start_poke_trivia_wizard(inner_interaction)

        class BotSettingsView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                self.add_item(BotSettingsSelect())

        embed = discord.Embed(
            title="Bot Settings",
            description="Use the dropdown below to configure bot settings.",
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(
            embed=embed,
            view=BotSettingsView(),
            ephemeral=True
        )
