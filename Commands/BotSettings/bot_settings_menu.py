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

                elif choice == "singles_channel":

                    # -----------------------------
                    # CATEGORY → CHANNEL SELECTOR (max 25 each)
                    # -----------------------------
                    class CategorySelect(discord.ui.Select):
                        def __init__(self):
                            categories = inner_interaction.guild.categories[:25]

                            if not categories:
                                options = [
                                    discord.SelectOption(label="All Channels", value="__ALL__")
                                ]
                            else:
                                options = [
                                    discord.SelectOption(label=c.name, value=str(c.id))
                                    for c in categories
                                ]

                            super().__init__(
                                placeholder="Select a category",
                                options=options
                            )

                        async def callback(self, category_interaction: discord.Interaction):
                            selected = self.values[0]

                            class ChannelSelect(discord.ui.Select):
                                def __init__(self):
                                    if selected == "__ALL__":
                                        channels = inner_interaction.guild.text_channels
                                    else:
                                        category_id = int(selected)
                                        category = inner_interaction.guild.get_channel(category_id)
                                        channels = category.text_channels if category else []

                                    channels = channels[:25]

                                    options = [
                                        discord.SelectOption(label=ch.name, value=str(ch.id))
                                        for ch in channels
                                    ]

                                    super().__init__(
                                        placeholder="Select the Singles notification channel",
                                        options=options
                                    )

                                async def callback(self, channel_interaction: discord.Interaction):
                                    channel_id = int(self.values[0])
                                    channel = channel_interaction.guild.get_channel(channel_id)
                                    await set_singles_channel(channel_interaction, channel)

                            class ChannelSelectView(discord.ui.View):
                                def __init__(self):
                                    super().__init__(timeout=120)
                                    self.add_item(ChannelSelect())

                            embed = discord.Embed(
                                title="Select Singles Notification Channel",
                                description="Choose which channel should receive Singles notifications.",
                                color=discord.Color.blurple()
                            )

                            await category_interaction.response.send_message(
                                embed=embed,
                                view=ChannelSelectView(),
                                ephemeral=True
                            )

                    class CategorySelectView(discord.ui.View):
                        def __init__(self):
                            super().__init__(timeout=120)
                            self.add_item(CategorySelect())

                    embed = discord.Embed(
                        title="Select Category",
                        description="Choose a category to browse its channels.",
                        color=discord.Color.blurple()
                    )

                    await inner_interaction.response.send_message(
                        embed=embed,
                        view=CategorySelectView(),
                        ephemeral=True
                    )

                elif choice == "upcoming_shows_channel":

                    # -----------------------------
                    # CATEGORY → CHANNEL SELECTOR (same as singles)
                    # -----------------------------
                    class CategorySelect(discord.ui.Select):
                        def __init__(self):
                            categories = inner_interaction.guild.categories[:25]

                            if not categories:
                                options = [
                                    discord.SelectOption(label="All Channels", value="__ALL__")
                                ]
                            else:
                                options = [
                                    discord.SelectOption(label=c.name, value=str(c.id))
                                    for c in categories
                                ]

                            super().__init__(
                                placeholder="Select a category",
                                options=options
                            )

                        async def callback(self, category_interaction: discord.Interaction):
                            selected = self.values[0]

                            class ChannelSelect(discord.ui.Select):
                                def __init__(self):
                                    if selected == "__ALL__":
                                        channels = inner_interaction.guild.text_channels
                                    else:
                                        category_id = int(selected)
                                        category = inner_interaction.guild.get_channel(category_id)
                                        channels = category.text_channels if category else []

                                    channels = channels[:25]

                                    options = [
                                        discord.SelectOption(label=ch.name, value=str(ch.id))
                                        for ch in channels
                                    ]

                                    super().__init__(
                                        placeholder="Select the Upcoming Shows channel",
                                        options=options
                                    )

                                async def callback(self, channel_interaction: discord.Interaction):
                                    channel_id = int(self.values[0])
                                    channel = channel_interaction.guild.get_channel(channel_id)
                                    await set_upcoming_shows_channel(channel_interaction, channel)

                            class ChannelSelectView(discord.ui.View):
                                def __init__(self):
                                    super().__init__(timeout=120)
                                    self.add_item(ChannelSelect())

                            embed = discord.Embed(
                                title="Select Upcoming Shows Channel",
                                description="Choose which channel should receive upcoming show announcements.",
                                color=discord.Color.blurple()
                            )

                            await category_interaction.response.send_message(
                                embed=embed,
                                view=ChannelSelectView(),
                                ephemeral=True
                            )

                    class CategorySelectView(discord.ui.View):
                        def __init__(self):
                            super().__init__(timeout=120)
                            self.add_item(CategorySelect())

                    embed = discord.Embed(
                        title="Select Category",
                        description="Choose a category to browse its channels.",
                        color=discord.Color.blurple()
                    )

                    await inner_interaction.response.send_message(
                        embed=embed,
                        view=CategorySelectView(),
                        ephemeral=True
                    )

                # ---------------------------------------------------------
                # NON-CHANNEL SETTINGS
                # ---------------------------------------------------------
                elif choice == "payment_info":
                    await set_payment_info(inner_interaction)

                elif choice == "singles_role":

                    # -----------------------------
                    # ROLE SELECTOR DROPDOWN
                    # -----------------------------
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
