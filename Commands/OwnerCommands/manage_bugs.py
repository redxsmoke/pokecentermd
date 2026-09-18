import datetime
import discord
from discord import ui, app_commands
from discord.ext import commands

OWNER_ID = 337773020770729985
BUG_BADGE_ID = 14


# -------------------------------------------------
# Modal: NotABugModal
# -------------------------------------------------

class NotABugModal(ui.Modal, title="Mark as Not a Bug"):
    def __init__(self, bug_record: dict):
        super().__init__()
        self.bug_record = bug_record

        self.reason = ui.TextInput(
            label="Reason",
            placeholder="Explain why this is not a bug.",
            required=True,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        pool = interaction.client.db
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_reported_bugs SET status = 'Not a Bug' WHERE id = $1",
                self.bug_record["id"]
            )

        # DM user
        user = interaction.client.get_user(self.bug_record["user_id"])
        if user:
            embed = discord.Embed(
                title="🐞 Bug Report Update",
                description=(
                    "**Status:** Not a Bug\n"
                    f"**Reason:** {self.reason.value}"
                ),
                color=discord.Color.red()
            )
            try:
                await user.send(embed=embed)
            except:
                pass

        admin_embed = discord.Embed(
            title="Bug Updated",
            description=f"Bug ID **{self.bug_record['id']}** marked as **Not a Bug**.",
            color=discord.Color.red()
        )

        await interaction.response.send_message(embed=admin_embed, ephemeral=True)


# -------------------------------------------------
# Modal: BugFixedModal
# -------------------------------------------------

class BugFixedModal(ui.Modal, title="Bug Fixed"):
    def __init__(self, bug_record: dict):
        super().__init__()
        self.bug_record = bug_record

        self.release = ui.TextInput(
            label="Fixed in release",
            placeholder="e.g., v1.4.2 or September 2026 Patch",
            required=True,
            style=discord.TextStyle.short
        )
        self.add_item(self.release)

    async def on_submit(self, interaction: discord.Interaction):
        pool = interaction.client.db

        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_reported_bugs
                SET status = 'Closed',
                    fixed_in_release = $2
                WHERE id = $1
            """, self.bug_record["id"], self.release.value)

        embed = discord.Embed(
            title="Bug Closed",
            description=(
                f"Bug ID **{self.bug_record['id']}** marked as **Closed**.\n"
                f"**Fixed in release:** {self.release.value}"
            ),
            color=discord.Color.blue()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# -------------------------------------------------
# Pagination View
# -------------------------------------------------

class BotBugsView(ui.View):
    def __init__(self, bugs: list[dict]):
        super().__init__(timeout=None)
        self.bugs = bugs
        self.index = 0
        self.update_button_states()

    def current_bug(self):
        return self.bugs[self.index]

    def make_embed(self):
        bug = self.current_bug()
        embed = discord.Embed(
            title=f"🐞 Bug ID {bug['id']}",
            color=discord.Color.gold()
        )
        embed.add_field(name="Date Reported", value=str(bug["created_at"]), inline=False)
        embed.add_field(name="Description", value=bug["description"], inline=False)
        embed.add_field(name="Additional Details", value=bug["additional_details"] or "None", inline=False)
        embed.add_field(name="Status", value=bug["status"], inline=False)

        if bug.get("fixed_in_release"):
            embed.add_field(name="Fixed In Release", value=bug["fixed_in_release"], inline=False)

        embed.set_footer(text=f"Bug {self.index + 1} of {len(self.bugs)}")
        return embed

    def update_button_states(self):
        if len(self.bugs) <= 1:
            self.previous.disabled = True
            self.next.disabled = True
        else:
            self.previous.disabled = (self.index == 0)
            self.next.disabled = (self.index == len(self.bugs) - 1)

    @ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != OWNER_ID:
            embed = discord.Embed(
                title="Access Denied",
                description="Owner only.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if self.index > 0:
            self.index -= 1

        self.update_button_states()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != OWNER_ID:
            embed = discord.Embed(
                title="Access Denied",
                description="Owner only.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if self.index < len(self.bugs) - 1:
            self.index += 1

        self.update_button_states()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @ui.button(label="Not A Bug", style=discord.ButtonStyle.danger)
    async def not_a_bug(self, interaction: discord.Interaction, button: ui.Button):
        modal = NotABugModal(self.current_bug())
        await interaction.response.send_modal(modal)

    @ui.button(label="Mark as Bug", style=discord.ButtonStyle.success)
    async def mark_as_bug(self, interaction: discord.Interaction, button: ui.Button):
        bug = self.current_bug()
        pool = interaction.client.db

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_reported_bugs SET status = 'Active' WHERE id = $1",
                bug["id"]
            )

            existing = await conn.fetchrow("""
                SELECT quantity
                FROM user_badges
                WHERE user_id = $1
                  AND badge_id = $2
                  AND guild_id IS NULL
            """, bug["user_id"], BUG_BADGE_ID)

            if existing:
                await conn.execute("""
                    UPDATE user_badges
                    SET quantity = quantity + 1,
                        awarded_at = NOW()
                    WHERE user_id = $1
                      AND badge_id = $2
                      AND guild_id IS NULL
                """, bug["user_id"], BUG_BADGE_ID)
            else:
                await conn.execute("""
                    INSERT INTO user_badges (
                        user_id,
                        badge_id,
                        guild_id,
                        quantity,
                        awarded_at
                    )
                    VALUES ($1, $2, NULL, 1, NOW())
                """, bug["user_id"], BUG_BADGE_ID)

        # DM user with badge thumbnail
        user = interaction.client.get_user(bug["user_id"])
        if user:
            embed = discord.Embed(
                title="🐞 Bug Report Update",
                description=(
                    "**Status:** Confirmed Bug\n"
                    "**Fix:** Will be fixed in a future release\n"
                    "**Reward:** You earned **1× Bug Catcher Badge!**\n"
                    "**Run /mybadges to see your new badge!**"
                ),
                color=discord.Color.green()
            )

            # ⭐ Add badge thumbnail (top-right)
            embed.set_thumbnail(
                url="https://yourcdn.com/badges/bug_catcher.png"
            )

            try:
                await user.send(embed=embed)
            except:
                pass

        admin_embed = discord.Embed(
            title="Bug Updated",
            description=f"Bug ID **{bug['id']}** marked as **Confirmed Bug**.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=admin_embed, ephemeral=True)

    @ui.button(label="Bug Fixed", style=discord.ButtonStyle.primary)
    async def bug_fixed(self, interaction: discord.Interaction, button: ui.Button):
        modal = BugFixedModal(self.current_bug())
        await interaction.response.send_modal(modal)


# -------------------------------------------------
# COG: Manage Bugs
# -------------------------------------------------

class ManageBugs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="botbugs", description="View and manage reported bugs (owner only).")
    async def botbugs(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            embed = discord.Embed(
                title="Access Denied",
                description="Owner only.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        pool = interaction.client.db
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id,
                       user_id,
                       guild_id,
                       date,
                       reported_at,
                       description,
                       additional_details,
                       status,
                       fixed_in_release,
                       created_at
                FROM user_reported_bugs
                WHERE status IN ('pending investigation', 'active')
                ORDER BY created_at ASC
            """)

        if not rows:
            embed = discord.Embed(
                title="No Bugs Found",
                description="No bugs currently in 'pending investigation' or 'active' status.",
                color=discord.Color.blue()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        bugs = [dict(row) for row in rows]
        view = BotBugsView(bugs)
        await interaction.response.send_message(embed=view.make_embed(), view=view, ephemeral=True)


# -------------------------------------------------
# SETUP
# -------------------------------------------------

async def setup(bot):
    await bot.add_cog(ManageBugs(bot))
