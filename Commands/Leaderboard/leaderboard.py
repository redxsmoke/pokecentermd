import discord
from discord.ext import commands
from discord import app_commands

POKEBALL_EMOJI = "<:Pokeball1:1540904892195930182>"
POKETRIVIA_EMOJI = "<:PokeTrivia:1550328600170074163>"
POKETRIVIA_IMAGE = "https://cdn.discordapp.com/attachments/1540905804293607435/1545631848284291092/card.jpg"
UNOWN_EMOJI = "🔡"   
DEXDECODER_EMOJI = "🧩"


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
            discord.SelectOption(
                label="Poké Trivia Winners",
                emoji=POKETRIVIA_EMOJI,
                description="Ranked by correct trivia answers",
                value="trivia"
            ),
            discord.SelectOption(
                label="Unown Cipher Solvers",
                emoji=UNOWN_EMOJI,
                description="Ranked by ciphers solved",
                value="cipher"
            ),
           discord.SelectOption(
               label="DexDecoder Winners",
               emoji=DEXDECODER_EMOJI,
               description="Ranked by puzzles solved",
               value="dexdecoder"
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
                lines.append(f"{rank}. {name} | Lv {r['level']} | {r['exp']:,} EXP")
                rank += 1

            desc = "\n".join(lines) if lines else "No data."
            title = "🏆 Level Leaderboard"
            title += " — 🏙️ Guild" if scope == "guild" else " — 🌐 Global"

            embed = discord.Embed(
                title=title,
                description=desc,
                color=discord.Color.gold()
            )
            return embed

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
                lines.append(
                    f"{rank}. {name} | {POKEBALL_EMOJI} {r['total']:,}"
                )
                rank += 1

            desc = "\n".join(lines) if lines else "No data."
            title = f"{POKEBALL_EMOJI} Pokémon Caught Leaderboard"
            title += " — 🏙️ Guild" if scope == "guild" else " — 🌐 Global"

            embed = discord.Embed(
                title=title,
                description=desc,
                color=discord.Color.blue()
            )
            return embed

        # -------------------------
        # POKÉ TRIVIA WINNERS LEADERBOARD
        # -------------------------
        if tab == "trivia":
            if scope == "guild":
                rows = await conn.fetch("""
                    SELECT user_id, correct_answers
                    FROM poke_trivia_winners
                    WHERE guild_id = $1
                    ORDER BY correct_answers DESC
                    LIMIT 10
                """, guild_id)
            else:
                rows = await conn.fetch("""
                    SELECT user_id, SUM(correct_answers) AS total
                    FROM poke_trivia_winners
                    GROUP BY user_id
                    ORDER BY total DESC
                    LIMIT 10
                """)

            lines = []
            rank = 1

            for r in rows:
                user = bot.get_user(r["user_id"])
                name = user.name if user else f"User {r['user_id']}"

                total = (
                    r["correct_answers"]
                    if scope == "guild"
                    else r["total"]
                )

                lines.append(
                    f"{rank}. {name} | {POKETRIVIA_EMOJI} {total:,} correct answers"
                )

                rank += 1

            desc = "\n".join(lines) if lines else "No trivia winners yet."

            title = f"{POKETRIVIA_EMOJI} Poké Trivia Winners"
            title += " — 🏙️ Guild" if scope == "guild" else " — 🌐 Global"

            embed = discord.Embed(
                title=title,
                description=desc,
                color=discord.Color.purple()
            )

            embed.set_thumbnail(url=POKETRIVIA_IMAGE)
            return embed

        # -------------------------
        # UNOWN CIPHER LEADERBOARD
        # -------------------------
        if tab == "cipher":
            if scope == "guild":
                rows = await conn.fetch("""
                    SELECT user_id, ciphers_solved
                    FROM unown_cipher_leaders
                    WHERE guild_id = $1
                    ORDER BY ciphers_solved DESC
                    LIMIT 10
                """, guild_id)
            else:
                rows = await conn.fetch("""
                    SELECT user_id, SUM(ciphers_solved) AS total
                    FROM unown_cipher_leaders
                    GROUP BY user_id
                    ORDER BY total DESC
                    LIMIT 10
                """)

            lines = []
            rank = 1

            for r in rows:
                user = bot.get_user(r["user_id"])
                name = user.name if user else f"User {r['user_id']}"

                total = (
                    r["ciphers_solved"]
                    if scope == "guild"
                    else r["total"]
                )

                lines.append(
                    f"{rank}. {name} | {UNOWN_EMOJI} {total:,} solved"
                )

                rank += 1

            desc = "\n".join(lines) if lines else "No cipher solves yet."

            title = f"{UNOWN_EMOJI} Unown Cipher Solvers"
            title += " — 🏙️ Guild" if scope == "guild" else " — 🌐 Global"

            embed = discord.Embed(
                title=title,
                description=desc,
                color=discord.Color.orange()
            )

            return embed

        # -------------------------
        # DEXDECODER LEADERBOARD
        # -------------------------
        if tab == "dexdecoder":
            if scope == "guild":
                rows = await conn.fetch("""
                    SELECT user_id,
                           times_won,
                           times_lost
                    FROM dexdecoder
                    WHERE guild_id = $1
                    ORDER BY times_won DESC,
                             times_lost ASC
                    LIMIT 10
                """, guild_id)

            else:
                rows = await conn.fetch("""
                    SELECT user_id,
                           SUM(times_won) AS total_wins,
                           SUM(times_lost) AS total_losses
                    FROM dexdecoder
                    GROUP BY user_id
                    ORDER BY total_wins DESC,
                             total_losses ASC
                    LIMIT 10
                """)

            lines = []
            rank = 1

            for r in rows:
                user = bot.get_user(r["user_id"])
                name = user.name if user else f"User {r['user_id']}"

                if scope == "guild":
                    wins = r["times_won"]
                    losses = r["times_lost"]
                else:
                    wins = r["total_wins"]
                    losses = r["total_losses"]

                total_games = wins + losses

                if total_games > 0:
                    win_rate = (wins / total_games) * 100
                else:
                    win_rate = 0.0

                lines.append(
                    f"{rank}. {name} | "
                    f"{DEXDECODER_EMOJI} {wins:,} solved | "
                    f"❌ {losses:,} lost | "
                    f"📈 {win_rate:.1f}%"
                )

                rank += 1

            desc = "\n".join(lines) if lines else "No DexDecoder winners yet."

            title = f"{DEXDECODER_EMOJI} DexDecoder Winners"
            title += " — 🏙️ Guild" if scope == "guild" else " — 🌐 Global"

            embed = discord.Embed(
                title=title,
                description=desc,
                color=discord.Color.teal()
            )

            embed.set_footer(
                text="Ranked by total solves. Win rate shown for reference."
            )

            return embed


class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="leaderboard",
        description="View the level, Pokémon caught, trivia, Unown Cipher, and DexDecoder leaderboards."
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
