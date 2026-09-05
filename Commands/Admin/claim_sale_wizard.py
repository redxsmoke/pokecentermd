import discord
from discord.ext import commands
from datetime import datetime, date as dt_date, time as dt_time, timedelta

# ============================================
#  WIZARD STATE
# ============================================

class ClaimSaleWizardState:
    def __init__(self, guild_id: int, admin_id: int):
        self.guild_id = guild_id
        self.admin_id = admin_id

        self.sale_date: dt_date | None = None
        self.sale_time: dt_time | None = None

        self.max_price_label: str | None = None
        self.max_price_value: int | None = None

        self.conditions_selected: list[str] = []
        self.payment_hours: int | None = None

        self.claim_sale_channel_id: int | None = None

    def compute_condition_display(self) -> str:
        if "All Conditions" in self.conditions_selected:
            return "All Conditions"
        return ", ".join(self.conditions_selected)

    def compute_deadline(self) -> datetime | None:
        if not (self.sale_date and self.sale_time and self.payment_hours):
            return None
        base = datetime.combine(self.sale_date, self.sale_time)
        return base + timedelta(hours=self.payment_hours)


# ============================================
#  BASE WIZARD VIEW — SINGLE TIMEOUT
# ============================================

class BaseWizardView(discord.ui.View):
    timeout_sent = False

    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.state = state
        self.root_interaction = interaction

    async def on_timeout(self):
        if BaseWizardView.timeout_sent:
            return

        BaseWizardView.timeout_sent = True

        try:
            embed = discord.Embed(
                title="Claim Sale Wizard",
                description="Wizard expired. Please restart from the admin menu.",
                color=discord.Color.gold(),
            )
            await self.root_interaction.followup.send(embed=embed, ephemeral=True)
        except Exception:
            pass


# ============================================
#  HOME MENU VIEW
# ============================================

class ClaimSaleHomeView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(state, interaction)

        self.create_btn = discord.ui.Button(label="Create Claim Sale", style=discord.ButtonStyle.primary)
        self.update_btn = discord.ui.Button(label="Update Existing Claim Sale", style=discord.ButtonStyle.secondary)
        self.delete_btn = discord.ui.Button(label="Delete Claim Sale", style=discord.ButtonStyle.danger)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.create_btn.callback = self.create_claim_sale
        self.update_btn.callback = self.update_claim_sale
        self.delete_btn.callback = self.delete_claim_sale
        self.cancel_btn.callback = self.cancel

        self.add_item(self.create_btn)
        self.add_item(self.update_btn)
        self.add_item(self.delete_btn)
        self.add_item(self.cancel_btn)

    async def create_claim_sale(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Step 1 — Claim Sale Date",
            description="Enter the **date** for the claim sale.\nFormat: YYYY-MM-DD",
            color=discord.Color.gold(),
        )
        view = ClaimSaleDateView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def update_claim_sale(self, interaction: discord.Interaction):
        view = ClaimSaleSelectExistingView(self.state, self.root_interaction)
        await view.load_sales(interaction)

    async def delete_claim_sale(self, interaction: discord.Interaction):
        view = ClaimSaleSelectExistingForDeleteView(self.state, self.root_interaction)
        await view.load_sales(interaction)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Claim Sale Wizard",
            description="Wizard closed.",
            color=discord.Color.gold(),
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  STEP 1 — CLAIM SALE DATE
# ============================================

class ClaimSaleDateModal(discord.ui.Modal, title="Claim Sale Date"):
    date_input = discord.ui.TextInput(
        label="Date (YYYY-MM-DD)",
        required=True,
        placeholder="2026-12-25"
    )

    def __init__(self, state: ClaimSaleWizardState, parent_view: "ClaimSaleDateView"):
        super().__init__()
        self.state = state
        self.parent_view = parent_view

        if self.state.sale_date:
            self.date_input.default = self.state.sale_date.isoformat()

    async def on_submit(self, interaction: discord.Interaction):
        try:
            parsed = datetime.strptime(self.date_input.value.strip(), "%Y-%m-%d").date()
        except ValueError:
            await interaction.response.send_message(
                "Invalid date format. Use YYYY-MM-DD.",
                ephemeral=True
            )
            return

        today = datetime.now().date()
        if parsed < today:
            await interaction.response.send_message(
                "Date must be in the future.",
                ephemeral=True
            )
            return

        self.state.sale_date = parsed
        await self.parent_view.go_next(interaction)


class ClaimSaleDateView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(state, interaction)

        self.next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.next_btn.callback = self.open_modal
        self.cancel_btn.callback = self.cancel

        self.add_item(self.next_btn)
        self.add_item(self.cancel_btn)

    async def open_modal(self, interaction: discord.Interaction):
        modal = ClaimSaleDateModal(self.state, self)
        await interaction.response.send_modal(modal)

    async def go_next(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Step 2 — Claim Sale Time",
            description="Enter the **time** for the claim sale.\nFormat: HH:MM (24-hour EST)",
            color=discord.Color.gold()
        )
        view = ClaimSaleTimeView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Claim Sale Wizard",
            description="Wizard closed.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  STEP 2 — CLAIM SALE TIME
# ============================================

class ClaimSaleTimeModal(discord.ui.Modal, title="Claim Sale Time"):
    time_input = discord.ui.TextInput(
        label="Time (HH:MM, 24-hour EST)",
        required=True,
        placeholder="14:30"
    )

    def __init__(self, state: ClaimSaleWizardState, parent_view: "ClaimSaleTimeView"):
        super().__init__()
        self.state = state
        self.parent_view = parent_view

        if self.state.sale_time:
            self.time_input.default = self.state.sale_time.strftime("%H:%M")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            parsed = datetime.strptime(self.time_input.value.strip(), "%H:%M").time()
        except ValueError:
            await interaction.response.send_message(
                "Invalid time format. Use HH:MM (24-hour).",
                ephemeral=True
            )
            return

        self.state.sale_time = parsed
        await self.parent_view.go_next(interaction)


class ClaimSaleTimeView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(state, interaction)

        self.next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary)
        self.back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.next_btn.callback = self.open_modal
        self.back_btn.callback = self.go_back
        self.cancel_btn.callback = self.cancel

        self.add_item(self.next_btn)
        self.add_item(self.back_btn)
        self.add_item(self.cancel_btn)

    async def open_modal(self, interaction: discord.Interaction):
        modal = ClaimSaleTimeModal(self.state, self)
        await interaction.response.send_modal(modal)

    async def go_back(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Step 1 — Claim Sale Date",
            description="Enter the **date** for the claim sale.\nFormat: YYYY-MM-DD",
            color=discord.Color.gold()
        )
        view = ClaimSaleDateView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def go_next(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Step 3 — Price Range",
            description="Select the **inventory price range** to include.",
            color=discord.Color.gold()
        )
        view = ClaimSalePriceView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Claim Sale Wizard",
            description="Wizard closed.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  STEP 3 — PRICE RANGE
# ============================================

class PriceRangeDropdown(discord.ui.Select):
    def __init__(self, state: ClaimSaleWizardState):
        self.state = state

        options = [
            discord.SelectOption(label="All Inventory", value="all"),
            discord.SelectOption(label="Under $5", value="5"),
            discord.SelectOption(label="Under $10", value="10"),
            discord.SelectOption(label="Under $25", value="25"),
            discord.SelectOption(label="Under $50", value="50"),
            discord.SelectOption(label="Under $100", value="100"),
        ]

        super().__init__(
            placeholder="Select a price range...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]

        async with interaction.client.db.acquire() as conn:

            # ================================
            # ALL INVENTORY → full min/max
            # ================================
            if val == "all":
                row = await conn.fetchrow(
                    """
                    SELECT 
                        MIN(price) AS min_price,
                        MAX(price) AS max_price
                    FROM inventory
                    WHERE guild_id = $1
                      AND is_active = TRUE
                      AND quantity_available >= 1
                    """,
                    self.state.guild_id
                )

            # ================================
            # SPECIFIC RANGE → min/max ≤ val
            # ================================
            else:
                max_limit = int(val)
                row = await conn.fetchrow(
                    """
                    SELECT 
                        MIN(price) AS min_price,
                        MAX(price) AS max_price
                    FROM inventory
                    WHERE guild_id = $1
                      AND is_active = TRUE
                      AND quantity_available >= 1
                      AND price <= $2
                    """,
                    self.state.guild_id,
                    max_limit
                )

        # Handle no matching rows
        if not row or row["min_price"] is None or row["max_price"] is None:
            self.state.min_price_value = None
            self.state.max_price_value = None
            self.state.max_price_label = "No Matching Inventory"
        else:
            self.state.min_price_value = row["min_price"]
            self.state.max_price_value = row["max_price"]
            self.state.max_price_label = f"${row['min_price']} - ${row['max_price']}"

        await self.view.go_next(interaction)


class ClaimSalePriceView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(state, interaction)

        self.dropdown = PriceRangeDropdown(state)
        self.back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.back_btn.callback = self.go_back
        self.cancel_btn.callback = self.cancel

        self.add_item(self.dropdown)
        self.add_item(self.back_btn)
        self.add_item(self.cancel_btn)

    async def go_back(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Step 2 — Claim Sale Time",
            description="Enter the **time** for the claim sale.\nFormat: HH:MM (24-hour EST)",
            color=discord.Color.gold()
        )
        view = ClaimSaleTimeView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def go_next(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Step 4 — Conditions",
            description="Select the **conditions** to include.\nYou may choose multiple.",
            color=discord.Color.gold()
        )
        view = ClaimSaleConditionsView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Claim Sale Wizard",
            description="Wizard closed.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  STEP 4 — CONDITIONS
# ============================================

class ConditionsDropdown(discord.ui.Select):
    def __init__(self, state: ClaimSaleWizardState):
        self.state = state

        options = [
            discord.SelectOption(label="All Conditions", value="All Conditions"),
            discord.SelectOption(label="Near Mint", value="Near Mint"),
            discord.SelectOption(label="Lightly Played", value="Lightly Played"),
            discord.SelectOption(label="Moderately Played", value="Moderately Played"),
            discord.SelectOption(label="Heavily Played", value="Heavily Played"),
            discord.SelectOption(label="Damaged", value="Damaged"),
        ]

        super().__init__(
            placeholder="Select conditions...",
            min_values=1,
            max_values=6,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        vals = self.values

        if "All Conditions" in vals:
            self.state.conditions_selected = ["All Conditions"]
        else:
            self.state.conditions_selected = vals

        await self.view.go_next(interaction)


class ClaimSaleConditionsView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(state, interaction)

        self.dropdown = ConditionsDropdown(state)
        self.back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.back_btn.callback = self.go_back
        self.cancel_btn.callback = self.cancel

        self.add_item(self.dropdown)
        self.add_item(self.back_btn)
        self.add_item(self.cancel_btn)

    async def go_back(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Step 3 — Price Range",
            description="Select the **inventory price range** to include.",
            color=discord.Color.gold()
        )
        view = ClaimSalePriceView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def go_next(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Step 5 — Payment Deadline",
            description="Select how many hours buyers have to pay.",
            color=discord.Color.gold()
        )
        view = ClaimSalePaymentView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Claim Sale Wizard",
            description="Wizard closed.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  STEP 5 — PAYMENT DEADLINE
# ============================================

class PaymentDeadlineDropdown(discord.ui.Select):
    def __init__(self, state: ClaimSaleWizardState):
        self.state = state

        options = [
            discord.SelectOption(label="6 hours", value="6"),
            discord.SelectOption(label="12 hours", value="12"),
            discord.SelectOption(label="24 hours", value="24"),
            discord.SelectOption(label="48 hours", value="48"),
            discord.SelectOption(label="72 hours", value="72"),
            discord.SelectOption(label="7 days", value="168"),
        ]

        super().__init__(
            placeholder="Select payment deadline...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        self.state.payment_hours = int(self.values[0])
        await self.view.go_next(interaction)


class ClaimSalePaymentView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(state, interaction)

        self.dropdown = PaymentDeadlineDropdown(state)
        self.back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.back_btn.callback = self.go_back
        self.cancel_btn.callback = self.cancel

        self.add_item(self.dropdown)
        self.add_item(self.back_btn)
        self.add_item(self.cancel_btn)

    async def go_back(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Step 4 — Conditions",
            description="Select the **conditions** to include.\nYou may choose multiple.",
            color=discord.Color.gold()
        )
        view = ClaimSaleConditionsView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def go_next(self, interaction: discord.Interaction):
        view = ClaimSaleChannelSelectView(self.state, self.root_interaction)
        await view.load_channels(interaction)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Claim Sale Wizard",
            description="Wizard closed.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  STEP 6 — CHANNEL SELECTION
# ============================================

class ChannelSelectDropdown(discord.ui.Select):
    def __init__(self, state: ClaimSaleWizardState, channels: list[discord.SelectOption]):
        self.state = state

        super().__init__(
            placeholder="Select a channel for the claim sale...",
            min_values=1,
            max_values=1,
            options=channels
        )

    async def callback(self, interaction: discord.Interaction):
        self.state.claim_sale_channel_id = int(self.values[0])
        await self.view.go_next(interaction)


class ClaimSaleChannelSelectView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(state, interaction)

        self.back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.back_btn.callback = self.go_back
        self.cancel_btn.callback = self.cancel

        self.add_item(self.back_btn)
        self.add_item(self.cancel_btn)

    async def load_channels(self, interaction: discord.Interaction):
        options = []

        for channel in interaction.guild.channels:
            if isinstance(channel, discord.TextChannel):
                options.append(
                    discord.SelectOption(
                        label=f"#{channel.name}",
                        value=str(channel.id)
                    )
                )

        dropdown = ChannelSelectDropdown(self.state, options)
        self.add_item(dropdown)

        embed = discord.Embed(
            title="Step 6 — Claim Sale Channel",
            description="Select the **channel** where claim sale announcements will be posted.",
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def go_back(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Step 5 — Payment Deadline",
            description="Select how many hours buyers have to pay.",
            color=discord.Color.gold()
        )
        view = ClaimSalePaymentView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def go_next(self, interaction: discord.Interaction):
        deadline = self.state.compute_deadline()
        deadline_str = deadline.strftime("%Y-%m-%d %H:%M EST") if deadline else "N/A"

        conditions_display = self.state.compute_condition_display()
        price_display = self.state.max_price_label or "Not set"

        async with interaction.client.db.acquire() as conn:
            if "All Conditions" in self.state.conditions_selected:
                count = await conn.fetchval(
                    """
                    SELECT COALESCE(SUM(quantity_available), 0)
                    FROM inventory
                    WHERE guild_id = $1
                      AND is_active = TRUE
                      AND quantity_available >= 1 
                      AND ($2::int IS NULL OR price < $2)
                    """,
                    self.state.guild_id,
                    self.state.max_price_value,
                )
            else:
                count = await conn.fetchval(
                    """
                    SELECT COALESCE(SUM(quantity_available), 0)
                    FROM inventory
                    WHERE guild_id = $1
                      AND is_active = TRUE
                      AND quantity_available >= 1 
                      AND ($3::int IS NULL OR price < $3)
                      AND condition = ANY($2::text[])
                    """,
                    self.state.guild_id,
                    self.state.conditions_selected,
                    self.state.max_price_value,
                )

        embed = discord.Embed(
            title="Claim Sale Preview",
            description="Review the configuration below.",
            color=discord.Color.gold()
        )
        embed.add_field(name="Date", value=self.state.sale_date.isoformat(), inline=False)
        embed.add_field(name="Time (EST)", value=self.state.sale_time.strftime("%H:%M"), inline=False)
        embed.add_field(name="Price Range", value=price_display, inline=False)
        embed.add_field(name="Conditions", value=conditions_display, inline=False)
        embed.add_field(name="Payment Deadline", value=deadline_str, inline=False)
        embed.add_field(name="Channel", value=f"<#{self.state.claim_sale_channel_id}>", inline=False)
        embed.add_field(name="Matching Inventory Count", value=str(count), inline=False)

        view = ClaimSalePreviewView(self.state, self.root_interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Claim Sale Wizard",
            description="Wizard closed.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  PREVIEW + CREATE SALE
# ============================================

class ClaimSalePreviewView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(state, interaction)

        self.create_btn = discord.ui.Button(label="Create Sale", style=discord.ButtonStyle.success)
        self.back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.create_btn.callback = self.create_sale
        self.back_btn.callback = self.go_back
        self.cancel_btn.callback = self.cancel

        self.add_item(self.create_btn)
        self.add_item(self.back_btn)
        self.add_item(self.cancel_btn)

    async def go_back(self, interaction: discord.Interaction):
        view = ClaimSaleChannelSelectView(self.state, self.root_interaction)
        await view.load_channels(interaction)

    async def create_sale(self, interaction: discord.Interaction):

        # ⭐ FIRST: compute number_of_cards using same logic as runtime
        async with interaction.client.db.acquire() as conn:

            # All Conditions
            if "All Conditions" in self.state.conditions_selected:
                rows = await conn.fetch(
                    """
                    SELECT quantity_available
                    FROM inventory
                    WHERE guild_id = $1
                      AND is_active = TRUE
                      AND quantity_available >= 1
                      AND ($2::int IS NULL OR price <= $2)
                    """,
                    self.state.guild_id,
                    self.state.max_price_value
                )
            else:
                # Specific conditions
                rows = await conn.fetch(
                    """
                    SELECT quantity_available
                    FROM inventory
                    WHERE guild_id = $1
                      AND is_active = TRUE
                      AND quantity_available >= 1
                      AND price <= $3
                      AND condition = ANY($2::text[])
                    """,
                    self.state.guild_id,
                    self.state.conditions_selected,
                    self.state.max_price_value
                )


        expanded_count = sum(r["quantity_available"] for r in rows)
        self.state.number_of_cards = expanded_count

        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO claim_sales
                    (guild_id, admin_id, sale_date, sale_time,
                     min_price_value, max_price_value,
                     max_price_label, conditions,
                     payment_hours, claim_sale_channel_id,
                     number_of_cards, is_ran)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,FALSE)
                """,
                self.state.guild_id,
                self.state.admin_id,
                self.state.sale_date,
                self.state.sale_time,
                self.state.min_price_value,
                self.state.max_price_value,
                self.state.max_price_label,
                self.state.conditions_selected,
                self.state.payment_hours,
                self.state.claim_sale_channel_id,
                self.state.number_of_cards
            )

        embed = discord.Embed(
            title="Claim Sale Created",
            description="Your claim sale has been created successfully.",
            color=discord.Color.green()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Claim Sale Wizard",
            description="Wizard closed.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)



# ============================================
#  SELECT EXISTING CLAIM SALE (UPDATE)
# ============================================

class ClaimSaleExistingDropdown(discord.ui.Select):
    def __init__(self, state: ClaimSaleWizardState, sales: list[discord.SelectOption]):
        self.state = state

        super().__init__(
            placeholder="Select a claim sale...",
            min_values=1,
            max_values=1,
            options=sales
        )

    async def callback(self, interaction: discord.Interaction):
        sale_id = int(self.values[0])
        await self.view.load_sale(interaction, sale_id)


class ClaimSaleSelectExistingView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(state, interaction)

        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        self.cancel_btn.callback = self.cancel
        self.add_item(self.cancel_btn)

    async def load_sales(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT claim_sale_id, sale_date, sale_time
                FROM claim_sales
                WHERE guild_id = $1
                ORDER BY claim_sale_id DESC
                """,
                self.state.guild_id
            )

        options = [
            discord.SelectOption(
                label=f"Sale #{r['claim_sale_id']} — {r['sale_date']} {r['sale_time']}",
                value=str(r["claim_sale_id"])
            )
            for r in rows
        ]

        dropdown = ClaimSaleExistingDropdown(self.state, options)
        self.add_item(dropdown)

        embed = discord.Embed(
            title="Update Claim Sale",
            description="Select an existing claim sale to edit.",
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def load_sale(self, interaction: discord.Interaction, sale_id: int):
        view = ClaimSaleEditMenuView(self.state, self.root_interaction, sale_id)
        embed = discord.Embed(
            title="Edit Claim Sale",
            description="Choose what to edit.",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Claim Sale Wizard",
            description="Wizard closed.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  EDIT MENU
# ============================================

class ClaimSaleEditMenuView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction, sale_id: int):
        super().__init__(state, interaction)
        self.sale_id = sale_id

        self.edit_date_btn = discord.ui.Button(label="Edit Date", style=discord.ButtonStyle.primary)
        self.edit_time_btn = discord.ui.Button(label="Edit Time", style=discord.ButtonStyle.primary)
        self.edit_price_btn = discord.ui.Button(label="Edit Price Range", style=discord.ButtonStyle.primary)
        self.edit_conditions_btn = discord.ui.Button(label="Edit Conditions", style=discord.ButtonStyle.primary)
        self.edit_payment_btn = discord.ui.Button(label="Edit Payment Deadline", style=discord.ButtonStyle.primary)
        self.edit_channel_btn = discord.ui.Button(label="Edit Channel", style=discord.ButtonStyle.primary)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.edit_date_btn.callback = self.edit_date
        self.edit_time_btn.callback = self.edit_time
        self.edit_price_btn.callback = self.edit_price
        self.edit_conditions_btn.callback = self.edit_conditions
        self.edit_payment_btn.callback = self.edit_payment
        self.edit_channel_btn.callback = self.edit_channel
        self.cancel_btn.callback = self.cancel

        self.add_item(self.edit_date_btn)
        self.add_item(self.edit_time_btn)
        self.add_item(self.edit_price_btn)
        self.add_item(self.edit_conditions_btn)
        self.add_item(self.edit_payment_btn)
        self.add_item(self.edit_channel_btn)
        self.add_item(self.cancel_btn)

    async def load_state(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT sale_date, sale_time, max_price_label, max_price_value,
                       conditions, payment_hours, claim_sale_channel_id
                FROM claim_sales
                WHERE claim_sale_id = $1
                """,
                self.sale_id
            )

        self.state.sale_date = row["sale_date"]
        self.state.sale_time = row["sale_time"]
        self.state.max_price_label = row["max_price_label"]
        self.state.max_price_value = row["max_price_value"]
        self.state.conditions_selected = row["conditions"]
        self.state.payment_hours = row["payment_hours"]
        self.state.claim_sale_channel_id = row["claim_sale_channel_id"]

    async def edit_date(self, interaction: discord.Interaction):
        await self.load_state(interaction)
        view = ClaimSaleDateEditView(self.state, self.root_interaction, self.sale_id)

        embed = discord.Embed(
            title="Edit Date",
            description="Update the **date** for this claim sale.",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def edit_time(self, interaction: discord.Interaction):
        await self.load_state(interaction)
        view = ClaimSaleTimeEditView(self.state, self.root_interaction, self.sale_id)

        embed = discord.Embed(
            title="Edit Time",
            description="Update the **time** for this claim sale.",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def edit_price(self, interaction: discord.Interaction):
        await self.load_state(interaction)
        view = ClaimSalePriceEditView(self.state, self.root_interaction, self.sale_id)

        embed = discord.Embed(
            title="Edit Price Range",
            description="Update the **inventory price range**.",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def edit_conditions(self, interaction: discord.Interaction):
        await self.load_state(interaction)
        view = ClaimSaleConditionsEditView(self.state, self.root_interaction, self.sale_id)

        embed = discord.Embed(
            title="Edit Conditions",
            description="Update the **conditions** included.",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def edit_payment(self, interaction: discord.Interaction):
        await self.load_state(interaction)
        view = ClaimSalePaymentEditView(self.state, self.root_interaction, self.sale_id)

        embed = discord.Embed(
            title="Edit Payment Deadline",
            description="Update how many hours buyers have to pay.",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def edit_channel(self, interaction: discord.Interaction):
        await self.load_state(interaction)
        view = ClaimSaleChannelEditView(self.state, self.root_interaction, self.sale_id)
        await view.load_channels(interaction)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Edit Wizard",
            description="Edit canceled.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  EDIT DATE
# ============================================

class ClaimSaleDateEditModal(discord.ui.Modal, title="Edit Claim Sale Date"):
    date_input = discord.ui.TextInput(
        label="Date (YYYY-MM-DD)",
        required=True
    )

    def __init__(self, state: ClaimSaleWizardState, parent_view: "ClaimSaleDateEditView"):
        super().__init__()
        self.state = state
        self.parent_view = parent_view

        if self.state.sale_date:
            self.date_input.default = self.state.sale_date.isoformat()

    async def on_submit(self, interaction: discord.Interaction):
        try:
            parsed = datetime.strptime(self.date_input.value.strip(), "%Y-%m-%d").date()
        except ValueError:
            await interaction.response.send_message("Invalid date format.", ephemeral=True)
            return

        today = datetime.now().date()
        if parsed < today:
            await interaction.response.send_message("Date must be in the future.", ephemeral=True)
            return

        self.state.sale_date = parsed
        await self.parent_view.save(interaction)


class ClaimSaleDateEditView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction, sale_id: int):
        super().__init__(state, interaction)
        self.sale_id = sale_id

        self.edit_btn = discord.ui.Button(label="Edit Date", style=discord.ButtonStyle.primary)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.edit_btn.callback = self.open_modal
        self.cancel_btn.callback = self.cancel

        self.add_item(self.edit_btn)
        self.add_item(self.cancel_btn)

    async def open_modal(self, interaction: discord.Interaction):
        modal = ClaimSaleDateEditModal(self.state, self)
        await interaction.response.send_modal(modal)

    async def save(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE claim_sales
                SET sale_date = $1
                WHERE claim_sale_id = $2
                """,
                self.state.sale_date,
                self.sale_id
            )

        embed = discord.Embed(
            title="Date Updated",
            description="Claim sale date updated successfully.",
            color=discord.Color.green()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Edit Wizard",
            description="Edit canceled.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  EDIT TIME
# ============================================

class ClaimSaleTimeEditModal(discord.ui.Modal, title="Edit Claim Sale Time"):
    time_input = discord.ui.TextInput(
        label="Time (HH:MM, 24-hour EST)",
        required=True
    )

    def __init__(self, state: ClaimSaleWizardState, parent_view: "ClaimSaleTimeEditView"):
        super().__init__()
        self.state = state
        self.parent_view = parent_view

        if self.state.sale_time:
            self.time_input.default = self.state.sale_time.strftime("%H:%M")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            parsed = datetime.strptime(self.time_input.value.strip(), "%H:%M").time()
        except ValueError:
            await interaction.response.send_message("Invalid time format.", ephemeral=True)
            return

        self.state.sale_time = parsed
        await self.parent_view.save(interaction)


class ClaimSaleTimeEditView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction, sale_id: int):
        super().__init__(state, interaction)
        self.sale_id = sale_id

        self.edit_btn = discord.ui.Button(label="Edit Time", style=discord.ButtonStyle.primary)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.edit_btn.callback = self.open_modal
        self.cancel_btn.callback = self.cancel

        self.add_item(self.edit_btn)
        self.add_item(self.cancel_btn)

    async def open_modal(self, interaction: discord.Interaction):
        modal = ClaimSaleTimeEditModal(self.state, self)
        await interaction.response.send_modal(modal)

    async def save(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE claim_sales
                SET sale_time = $1
                WHERE claim_sale_id = $2
                """,
                self.state.sale_time,
                self.sale_id
            )

        embed = discord.Embed(
            title="Time Updated",
            description="Claim sale time updated successfully.",
            color=discord.Color.green()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Edit Wizard",
            description="Edit canceled.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  EDIT PRICE RANGE
# ============================================

class ClaimSalePriceEditView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction, sale_id: int):
        super().__init__(state, interaction)
        self.sale_id = sale_id

        self.dropdown = PriceRangeDropdown(state)
        self.save_btn = discord.ui.Button(label="Save", style=discord.ButtonStyle.success)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.save_btn.callback = self.save
        self.cancel_btn.callback = self.cancel

        self.add_item(self.dropdown)
        self.add_item(self.save_btn)
        self.add_item(self.cancel_btn)

    async def go_next(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Edit Conditions",
            description="Select the conditions to include.",
            color=discord.Color.gold()
        )
        view = ClaimSaleConditionsEditView(self.state, self.root_interaction, self.sale_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def save(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE claim_sales
                SET max_price_label = $1,
                    max_price_value = $2
                WHERE claim_sale_id = $3
                """,
                self.state.max_price_label,
                self.state.max_price_value,
                self.sale_id
            )

        embed = discord.Embed(
            title="Price Range Updated",
            description="Price range updated successfully.",
            color=discord.Color.green()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Edit Wizard",
            description="Edit canceled.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  EDIT CONDITIONS
# ============================================

class ClaimSaleConditionsEditView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction, sale_id: int):
        super().__init__(state, interaction)
        self.sale_id = sale_id

        self.dropdown = ConditionsDropdown(state)
        self.save_btn = discord.ui.Button(label="Save", style=discord.ButtonStyle.success)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.save_btn.callback = self.save
        self.cancel_btn.callback = self.cancel

        self.add_item(self.dropdown)
        self.add_item(self.save_btn)
        self.add_item(self.cancel_btn)

    async def go_next(self, interaction: discord.Interaction):
        # Conditions selected via dropdown; just save immediately or move to next edit step if desired.
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE claim_sales
                SET conditions = $1
                WHERE claim_sale_id = $2
                """,
                self.state.conditions_selected,
                self.sale_id
            )

        embed = discord.Embed(
            title="Conditions Updated",
            description="Conditions updated successfully.",
            color=discord.Color.green()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def save(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE claim_sales
                SET conditions = $1
                WHERE claim_sale_id = $2
                """,
                self.state.conditions_selected,
                self.sale_id
            )

        embed = discord.Embed(
            title="Conditions Updated",
            description="Conditions updated successfully.",
            color=discord.Color.green()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Edit Wizard",
            description="Edit canceled.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  EDIT PAYMENT DEADLINE
# ============================================

class ClaimSalePaymentEditView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction, sale_id: int):
        super().__init__(state, interaction)
        self.sale_id = sale_id

        self.dropdown = PaymentDeadlineDropdown(state)
        self.save_btn = discord.ui.Button(label="Save", style=discord.ButtonStyle.success)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.save_btn.callback = self.save
        self.cancel_btn.callback = self.cancel

        self.add_item(self.dropdown)
        self.add_item(self.save_btn)
        self.add_item(self.cancel_btn)

    async def go_next(self, interaction: discord.Interaction):
        # Payment hours selected via dropdown; just save immediately or move to next edit step if desired.
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE claim_sales
                SET payment_hours = $1
                WHERE claim_sale_id = $2
                """,
                self.state.payment_hours,
                self.sale_id
            )

        embed = discord.Embed(
            title="Payment Deadline Updated",
            description="Payment deadline updated successfully.",
            color=discord.Color.green()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def save(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE claim_sales
                SET payment_hours = $1
                WHERE claim_sale_id = $2
                """,
                self.state.payment_hours,
                self.sale_id
            )

        embed = discord.Embed(
            title="Payment Deadline Updated",
            description="Payment deadline updated successfully.",
            color=discord.Color.green()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Edit Wizard",
            description="Edit canceled.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)



# ============================================
#  EDIT CHANNEL
# ============================================

class ClaimSaleChannelEditView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction, sale_id: int):
        super().__init__(state, interaction)
        self.sale_id = sale_id

        self.save_btn = discord.ui.Button(label="Save", style=discord.ButtonStyle.success)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.save_btn.callback = self.save
        self.cancel_btn.callback = self.cancel

        self.add_item(self.save_btn)
        self.add_item(self.cancel_btn)

    async def load_channels(self, interaction: discord.Interaction):
        options = []

        for channel in interaction.guild.channels:
            if isinstance(channel, discord.TextChannel):
                options.append(
                    discord.SelectOption(
                        label=f"#{channel.name}",
                        value=str(channel.id)
                    )
                )

        dropdown = ChannelSelectDropdown(self.state, options)
        self.add_item(dropdown)

        embed = discord.Embed(
            title="Edit Claim Sale Channel",
            description="Select the **channel** where claim sale announcements will be posted.",
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def go_next(self, interaction: discord.Interaction):
        # Called automatically when the dropdown is selected
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE claim_sales
                SET claim_sale_channel_id = $1
                WHERE claim_sale_id = $2
                """,
                self.state.claim_sale_channel_id,
                self.sale_id
            )

        embed = discord.Embed(
            title="Channel Updated",
            description="Claim sale channel updated successfully.",
            color=discord.Color.green()
        )

        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def save(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE claim_sales
                SET claim_sale_channel_id = $1
                WHERE claim_sale_id = $2
                """,
                self.state.claim_sale_channel_id,
                self.sale_id
            )

        embed = discord.Embed(
            title="Channel Updated",
            description="Claim sale channel updated successfully.",
            color=discord.Color.green()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Edit Wizard",
            description="Edit canceled.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)



# ============================================
#  SELECT EXISTING CLAIM SALE (DELETE)
# ============================================

class ClaimSaleExistingDeleteDropdown(discord.ui.Select):
    def __init__(self, state: ClaimSaleWizardState, sales: list[discord.SelectOption]):
        self.state = state

        super().__init__(
            placeholder="Select a claim sale to delete...",
            min_values=1,
            max_values=1,
            options=sales
        )

    async def callback(self, interaction: discord.Interaction):
        sale_id = int(self.values[0])
        await self.view.confirm_delete(interaction, sale_id)


class ClaimSaleSelectExistingForDeleteView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction):
        super().__init__(state, interaction)

        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        self.cancel_btn.callback = self.cancel
        self.add_item(self.cancel_btn)

    async def load_sales(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT claim_sale_id, sale_date, sale_time
                FROM claim_sales
                WHERE guild_id = $1
                ORDER BY claim_sale_id DESC
                """,
                self.state.guild_id
            )

        options = [
            discord.SelectOption(
                label=f"Sale #{r['claim_sale_id']} — {r['sale_date']} {r['sale_time']}",
                value=str(r["claim_sale_id"])
            )
            for r in rows
        ]

        dropdown = ClaimSaleExistingDeleteDropdown(self.state, options)
        self.add_item(dropdown)

        embed = discord.Embed(
            title="Delete Claim Sale",
            description="Select an existing claim sale to delete.",
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def confirm_delete(self, interaction: discord.Interaction, sale_id: int):
        view = ClaimSaleDeleteConfirmView(self.state, self.root_interaction, sale_id)

        embed = discord.Embed(
            title="Confirm Delete",
            description=f"Are you sure you want to delete claim sale #{sale_id}?",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Delete Wizard",
            description="Delete canceled.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  DELETE CONFIRMATION
# ============================================

class ClaimSaleDeleteConfirmView(BaseWizardView):
    def __init__(self, state: ClaimSaleWizardState, interaction: discord.Interaction, sale_id: int):
        super().__init__(state, interaction)
        self.sale_id = sale_id

        self.delete_btn = discord.ui.Button(label="Delete", style=discord.ButtonStyle.danger)
        self.cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        self.delete_btn.callback = self.delete_sale
        self.cancel_btn.callback = self.cancel

        self.add_item(self.delete_btn)
        self.add_item(self.cancel_btn)

    async def delete_sale(self, interaction: discord.Interaction):
        async with interaction.client.db.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM claim_sales
                WHERE claim_sale_id = $1
                """,
                self.sale_id
            )

        embed = discord.Embed(
            title="Claim Sale Deleted",
            description=f"Claim sale #{self.sale_id} has been deleted.",
            color=discord.Color.green()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Delete Wizard",
            description="Delete canceled.",
            color=discord.Color.gold()
        )
        self.stop()
        BaseWizardView.timeout_sent = True
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================
#  COG + ADMIN ENTRYPOINT
# ============================================

class ClaimSaleCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

     
        self.admin_claimsale_group = discord.app_commands.Group(
            name="admin_claimsale",
            description="Admin Claim Sale Commands",
            default_permissions=discord.Permissions(administrator=True),
            guild_only=True
        )

    async def cog_load(self):

        claim_sale_cmd = discord.app_commands.Command(
            name="manage",
            description="Open the Claim Sale Wizard.",
            callback=self.admin_claim_sale
        )

        claim_sale_cmd.guild_only = True

        # This is why it loaded — no dependency on admincommands.py
        self.admin_claimsale_group.add_command(claim_sale_cmd)

        # And this is why it registered cleanly
        self.bot.tree.add_command(self.admin_claimsale_group)

    async def admin_claim_sale(self, interaction: discord.Interaction):
        BaseWizardView.timeout_sent = False

        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True
            )
            return

        state = ClaimSaleWizardState(
            guild_id=interaction.guild_id,
            admin_id=interaction.user.id,
        )

        embed = discord.Embed(
            title="Claim Sale Wizard",
            description=(
                "Use this wizard to **create**, **update**, or **delete** claim sales.\n\n"
                "Choose an option below to begin."
            ),
            color=discord.Color.gold(),
        )

        view = ClaimSaleHomeView(state, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ClaimSaleCommands(bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(ClaimSaleCommands(bot))
