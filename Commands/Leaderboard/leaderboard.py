import discord
from discord.ext import commands
from discord import app_commands

POKEBALL_EMOJI = "<:Pokeball1:1540904892195930182>"


class LeaderboardView(discord.ui.View):
    def __init__(self, bot, guild_id, scope="guild", tab="level"):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.scope = scope
        self.tab = tab

        self.add_item(TabSelect(self))
        self.add_item(ScopeSelect(self))

    async def refresh(self, interaction: discord.Interaction):
        embed = await build_leaderboard_embed(
            self.bot,
            self.guild_id,
            self.scope,
            self.tab
        )
        await interaction.edit_original_response(embed=embed, view=self)


class TabSelect(discord.ui.Select):
    def __init__(self, view: LeaderboardView):
        options = [
            discord.SelectOption(
                label="Level",
                emoji="🏆",
                description="Ranked by level and EXP",
                value="level"
            ),
            discord.SelectOption(
                label="Pokémon Caught",
                emoji=POKEBALL_EMOJI,
                description="Ranked by total caught",
                value="caught"
            ),
        ]
        super().__init__(placeholder="Select category…", min_values=1, max_values=1, options=options)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.view_ref.tab = self.values[0]
        await self.view_ref.refresh(interaction)


class ScopeSelect(discord.ui.Select):
    def __init__(self, view: LeaderboardView):
        options = [
            discord.SelectOption(
                label="Guild",
                emoji="🏙️",
                description="Only this server",
                value="guild"
            ),
            discord.SelectOption(
                label="Global",
                emoji="🌐",
                description="All servers",
                value="global"
            ),
        ]
        super().__init__(placeholder="Select scope…", min_values=1, max_values=1, options=options)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.view_ref.scope = self.values[0]
        await self.view_ref.refresh(interaction)


async def build_leaderboard_embed(bot, guild_id, scope, tab):
    async with bot.db.acquire() as conn:

        # -------------------------
        # LEVEL LEADERBOARD
        # -------------------------
        if tab == "level":
            if scope == "guild":
                rows = await conn.fetch("""
                    SELECT user_id, level, exp
                    FROM users
                    WHERE guild_id = $1
                    ORDER BY level DESC, exp DESC
                    LIMIT 10
                """, guild_id)
            else:
                rows = await conn.fetch("""
                    SELECT user_id, level, exp
                    FROM users
                    ORDER BY level DESC, exp DESC
                    LIMIT 10
                """)

            lines = []
            rank = 1
            for r in rows:
                user = bot.get_user(r["user_id"])
                name = user.name if user else f"User {r['user_id']}"
                lines.append(
                    f"{rank}. {name} | Lv {r['level']} | {r['exp']:,} EXP"
                )
                rank += 1

            desc = "\n".join(lines) if lines else "No data."

            title = "🏆 Level Leaderboard"
            title += " — 🏙️ Guild" if scope == "guild" else " — 🌐 Global"

            return discord.Embed(title=title, description=desc, color=discord.Color.gold())

        # -------------------------
        # POKÉMON CAUGHT LEADERBOARD
        # -------------------------
        if tab == "caught":
            if scope == "guild":
                rows = await conn.fetch("""
                    SELECT user_id, SUM(quantity) AS total
                    FROM user_pokemon
                    WHERE guild_id = $1
                    GROUP BY user_id
                    ORDER BY total DESC
                    LIMIT 10
                """, guild_id)
            else:
                rows = await conn.fetch("""
                    SELECT user_id, SUM(quantity) AS total
                    FROM user_pokemon
                    GROUP BY user_id
                    ORDER BY total DESC
                    LIMIT 10
                """)

            lines = []
            rank = 1
            for r in rows:
                user = bot.get_user(r["user_id"])
                name = user.name if user else f"User {r['user_id']}"

                # NON-WRAPPING SINGLE LINE
                lines.append(
                    f"{rank}. {name} | {POKEBALL_EMOJI} {r['total']:,}"
                )
                rank += 1

            desc = "\n".join(lines) if lines else "No data."

            title = f"{POKEBALL_EMOJI} Pokémon Caught Leaderboard"
            title += " — 🏙️ Guild" if scope == "guild" else " — 🌐 Global"

            return discord.Embed(title=title, description=desc, color=discord.Color.blue())


class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="leaderboard",
        description="View the level and Pokémon caught leaderboards."
    )
    async def leaderboard(self, interaction: discord.Interaction):
        embed = await build_leaderboard_embed(
            self.bot,
            interaction.guild.id,
            scope="guild",
            tab="level"
        )

        view = LeaderboardView(self.bot, interaction.guild.id)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))
