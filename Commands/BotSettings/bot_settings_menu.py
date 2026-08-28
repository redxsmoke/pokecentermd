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


class BotSettingsMenu(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def bot_settings(self, interaction: discord.Interaction):

        class BotSettingsSelect(discord.ui.Select):
            def __init__(self):

                # ---------------------------------------------------------
                # REORDERED DROPDOWN — CHANNEL SETTINGS FIRST
                # ---------------------------------------------------------
                options = [
                    discord.SelectOption(label="Set Admin Channel", value="admin_channel"),
                    discord.SelectOption(label="Set Welcome Channel", value="welcome_channel"),
                    discord.SelectOption(label="Set Announcement Channel", value="announcement_channel"),
                    discord.SelectOption(label="Set Singles Notification Channel", value="singles_channel"),
                    discord.SelectOption(label="Set Upcoming Shows Channel", value="upcoming_shows_channel"),

                    # ---------------------------------------------------------
                    # NON-CHANNEL SETTINGS (BOTTOM GROUP)
                    # ---------------------------------------------------------
                    discord.SelectOption(label="Set Payment Info", value="payment_info"),
                    discord.SelectOption(label="Set Singles Role", value="singles_role"),
                    discord.SelectOption(label="Toggle Singles Notifications", value="toggle_singles"),
                ]

                super().__init__(placeholder="Choose a bot setting to configure", options=options)

            async def callback(self, inner_interaction: discord.Interaction):
                choice = self.values[0]

                # ---------------------------------------------------------
                # CHANNEL SETTINGS
                # ---------------------------------------------------------
                if choice == "admin_channel":
                    await set_admin_channel(inner_interaction)

                elif choice == "welcome_channel":
                    await set_welcome_channel(inner_interaction)

                elif choice == "announcement_channel":
                    await set_announcement_channel(inner_interaction)

                # ✅ NOW MATCHES WELCOME CHANNEL BEHAVIOR (ONE CLICK)
                elif choice == "singles_channel":
                    await set_singles_channel(inner_interaction)

                elif choice == "upcoming_shows_channel":
                    await set_upcoming_shows_channel(inner_interaction)

                # ---------------------------------------------------------
                # NON-CHANNEL SETTINGS
                # ---------------------------------------------------------
                elif choice == "payment_info":
                    await set_payment_info(inner_interaction)

                elif choice == "singles_role":

                    class RoleSelect(discord.ui.Select):
                        def __init__(self):
                            options = []

                            default_role = inner_interaction.guild.default_role
                            roles = [default_role] + [
                                r for r in inner_interaction.guild.roles
                                if r != default_role
                            ]

                            roles = roles[:25]

                            for role in roles:
                                label = "@everyone" if role == default_role else role.name
                                options.append(
                                    discord.SelectOption(
                                        label=label,
                                        value=str(role.id)
                                    )
                                )

                            super().__init__(
                                placeholder="Select the Singles role",
                                options=options
                            )

                        async def callback(self, role_interaction: discord.Interaction):
                            role_id = int(self.values[0])
                            role = role_interaction.guild.get_role(role_id)
                            await set_singles_role(role_interaction, role)

                    class RoleSelectView(discord.ui.View):
                        def __init__(self):
                            super().__init__(timeout=120)
                            self.add_item(RoleSelect())

                    embed = discord.Embed(
                        title="Select Singles Role",
                        description=(
                            "Choose which role should receive Singles notifications.\n\n"
                            "If you do not see the role you want, run `/admin set_singles_role`."
                        ),
                        color=discord.Color.blurple()
                    )

                    await inner_interaction.response.send_message(
                        embed=embed,
                        view=RoleSelectView(),
                        ephemeral=True
                    )

                elif choice == "toggle_singles":
                    await toggle_singles_notifications(inner_interaction)

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
