import discord
from discord import ui


class PaymentSettingsModal(ui.Modal, title="Configure Payment Methods"):
    def __init__(self, bot: discord.Client, guild_id: int):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id

        self.venmo_input = ui.TextInput(
            label="Venmo Handle",
            placeholder="e.g. @VenmoHandle. Leave blank if not used",
            required=False,
            max_length=64,
        )
        self.cashapp_input = ui.TextInput(
            label="CashApp Handle",
            placeholder="e.g. $CashAppHandle. Leave blank if not used",
            required=False,
            max_length=64,
        )
        self.paypal_input = ui.TextInput(
            label="PayPal Handle",
            placeholder="e.g. PayPal Handle. Leave blank if not used",
            required=False,
            max_length=64,
        )

        self.add_item(self.venmo_input)
        self.add_item(self.cashapp_input)
        self.add_item(self.paypal_input)

    async def on_submit(self, interaction: discord.Interaction):
        venmo = self.venmo_input.value.strip() or None
        cashapp = self.cashapp_input.value.strip() or None
        paypal = self.paypal_input.value.strip() or None

        # Validation
        errors = []

        if venmo is not None and not venmo.startswith("@"):
            errors.append("Venmo handle must start with `@` (e.g. `@username`).")

        if cashapp is not None and not cashapp.startswith("$"):
            errors.append("CashApp handle must start with `$` (e.g. `$username`).")

        # PayPal: any non-empty string allowed

        if errors:
            embed = discord.Embed(
                title="Payment Settings Error",
                description="\n".join(errors),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        admin_id = interaction.guild.owner_id if interaction.guild else None

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO guild_settings (
                    guild_id,
                    admin_channel_id,
                    welcome_channel_id,
                    venmo_handle,
                    cashapp_handle,
                    paypal_handle,
                    admin_id
                )
                VALUES ($1, NULL, NULL, $2, $3, $4, $5)
                ON CONFLICT (guild_id)
                DO UPDATE SET
                    venmo_handle   = EXCLUDED.venmo_handle,
                    cashapp_handle = EXCLUDED.cashapp_handle,
                    paypal_handle  = EXCLUDED.paypal_handle,
                    admin_id       = EXCLUDED.admin_id;
                """,
                self.guild_id,
                venmo,
                cashapp,
                paypal,
                admin_id
            )

        venmo_display = venmo or "Not set"
        cashapp_display = cashapp or "Not set"
        paypal_display = paypal or "Not set"

        embed = discord.Embed(
            title="Payment Methods Updated",
            description=(
                f"**Guild:** {interaction.guild.name if interaction.guild else 'Unknown'}\n"
                f"**Admin (Owner) ID:** `{admin_id}`\n\n"
                f"**Venmo:** {venmo_display}\n"
                f"**CashApp:** {cashapp_display}\n"
                f"**PayPal:** {paypal_display}"
            ),
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


class PaymentSettingsView(ui.View):
    def __init__(self, bot: discord.Client, guild_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @ui.button(label="Configure Payment Methods", style=discord.ButtonStyle.primary)
    async def configure_payment(
        self,
        interaction: discord.Interaction,
        button: ui.Button
    ):
        modal = PaymentSettingsModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)


async def set_payment_info(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None:
        embed = discord.Embed(
            title="Payment Settings",
            description="❌ This command cannot be used in DMs.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(
        title="Bot Settings — Payment Methods",
        description=(
            "Configure the payment handles used for checkout.\n\n"
            "**Supported methods:**\n"
            "• Venmo (must start with `@`)\n"
            "• CashApp (must start with `$`)\n"
            "• PayPal (any identifier)\n\n"
            "You may leave any field blank if you do not use that method.\n"
            "The guild owner will be stored as the administrator for these settings."
        ),
        color=discord.Color.blurple()
    )

    view = PaymentSettingsView(interaction.client, guild.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
