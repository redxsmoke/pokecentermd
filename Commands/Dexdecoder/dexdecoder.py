import asyncio
import random
from datetime import datetime

import discord
from discord import app_commands
from LevelManager.level_up_manager import LevelUpManager


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

COOLDOWN_SECONDS = 180

active_games = {}
cooldowns = {}


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def normalize_name(name: str) -> str:
    return ''.join(ch for ch in name.lower() if ch.isalpha())


def scramble_name(name: str) -> str:
    letters = list(name.upper())

    if len(letters) < 2:
        return name.upper()

    scrambled = letters.copy()

    while ''.join(scrambled) == ''.join(letters):
        random.shuffle(scrambled)

    return ' '.join(scrambled)


# ---------------------------------------------------------
# ANSWER MODAL
# ---------------------------------------------------------

class DexDecoderAnswerModal(discord.ui.Modal, title="DexDecoder Answer"):

    answer = discord.ui.TextInput(
        label="Your Guess",
        placeholder="Enter the Pokémon's name",
        required=True
    )

    def __init__(self, puzzle_view):
        super().__init__()
        self.puzzle_view = puzzle_view

    async def on_submit(self, interaction: discord.Interaction):

        if interaction.user.id != self.puzzle_view.allowed_user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⚠️ Not Allowed",
                    description=(
                        "This puzzle belongs to another user.\n"
                        "Start your own puzzle with /dexdecoder."
                    ),
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        if self.puzzle_view.completed:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Puzzle Closed",
                    description="This puzzle has already ended.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        guess = normalize_name(self.answer.value)
        correct = normalize_name(self.puzzle_view.pokemon_name)

        # -------------------------------------------------
        # INCORRECT ANSWER
        # -------------------------------------------------

        if guess != correct:

            async with interaction.client.db.acquire() as conn:

                await conn.execute(
                    """
                    INSERT INTO dexdecoder (
                        user_id,
                        guild_id,
                        times_won,
                        times_lost
                    )
                    VALUES ($1, $2, 0, 1)
                    ON CONFLICT (user_id, guild_id)
                    DO UPDATE SET
                        times_lost = dexdecoder.times_lost + 1;
                    """,
                    interaction.user.id,
                    interaction.guild.id
                )

            self.puzzle_view.completed = True

            active_games.pop(
                self.puzzle_view.allowed_user_id,
                None
            )

            cooldowns[
                self.puzzle_view.allowed_user_id
            ] = datetime.utcnow()

            for child in self.puzzle_view.children:
                child.disabled = True

            embed = discord.Embed(
                title="❌ Incorrect",
                description=(
                    f"The Pokémon was **{self.puzzle_view.pokemon_name}**.\n\n"
                    "Better luck next time!"
                ),
                color=discord.Color.red()
            )

            if self.puzzle_view.pokemon_image:
                embed.set_thumbnail(
                    url=self.puzzle_view.pokemon_image
                )

            await interaction.response.send_message(
                embed=embed
            )

            try:
                await self.puzzle_view.message.edit(
                    view=self.puzzle_view
                )
            except:
                pass

            return

        # -------------------------------------------------
        # CORRECT ANSWER
        # -------------------------------------------------

        if self.puzzle_view.difficulty == "easy":

            xp_reward = int(
                100 * random.uniform(1.0, 2.5)
            )

            coin_reward = int(
                500 * random.uniform(1.0, 1.95)
            )

        elif self.puzzle_view.difficulty == "medium":

            xp_reward = int(
                200 * random.uniform(1.0, 3.5)
            )

            coin_reward = int(
                750 * random.uniform(1.0, 2.95)
            )

        else:

            xp_reward = int(
                300 * random.uniform(1.0, 4.5)
            )

            coin_reward = int(
                1000 * random.uniform(1.0, 3.95)
            )

        async with interaction.client.db.acquire() as conn:

            current_exp = await conn.fetchval(
                """
                SELECT exp
                FROM users
                WHERE user_id = $1
                  AND guild_id = $2
                """,
                interaction.user.id,
                interaction.guild.id
            )

            if current_exp is None:
                current_exp = 0

            new_exp = current_exp + xp_reward

            await conn.execute(
                """
                UPDATE users
                SET
                    exp = $1,
                    coin_balance = coin_balance + $2
                WHERE user_id = $3
                  AND guild_id = $4
                """,
                new_exp,
                coin_reward,
                interaction.user.id,
                interaction.guild.id
            )

            await conn.execute(
                """
                INSERT INTO dexdecoder (
                    user_id,
                    guild_id,
                    times_won,
                    times_lost
                )
                VALUES ($1, $2, 1, 0)
                ON CONFLICT (user_id, guild_id)
                DO UPDATE SET
                    times_won = dexdecoder.times_won + 1;
                """,
                interaction.user.id,
                interaction.guild.id
            )

        level_manager = LevelUpManager(
            interaction.client,
            interaction.client.db
        )

        await level_manager.check_level_up(
            user_id=interaction.user.id,
            new_xp=new_exp,
            channel=interaction.channel
        )

        self.puzzle_view.completed = True

        active_games.pop(
            self.puzzle_view.allowed_user_id,
            None
        )

        cooldowns[
            self.puzzle_view.allowed_user_id
        ] = datetime.utcnow()

        for child in self.puzzle_view.children:
            child.disabled = True

        embed = discord.Embed(
            title="🎉 Correct!",
            description=(
                f"The Pokémon was **{self.puzzle_view.pokemon_name}**.\n\n"
                f"⭐ EXP Earned: **{xp_reward:,}**\n"
                f"🪙 Coins Earned: **{coin_reward:,}**"
            ),
            color=discord.Color.green()
        )

        if self.puzzle_view.pokemon_image:
            embed.set_thumbnail(
                url=self.puzzle_view.pokemon_image
            )

        await interaction.response.send_message(
            embed=embed
        )

        try:
            await self.puzzle_view.message.edit(
                view=self.puzzle_view
            )
        except:
            pass
# ---------------------------------------------------------
# PUZZLE VIEW
# ---------------------------------------------------------

class DexDecoderPuzzleView(discord.ui.View):

    def __init__(
        self,
        interaction,
        difficulty,
        pokemon_name,
        pokemon_image,
        time_limit
    ):
        super().__init__(timeout=time_limit)

        self.allowed_user_id = interaction.user.id
        self.difficulty = difficulty
        self.pokemon_name = pokemon_name
        self.pokemon_image = pokemon_image
        self.time_limit = time_limit
        self.completed = False
        self.message = None
    async def on_timeout(self):

        if self.completed:
            return

        self.completed = True

        active_games.pop(
            self.allowed_user_id,
            None
        )

        cooldowns[
            self.allowed_user_id
        ] = datetime.utcnow()

        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="⌛ Time's Up!",
            description=(
                f"The Pokémon was **{self.pokemon_name}**.\n\n"
                "Better luck next time!"
            ),
            color=discord.Color.orange()
        )

        if self.pokemon_image:
            embed.set_thumbnail(
                url=self.pokemon_image
            )

        try:
            await self.message.edit(
                embed=embed,
                view=self
            )
        except:
            pass

    @discord.ui.button(
        label="Submit Answer",
        style=discord.ButtonStyle.primary
    )
    async def submit_answer(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if interaction.user.id != self.allowed_user_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⚠️ Not Allowed",
                    description=(
                        "This puzzle belongs to another user.\n"
                        "Start your own puzzle with /dexdecoder."
                    ),
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            DexDecoderAnswerModal(self)
        )


# ---------------------------------------------------------
# DIFFICULTY VIEW
# ---------------------------------------------------------

class DexDecoderDifficultyView(discord.ui.View):

    def __init__(self, interaction):
        super().__init__(timeout=120)

        self.original_interaction = interaction
        self.allowed_user_id = interaction.user.id

    async def start_game(
        self,
        interaction,
        difficulty
    ):

        async with interaction.client.db.acquire() as conn:

            rows = await conn.fetch(
                """
                SELECT pokemon_name, pokemon_image
                FROM cd_pokemon
                """
            )

        valid = []

        for row in rows:

            letters = len(
                ''.join(
                    c for c in row["pokemon_name"]
                    if c.isalpha()
                )
            )

            if difficulty == "easy":
                if 3 <= letters <= 6:
                    valid.append(row)

            elif difficulty == "medium":
                if 7 <= letters <= 9:
                    valid.append(row)

            elif difficulty == "hard":
                if letters >= 10:
                    valid.append(row)

        if not valid:

            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Error",
                    description=(
                        "No Pokémon found for "
                        f"{difficulty.title()} difficulty."
                    ),
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        selected = random.choice(valid)

        pokemon_name = selected["pokemon_name"]
        pokemon_image = selected["pokemon_image"]

        scrambled = scramble_name(
            ''.join(
                c for c in pokemon_name
                if c.isalpha()
            )
        )

        if difficulty == "easy":
            time_limit = 60

        elif difficulty == "medium":
            time_limit = 90

        else:
            time_limit = 120

        embed = discord.Embed(
            title="🧩 DexDecoder",
            description=(
                f"**Difficulty:** {difficulty.title()}\n\n"
                "Unscramble this Pokémon:\n\n"
                f"```{scrambled}```\n"
                f"⏰ Time Limit: {time_limit} Seconds"
            ),
            color=discord.Color.blurple()
        )

        puzzle_view = DexDecoderPuzzleView(
            interaction=interaction,
            difficulty=difficulty,
            pokemon_name=pokemon_name,
            pokemon_image=pokemon_image,
            time_limit=time_limit
        )

        await interaction.response.edit_message(
            embed=embed,
            view=puzzle_view
        )

        msg = await interaction.original_response()

        puzzle_view.message = msg

        active_games[
            interaction.user.id
        ] = puzzle_view

    @discord.ui.button(
        label="Easy",
        style=discord.ButtonStyle.success
    )
    async def easy(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if interaction.user.id != self.allowed_user_id:
            await interaction.response.send_message(
                "This isn't your puzzle.",
                ephemeral=True
            )
            return

        await self.start_game(
            interaction,
            "easy"
        )

    @discord.ui.button(
        label="Medium",
        style=discord.ButtonStyle.primary
    )
    async def medium(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if interaction.user.id != self.allowed_user_id:
            await interaction.response.send_message(
                "This isn't your puzzle.",
                ephemeral=True
            )
            return

        await self.start_game(
            interaction,
            "medium"
        )

    @discord.ui.button(
        label="Hard",
        style=discord.ButtonStyle.danger
    )
    async def hard(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if interaction.user.id != self.allowed_user_id:
            await interaction.response.send_message(
                "This isn't your puzzle.",
                ephemeral=True
            )
            return

        await self.start_game(
            interaction,
            "hard"
        )


# ---------------------------------------------------------
# COMMAND
# ---------------------------------------------------------

@app_commands.command(
    name="dexdecoder",
    description="Unscramble a Pokémon name before time runs out."
)
async def dexdecoder(
    interaction: discord.Interaction
):

    user_id = interaction.user.id

    if user_id in active_games:

        embed = discord.Embed(
            title="⚠️ Active Game",
            description=(
                "You already have a DexDecoder "
                "game in progress."
            ),
            color=discord.Color.orange()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

        return

    last_play = cooldowns.get(user_id)

    if last_play:

        elapsed = (
            datetime.utcnow()
            - last_play
        ).total_seconds()

        if elapsed < COOLDOWN_SECONDS:

            remaining = (
                COOLDOWN_SECONDS - elapsed
            )

            minutes = int(
                remaining // 60
            )

            seconds = int(
                remaining % 60
            )

            embed = discord.Embed(
                title="⏳ DexDecoder Cooldown",
                description=(
                    "You must wait "
                    f"**{minutes}m {seconds}s** "
                    "before starting another game."
                ),
                color=discord.Color.red()
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True
            )

            return

    embed = discord.Embed(
        title="🧩 DexDecoder",
        description=(
            "Unscramble a Pokémon name before time expires.\n\n"
            "**🟢 Easy**\n"
            "3-6 Letters\n"
            "60 Seconds\n\n"
            "**🟡 Medium**\n"
            "7-9 Letters\n"
            "90 Seconds\n\n"
            "**🔴 Hard**\n"
            "10+ Letters\n"
            "120 Seconds"
        ),
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(
        embed=embed,
        view=DexDecoderDifficultyView(
            interaction
        )
    )


# ---------------------------------------------------------
# SETUP
# ---------------------------------------------------------

async def setup(bot):
    bot.tree.add_command(
        dexdecoder
    )