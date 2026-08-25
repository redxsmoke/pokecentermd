import discord
from discord.ext import commands
import shop_state

from Commands.Admin.inventory_csv_import import InventoryCSVImport
from Commands.Admin.inventory_add_single_wizard import start_add_single_wizard
from Commands.Admin.update_single_wizard import start_update_single_wizard
from Commands.Admin.manageorders import start_manage_orders

# Batch upload
from Commands.Admin.batch_image_upload import batch_image_upload

# Inventory update/delete flows
from Commands.Admin.inventory_update_single import (
    start_update_single_flow,
    start_update_single_flow_with_id
)

from Commands.Admin.inventory_delete_single import (
    start_delete_single_flow,
    start_delete_single_flow_with_id
)

from Commands.BotSettings.bot_settings_menu import BotSettingsMenu

from Commands.BotSettings.set_singles_role_slash import (
    set_singles_role_callback,
    singles_role_autocomplete
)

from Commands.Admin.wishlist_dashboard import (
    WishlistDashboardView,
    WishlistDetailsSelect
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

        # -----------------------------
        # Core admin commands
        # -----------------------------
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

        manage_orders_cmd = discord.app_commands.Command(
            name="manage_orders",
            description="Manage orders by status.",
            callback=self.manage_orders
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

        set_singles_role_cmd = discord.app_commands.Command(
            name="set_singles_role",
            description="Set the Singles notification role (admin only).",
            callback=set_singles_role_callback
        )
        set_singles_role_cmd.autocomplete("role")(singles_role_autocomplete)
        self.admin_group.add_command(set_singles_role_cmd)

        bot_settings_cmd = discord.app_commands.Command(
            name="bot_settings",
            description="Configure bot settings.",
            callback=self.bot_settings
        )

        wishlist_dashboard_cmd = discord.app_commands.Command(
            name="wishlist_dashboard",
            description="Admin-only: View wishlist dashboard.",
            callback=self.wishlist_dashboard
        )

        # -----------------------------
        # Batch upload
        # -----------------------------
        batch_upload_cmd = discord.app_commands.Command(
            name="batch_image_upload",
            description="Batch upload images for cards missing images.",
            callback=batch_image_upload
        )

        # -----------------------------
        # Register commands
        # -----------------------------
        self.admin_group.add_command(closeshop_cmd)
        self.admin_group.add_command(openshop_cmd)
        self.admin_group.add_command(manage_inventory_cmd)
        self.admin_group.add_command(manage_orders_cmd)
        self.admin_group.add_command(update_single_cmd)
        self.admin_group.add_command(activate_single_cmd)
        self.admin_group.add_command(deactivate_single_cmd)
        self.admin_group.add_command(delete_single_cmd)
        self.admin_group.add_command(wishlist_dashboard_cmd)

        # NEW — bot settings dropdown
        self.admin_group.add_command(bot_settings_cmd)

        # Batch upload
        self.admin_group.add_command(batch_upload_cmd)

        # Add group to bot
        self.bot.tree.add_command(self.admin_group)
    # ---------------------------------------------------------
    # BOT SETTINGS DROPDOWN HANDLER
    # ---------------------------------------------------------
    async def bot_settings(self, interaction: discord.Interaction):
        menu = BotSettingsMenu(self.bot)
        await menu.bot_settings(interaction)

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
        class InventoryActionSelect(discord.ui.Select):
            def __init__(self):
                options = [
                    discord.SelectOption(label="Add a single", value="add_single"),
                    discord.SelectOption(label="Add singles (upload CSV)", value="upload_csv"),
                    discord.SelectOption(label="Update a single", value="update_single"),
                    discord.SelectOption(label="Deactivate a single", value="deactivate_single"),
                    discord.SelectOption(label="Activate a single", value="activate_single"),
                    discord.SelectOption(label="Delete a single", value="delete_single"),
                ]
                super().__init__(placeholder="Select an inventory action", options=options)

            async def callback(self, inner_interaction: discord.Interaction):

                action = self.values[0]

                if action == "delete_single":

                    warning = (
                        "**Warning — Permanent Deletion**\n\n"
                        "Deleting a card will permanently remove it and all of its data from your inventory.\n\n"
                        "If you simply no longer have this card and want it removed from search results, "
                        "use **/admin deactivate_single** instead.\n\n"
                        "You may reactivate hidden cards at any time using **/admin activate_single**.\n\n"
                        "**This action cannot be undone.**"
                    )

                    class DeleteWarningView(discord.ui.View):
                        def __init__(self):
                            super().__init__(timeout=120)

                        @discord.ui.button(label="Continue", style=discord.ButtonStyle.danger)
                        async def continue_delete(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                            await btn_interaction.response.send_message(
                                "Run `/admin delete_single` and select the card using autocomplete.",
                                ephemeral=True
                            )

                        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
                        async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                            await btn_interaction.response.send_message(
                                "Delete cancelled.",
                                ephemeral=True
                            )

                    await inner_interaction.response.send_message(
                        warning,
                        view=DeleteWarningView(),
                        ephemeral=True
                    )
                    return

                if action == "update_single":

                    class UpdateMethodView(discord.ui.View):
                        def __init__(self):
                            super().__init__(timeout=120)

                        @discord.ui.button(label="Search by Pokémon Name", style=discord.ButtonStyle.primary)
                        async def search_by_name(self, btn_interaction: discord.Interaction, button: discord.ui.Button):

                            await btn_interaction.response.send_message(
                                "Run `/admin update_single` and type the Pokémon name in the autocomplete box.",
                                ephemeral=True
                            )

                        @discord.ui.button(label="Enter Inventory ID", style=discord.ButtonStyle.secondary)
                        async def enter_id(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                            await start_update_single_flow(btn_interaction)

                    await inner_interaction.response.send_message(
                        "How would you like to find the card?",
                        view=UpdateMethodView(),
                        ephemeral=True
                    )
                    return

                elif action == "add_single":
                    await start_add_single_wizard(inner_interaction, inner_interaction.client)
                    await inner_interaction.followup.send("Add Single wizard started.", ephemeral=True)
                    return

                elif action == "upload_csv":

                    embed = discord.Embed(
                        title="📄 CSV Upload Mode",
                        description=(
                            "Please upload your **CSV file** in this channel.\n\n"
                            "Supported formats:\n"
                            "• UTF‑16 CSV\n"
                            "• UTF‑8 CSV\n"
                            "• Semicolon‑delimited CSV\n\n"
                            "Required columns:\n"
                            "• Name\n"
                            "• Series\n"
                            "• Set\n"
                            "• Quantity\n"
                            "• Price\n\n"
                            "Optional columns:\n"
                            "• Variant\n"
                            "• Rarity\n"
                            "• Condition\n"
                            "• ImageURL (direct link ending in .jpg/.png/.gif/.webp)\n\n"
                            "Upload your CSV file now."
                        ),
                        color=discord.Color.green()
                    )

                    await inner_interaction.response.send_message(embed=embed, ephemeral=True)
                    return

                elif action == "deactivate_single":
                    await inner_interaction.response.send_message(
                        "Run `/admin deactivate_single` to hide a card.",
                        ephemeral=True
                    )
                    return

                elif action == "activate_single":
                    await inner_interaction.response.send_message(
                        "Run `/admin activate_single` to reactivate a hidden card.",
                        ephemeral=True
                    )
                    return

        class InventoryActionView(discord.ui.View):
            def __init__(self):
                super().__init__()
                self.add_item(InventoryActionSelect())

        await interaction.response.send_message(
            "Choose an inventory action:",
            view=InventoryActionView(),
            ephemeral=True
        )

    # ---------------------------------------------------------
    # /admin closeshop
    # ---------------------------------------------------------
    async def closeshop(self, interaction: discord.Interaction):

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

                if inner_interaction.guild is None:
                    await inner_interaction.response.send_message(
                        "❌ Admin commands cannot be used in DMs.",
                        ephemeral=True
                    )
                    return

                shop_state.SHOP_OPEN = False
                shop_state.SHOP_CLOSE_REASON = self.values[0]

                await inner_interaction.response.send_message(
                    "Shop closed successfully.",
                    ephemeral=True
                )

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

    # ---------------------------------------------------------
    # /admin manage_orders
    # ---------------------------------------------------------
    async def manage_orders(self, interaction: discord.Interaction):
        await start_manage_orders(interaction)

    # ---------------------------------------------------------
    # /admin wishlist_dashboard
    # ---------------------------------------------------------
    async def wishlist_dashboard(self, interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)

        view = WishlistDashboardView(interaction)
        await view.load_page()

        await interaction.followup.send(
            "Wishlist Dashboard:",
            embed=view.embed,
            view=view,
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
