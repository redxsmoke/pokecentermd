# poke_trivia.py

import asyncio
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord

# ============================================================
#   CONFIG SETTINGS
# ============================================================
TEST_MODE = False               # Set to False for production
TEST_INTERVAL_SECONDS = 20     # How often trivia fires in test mode

TRIVIA_TIMEZONE = ZoneInfo("America/New_York")  # EST/EDT
TRIVIA_HOUR = 16  # 4 PM
TRIVIA_MINUTE = 0

TRIVIA_EXP_REWARD = 1000


# ============================================================
#   TRIVIA BUTTON VIEW
# ============================================================
class TriviaView(discord.ui.View):
    def __init__(self, bot, pool, question_row, answers, correct_answer):
        super().__init__(timeout=None)
        self.bot = bot
        self.pool = pool
        self.question_row = question_row
        self.correct_answer = correct_answer
        self.answers = answers
        self.message: discord.Message | None = None
        self.winner_user_id: int | None = None
        self.delete_task: asyncio.Task | None = None
        self.no_winner_task: asyncio.Task | None = None

        # Track users who already guessed (one guess per user)
        self.incorrect_users: set[int] = set()

        random.shuffle(self.answers)

        for ans in self.answers:
            self.add_item(TriviaButton(label=ans, parent_view=self))

    async def start_delete_timer_on_correct(self):
        if self.delete_task is not None:
            return
        self.delete_task = self.bot.loop.create_task(self._delete_after_delay(300))

    async def start_no_winner_timer(self):
        if self.no_winner_task is not None:
            return
        self.no_winner_task = self.bot.loop.create_task(self._delete_after_delay(600, no_winner=True))

    async def _delete_after_delay(self, seconds: int, no_winner: bool = False):
        try:
            await asyncio.sleep(seconds)
            if self.message:
                try:
                    await self.message.delete()
                except discord.HTTPException:
                    pass

            if no_winner and self.winner_user_id is None and self.message is not None:
                try:
                    await self.message.channel.send(
                        embed=discord.Embed(
                            title="No Winner Today",
                            description=f"No one answered the trivia correctly for question ID **{self.question_row['poke_trivia_id']}**.",
                            color=discord.Color.red()
                        )
                    )
                except discord.HTTPException:
                    pass
        except asyncio.CancelledError:
            pass

    async def mark_winner(self, interaction: discord.Interaction):
        if self.winner_user_id is not None:
            return

        self.winner_user_id = interaction.user.id

        # ============================================================
        #   AWARD XP
        # ============================================================
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                SET exp = exp + $1
                WHERE user_id = $2
                """,
                TRIVIA_EXP_REWARD,
                interaction.user.id,
            )

        # ============================================================
        #   RECORD TRIVIA WIN
        # ============================================================
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO poke_trivia_winners (user_id, guild_id, correct_answers)
                VALUES ($1, $2, 1)
                ON CONFLICT (user_id, guild_id)
                DO UPDATE SET correct_answers = poke_trivia_winners.correct_answers + 1;
                """,
                interaction.user.id,
                interaction.guild.id
            )

        # Fetch updated correct answer count
        async with self.pool.acquire() as conn:
            correct_count = await conn.fetchval(
                """
                SELECT correct_answers
                FROM poke_trivia_winners
                WHERE user_id = $1 AND guild_id = $2
                """,
                interaction.user.id,
                interaction.guild.id
            )

        # ============================================================
        #   ⭐ MASTER BALL REWARD AT 5 CORRECT ANSWERS
        # ============================================================
        if correct_count == 5:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_pokemon_catch_items (user_id, guild_id, item_id, quantity)
                    VALUES ($1, $2, 4, 1)
                    ON CONFLICT (user_id, guild_id, item_id)
                    DO UPDATE SET quantity = user_pokemon_catch_items.quantity + 1;
                    """,
                    interaction.user.id,
                    interaction.guild.id
                )

            await interaction.channel.send(
                embed=discord.Embed(
                    title="🎉 Master Ball Earned!",
                    description=f"{interaction.user.mention} has answered **5 trivia questions correctly** and earned a **Master Ball**!\n\nIt has been added to their bag.",
                    color=discord.Color.purple()
                )
            )

        # ============================================================
        #   ⭐ BADGE REWARDS AT 10, 20, 50 CORRECT ANSWERS (WITH IMAGE)
        # ============================================================
        badge_rewards = {
            10: "Jr Professor Badge",
            20: "Seasoned Professor Badge",
            50: "Legendary Professor Badge"
        }

        if correct_count in badge_rewards:
            badge_name = badge_rewards[correct_count]

            async with self.pool.acquire() as conn:
                # Fetch badge_id + badge_url
                badge_row = await conn.fetchrow(
                    """
                    SELECT badge_id, badge_url
                    FROM badges
                    WHERE LOWER(name) = LOWER($1)
                    """,
                    badge_name
                )

                if badge_row:
                    badge_id = badge_row["badge_id"]
                    badge_url = badge_row["badge_url"]

                    # Check if user already has this badge
                    existing = await conn.fetchval(
                        """
                        SELECT badge_award_id
                        FROM user_badges
                        WHERE user_id = $1 AND guild_id = $2 AND badge_id = $3
                        """,
                        interaction.user.id,
                        interaction.guild.id,
                        badge_id
                    )

                    if existing is None:
                        # Award badge
                        await conn.execute(
                            """
                            INSERT INTO user_badges (user_id, badge_id, guild_id, awarded_at, quantity)
                            VALUES ($1, $2, $3, NOW(), 1)
                            """,
                            interaction.user.id,
                            badge_id,
                            interaction.guild.id
                        )

                        embed = discord.Embed(
                            title="🏅 New Trivia Badge Earned!",
                            description=f"{interaction.user.mention} has earned the **{badge_name}**!",
                            color=discord.Color.gold()
                        )

                        if badge_url:
                            embed.set_thumbnail(url=badge_url)

                        await interaction.channel.send(embed=embed)

        # ============================================================
        #   ⭐ LEVEL-UP CHECK
        # ============================================================
        async with self.pool.acquire() as conn:
            new_xp = await conn.fetchval(
                "SELECT exp FROM users WHERE user_id = $1",
                interaction.user.id
            )

        await self.bot.level_up_manager.check_level_up(
            interaction.user.id,
            new_xp,
            interaction.channel
        )

        # ============================================================
        #   DISABLE BUTTONS (AFTER EDIT)
        # ============================================================
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        # FIRST edit the message (interaction still valid)
        await interaction.response.edit_message(view=self)

        # THEN send followup
        try:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Correct Answer!",
                    description=f"{interaction.user.mention} earned **{TRIVIA_EXP_REWARD} EXP**!",
                    color=discord.Color.green()
                ),
                ephemeral=False,
            )
        except discord.HTTPException:
            pass

        await self.start_delete_timer_on_correct()

        if self.no_winner_task is not None:
            self.no_winner_task.cancel()
            self.no_winner_task = None
class TriviaButton(discord.ui.Button):
    def __init__(self, label: str, parent_view: TriviaView):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):

        # If someone already answered correctly, trivia is closed for everyone
        if self.parent_view.winner_user_id is not None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Trivia Closed",
                    description="Someone already answered correctly.",
                    color=discord.Color.orange()
                ),
                ephemeral=True,
            )
            return

        # User already guessed once (wrong)
        if interaction.user.id in self.parent_view.incorrect_users:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Trivia Attempt Used",
                    description="You only get one guess per question, please try again tomorrow!",
                    color=discord.Color.red()
                ),
                ephemeral=True,
            )
            return

        # Correct answer
        if self.label == self.parent_view.correct_answer:
            await self.parent_view.mark_winner(interaction)
            return

        # First incorrect attempt → record user
        self.parent_view.incorrect_users.add(interaction.user.id)

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Your answer was incorrect!",
                description="You only get one guess per question, please try again tomorrow!",
                color=discord.Color.red()
            ),
            ephemeral=True,
        )


# ============================================================
#   TRIVIA MANAGER
# ============================================================
class PokeTriviaManager:
    def __init__(self, bot, pool: "asyncpg.pool.Pool"):
        self.bot = bot
        self.pool = pool

        self.task: asyncio.Task | None = None
        self.test_task: asyncio.Task | None = None

    def start(self):
        if self.task is None:
            self.task = self.bot.loop.create_task(self.trivia_loop())

        if TEST_MODE and self.test_task is None:
            print(f"[PokeTrivia] TEST MODE ENABLED — posting trivia every {TEST_INTERVAL_SECONDS} seconds")
            self.test_task = self.bot.loop.create_task(self.test_trivia_loop())

    # ============================================================
    #   DAILY TRIVIA LOOP (4 PM EST)
    # ============================================================
    async def trivia_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            now = datetime.now(TRIVIA_TIMEZONE)
            next_run = now.replace(hour=TRIVIA_HOUR, minute=TRIVIA_MINUTE, second=0, microsecond=0)

            if next_run <= now:
                next_run += timedelta(days=1)

            sleep_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(sleep_seconds)

            try:
                await self.post_daily_trivia()
            except Exception as e:
                print(f"[PokeTrivia] Error posting daily trivia: {e}")

    # ============================================================
    #   TEST MODE LOOP (fires every X seconds)
    # ============================================================
    async def test_trivia_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                await self.post_daily_trivia()
            except Exception as e:
                print(f"[PokeTrivia] Test mode error: {e}")

            await asyncio.sleep(TEST_INTERVAL_SECONDS)

    # ============================================================
    #   POST TRIVIA MESSAGE
    # ============================================================
    async def post_daily_trivia(self):

        # ============================================================
        #   CHECK IF TRIVIA IS ENABLED + GET CHANNEL
        # ============================================================
        async with self.pool.acquire() as conn:
            settings = await conn.fetchrow(
                """
                SELECT poke_trivia_enabled, poke_trivia_channel_id
                FROM guild_settings
                WHERE guild_id = $1
                """,
                self.bot.guilds[0].id  # assuming 1 guild bot
            )

        if not settings or not settings["poke_trivia_enabled"]:
            print("[PokeTrivia] Trivia disabled for this guild.")
            return

        # Try configured channel first
        channel = None
        if settings["poke_trivia_channel_id"]:
            for guild in self.bot.guilds:
                ch = guild.get_channel(settings["poke_trivia_channel_id"])
                if ch and isinstance(ch, discord.TextChannel):
                    if ch.permissions_for(guild.me).send_messages:
                        channel = ch
                        break

        # Fall back to #general
        if channel is None:
            for guild in self.bot.guilds:
                general = discord.utils.get(guild.text_channels, name="general")
                if general and general.permissions_for(guild.me).send_messages:
                    channel = general
                    break

        # Fall back to ANY text channel
        if channel is None:
            channel = self._get_any_text_channel()

        if channel is None:
            print("[PokeTrivia] No suitable channel found to post trivia.")
            return

        # ============================================================
        #   FETCH TRIVIA QUESTION
        # ============================================================
        async with self.pool.acquire() as conn:
            total_active = await conn.fetchval(
                "SELECT COUNT(*) FROM poke_trivia_question WHERE is_active = TRUE"
            )

            if total_active == 0:
                print("[PokeTrivia] No active trivia questions.")
                return

            # First: never asked
            row = await conn.fetchrow(
                """
                SELECT *
                FROM poke_trivia_question
                WHERE is_active = TRUE
                  AND last_asked IS NULL
                ORDER BY created_at ASC
                LIMIT 1
                """
            )

            if row is None:
                now_utc = datetime.now(TRIVIA_TIMEZONE)
                cutoff = now_utc - timedelta(days=total_active)

                row = await conn.fetchrow(
                    """
                    SELECT *
                    FROM poke_trivia_question
                    WHERE is_active = TRUE
                      AND last_asked <= $1
                    ORDER BY last_asked ASC
                    LIMIT 1
                    """,
                    cutoff,
                )

            if row is None:
                print("[PokeTrivia] No eligible trivia questions found.")
                return

            # Convert DB timestamp to aware if needed
            if row["last_asked"] is not None and row["last_asked"].tzinfo is None:
                row["last_asked"] = row["last_asked"].replace(tzinfo=TRIVIA_TIMEZONE)

            now_utc = datetime.now(TRIVIA_TIMEZONE)
            await conn.execute(
                """
                UPDATE poke_trivia_question
                SET last_asked = $1
                WHERE poke_trivia_id = $2
                """,
                now_utc,
                row["poke_trivia_id"],
            )

        # ============================================================
        #   BUILD EMBED
        # ============================================================
        embed = discord.Embed(
            title="🎯 Here is today's Poké Trivia Question!",
            description=(
                "Be the first one to answer correctly and earn **EXP!**\n\n"
                f"**Question:** {row['question']}"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Question ID: {row['poke_trivia_id']}")

        if row["question_image_url"]:
            embed.set_thumbnail(url=row["question_image_url"])

        correct_answer = row["correct_answer"]
        answers = [
            row["correct_answer"],
            row["wrong_answer_1"],
            row["wrong_answer_2"],
            row["wrong_answer_3"],
        ]

        view = TriviaView(self.bot, self.pool, row, answers, correct_answer)

        msg = await channel.send(embed=embed, view=view)
        view.message = msg

        await view.start_no_winner_timer()

    # ============================================================
    #   CHANNEL PICKER (fallback)
    # ============================================================
    def _get_any_text_channel(self) -> discord.TextChannel | None:
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    return channel
        return None
# ============================================================
#   EXTENSION SETUP
# ============================================================
async def setup(bot):
    from LevelManager.level_up_manager import LevelUpManager

    # Register the level-up manager so TriviaView can call it
    bot.level_up_manager = LevelUpManager(bot, bot.db)

    # Start trivia manager
    trivia = PokeTriviaManager(bot, bot.db)
    trivia.start()

