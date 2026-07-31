import discord
from discord.ext import commands
import shop_state


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # ADMIN-ONLY GROUP (hidden from non-admins in guilds)
        self.admin_group = discord.app_commands.Group(
            name="admin",
            description="Admin-only commands for managing the shop.",
            default_permissions=discord.Permissions(administrator=True)
        )

    async def cog_load(self):
        closeshop_cmd = discord.app_commands.Command(
            name="closeshop",
            description="Close the shop with a selected reason.",
            callback=self.closeshop
        )

        openshop_cmd = discord.app_commands.Command(
            name="openshop",
            description="Open the shop again.",
            callback=self.openshop
        )

        self.admin_group.add_command(closeshop_cmd)
        self.admin_group.add_command(openshop_cmd)

        self.bot.tree.add_command(self.admin_group)

    # ---------------------------------------------------------
    # /admin closeshop
    # ---------------------------------------------------------
    async def closeshop(self, interaction: discord.Interaction):

        # BLOCK DMs
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Admin commands cannot be used in DMs.",
                ephemeral=True
            )
            return

        class CloseReasonSelect(discord.ui.Select):
            def __init__(self):
                options = [
                    discord.SelectOption(label="At show", value="show"),
                    discord.SelectOption(label="Maintenance", value="maintenance"),
                ]
                super().__init__(placeholder="Select a reason", options=options)

            async def callback(self, inner_interaction: discord.Interaction):

                # BLOCK DMs
                if inner_interaction.guild is None:
                    await inner_interaction.response.send_message(
                        "❌ Admin commands cannot be used in DMs.",
                        ephemeral=True
                    )
                    return

                # Update shared state
                shop_state.SHOP_OPEN = False
                shop_state.SHOP_CLOSE_REASON = self.values[0]

                await inner_interaction.response.send_message(
                    "Shop closed successfully.",
                    ephemeral=True
                )

                # PUBLIC BROADCAST
                if self.values[0] == "show":
                    desc = (
                        "📢 **The shop is now CLOSED because we are currently at a show.**\n"
                        "Orders are disabled until the show ends."
                    )
                else:
                    desc = (
                        "📢 **The shop is now CLOSED for maintenance.**\n"
                        "Orders will resume once improvements are complete."
                    )

                embed = discord.Embed(
                    title="🚫 Shop Closed",
                    description=desc,
                    color=discord.Color.red()
                )

                await interaction.channel.send(embed=embed)

        class CloseReasonView(discord.ui.View):
            def __init__(self):
                super().__init__()
                self.add_item(CloseReasonSelect())

        await interaction.response.send_message(
            "Choose a reason for closing the shop:",
            view=CloseReasonView(),
            ephemeral=True
        )

    # ---------------------------------------------------------
    # /admin openshop
    # ---------------------------------------------------------
    async def openshop(self, interaction: discord.Interaction):

        # BLOCK DMs
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Admin commands cannot be used in DMs.",
                ephemeral=True
            )
            return

        shop_state.SHOP_OPEN = True
        shop_state.SHOP_CLOSE_REASON = None

        await interaction.response.send_message(
            "✅ The shop is now **open**.",
            ephemeral=True
        )

        embed = discord.Embed(
            title="🟢 Shop Open",
            description="📢 **The shop is now OPEN!**\nYou may resume browsing and ordering.",
            color=discord.Color.green()
        )

        await interaction.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
