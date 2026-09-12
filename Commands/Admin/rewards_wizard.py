import discord

# ---------------------------------------------------------
# ENTRY POINT — /admin manage_rewards → Create Reward
# ---------------------------------------------------------
async def start_create_reward_wizard(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Select a reward category:",
        view=RewardCategoryView(),
        ephemeral=True
    )


# ---------------------------------------------------------
# STEP 1 — CATEGORY SELECT
# ---------------------------------------------------------
class RewardCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Level Locked Rewards", value="level_locked"),
            discord.SelectOption(label="Limited Time Promotion", value="timed"),
            discord.SelectOption(label="Limited Use Promotion", value="limited_use"),
        ]
        super().__init__(placeholder="Select reward category...", options=options)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        await interaction.response.send_modal(RewardRequirementsModal(category))


class RewardCategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(RewardCategorySelect())


# ---------------------------------------------------------
# STEP 2 — REQUIREMENTS MODAL
# ---------------------------------------------------------
class RewardRequirementsModal(discord.ui.Modal, title="Reward Requirements"):
    def __init__(self, category):
        super().__init__()
        self.category = category

        if category == "level_locked":
            self.level = discord.ui.TextInput(label="Required level")
            self.add_item(self.level)

        elif category == "timed":
            self.days = discord.ui.TextInput(label="Expires after X days")
            self.add_item(self.days)

        elif category == "limited_use":
            self.max_uses = discord.ui.TextInput(label="Max uses per user")
            self.add_item(self.max_uses)

    async def on_submit(self, interaction: discord.Interaction):

        # -------------------------
        # VALIDATION
        # -------------------------
        if hasattr(self, "level"):
            lvl = self.level.value.strip()
            if not lvl.isdigit() or int(lvl) <= 0:
                return await interaction.response.send_message(
                    "❌ Level must be a positive number.",
                    ephemeral=True
                )

        if hasattr(self, "days"):
            d = self.days.value.strip()
            if not d.isdigit() or int(d) <= 0:
                return await interaction.response.send_message(
                    "❌ Days must be a positive number.",
                    ephemeral=True
                )

        if hasattr(self, "max_uses"):
            mu = self.max_uses.value.strip()
            if not mu.isdigit() or int(mu) <= 0:
                return await interaction.response.send_message(
                    "❌ Max uses must be a positive number.",
                    ephemeral=True
                )

        # -------------------------
        # BUILD DATA
        # -------------------------
        raw_days = getattr(self, "days", None).value if hasattr(self, "days") else None
        if raw_days is None or raw_days.strip() == "":
            expires_days = None
        else:
            expires_days = raw_days.strip()

        data = {
            "category": self.category,
            "required_level": getattr(self, "level", None).value if hasattr(self, "level") else None,
            "expires_days": expires_days,
            "max_uses": getattr(self, "max_uses", None).value if hasattr(self, "max_uses") else None,
        }

        await interaction.response.send_message(
            "Select reward action:",
            view=RewardActionView(data),
            ephemeral=True
        )


# ---------------------------------------------------------
# STEP 3 — ACTION SELECT
# ---------------------------------------------------------
class RewardActionSelect(discord.ui.Select):
    def __init__(self, data):
        self.data = data
        options = [
            discord.SelectOption(label="Free Shipping", value="free_shipping"),
            discord.SelectOption(label="Percent Off", value="percent_off"),
            discord.SelectOption(label="Flat Amount Off", value="flat_off"),
        ]
        super().__init__(placeholder="Select reward action...", options=options)

    async def callback(self, interaction: discord.Interaction):
        action = self.values[0]

        # FREE SHIPPING HAS NO MODAL → SKIP DIRECTLY
        if action == "free_shipping":
            self.data["action"] = "free_shipping"
            self.data["value"] = None

            return await interaction.response.send_message(
                "Select order condition:",
                view=RewardConditionView(self.data),
                ephemeral=True
            )

        # OTHER ACTIONS REQUIRE A MODAL
        await interaction.response.send_modal(RewardActionValueModal(self.data, action))


class RewardActionView(discord.ui.View):
    def __init__(self, data):
        super().__init__(timeout=300)
        self.add_item(RewardActionSelect(data))


# ---------------------------------------------------------
# STEP 4 — ACTION VALUE MODAL
# ---------------------------------------------------------
class RewardActionValueModal(discord.ui.Modal, title="Reward Value"):
    def __init__(self, data, action):
        super().__init__()
        self.data = data
        self.action = action

        if action == "percent_off":
            self.value = discord.ui.TextInput(label="Percent off (e.g., 10)")
            self.add_item(self.value)

        elif action == "flat_off":
            self.value = discord.ui.TextInput(label="Amount off (e.g., 10.00)")
            self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):

        # -------------------------
        # VALIDATION
        # -------------------------
        if hasattr(self, "value"):
            v = self.value.value.strip()

            if self.action == "percent_off":
                if not v.isdigit() or not (1 <= int(v) <= 100):
                    return await interaction.response.send_message(
                        "❌ Percent off must be a number between 1 and 100.",
                        ephemeral=True
                    )

            elif self.action == "flat_off":
                try:
                    fv = float(v)
                    if fv <= 0:
                        return await interaction.response.send_message(
                            "❌ Amount off must be greater than 0.",
                            ephemeral=True
                        )
                except:
                    return await interaction.response.send_message(
                        "❌ Amount off must be a valid number (e.g., 10.00).",
                        ephemeral=True
                    )

        # -------------------------
        # BUILD DATA
        # -------------------------
        self.data["action"] = self.action
        self.data["value"] = getattr(self, "value", None).value if hasattr(self, "value") else None

        await interaction.response.send_message(
            "Select order condition:",
            view=RewardConditionView(self.data),
            ephemeral=True
        )


# ---------------------------------------------------------
# STEP 5 — ORDER CONDITION SELECT
# ---------------------------------------------------------
class RewardConditionSelect(discord.ui.Select):
    def __init__(self, data):
        self.data = data
        options = [
            discord.SelectOption(label="Any Order", value="any"),
            discord.SelectOption(label="Orders Over X Amount", value="min_total"),
        ]
        super().__init__(placeholder="Select order condition...", options=options)

    async def callback(self, interaction: discord.Interaction):
        condition = self.values[0]

        if condition == "any":
            self.data["min_order_total"] = None
            await send_summary(interaction, self.data)

        else:
            await interaction.response.send_modal(RewardMinTotalModal(self.data))


class RewardConditionView(discord.ui.View):
    def __init__(self, data):
        super().__init__(timeout=300)
        self.add_item(RewardConditionSelect(data))


# ---------------------------------------------------------
# STEP 5b — MIN ORDER TOTAL MODAL
# ---------------------------------------------------------
class RewardMinTotalModal(discord.ui.Modal, title="Minimum Order Total"):
    def __init__(self, data):
        super().__init__()
        self.data = data
        self.min_total = discord.ui.TextInput(label="Minimum order total (e.g., 50.00)")
        self.add_item(self.min_total)

    async def on_submit(self, interaction: discord.Interaction):

        # -------------------------
        # VALIDATION
        # -------------------------
        mt = self.min_total.value.strip()
        try:
            fv = float(mt)
            if fv <= 0:
                return await interaction.response.send_message(
                    "❌ Minimum order total must be greater than 0.",
                    ephemeral=True
                )
        except:
            return await interaction.response.send_message(
                "❌ Minimum order total must be a valid number (e.g., 50.00).",
                ephemeral=True
            )

        # -------------------------
        # BUILD DATA
        # -------------------------
        self.data["min_order_total"] = self.min_total.value
        await send_summary(interaction, self.data)


# ---------------------------------------------------------
# FINAL SUMMARY + CONFIRM
# ---------------------------------------------------------
async def send_summary(interaction: discord.Interaction, data: dict):
    embed = discord.Embed(
        title="Reward Summary",
        color=discord.Color.green()
    )

    embed.add_field(name="Category", value=data["category"], inline=False)
    embed.add_field(name="Action", value=data["action"], inline=False)
    embed.add_field(name="Value", value=str(data.get("value", "N/A")), inline=False)
    embed.add_field(name="Required Level", value=str(data.get("required_level", "N/A")), inline=False)
    embed.add_field(name="Expires (days)", value=str(data.get("expires_days", "N/A")), inline=False)
    embed.add_field(name="Max Uses", value=str(data.get("max_uses", "N/A")), inline=False)
    embed.add_field(name="Min Order Total", value=str(data.get("min_order_total", "Any")), inline=False)

    view = RewardConfirmView(data)

    await interaction.response.send_message(
        "Confirm reward creation:",
        embed=embed,
        view=view,
        ephemeral=True
    )


class RewardConfirmView(discord.ui.View):
    def __init__(self, data):
        super().__init__(timeout=300)
        self.data = data

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await save_reward_to_db(interaction, self.data)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Reward creation cancelled.", ephemeral=True)


# ---------------------------------------------------------
# DATABASE INSERT LOGIC
# ---------------------------------------------------------
async def save_reward_to_db(interaction: discord.Interaction, data: dict):
    async with interaction.client.db.acquire() as conn:

        # -------------------------
        # CLEAN PARSED VALUES
        # -------------------------
        required_level = int(data["required_level"]) if data.get("required_level") else None
        max_uses = int(data["max_uses"]) if data.get("max_uses") else None
        min_order_total = float(data["min_order_total"]) if data.get("min_order_total") else None

        # expiration_date: convert expires_days → timestamp
        expires_days = data.get("expires_days")
        if expires_days:
            expiration_date_sql = f"NOW() + ({int(expires_days)} * INTERVAL '1 day')"
        else:
            expiration_date_sql = "NULL"

        # -------------------------
        # INSERT INTO NEW guild_rewards SCHEMA
        # -------------------------
        reward_row = await conn.fetchrow(
            f"""
            INSERT INTO guild_rewards (
                guild_id,
                name,
                category,
                type,
                value,
                required_level,
                expiration_date,
                max_uses,
                min_order_total,
                active
            )
            VALUES (
                $1,
                $2,
                $3,
                $4,
                $5,
                $6,
                {expiration_date_sql},
                $7,
                $8,
                TRUE
            )
            RETURNING reward_id
            """,
            interaction.guild.id,
            f"{data['category'].replace('_', ' ').title()} Reward",
            data["category"],
            data["action"],
            data.get("value"),
            required_level,
            max_uses,
            min_order_total
        )

        reward_id = reward_row["reward_id"]

    # ---------------------------------------------------------
    # EMBEDDED SUCCESS MESSAGE
    # ---------------------------------------------------------
    success_embed = discord.Embed(
        title="🎉 Reward Created!",
        description="Your reward has been successfully saved and is now active.",
        color=discord.Color.green()
    )

    await interaction.response.send_message(
        embed=success_embed,
        ephemeral=True
    )


# ---------------------------------------------------------
# UPDATE + DELETE WIZARDS 
# ---------------------------------------------------------

async def start_update_reward_wizard(interaction: discord.Interaction):
    async with interaction.client.db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT reward_id, name, category, type
            FROM guild_rewards
            WHERE guild_id = $1
            ORDER BY reward_id
            """,
            interaction.guild.id
        )

    if not rows:
        await interaction.response.send_message(
            "No rewards exist yet.",
            ephemeral=True
        )
        return

    class RewardUpdateSelect(discord.ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(
                    label=f"{r['name']} ({r['category']} / {r['type']})",
                    value=str(r["reward_id"])
                )
                for r in rows
            ]
            super().__init__(placeholder="Select a reward to update", options=options)

        async def callback(self, inner_interaction: discord.Interaction):
            reward_id = int(self.values[0])
            await start_update_reward_flow(inner_interaction, reward_id)

    class RewardUpdateView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            self.add_item(RewardUpdateSelect())

    await interaction.response.send_message(
        "Select a reward to update:",
        view=RewardUpdateView(),
        ephemeral=True
    )


async def start_update_reward_flow(interaction: discord.Interaction, reward_id: int):
    async with interaction.client.db.acquire() as conn:
        reward = await conn.fetchrow(
            """
            SELECT reward_id, name, category, type, value,
                   required_level, expiration_date, max_uses, min_order_total
            FROM guild_rewards
            WHERE reward_id = $1 AND guild_id = $2
            """,
            reward_id,
            interaction.guild.id
        )

    if not reward:
        await interaction.response.send_message(
            "Reward not found.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"Update Reward: {reward['name']}",
        color=discord.Color.blue()
    )

    embed.add_field(name="Category", value=reward["category"], inline=False)
    embed.add_field(name="Action", value=reward["type"], inline=False)
    embed.add_field(name="Value", value=str(reward["value"]), inline=False)
    embed.add_field(name="Required Level", value=str(reward["required_level"]), inline=False)
    embed.add_field(name="Expires At", value=str(reward["expiration_date"]), inline=False)
    embed.add_field(name="Max Uses", value=str(reward["max_uses"]), inline=False)
    embed.add_field(name="Min Order Total", value=str(reward["min_order_total"]), inline=False)

    class UpdateRewardView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=300)

        @discord.ui.button(label="Edit Reward", style=discord.ButtonStyle.green)
        async def edit(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await btn_interaction.response.send_message(
                "Select a new reward category:",
                view=RewardCategoryView(),
                ephemeral=True
            )

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
        async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await btn_interaction.response.send_message(
                "Update cancelled.",
                ephemeral=True
            )

    await interaction.response.send_message(
        "Reward details:",
        embed=embed,
        view=UpdateRewardView(),
        ephemeral=True
    )


async def start_delete_reward_wizard(interaction: discord.Interaction):
    async with interaction.client.db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT reward_id, name, category, type
            FROM guild_rewards
            WHERE guild_id = $1
            ORDER BY reward_id
            """,
            interaction.guild.id
        )

    if not rows:
        await interaction.response.send_message(
            "No rewards exist yet.",
            ephemeral=True
        )
        return

    class RewardDeleteSelect(discord.ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(
                    label=f"{r['name']} ({r['category']} / {r['type']})",
                    value=str(r["reward_id"])
                )
                for r in rows
            ]
            super().__init__(placeholder="Select a reward to delete", options=options)

        async def callback(self, inner_interaction: discord.Interaction):
            reward_id = int(self.values[0])
            await start_delete_reward_flow(inner_interaction, reward_id)

    class RewardDeleteView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            self.add_item(RewardDeleteSelect())

    await interaction.response.send_message(
        "Select a reward to delete:",
        view=RewardDeleteView(),
        ephemeral=True
    )


async def start_delete_reward_flow(interaction: discord.Interaction, reward_id: int):
    async with interaction.client.db.acquire() as conn:
        reward = await conn.fetchrow(
            """
            SELECT name, category, type
            FROM guild_rewards
            WHERE reward_id = $1 AND guild_id = $2
            """,
            reward_id,
            interaction.guild.id
        )

    if not reward:
        await interaction.response.send_message(
            "Reward not found.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="Confirm Delete",
        description=(
            f"Are you sure you want to delete **{reward['name']}**?\n\n"
            f"Category: `{reward['category']}`\n"
            f"Type: `{reward['type']}`\n\n"
            "**This action cannot be undone.**"
        ),
        color=discord.Color.red()
    )

    class DeleteConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=300)

        @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
        async def delete(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            async with btn_interaction.client.db.acquire() as conn:
                await conn.execute(
                    """
                    DELETE FROM guild_rewards
                    WHERE reward_id = $1 AND guild_id = $2
                    """,
                    reward_id,
                    btn_interaction.guild.id
                )

                # NEW SCHEMA: delete user reward usage
                await conn.execute(
                    """
                    DELETE FROM user_rewards
                    WHERE reward_id = $1 AND guild_id = $2
                    """,
                    reward_id,
                    btn_interaction.guild.id
                )

            await btn_interaction.response.send_message(
                "Reward deleted successfully.",
                ephemeral=True
            )

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await btn_interaction.response.send_message(
                "Delete cancelled.",
                ephemeral=True
            )

    await interaction.response.send_message(
        "Confirm deletion:",
        embed=embed,
        view=DeleteConfirmView(),
        ephemeral=True
    )


# ---------------------------------------------------------
# EXPORTS FOR ADMIN COMMANDS
# ---------------------------------------------------------
__all__ = [
    "start_create_reward_wizard",
    "start_update_reward_wizard",
    "start_delete_reward_wizard",
]
