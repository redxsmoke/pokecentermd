import asyncio
import random
from datetime import datetime, timezone, timedelta
from itertools import combinations

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
POKEBALL_EMOJI = "<:Pokeball1:1540904892195930182>"
MEOWTH_CHARM_EMOJI = "<:MeowthCharm:1559756889548529684>"


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
# Active boosts are intentionally in memory, keyed by (user_id, guild_id).
# They expire after 10 minutes and reset when the bot restarts.
active_charm_boosts = {}


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

# Meowth's Charm is activated ONLY by its button. Timers are in memory.
CHARM_NAME = "Meowth's Charm"
CHARM_DURATION = timedelta(minutes=10)


def normal_win_probability():
    """Exact probability of at least one winning line with the original reels."""
    n = len(SYMBOL_POOL)
    counts = {}
    for symbol in SYMBOL_POOL:
        counts[symbol] = counts.get(symbol, 0) + 1
    weights = [count / n for count in counts.values()]
    answer = 0.0
    for count in range(1, len(PAYLINES) + 1):
        for selected in combinations(PAYLINES, count):
            parent = list(range(9))

            def root(x):
                while parent[x] != x:
                    x = parent[x]
                return x

            for line in selected:
                first = line[0][0] * 3 + line[0][1]
                for r, c in line[1:]:
                    parent[root(r * 3 + c)] = root(first)
            components = {}
            for pos in range(9):
                r = root(pos)
                components[r] = components.get(r, 0) + 1
            probability = 1.0
            for size in components.values():
                probability *= sum(weight ** size for weight in weights)
            answer += (1 if count % 2 else -1) * probability
    return answer


BASE_WIN_PROBABILITY = normal_win_probability()
# Converts the appropriate fraction of losing boards into ordinary wins.
# The total win probability increases by 25% relative to the unboosted rate.
LOSS_CONVERSION_CHANCE = min(
    1.0, 0.25 * BASE_WIN_PROBABILITY / (1 - BASE_WIN_PROBABILITY)
)


def generate_charmed_board():
    board = generate_board()
    multiplier, jackpot, lines = evaluate_board(board)
    if multiplier == 0 and not jackpot and random.random() < LOSS_CONVERSION_CHANCE:
        # Generate an ordinary winning board, never a jackpot. This preserves
        # the probability of landing a natural Mew jackpot.
        for _ in range(10000):
            candidate = generate_board()
            new_multiplier, new_jackpot, new_lines = evaluate_board(candidate)
            if new_multiplier > 0 and not new_jackpot:
                return candidate, new_multiplier, False, new_lines
    return board, multiplier, jackpot, lines


def error_embed(title, description):
    return discord.Embed(title=title, description=description, color=discord.Color.red())


async def send_private_error(interaction, title, description):
    embed = error_embed(title, description)
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def load_lobby_embed(interaction):
    async with interaction.client.db.acquire() as conn:
        balance = await conn.fetchval(
            "SELECT coin_balance FROM users WHERE user_id=$1 AND guild_id=$2",
            interaction.user.id, interaction.guild.id
        ) or 0
        jackpots = {}
        for bet, tier in SLOT_TIERS.items():
            jackpots[bet] = await conn.fetchval(
                "SELECT current_amount FROM slot_jackpot WHERE guild_id=$1 AND tier=$2",
                interaction.guild.id, bet
            ) or tier['reset_jackpot']
        owned = await conn.fetchrow("""
            SELECT u.quantity, i.emoji_name, i.emoji_id
            FROM user_items u JOIN cd_items i ON i.cd_item_id=u.cd_item_id
            WHERE u.user_id=$1 AND u.guild_id=$2 AND i.item_name=$3
        """, interaction.user.id, interaction.guild.id, CHARM_NAME)
    description = (
        f"🏦 Balance: **{balance:,}** Coins\n\n"
        f"🟢 Beginner Jackpot: **{jackpots[1000]:,}**\n"
        f"🔵 Trainer Jackpot: **{jackpots[10000]:,}**\n"
        f"🟣 Champion Jackpot: **{jackpots[100000]:,}**\n\n"
        "Select your wager below."
    )
    expires_at = active_charm_boosts.get((interaction.user.id, interaction.guild.id))
    if expires_at and expires_at > datetime.now(timezone.utc):
        description += f"\n\n{MEOWTH_CHARM_EMOJI} **Meowth's Charm is active.**"
    elif owned and owned['quantity'] > 0:
        description += f"\n\n🎟️ **Meowth's Charm x{owned['quantity']}** — select **Use Meowth’s Charm** to activate."
    return discord.Embed(title='🎰 PokéSlots', description=description, color=discord.Color.gold())


async def player_has_available_charm(interaction):
    """Only offer activation when an unused Charm is in this player's inventory."""
    key = (interaction.user.id, interaction.guild.id)
    expires = active_charm_boosts.get(key)
    if expires and expires > datetime.now(timezone.utc):
        return False
    async with interaction.client.db.acquire() as conn:
        quantity = await conn.fetchval("""
            SELECT u.quantity
            FROM user_items u
            JOIN cd_items i ON i.cd_item_id = u.cd_item_id
            WHERE u.user_id = $1 AND u.guild_id = $2
              AND i.item_name = $3
        """, interaction.user.id, interaction.guild.id, CHARM_NAME)
    return bool(quantity and quantity > 0)


async def make_slots_view(interaction):
    return SlotsView(interaction.user.id, await player_has_available_charm(interaction))


async def make_after_spin_view(interaction, bet):
    return AfterSpinView(interaction.user.id, bet, await player_has_available_charm(interaction))


class OwnedSlotsView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await send_private_error(interaction, '⛔ Not Your Game', 'Start your own game with **/slots**.')
            return False
        return True


async def activate_charm(interaction, current_bet=None):
    """Explicitly activate one owned Charm without placing a wager."""
    key = (interaction.user.id, interaction.guild.id)
    if key in slot_locks:
        await send_private_error(interaction, '⏳ Spin In Progress', 'Wait for the current spin to finish.')
        return
    slot_locks.add(key)
    try:
        existing = active_charm_boosts.get(key)
        if existing and existing > datetime.now(timezone.utc):
            await send_private_error(interaction, '🎟️ Charm Already Active',
                                     f'Your boost expires <t:{int(existing.timestamp())}:R>.')
            return
        async with interaction.client.db.acquire() as conn:
            async with conn.transaction():
                expires, activated = await get_or_activate_charm(
                    conn, interaction.user.id, interaction.guild.id
                )
        if not activated:
            await send_private_error(interaction, '🎟️ No Charm Available',
                                     'Purchase Meowth’s Charm from the Poké Mart first.')
            return
        active_charm_boosts[key] = expires
        if current_bet is None:
            embed = await load_lobby_embed(interaction)
            view = await make_slots_view(interaction)
        else:
            embed = interaction.message.embeds[0].copy() if interaction.message.embeds else discord.Embed(title='🎰 PokéSlots')
            embed.add_field(name='🎟️ Meowth’s Charm Activated',
                            value=f'+25% win chance until <t:{int(expires.timestamp())}:R>.', inline=False)
            view = await make_after_spin_view(interaction, current_bet)
        await interaction.response.edit_message(embed=embed, view=view)
    finally:
        slot_locks.discard(key)


class SlotsView(OwnedSlotsView):
    def __init__(self, user_id, show_charm=False):
        super().__init__(user_id)
        if not show_charm:
            self.remove_item(self.use_charm)

    @discord.ui.button(label='Use Meowth’s Charm', style=discord.ButtonStyle.secondary,
                       emoji=discord.PartialEmoji(name='MeowthCharm', id=1559756889548529684), row=1)
    async def use_charm(self, interaction, button):
        await activate_charm(interaction)

    @discord.ui.button(label='1,000 Coins', style=discord.ButtonStyle.success, emoji='🟢')
    async def beginner(self, interaction, button):
        await run_slot_spin(interaction, 1000)

    @discord.ui.button(label='10,000 Coins', style=discord.ButtonStyle.primary, emoji='🔵')
    async def trainer(self, interaction, button):
        await run_slot_spin(interaction, 10000)

    @discord.ui.button(label='100,000 Coins', style=discord.ButtonStyle.danger, emoji='🟣')
    async def champion(self, interaction, button):
        await run_slot_spin(interaction, 100000)


class AfterSpinView(OwnedSlotsView):
    @discord.ui.button(label='Use Meowth’s Charm', style=discord.ButtonStyle.secondary,
                       emoji=discord.PartialEmoji(name='MeowthCharm', id=1559756889548529684), row=1)
    async def use_charm(self, interaction, button):
        await activate_charm(interaction, self.bet)

    def __init__(self, user_id, bet, show_charm=False):
        super().__init__(user_id)
        self.bet = bet
        if not show_charm:
            self.remove_item(self.use_charm)

    @discord.ui.button(label='Spin Again', style=discord.ButtonStyle.success, emoji='🎰')
    async def spin_again(self, interaction, button):
        await run_slot_spin(interaction, self.bet)

    @discord.ui.button(label='Change Bet Amount', style=discord.ButtonStyle.primary, emoji='💰')
    async def change_bet(self, interaction, button):
        if (interaction.user.id, interaction.guild.id) in slot_locks:
            await send_private_error(interaction, '⏳ Spin In Progress', 'Wait for the current spin to finish.')
            return
        embed = await load_lobby_embed(interaction)
        await interaction.response.edit_message(embed=embed, view=await make_slots_view(interaction))

    @discord.ui.button(label='Finished', style=discord.ButtonStyle.secondary, emoji='✅')
    async def finished(self, interaction, button):
        if (interaction.user.id, interaction.guild.id) in slot_locks:
            await send_private_error(interaction, '⏳ Spin In Progress', 'Wait for the current spin to finish.')
            return
        embed = discord.Embed(title='🎰 PokéSlots', description='Thanks for playing!', color=discord.Color.gold())
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()


async def get_or_activate_charm(conn, user_id, guild_id):
    """Consume one Charm only when the player explicitly clicks Use Charm."""
    key = (user_id, guild_id)
    now = datetime.now(timezone.utc)
    expires_at = active_charm_boosts.get(key)
    if expires_at and expires_at > now:
        return expires_at, False

    # Only a successfully purchased, available ticket can be activated.
    item = await conn.fetchrow("""
        SELECT i.cd_item_id
        FROM cd_items i
        JOIN user_items u ON u.cd_item_id=i.cd_item_id
        WHERE i.item_name=$1 AND u.user_id=$2 AND u.guild_id=$3 AND u.quantity > 0
        FOR UPDATE OF u
    """, CHARM_NAME, user_id, guild_id)
    if not item:
        return None, False

    await conn.execute("""
        UPDATE user_items SET quantity=quantity-1, updated_timestamp=NOW()
        WHERE user_id=$1 AND guild_id=$2 AND cd_item_id=$3
    """, user_id, guild_id, item['cd_item_id'])
    return now + CHARM_DURATION, True


async def run_slot_spin(interaction: discord.Interaction, bet: int):
    user_key = (interaction.user.id, interaction.guild.id)
    if user_key in slot_locks:
        await send_private_error(interaction, '⏳ Spin In Progress', 'You already have a spin processing.')
        return
    slot_locks.add(user_key)
    try:
        async with interaction.client.db.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO users (
                        user_id, guild_id, username, global_name, avatar_url,
                        created_at, last_seen_at, exp, level, coin_balance, daily_streak
                    ) VALUES ($1,$2,$3,$4,$5,NOW(),NOW(),0,1,0,0)
                    ON CONFLICT (user_id,guild_id) DO NOTHING
                """, interaction.user.id, interaction.guild.id, interaction.user.name,
                    interaction.user.global_name or interaction.user.display_name,
                    str(interaction.user.display_avatar.url))
                balance = await conn.fetchval("""
                    SELECT coin_balance FROM users WHERE user_id=$1 AND guild_id=$2 FOR UPDATE
                """, interaction.user.id, interaction.guild.id)
                if balance < bet:
                    await send_private_error(
                        interaction, '💸 Not Enough Coins',
                        f'You need **{bet:,}** coins.\nCurrent Balance: **{balance:,}**'
                    )
                    return

                charm_expires = active_charm_boosts.get(user_key)
                charm_active = bool(charm_expires and charm_expires > datetime.now(timezone.utc))
                newly_activated = False
                await conn.execute("""
                    INSERT INTO slot_jackpot(guild_id,tier,current_amount)
                    VALUES($1,$2,$3) ON CONFLICT (guild_id,tier) DO NOTHING
                """, interaction.guild.id, bet, SLOT_TIERS[bet]['reset_jackpot'])
                starting_jackpot = await conn.fetchval("""
                    SELECT current_amount FROM slot_jackpot
                    WHERE guild_id=$1 AND tier=$2
                """, interaction.guild.id, bet)
                await conn.execute("""
                    UPDATE users SET coin_balance=coin_balance-$1
                    WHERE user_id=$2 AND guild_id=$3
                """, bet, interaction.user.id, interaction.guild.id)
                await conn.execute("""
                    UPDATE slot_jackpot SET current_amount=current_amount+$1
                    WHERE guild_id=$2 AND tier=$3
                """, int(bet*0.05), interaction.guild.id, bet)
                if charm_active:
                    board, multiplier, jackpot_hit, winning_lines = generate_charmed_board()
                else:
                    board = generate_board()
                    multiplier, jackpot_hit, winning_lines = evaluate_board(board)
                payout = bet * multiplier
                jackpot_amount = 0

        charm_text = ''
        if charm_active:
            charm_text = f"\n🎟️ Meowth's Charm **+25% win chance** (<t:{int(charm_expires.timestamp())}:R>)"
        embed = discord.Embed(
            title=f"🎰 {SLOT_TIERS[bet]['name']} Slots",
            description=f'💎 Current Jackpot: **{starting_jackpot:,}** Coins{charm_text}\n\n{hidden_board()}\n\n🎰 Spinning...',
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=None)
        message = interaction.message
        await asyncio.sleep(0.8)
        embed.description = f'💎 Current Jackpot: **{starting_jackpot:,}** Coins{charm_text}\n\n{reveal_row_1(board)}\n\n🎰 Spinning...'
        await message.edit(embed=embed)
        await asyncio.sleep(0.8)
        embed.description = f'💎 Current Jackpot: **{starting_jackpot:,}** Coins{charm_text}\n\n{reveal_row_2(board)}\n\n🎰 Spinning...'
        await message.edit(embed=embed)
        await asyncio.sleep(0.8)

        async with interaction.client.db.acquire() as conn:
            async with conn.transaction():
                if jackpot_hit:
                    jackpot_amount = await conn.fetchval("""
                        SELECT current_amount FROM slot_jackpot
                        WHERE guild_id=$1 AND tier=$2 FOR UPDATE
                    """, interaction.guild.id, bet)
                    payout += jackpot_amount
                    await conn.execute("""
                        UPDATE slot_jackpot
                        SET current_amount=$1, last_winner_id=$2, last_win_amount=$3
                        WHERE guild_id=$4 AND tier=$5
                    """, SLOT_TIERS[bet]['reset_jackpot'], interaction.user.id,
                        jackpot_amount, interaction.guild.id, bet)
                if payout > 0:
                    await conn.execute("""
                        UPDATE users SET coin_balance=coin_balance+$1
                        WHERE user_id=$2 AND guild_id=$3
                    """, payout, interaction.user.id, interaction.guild.id)
                await conn.execute("""
                    INSERT INTO slot_history(user_id,guild_id,tier,bet_amount,payout_amount,jackpot_hit)
                    VALUES($1,$2,$3,$4,$5,$6)
                """, interaction.user.id, interaction.guild.id, bet, bet, payout, jackpot_hit)
                new_balance = await conn.fetchval("""
                    SELECT coin_balance FROM users WHERE user_id=$1 AND guild_id=$2
                """, interaction.user.id, interaction.guild.id)
                current_jackpot = await conn.fetchval("""
                    SELECT current_amount FROM slot_jackpot WHERE guild_id=$1 AND tier=$2
                """, interaction.guild.id, bet)

        if jackpot_hit:
            announcement = discord.Embed(
                title='🚨 JACKPOT HIT 🚨',
                description=f'{interaction.user.mention} won **{jackpot_amount:,}** coins!\n\nTier: {SLOT_TIERS[bet]["name"]}',
                color=discord.Color.green()
            )
            try:
                await interaction.channel.send(embed=announcement)
            except discord.HTTPException:
                pass

        embed = discord.Embed(
            title=f"🎰 {SLOT_TIERS[bet]['name']} Slots",
            description=f'💎 Current Jackpot: **{starting_jackpot:,}** Coins{charm_text}\n\n{format_board(board)}',
            color=discord.Color.green() if jackpot_hit else (
                discord.Color.blurple() if payout > bet else discord.Color.gold()
            )
        )
        if winning_lines:
            embed.add_field(name='🏆 Winning Lines', value='\n'.join(f'• {line}' for line in winning_lines), inline=False)
        else:
            embed.add_field(name='❌ No Wins', value='Better luck next time!', inline=False)
        if jackpot_hit:
            embed.add_field(name='🚨 JACKPOT HIT 🚨', value=f'You won **{jackpot_amount:,}** coins!', inline=False)
        embed.add_field(name='🪙 Bet', value=f'{bet:,}', inline=True)
        embed.add_field(name='💰 Payout', value=f'{payout:,}', inline=True)
        embed.add_field(name='📈 Net Winnings', value=f'{payout-bet:,}', inline=True)
        embed.add_field(name='💵 Balance', value=f'{new_balance:,}', inline=True)
        embed.add_field(name=f'{MEW_EMOJI} New Jackpot Amount', value=f'{current_jackpot:,}', inline=True)
        embed.set_footer(text=f'{SLOT_TIERS[bet]["name"]} Slot Machine')
        await message.edit(embed=embed, view=await make_after_spin_view(interaction, bet))
    finally:
        slot_locks.discard(user_key)


@app_commands.command(name='slots', description='Play PokéSlots.')
async def slots(interaction: discord.Interaction):
    embed = await load_lobby_embed(interaction)
    await interaction.response.send_message(embed=embed, view=await make_slots_view(interaction))


async def setup(bot):
    bot.tree.add_command(slots)
