import discord
from discord import app_commands
from discord.ext import commands

class SetMemberRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="setmemberrole",
        description="Sets the role users receive after agreeing to the rules."
    )
    @app_commands.describe(role="The role to assign to new members")
    @app_commands.default_permissions(administrator=True)  # 🔒 Admins only
    async def set_member_role(self, interaction: discord.Interaction, role: discord.Role):

        # Extra safety: runtime check
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⚠️ You must be an administrator to use this command.",
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                UPDATE guild_settings
                SET member_role_id = $1
                WHERE guild_id = $2
            """, role.id, interaction.guild.id)

        await interaction.response.send_message(
            f"✅ Member role set to **{role.name}**.",
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(SetMemberRole(bot))
