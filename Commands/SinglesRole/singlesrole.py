import discord
from discord.ext import commands
from discord import ui
from Commands.BotSettings.admin_channel_helpers import get_singles_role


class SinglesRoleView(ui.View):
    def __init__(self, bot, user):
        super().__init__(timeout=60)
        self.bot = bot
        self.user = user

    @ui.button(label="Join Singles Role", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user.id:
            embed = discord.Embed(
                title="Not Allowed",
                description="This prompt isn't for you.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        singles_role = await get_singles_role(self.bot, interaction.guild.id)
        if singles_role is None:
            embed = discord.Embed(
                title="Singles Role Not Set",
                description="❌ The Singles role has not been configured.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        try:
            await interaction.user.add_roles(singles_role)
            embed = discord.Embed(
                title="Role Added",
                description=f"✅ You have been added to the {singles_role.mention} role!",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.Forbidden:
            embed = discord.Embed(
                title="Permission Error",
                description="❌ I don't have permission to assign that role.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        self.stop()

    @ui.button(label="Leave Singles Role", style=discord.ButtonStyle.danger)
    async def leave_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user.id:
            embed = discord.Embed(
                title="Not Allowed",
                description="This prompt isn't for you.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        singles_role = await get_singles_role(self.bot, interaction.guild.id)
        if singles_role is None:
            embed = discord.Embed(
                title="Singles Role Not Set",
                description="❌ The Singles role has not been configured.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        try:
            await interaction.user.remove_roles(singles_role)
            embed = discord.Embed(
                title="Role Removed",
                description=f"❌ You have been removed from the {singles_role.mention} role.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.Forbidden:
            embed = discord.Embed(
                title="Permission Error",
                description="❌ I don't have permission to remove that role.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        self.stop()


class SinglesRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="singlesrole", description="Join or leave the Singles role.")
    async def singlesrole(self, ctx: commands.Context):
        """User-facing command to join or leave the Singles role."""
        view = SinglesRoleView(self.bot, ctx.author)

        embed = discord.Embed(
            title="Singles Role",
            description=(
                "By joining the Singles role, you will receive notifications when new singles are added.\n\n"
                "**Choose an option below:**"
            ),
            color=discord.Color.blurple()
        )

        await ctx.reply(embed=embed, view=view, mention_author=False)


async def setup(bot):
    await bot.add_cog(SinglesRole(bot))
