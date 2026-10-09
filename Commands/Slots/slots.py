import asyncio
import random

import discord
from discord import app_commands

# ---------------------------------------------------------
# EMOJIS
# ---------------------------------------------------------

PIKACHU_EMOJI = "<:Pikachu:1557948194938167296>"
CHARMANDER_EMOJI = "<:Charmander:1557948537839296683>"
SQUIRTLE_EMOJI = "<:Squirtle:1557948702973501440>"
BULBASAUR_EMOJI = "<:Bulbasaur:1557948646799057057>"
EEVEE_EMOJI = "<:Eevee:1557948753615265915>"
MEW_EMOJI = "<:Mew:1557948902760779837>"
POKEBALL_EMOJI = "<:Pokeball1:1540418809939099818>"

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

SLOT_TIERS = {
    1000: {
        "name": "🟢 Beginner",
        "reset_jackpot": 100_000
    },
    10000: {
        "name": "🔵 Trainer",
        "reset_jackpot": 1_000_000
    },
    100000: {
        "name": "🟣 Champion",
        "reset_jackpot": 10_000_000
    }
}

SYMBOL_POOL = [
    PIKACHU_EMOJI,
    PIKACHU_EMOJI,
    PIKACHU_EMOJI,
    PIKACHU_EMOJI,

    CHARMANDER_EMOJI,
    CHARMANDER_EMOJI,
    CHARMANDER_EMOJI,
    CHARMANDER_EMOJI,

    SQUIRTLE_EMOJI,
    SQUIRTLE_EMOJI,
    SQUIRTLE_EMOJI,
    SQUIRTLE_EMOJI,

    BULBASAUR_EMOJI,
    BULBASAUR_EMOJI,
    BULBASAUR_EMOJI,
    BULBASAUR_EMOJI,

    EEVEE_EMOJI,
    EEVEE_EMOJI,

    MEW_EMOJI
]

PAYLINES = [
    [(0, 0), (0, 1), (0, 2)],
    [(1, 0), (1, 1), (1, 2)],
    [(2, 0), (2, 1), (2, 2)],
    [(0, 0), (1, 1), (2, 2)],
    [(0, 2), (1, 1), (2, 0)]
]

slot_locks = set()

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def generate_board():
    return [
        [random.choice(SYMBOL_POOL) for _ in range(3)]
        for _ in range(3)
    ]


def format_board(board):
    return (
        f"{board[0][0]} {board[0][1]} {board[0][2]}\n"
        f"{board[1][0]} {board[1][1]} {board[1][2]}\n"
        f"{board[2][0]} {board[2][1]} {board[2][2]}"
    )


def hidden_board():
    return (
        f"{POKEBALL_EMOJI} {POKEBALL_EMOJI} {POKEBALL_EMOJI}\n"
        f"{POKEBALL_EMOJI} {POKEBALL_EMOJI} {POKEBALL_EMOJI}\n"
        f"{POKEBALL_EMOJI} {POKEBALL_EMOJI} {POKEBALL_EMOJI}"
    )


def evaluate_board(board):

    total_multiplier = 0
    jackpot_hit = False
    winning_lines = []

    for line_number, line in enumerate(
        PAYLINES,
        start=1
    ):

        symbols = [
            board[row][col]
            for row, col in line
        ]

        if len(set(symbols)) != 1:
            continue

        symbol = symbols[0]

        if symbol == MEW_EMOJI:

            jackpot_hit = True

            winning_lines.append(
                f"Line {line_number}: Mew x3 JACKPOT"
            )

        elif symbol == EEVEE_EMOJI:

            total_multiplier += 20

            winning_lines.append(
                f"Line {line_number}: Eevee x3 (20x)"
            )

        else:

            total_multiplier += 5

            winning_lines.append(
                f"Line {line_number}: "
                f"{symbol}{symbol}{symbol} (5x)"
            )

    return (
        total_multiplier,
        jackpot_hit,
        winning_lines
    )


def reveal_row_1(board):

    return (
        f"{board[0][0]} {board[0][1]} {board[0][2]}\n"
        f"{POKEBALL_EMOJI} {POKEBALL_EMOJI} {POKEBALL_EMOJI}\n"
        f"{POKEBALL_EMOJI} {POKEBALL_EMOJI} {POKEBALL_EMOJI}"
    )


def reveal_row_2(board):

    return (
        f"{board[0][0]} {board[0][1]} {board[0][2]}\n"
        f"{board[1][0]} {board[1][1]} {board[1][2]}\n"
        f"{POKEBALL_EMOJI} {POKEBALL_EMOJI} {POKEBALL_EMOJI}"
    )
class SlotsView(discord.ui.View):

    def __init__(
        self,
        interaction: discord.Interaction
    ):
        super().__init__(timeout=120)

        self.allowed_user_id = interaction.user.id

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ):

        if interaction.user.id != self.allowed_user_id:

            await interaction.response.send_message(
                "These buttons belong to another player.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="1,000 Coins",
        style=discord.ButtonStyle.success,
        emoji="🟢"
    )
    async def beginner(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await run_slot_spin(
            interaction,
            1000
        )

    @discord.ui.button(
        label="10,000 Coins",
        style=discord.ButtonStyle.primary,
        emoji="🔵"
    )
    async def trainer(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await run_slot_spin(
            interaction,
            10000
        )

    @discord.ui.button(
        label="100,000 Coins",
        style=discord.ButtonStyle.danger,
        emoji="🟣"
    )
    async def champion(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await run_slot_spin(
            interaction,
            100000
        )


async def run_slot_spin(
    interaction: discord.Interaction,
    bet: int
):

    user_key = (
        interaction.user.id,
        interaction.guild.id
    )

    if user_key in slot_locks:

        await interaction.response.send_message(
            "You already have a spin processing.",
            ephemeral=True
        )

        return

    slot_locks.add(user_key)

    try:

        async with interaction.client.db.acquire() as conn:

            # -------------------------------------------------
            # ENSURE USER EXISTS
            # -------------------------------------------------

            await conn.execute(
                """
                INSERT INTO users (
                    user_id,
                    guild_id,
                    username,
                    global_name,
                    avatar_url,
                    created_at,
                    last_seen_at,
                    exp,
                    level,
                    coin_balance,
                    daily_streak
                )
                VALUES (
                    $1,
                    $2,
                    $3,
                    $4,
                    $5,
                    NOW(),
                    NOW(),
                    0,
                    1,
                    0,
                    0
                )
                ON CONFLICT (user_id, guild_id)
                DO NOTHING
                """,
                interaction.user.id,
                interaction.guild.id,
                interaction.user.name,
                interaction.user.global_name
                or interaction.user.display_name,
                str(interaction.user.display_avatar.url)
            )

            balance = await conn.fetchval(
                """
                SELECT coin_balance
                FROM users
                WHERE user_id = $1
                  AND guild_id = $2
                """,
                interaction.user.id,
                interaction.guild.id
            )

            balance = balance or 0

            if balance < bet:

                embed = discord.Embed(
                    title="💸 Not Enough Coins",
                    description=(
                        f"You need **{bet:,}** coins.\n\n"
                        f"Current Balance: "
                        f"**{balance:,}**"
                    ),
                    color=discord.Color.red()
                )

                await interaction.response.send_message(
                    embed=embed,
                    ephemeral=True
                )

                return

            await conn.execute(
                """
                INSERT INTO slot_jackpot (
                    guild_id,
                    tier,
                    current_amount
                )
                VALUES (
                    $1,
                    $2,
                    $3
                )
                ON CONFLICT (guild_id, tier)
                DO NOTHING
                """,
                interaction.guild.id,
                bet,
                SLOT_TIERS[bet]["reset_jackpot"]
            )

            starting_jackpot = await conn.fetchval(
                """
                SELECT current_amount
                FROM slot_jackpot
                WHERE guild_id = $1
                  AND tier = $2
                """,
                interaction.guild.id,
                bet
            )

            await conn.execute(
                """
                UPDATE users
                SET coin_balance =
                    coin_balance - $1
                WHERE user_id = $2
                  AND guild_id = $3
                """,
                bet,
                interaction.user.id,
                interaction.guild.id
            )

            jackpot_contribution = int(
                bet * 0.05
            )

            await conn.execute(
                """
                UPDATE slot_jackpot
                SET current_amount =
                    current_amount + $1
                WHERE guild_id = $2
                  AND tier = $3
                """,
                jackpot_contribution,
                interaction.guild.id,
                bet
            )

            board = generate_board()

            (
                multiplier,
                jackpot_hit,
                winning_lines
            ) = evaluate_board(board)

            payout = bet * multiplier
            jackpot_amount = 0

        # -------------------------------------------------
        # START ANIMATION
        # -------------------------------------------------

        embed = discord.Embed(
            title=f"🎰 {SLOT_TIERS[bet]['name']} Slots",
            description=(
                f"💎 Current Jackpot: "
                f"**{starting_jackpot:,}** Coins\n\n"
                f"{hidden_board()}\n\n"
                f"🎰 Spinning..."
            ),
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=None
        )

        message = await interaction.original_response()

        await asyncio.sleep(0.8)

        embed.description = (
            f"💎 Current Jackpot: "
            f"**{starting_jackpot:,}** Coins\n\n"
            f"{reveal_row_1(board)}\n\n"
            f"🎰 Spinning..."
        )

        await message.edit(embed=embed)

        await asyncio.sleep(0.8)

        embed.description = (
            f"💎 Current Jackpot: "
            f"**{starting_jackpot:,}** Coins\n\n"
            f"{reveal_row_2(board)}\n\n"
            f"🎰 Spinning..."
        )

        await message.edit(embed=embed)

        await asyncio.sleep(0.8)
        # -------------------------------------------------
        # PROCESS PAYOUTS
        # -------------------------------------------------

        async with interaction.client.db.acquire() as conn:

            if jackpot_hit:

                jackpot_amount = await conn.fetchval(
                    """
                    SELECT current_amount
                    FROM slot_jackpot
                    WHERE guild_id = $1
                      AND tier = $2
                    """,
                    interaction.guild.id,
                    bet
                )

                payout += jackpot_amount

                await conn.execute(
                    """
                    UPDATE slot_jackpot
                    SET
                        current_amount = $1,
                        last_winner_id = $2,
                        last_win_amount = $3
                    WHERE guild_id = $4
                      AND tier = $5
                    """,
                    SLOT_TIERS[bet]["reset_jackpot"],
                    interaction.user.id,
                    jackpot_amount,
                    interaction.guild.id,
                    bet
                )

            if payout > 0:

                await conn.execute(
                    """
                    UPDATE users
                    SET coin_balance =
                        coin_balance + $1
                    WHERE user_id = $2
                      AND guild_id = $3
                    """,
                    payout,
                    interaction.user.id,
                    interaction.guild.id
                )

            await conn.execute(
                """
                INSERT INTO slot_history (
                    user_id,
                    guild_id,
                    tier,
                    bet_amount,
                    payout_amount,
                    jackpot_hit
                )
                VALUES (
                    $1,
                    $2,
                    $3,
                    $4,
                    $5,
                    $6
                )
                """,
                interaction.user.id,
                interaction.guild.id,
                bet,
                bet,
                payout,
                jackpot_hit
            )

            new_balance = await conn.fetchval(
                """
                SELECT coin_balance
                FROM users
                WHERE user_id = $1
                  AND guild_id = $2
                """,
                interaction.user.id,
                interaction.guild.id
            )

            current_jackpot = await conn.fetchval(
                """
                SELECT current_amount
                FROM slot_jackpot
                WHERE guild_id = $1
                  AND tier = $2
                """,
                interaction.guild.id,
                bet
            )

        # -------------------------------------------------
        # JACKPOT SERVER ANNOUNCEMENT
        # -------------------------------------------------

        if jackpot_hit:

            jackpot_embed = discord.Embed(
                title="🚨 JACKPOT HIT 🚨",
                description=(
                    f"{interaction.user.mention} "
                    f"won **{jackpot_amount:,}** coins!\n\n"
                    f"Tier: "
                    f"{SLOT_TIERS[bet]['name']}"
                ),
                color=discord.Color.green()
            )

            try:
                await interaction.channel.send(
                    embed=jackpot_embed
                )
            except:
                pass

        # -------------------------------------------------
        # FINAL REVEAL
        # -------------------------------------------------

        embed = discord.Embed(
            title=f"🎰 {SLOT_TIERS[bet]['name']} Slots",
            description=(
                f"💎 Current Jackpot: "
                f"**{starting_jackpot:,}** Coins\n\n"
                f"{format_board(board)}"
            ),
            color=discord.Color.gold()
        )

        if jackpot_hit:

            embed.color = discord.Color.green()

        elif payout > bet:

            embed.color = discord.Color.blurple()

        if winning_lines:

            embed.add_field(
                name="🏆 Winning Lines",
                value="\n".join(
                    f"• {line}"
                    for line in winning_lines
                ),
                inline=False
            )

        else:

            embed.add_field(
                name="❌ No Wins",
                value="Better luck next time!",
                inline=False
            )

        if jackpot_hit:

            embed.add_field(
                name="🚨 JACKPOT HIT 🚨",
                value=(
                    f"You won "
                    f"**{jackpot_amount:,}** coins!"
                ),
                inline=False
            )

        profit = payout - bet

        embed.add_field(
            name="🪙 Bet",
            value=f"{bet:,}",
            inline=True
        )

        embed.add_field(
            name="💰 Payout",
            value=f"{payout:,}",
            inline=True
        )

        embed.add_field(
            name="📈 Net Winnings",
            value=f"{profit:,}",
            inline=True
        )

        embed.add_field(
            name="💵 Balance",
            value=f"{new_balance:,}",
            inline=True
        )

        embed.add_field(
            name=f"{MEW_EMOJI} New Jackpot Amount",
            value=f"{current_jackpot:,}",
            inline=True      
        )

        tier_name = SLOT_TIERS[bet]["name"]

        embed.set_footer(
            text=f"{tier_name} Slot Machine"
        )

        await message.edit(
            embed=embed
        )

    finally:

        slot_locks.discard(user_key)


# ---------------------------------------------------------
# SLOTS COMMAND
# ---------------------------------------------------------

@app_commands.command(
    name="slots",
    description="Play PokéSlots."
)
async def slots(
    interaction: discord.Interaction
):

    async with interaction.client.db.acquire() as conn:

        balance = await conn.fetchval(
            """
            SELECT coin_balance
            FROM users
            WHERE user_id = $1
              AND guild_id = $2
            """,
            interaction.user.id,
            interaction.guild.id
        )

        balance = balance or 0

        beginner_jackpot = await conn.fetchval(
            """
            SELECT current_amount
            FROM slot_jackpot
            WHERE guild_id = $1
              AND tier = 1000
            """,
            interaction.guild.id
        )

        trainer_jackpot = await conn.fetchval(
            """
            SELECT current_amount
            FROM slot_jackpot
            WHERE guild_id = $1
              AND tier = 10000
            """,
            interaction.guild.id
        )

        champion_jackpot = await conn.fetchval(
            """
            SELECT current_amount
            FROM slot_jackpot
            WHERE guild_id = $1
              AND tier = 100000
            """,
            interaction.guild.id
        )

        beginner_jackpot = beginner_jackpot or 100_000
        trainer_jackpot = trainer_jackpot or 1_000_000
        champion_jackpot = champion_jackpot or 10_000_000

    embed = discord.Embed(
        title="🎰 PokéSlots",
        description=(
            f"🏦 Balance: **{balance:,}** Coins\n\n"
            f"🟢 Beginner Jackpot: "
            f"**{beginner_jackpot:,}**\n"
            f"🔵 Trainer Jackpot: "
            f"**{trainer_jackpot:,}**\n"
            f"🟣 Champion Jackpot: "
            f"**{champion_jackpot:,}**\n\n"
            "Select your wager below."
        ),
        color=discord.Color.gold()
    )

    await interaction.response.send_message(
        embed=embed,
        view=SlotsView(interaction)
    )


# ---------------------------------------------------------
# SETUP
# ---------------------------------------------------------

async def setup(bot):

    bot.tree.add_command(slots)