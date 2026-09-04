import discord
from discord.ext import commands

# ============================================================
# SHIPPING INFO COG
# ============================================================
class ShippingInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="shippinginfo",
        description="Manage your saved shipping address."
    )
    async def shippinginfo(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Command Not Available in DMs",
                    description="This command cannot be used in DMs.\n\nPlease run this command within the server.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Shipping Information",
            description=(
                "Use the buttons below to manage your saved shipping address:\n\n"
                "• **Add Shipping Address** — create a new saved address.\n"
                "• **Update Shipping Address** — modify an existing saved address.\n"
                "• **Delete Shipping Address** — remove your saved address."
            ),
            color=discord.Color.blue()
        )

        view = ShippingInfoMainView(self.bot, interaction.user.id, interaction.guild.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ============================================================
# MAIN VIEW WITH BUTTONS
# ============================================================
class ShippingInfoMainView(discord.ui.View):
    def __init__(self, bot, user_id: int, guild_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id

    @discord.ui.button(label="Add Shipping Address", style=discord.ButtonStyle.success)
    async def add_shipping(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="You can only manage your own shipping information.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            existing = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM user_shipping_info
                WHERE user_id = $1 AND guild_id = $2;
                """,
                self.user_id,
                self.guild_id
            )

        if existing and existing >= 1:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Maximum Addresses Reached",
                    description="You already have a saved shipping address. The maximum allowed is **1**.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            AddShippingModal(self.bot, self.user_id, self.guild_id)
        )

    @discord.ui.button(label="Update Shipping Address", style=discord.ButtonStyle.primary)
    async def update_shipping(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="You can only manage your own shipping information.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            record = await conn.fetchrow(
                """
                SELECT shipping_info_id
                FROM user_shipping_info
                WHERE user_id = $1 AND guild_id = $2;
                """,
                self.user_id,
                self.guild_id
            )

        if record is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="No Saved Address",
                    description="You do not have a saved shipping address to update.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        view = UpdateFieldView(self.bot, self.user_id, self.guild_id)
        embed = discord.Embed(
            title="Update Shipping Address",
            description="Select which field you want to update.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Delete Shipping Address", style=discord.ButtonStyle.danger)
    async def delete_shipping(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="You can only manage your own shipping information.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            record = await conn.fetchrow(
                """
                SELECT shipping_info_id
                FROM user_shipping_info
                WHERE user_id = $1 AND guild_id = $2;
                """,
                self.user_id,
                self.guild_id
            )

        if record is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="No Saved Address",
                    description="You do not have a saved shipping address to delete.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        view = DeleteConfirmView(self.bot, self.user_id, self.guild_id)
        embed = discord.Embed(
            title="Delete Shipping Address",
            description="Are you sure you want to delete your saved shipping address?",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ============================================================
# ADD SHIPPING MODAL
# ============================================================
class AddShippingModal(discord.ui.Modal, title="Add Shipping Address"):
    full_name = discord.ui.TextInput(label="Full Name (First & Last)", required=True)
    street = discord.ui.TextInput(label="Street Address", required=True)
    city = discord.ui.TextInput(label="City", required=True)
    state = discord.ui.TextInput(label="State", required=True)
    zip_code = discord.ui.TextInput(label="Zip Code", required=True)

    def __init__(self, bot, user_id: int, guild_id: int):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            existing = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM user_shipping_info
                WHERE user_id = $1 AND guild_id = $2;
                """,
                self.user_id,
                self.guild_id
            )

            if existing and existing >= 1:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Maximum Addresses Reached",
                        description="You already have a saved shipping address. The maximum allowed is **1**.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                return

            await conn.execute(
                """
                INSERT INTO user_shipping_info (
                    user_id, guild_id, full_name, street_address, city, state, zip
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7);
                """,
                self.user_id,
                self.guild_id,
                self.full_name.value,
                self.street.value,
                self.city.value,
                self.state.value,
                self.zip_code.value
            )

        embed = discord.Embed(
            title="Shipping Address Saved",
            description=(
                "Your shipping address has been saved:\n\n"
                f"**Name:** {self.full_name.value}\n"
                f"**Street:** {self.street.value}\n"
                f"**City:** {self.city.value}\n"
                f"**State:** {self.state.value}\n"
                f"**Zip:** {self.zip_code.value}"
            ),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# UPDATE FIELD VIEW + SELECT
# ============================================================
class UpdateFieldView(discord.ui.View):
    def __init__(self, bot, user_id: int, guild_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id

        options = [
            discord.SelectOption(label="Full Name", value="full_name"),
            discord.SelectOption(label="Street Address", value="street_address"),
            discord.SelectOption(label="City", value="city"),
            discord.SelectOption(label="State", value="state"),
            discord.SelectOption(label="Zip Code", value="zip"),
        ]

        self.field_select = discord.ui.Select(
            placeholder="Select a field to update",
            options=options,
            min_values=1,
            max_values=1
        )
        self.field_select.callback = self.field_selected
        self.add_item(self.field_select)

    async def field_selected(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="You can only manage your own shipping information.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        field = self.field_select.values[0]
        await interaction.response.send_modal(
            UpdateValueModal(self.bot, self.user_id, self.guild_id, field)
        )


class UpdateValueModal(discord.ui.Modal, title="Update Shipping Field"):
    new_value = discord.ui.TextInput(label="New Value", required=True)

    def __init__(self, bot, user_id: int, guild_id: int, field: str):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.field = field

    async def on_submit(self, interaction: discord.Interaction):
        column_map = {
            "full_name": "full_name",
            "street_address": "street_address",
            "city": "city",
            "state": "state",
            "zip": "zip"
        }

        column = column_map.get(self.field)
        if column is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Error",
                    description="Invalid field selected.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            record = await conn.fetchrow(
                """
                SELECT shipping_info_id
                FROM user_shipping_info
                WHERE user_id = $1 AND guild_id = $2;
                """,
                self.user_id,
                self.guild_id
            )

            if record is None:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="No Saved Address",
                        description="You do not have a saved shipping address to update.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                return

            await conn.execute(
                f"""
                UPDATE user_shipping_info
                SET {column} = $3
                WHERE user_id = $1 AND guild_id = $2;
                """,
                self.user_id,
                self.guild_id,
                self.new_value.value
            )

        field_label = {
            "full_name": "Full Name",
            "street_address": "Street Address",
            "city": "City",
            "state": "State",
            "zip": "Zip Code"
        }.get(self.field, self.field)

        embed = discord.Embed(
            title="Shipping Address Updated",
            description=(
                f"Your **{field_label}** has been updated to:\n\n"
                f"**{self.new_value.value}**"
            ),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# DELETE CONFIRMATION VIEW
# ============================================================
class DeleteConfirmView(discord.ui.View):
    def __init__(self, bot, user_id: int, guild_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id

    @discord.ui.button(label="Yes, Delete", style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="You can only manage your own shipping information.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM user_shipping_info
                WHERE user_id = $1 AND guild_id = $2;
                """,
                self.user_id,
                self.guild_id
            )

        embed = discord.Embed(
            title="Shipping Address Deleted",
            description="Your saved shipping address has been deleted.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="No, Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Access Denied",
                    description="You can only manage your own shipping information.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Deletion Cancelled",
            description="No changes were made. Your shipping address was **not** deleted.",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================================
# SETUP FUNCTION
# ============================================================
async def setup(bot):
    await bot.add_cog(ShippingInfo(bot))
