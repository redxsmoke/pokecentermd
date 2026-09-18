import discord
from discord.ext import commands
from discord import app_commands
import shop_state
import logging

log = logging.getLogger("inventory_grouped")


class InventoryGrouped(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------------------------------------------------------
    # /shop GROUP
    # ---------------------------------------------------------
    shop = app_commands.Group(
        name="shop",
        description="Browse the shop (singles or sealed)"
    )

    # ---------------------------------------------------------
    # /shop singles
    # ---------------------------------------------------------
    @shop.command(
        name="singles",
        description="Browse singles (cards)"
    )
    @app_commands.describe(
        pokemon_name="Search by Pokémon name",
        set_name="Search by set name"
    )
    async def shop_singles(
        self,
        interaction: discord.Interaction,
        pokemon_name: str = None,
        set_name: str = None
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command must be used inside a server.",
                ephemeral=True
            )
            return

        runtime = interaction.client.get_cog("ClaimSaleRuntime")
        if runtime and await runtime.is_shop_blocked(interaction.guild.id):
            await interaction.response.send_message(
                "🚫 Shop temporarily closed — claim sale in progress.",
                ephemeral=True
            )
            return

        if not shop_state.SHOP_OPEN:
            reason = (
                "We are currently **at a show**, and the shop is temporarily closed."
                if shop_state.SHOP_CLOSE_REASON == "show"
                else "The shop is currently **undergoing maintenance**."
            )
            await interaction.response.send_message(reason, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)

        inventory_cog = self.bot.get_cog("Inventory")
        if not inventory_cog:
            await interaction.followup.send("Inventory system unavailable.")
            return

        await inventory_cog.start_singles_inventory(
            interaction,
            pokemon_name,
            set_name
        )

    # ---------------------------------------------------------
    # /shop sealed
    # ---------------------------------------------------------
    @shop.command(
        name="sealed",
        description="Browse sealed products"
    )
    async def shop_sealed(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command must be used inside a server.",
                ephemeral=True
            )
            return

        runtime = interaction.client.get_cog("ClaimSaleRuntime")
        if runtime and await runtime.is_shop_blocked(interaction.guild.id):
            await interaction.response.send_message(
                "🚫 Shop temporarily closed — claim sale in progress.",
                ephemeral=True
            )
            return

        if not shop_state.SHOP_OPEN:
            reason = (
                "We are currently **at a show**, and the shop is temporarily closed."
                if shop_state.SHOP_CLOSE_REASON == "show"
                else "The shop is currently **undergoing maintenance**."
            )
            await interaction.response.send_message(reason, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)

        sealed_cog = self.bot.get_cog("InventorySealed")
        if not sealed_cog:
            await interaction.followup.send("Sealed inventory system unavailable.")
            return

        await sealed_cog.start_sealed_inventory(interaction)


async def setup(bot):
    print("INVENTORY GROUPED COG LOADED")
    await bot.add_cog(InventoryGrouped(bot))

    # ✅ Guard against duplicate registration of /shop
    existing = bot.tree.get_command("shop")
    if existing is None:
        bot.tree.add_command(InventoryGrouped.shop)
    else:
        log.warning("Slash command 'shop' already exists in CommandTree; skipping re-registration.")
