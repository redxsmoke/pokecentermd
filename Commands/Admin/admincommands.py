import discord
from discord.ext import commands
import shop_state

from Commands.Admin.inventory_csv_import import InventoryCSVImport
from Commands.Admin.inventory_add_single_wizard import start_add_single_wizard

from Commands.BotSettings.admin_channel import set_admin_channel
from Commands.BotSettings.welcome_channel import set_welcome_channel
from Commands.BotSettings.payment_settings import set_payment_info
from Commands.Admin.update_single_wizard import start_update_single_wizard



# ✅ NEW — import your batch upload function
from Commands.Admin.batch_image_upload import batch_image_upload

from Commands.Admin.inventory_update_single import (
    start_update_single_flow,
    start_update_single_flow_with_id
)

from Commands.Admin.inventory_delete_single import (
    start_delete_single_flow,
    start_delete_single_flow_with_id
)


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

        manage_inventory_cmd = discord.app_commands.Command(
            name="manage_inventory",
            description="Manage inventory (add/update/delete).",
            callback=self.manage_inventory
        )

        update_single_cmd = discord.app_commands.Command(
            name="update_single",
            description="Search for a card by Pokémon name.",
            callback=self.update_single
        )
        update_single_cmd.autocomplete("card")(self.inventory_autocomplete)

        activate_single_cmd = discord.app_commands.Command(
            name="activate_single",
            description="Reactivate a hidden inventory item.",
            callback=self.activate_single
        )
        activate_single_cmd.autocomplete("card")(self.inactive_inventory_autocomplete)

        deactivate_single_cmd = discord.app_commands.Command(
            name="deactivate_single",
            description="Hide an inventory item so it no longer appears in update_single.",
            callback=self.deactivate_single
        )
        deactivate_single_cmd.autocomplete("card")(self.inventory_autocomplete)

        delete_single_cmd = discord.app_commands.Command(
            name="delete_single",
            description="Permanently delete a card from inventory.",
            callback=self.delete_single
        )
        delete_single_cmd.autocomplete("card")(self.all_inventory_autocomplete)

        set_admin_channel_cmd = discord.app_commands.Command(
            name="set_admin_channel",
            description="Configure bot admin settings.",
            callback=set_admin_channel
        )

        welcome_channel_cmd = discord.app_commands.Command(
            name="set_welcome_channel",
            description="Configure the welcome channel for new user greetings.",
            callback=set_welcome_channel
        )

        payment_settings_cmd = discord.app_commands.Command(
            name="set_payment_info",
            description="Configure payment methods (Venmo, CashApp, PayPal).",
            callback=set_payment_info
        )

        # ✅ NEW — batch image upload command
        batch_upload_cmd = discord.app_commands.Command(
            name="batch_image_upload",
            description="Batch upload images for cards missing images.",
            callback=batch_image_upload
        )

        # Register all commands
        self.admin_group.add_command(closeshop_cmd)
        self.admin_group.add_command(openshop_cmd)
        self.admin_group.add_command(manage_inventory_cmd)
        self.admin_group.add_command(update_single_cmd)
        self.admin_group.add_command(activate_single_cmd)
        self.admin_group.add_command(deactivate_single_cmd)
        self.admin_group.add_command(delete_single_cmd)
        self.admin_group.add_command(set_admin_channel_cmd)
        self.admin_group.add_command(welcome_channel_cmd)
        self.admin_group.add_command(payment_settings_cmd)

        # ✅ NEW — register batch upload
        self.admin_group.add_command(batch_upload_cmd)

        # Add group to bot
        self.bot.tree.add_command(self.admin_group)

    # ---------------------------------------------------------
    # AUTOCOMPLETE — ACTIVE CARDS ONLY
    # ---------------------------------------------------------
    async def inventory_autocomplete(self, interaction: discord.Interaction, current: str):
        if not current:
            return []

        async with interaction.client.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT inventory_id, pokemon_name, series, set_name
                FROM inventory
                WHERE guild_id = $1
                  AND is_active = TRUE
                  AND pokemon_name ILIKE $2
                ORDER BY pokemon_name
                LIMIT 25
                """,
                interaction.guild.id,
                f"%{current}%"
            )

        return [
            discord.app_commands.Choice(
                name=f"{r['pokemon_name']} — {r['series']} — {r['set_name']}",
                value=str(r["inventory_id"])
            )
            for r in rows
        ]

    # ---------------------------------------------------------
    # AUTOCOMPLETE — INACTIVE CARDS ONLY
    # ---------------------------------------------------------
    async def inactive_inventory_autocomplete(self, interaction: discord.Interaction, current: str):
        if not current:
            return []

        async with interaction.client.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT inventory_id, pokemon_name, series, set_name
                FROM inventory
                WHERE guild_id = $1
                  AND is_active = FALSE
                  AND pokemon_name ILIKE $2
                ORDER BY pokemon_name
                LIMIT 25
                """,
                interaction.guild.id,
                f"%{current}%"
            )

        return [
            discord.app_commands.Choice(
                name=f"{r['pokemon_name']} — {r['series']} — {r['set_name']}",
                value=str(r["inventory_id"])
            )
            for r in rows
        ]

    # ---------------------------------------------------------
    # AUTOCOMPLETE — ALL CARDS (delete_single)
    # ---------------------------------------------------------
    async def all_inventory_autocomplete(self, interaction: discord.Interaction, current: str):
        if not current:
            return []

        async with interaction.client.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT inventory_id, pokemon_name, series, set_name
                FROM inventory
                WHERE guild_id = $1
                  AND pokemon_name ILIKE $2
                ORDER BY pokemon_name
                LIMIT 25
                """,
                interaction.guild.id,
                f"%{current}%"
            )

        return [
            discord.app_commands.Choice(
                name=f"{r['pokemon_name']} — {r['series']} — {r['set_name']}",
                value=str(r["inventory_id"])
            )
            for r in rows
        ]

    # ---------------------------------------------------------
    # /admin update_single
    # ---------------------------------------------------------
    async def update_single(self, interaction: discord.Interaction, card: str):
        inventory_id = int(card)
        await start_update_single_flow_with_id(interaction, inventory_id)

    # ---------------------------------------------------------
    # /admin activate_single
    # ---------------------------------------------------------
    async def activate_single(self, interaction: discord.Interaction, card: str):
        inventory_id = int(card)

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET is_active = TRUE
                WHERE inventory_id = $1 AND guild_id = $2
                """,
                inventory_id,
                interaction.guild.id
            )

        await interaction.response.send_message(
            "Card is now active and will display in the update single search results.",
            ephemeral=True
        )

    # ---------------------------------------------------------
    # /admin deactivate_single
    # ---------------------------------------------------------
    async def deactivate_single(self, interaction: discord.Interaction, card: str):
        inventory_id = int(card)

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE inventory
                SET is_active = FALSE
                WHERE inventory_id = $1 AND guild_id = $2
                """,
                inventory_id,
                interaction.guild.id
            )

        await interaction.response.send_message(
            "Card has been deactivated and will no longer appear in update single search results.",
            ephemeral=True
        )

    # ---------------------------------------------------------
    # /admin delete_single
    # ---------------------------------------------------------
    async def delete_single(self, interaction: discord.Interaction, card: str):
        inventory_id = int(card)
        await start_delete_single_flow_with_id(interaction, inventory_id)

    # ---------------------------------------------------------
    # /admin manage_inventory
    # ---------------------------------------------------------
    async def manage_inventory(self, interaction: discord.Interaction):
        ...
        # (unchanged — omitted for brevity)
        ...

    # ---------------------------------------------------------
    # /admin closeshop
    # ---------------------------------------------------------
    async def closeshop(self, interaction: discord.Interaction):
        ...
        # (unchanged)
        ...

    # ---------------------------------------------------------
    # /admin openshop
    # ---------------------------------------------------------
    async def openshop(self, interaction: discord.Interaction):
        ...
        # (unchanged)
        ...


async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
