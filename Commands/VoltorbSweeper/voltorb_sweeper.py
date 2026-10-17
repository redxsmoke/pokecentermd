"""VoltorbSweeper — single-file Discord app command for discord.py 2.x.

Load as an extension with bot.load_extension('Commands.VoltorbSweeper.voltorbsweeper')
or adjust the import path to match your folder structure.
Requires existing users(user_id, guild_id, coin_balance) and the voltorbsweeper stats table.
"""
import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands

ENTRY_FEE = 25_000
MAX_PRIZE = 100_000
BOARD_SIZE = 4
VOLTORB_COUNT = 4
VOLTORB_EMOJI = discord.PartialEmoji(name="Voltorb", id=1560468806567202906)
VOLTORB_TEXT = "<:Voltorb:1560468806567202906>"
# Total cash-out prize (not per-tile reward), indexed by safe tiles uncovered.
PRIZES = (0, 500, 1_200, 2_500, 4_500, 7_000, 11_000,
          16_000, 23_000, 32_000, 44_000, 60_000, MAX_PRIZE)
ACTIVE_GAMES = {}  # (guild_id, user_id) -> VoltorbView; clears on restart


async def record_result(conn, user_id, guild_id, won):
    """Record exactly one completed game per call, using the caller's transaction."""
    await conn.execute("""
        INSERT INTO voltorbsweeper
            (user_id, guild_id, times_won, times_lost, win_rate, last_played)
        VALUES ($1, $2, $3, $4, CASE WHEN $3 = 1 THEN 100.00 ELSE 0.00 END, NOW())
        ON CONFLICT (user_id, guild_id) DO UPDATE SET
            times_won = voltorbsweeper.times_won + EXCLUDED.times_won,
            times_lost = voltorbsweeper.times_lost + EXCLUDED.times_lost,
            win_rate = ROUND(
                (voltorbsweeper.times_won + EXCLUDED.times_won)::NUMERIC * 100 /
                NULLIF(voltorbsweeper.times_won + EXCLUDED.times_won +
                       voltorbsweeper.times_lost + EXCLUDED.times_lost, 0), 2),
            last_played = NOW()
    """, user_id, guild_id, int(won), int(not won))


def fmt(amount):
    return f'{amount:,}'


def error(message):
    return discord.Embed(description=message, color=discord.Color.red())


class PlayAgainView(discord.ui.View):
    # The only control shown after a completed game.
    def __init__(self, owner_id, guild_id):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.processing = False

    @discord.ui.button(label='Play Again', emoji='🎮', style=discord.ButtonStyle.success)
    async def play_again(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=error('Start your own game with **/voltorbsweeper**.'), ephemeral=True)
            return
        if self.processing:
            await interaction.response.send_message(embed=error('Please wait...'), ephemeral=True)
            return
        self.processing = True
        try:
            await show_buyin_prompt(interaction, replace_message=True)
        finally:
            self.processing = False


class FinishedBoardView(PlayAgainView):
    """Original tile-button reveal, with only Play Again interactive."""
    def __init__(self, owner_id, guild_id, board, revealed, flagged):
        super().__init__(owner_id, guild_id)
        # Add the 4x4 board first. Re-attach Play Again only after all tiles,
        # so Discord renders it in the final row without shifting the grid.
        replay_button = self.play_again
        self.remove_item(replay_button)
        for index, value in enumerate(board):
            if value == 0:
                tile = discord.ui.Button(emoji=VOLTORB_EMOJI,
                                         style=discord.ButtonStyle.danger,
                                         disabled=True, row=index // BOARD_SIZE)
            elif index in revealed:
                tile = discord.ui.Button(label=str(value),
                                         style=discord.ButtonStyle.success,
                                         disabled=True, row=index // BOARD_SIZE)
            elif index in flagged:
                tile = discord.ui.Button(emoji='🚩',
                                         style=discord.ButtonStyle.secondary,
                                         disabled=True, row=index // BOARD_SIZE)
            else:
                tile = discord.ui.Button(label='?',
                                         style=discord.ButtonStyle.secondary,
                                         disabled=True, row=index // BOARD_SIZE)
            self.add_item(tile)
        replay_button.row = 4
        self.add_item(replay_button)


class TileButton(discord.ui.Button):
    def __init__(self, index):
        self.index = index
        super().__init__(label='?', style=discord.ButtonStyle.secondary,
                         row=index // BOARD_SIZE)

    async def callback(self, interaction: discord.Interaction):
        await self.view.flip(interaction, self)


class VoltorbView(discord.ui.View):
    def __init__(self, owner_id, guild_id, board):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.key = (guild_id, owner_id)
        self.board = board
        self.revealed = set()
        self.flagged = set()
        self.flag_mode = False
        self.finished = False
        self.processing = False
        self.message = None
        self.bot = None
        self.tile_buttons = []
        for i in range(BOARD_SIZE * BOARD_SIZE):
            button = TileButton(i)
            self.tile_buttons.append(button)
            self.add_item(button)
        self.sync_buttons()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=error('This is another player’s game. Use **/voltorbsweeper** to start your own.'),
                ephemeral=True)
            return False
        return True

    @property
    def safe_count(self):
        return len(self.revealed)

    @property
    def prize(self):
        return PRIZES[self.safe_count]

    def sync_buttons(self):
        for button in self.tile_buttons:
            if button.index in self.revealed:
                button.label = str(self.board[button.index])
                button.style = discord.ButtonStyle.success
                button.disabled = True  # Revealed tiles cannot be flipped twice.
            elif button.index in self.flagged:
                button.label = None
                button.emoji = '🚩'
                button.style = discord.ButtonStyle.danger
                button.disabled = False
            else:
                button.label = '?'
                button.emoji = None
                button.style = discord.ButtonStyle.secondary
                button.disabled = False  # All remaining tiles stay playable.
            if button.index in self.revealed:
                button.emoji = None
        self.cash_out_button.disabled = self.safe_count == 0
        self.flag_button.label = '🚩 Marking ON' if self.flag_mode else '🚩 Mark Tiles'
        self.flag_button.style = discord.ButtonStyle.primary if self.flag_mode else discord.ButtonStyle.secondary

    def embed(self, status=None):
        rows = []
        for r in range(BOARD_SIZE):
            vals = self.board[r * BOARD_SIZE:(r + 1) * BOARD_SIZE]
            rows.append(f'**{r + 1}**  ·  {sum(vals)} pts  ·  {vals.count(0)} {VOLTORB_TEXT}')
        cols = []
        for c in range(BOARD_SIZE):
            vals = [self.board[r * BOARD_SIZE + c] for r in range(BOARD_SIZE)]
            cols.append(f'**{c + 1}**: {sum(vals)} pts / {vals.count(0)} {VOLTORB_TEXT}')
        if status is None:
            status = ('Pick a tile, or **Cash Out** to collect your winnings.'
                      if self.safe_count else 'Pick a tile. Avoid the Voltorbs!')
        e = discord.Embed(
            title=f'{VOLTORB_TEXT} VoltorbSweeper',
            description=(f'{status}\n\n'
                         f'💰 **Cash out: {fmt(self.prize)} coins**\n'
                         f'✅ Safe tiles: **{self.safe_count}/12** · 🚩 Marked: **{len(self.flagged)}/4**'
                         f'\n{"🚩 Mark mode: tap tiles to flag or unflag." if self.flag_mode else "Tap tiles to reveal · 🚩 Mark Tiles to place flags."}'),
            color=discord.Color.gold())
        e.add_field(name='Row clues · points / Voltorbs', value='\n'.join(rows), inline=False)
        e.add_field(name='Column clues', value='  |  '.join(cols), inline=False)
        e.set_footer(text=f'Numbers are safe · Voltorbs end the game · Entry: {fmt(ENTRY_FEE)} coins')
        return e

    def result_embed(self, heading, description, *, won=0, balance=None, color=None):
        lines = [description]
        if won:
            lines.append(f'\n🪙 **Winnings: {fmt(won)} coins**')
            lines.append(f'📈 **Net: {won - ENTRY_FEE:+,} coins**')
        else:
            lines.append('\n🪙 **Winnings: 0 coins**')
            lines.append(f'📉 **Net: -{fmt(ENTRY_FEE)} coins**')
        if balance is not None:
            lines.append(f'💵 **Balance: {fmt(balance)} coins**')
        lines.append(f'\nSafe tiles revealed: **{self.safe_count}/12**')
        e = discord.Embed(title=heading, description='\n'.join(lines),
                          color=color or discord.Color.gold())
        return e

    async def finish(self, interaction, embed):
        self.finished = True
        self.end()
        await interaction.response.edit_message(
            embed=embed, view=FinishedBoardView(self.owner_id, self.guild_id, self.board, self.revealed, self.flagged))

    async def flip(self, interaction, button):
        if self.processing or self.finished:
            await interaction.response.send_message(embed=error('This move is no longer available.'), ephemeral=True)
            return
        if button.index in self.revealed:
            await interaction.response.send_message(embed=error('You already revealed that tile.'), ephemeral=True)
            return
        self.processing = True
        try:
            if self.flag_mode:
                if button.index in self.flagged:
                    self.flagged.remove(button.index)
                else:
                    self.flagged.add(button.index)
                self.sync_buttons()
                await interaction.response.edit_message(embed=self.embed(), view=self)
                return
            if button.index in self.flagged:
                await interaction.response.send_message(
                    embed=error('That tile is flagged. Turn on 🚩 Mark Tiles and remove its flag before revealing it.'),
                    ephemeral=True)
                return
            if self.board[button.index] == 0:
                # Show the explosion first, then restore the classic button-grid
                # reveal with Play Again in its own bottom row.
                async with interaction.client.db.acquire() as conn:
                    await record_result(conn, self.owner_id, self.guild_id, False)
                self.finished = True
                self.end()
                explosion = discord.Embed(
                    title=f'💥 {VOLTORB_TEXT} VOLTORB EXPLODED!',
                    description=(
                        '### 💥 BOOOOM! 💥\n'
                        'You hit a Voltorb!\n\n'
                        f'**{fmt(self.prize)} coins** in unclaimed winnings went up in smoke...'
                    ),
                    color=discord.Color.red(),
                )
                await interaction.response.edit_message(embed=explosion, view=None)
                await asyncio.sleep(2.8)
                try:
                    await interaction.edit_original_response(
                        embed=self.result_embed(
                            f'{VOLTORB_TEXT} VOLTORB!',
                            'You uncovered a Voltorb! Your unclaimed coins are lost.',
                            color=discord.Color.red()),
                        view=FinishedBoardView(
                            self.owner_id, self.guild_id, self.board,
                            self.revealed, self.flagged),
                    )
                except discord.HTTPException:
                    pass  # The message may have been deleted during the animation.
                return
            self.revealed.add(button.index)
            if self.safe_count == BOARD_SIZE * BOARD_SIZE - VOLTORB_COUNT:
                await self.payout(interaction, cleared=True, already_processing=True)
                return
            self.sync_buttons()
            await interaction.response.edit_message(embed=self.embed(), view=self)
        finally:
            self.processing = False

    @discord.ui.button(label='Cash Out', emoji='💰', style=discord.ButtonStyle.success, row=4)
    async def cash_out_button(self, interaction, button):
        if self.processing or self.finished:
            await interaction.response.send_message(embed=error('Please wait for the current move.'), ephemeral=True)
            return
        if self.safe_count == 0:
            await interaction.response.send_message(embed=error('Reveal one safe tile before cashing out.'), ephemeral=True)
            return
        await self.payout(interaction)

    async def payout(self, interaction, cleared=False, already_processing=False):
        if not already_processing:
            if self.processing or self.finished:
                await interaction.response.send_message(embed=error('Please wait for the current move.'), ephemeral=True)
                return
            self.processing = True
        try:
            async with interaction.client.db.acquire() as conn:
                async with conn.transaction():
                    updated = await conn.fetchval('''
                        UPDATE users SET coin_balance=coin_balance+$1
                        WHERE user_id=$2 AND guild_id=$3
                        RETURNING coin_balance
                    ''', self.prize, self.owner_id, self.guild_id)
                    if updated is None:
                        raise RuntimeError('Coin account not found while paying VoltorbSweeper.')
                    await record_result(conn, self.owner_id, self.guild_id, True)
            title = '🏆 PERFECT CLEAR!' if cleared else '💰 DEAL! YOU CASHED OUT!'
            message = ('You revealed every safe tile and won the grand prize!'
                       if cleared else 'You walked away before hitting a Voltorb. Smart move!')
            await self.finish(interaction, self.result_embed(
                title, message, won=self.prize, balance=updated, color=discord.Color.green()))
        except Exception:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=error('Could not complete the cash-out. Please try again.'), ephemeral=True)
            raise
        finally:
            if not already_processing:
                self.processing = False

    @discord.ui.button(label='🚩 Mark Tiles', style=discord.ButtonStyle.secondary, row=4)
    async def flag_button(self, interaction, button):
        if self.processing or self.finished:
            await interaction.response.send_message(embed=error('This game is no longer available.'), ephemeral=True)
            return
        self.flag_mode = not self.flag_mode
        self.sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label='How to Play', emoji='📖', style=discord.ButtonStyle.secondary, row=4)
    async def rules_button(self, interaction, button):
        await interaction.response.send_message(embed=rules_embed(), ephemeral=True)

    @discord.ui.button(label='Forfeit', emoji='🚪', style=discord.ButtonStyle.danger, row=4)
    async def quit_button(self, interaction, button):
        if self.processing or self.finished:
            await interaction.response.send_message(embed=error('This game is already ending.'), ephemeral=True)
            return
        self.processing = True
        try:
            async with interaction.client.db.acquire() as conn:
                await record_result(conn, self.owner_id, self.guild_id, False)
            await self.finish(interaction, self.result_embed(
                '🚪 GAME OVER', 'You left the game without cashing out.',
                color=discord.Color.red()))
        finally:
            self.processing = False

    def end(self):
        if ACTIVE_GAMES.get(self.key) is self:
            ACTIVE_GAMES.pop(self.key, None)
        self.stop()

    async def on_timeout(self):
        if self.finished:
            return
        async with self.bot.db.acquire() as conn:
            await record_result(conn, self.owner_id, self.guild_id, False)
        self.finished = True
        self.end()
        if self.message:
            try:
                await self.message.edit(
                    embed=self.result_embed('⌛ GAME EXPIRED',
                        'Your unclaimed winnings were forfeited.', color=discord.Color.red()),
                    view=FinishedBoardView(self.owner_id, self.guild_id, self.board, self.revealed, self.flagged))
            except discord.HTTPException:
                pass


def rules_embed():
    e = discord.Embed(title='📖 How to Play VoltorbSweeper', color=discord.Color.blue(),
                      description=(
                          '**Goal:** Reveal safe tiles, earn an increasing coin prize, and escape before hitting a Voltorb.\n\n'
                          f'**1. Start a game.** Pay **{fmt(ENTRY_FEE)} coins** to play. Each board has **16 tiles**, including '
                          '**4 hidden Voltorbs** and **12 safe tiles** numbered 1–3.\n\n'
                          '**2. Study the clues.** Each row and column shows the **sum of its tile numbers** '
                          'and the **number of Voltorbs** hidden there. Voltorbs count as zero. '
                          'Use those clues to identify safer choices.\n\n'
                          f'**3. Flip a tile.** A number is safe and advances your prize. A {VOLTORB_TEXT} Voltorb '
                          'ends the round and you lose your unclaimed prize and entry fee.\n\n'
                          '**4. Mark suspected Voltorbs.** Press **🚩 Mark Tiles**, then tap a hidden tile to add or remove a flag. Press **🚩 Marking ON** to return to reveal mode. Flags are guesses and do not earn coins. Unflag a tile before revealing it.\n\n'
                          '**5. Choose.** After any safe tile, **Cash Out** to claim your prize, or flip another hidden tile to risk it for more.\n\n'
                          '**6. Win big.** Clear all 12 safe tiles to win the maximum **100,000 coins** '
                          'automatically. No prize can exceed 100,000 coins.\n\n'
                          '**Important:** The displayed prize is the **total cash-out amount**, not an '
                          f'additional payment for each tile. Your {fmt(ENTRY_FEE)}-coin entry fee is not refunded separately. '
                          'If you quit, hit a Voltorb, or time out, you lose the unclaimed prize. '
                          'At the end of every round, Voltorbs appear on the original tile grid. Only Play Again remains clickable.'))
    e.add_field(name='💰 Cash-out prizes', value=(
        '1 safe: **500** · 2: **1,200** · 3: **2,500**\n'
        '4: **4,500** · 5: **7,000** · 6: **11,000**\n'
        '7: **16,000** · 8: **23,000** · 9: **32,000**\n'
        '10: **44,000** · 11: **60,000** · 12: **100,000**'), inline=False)
    e.set_footer(text='Hint: A row or column with zero Voltorbs is completely safe!')
    return e


START_LOCKS = set()


def buyin_embed(balance):
    can_afford = balance >= ENTRY_FEE
    e = discord.Embed(
        title=f'{VOLTORB_TEXT} VoltorbSweeper · Confirm Entry',
        description=(
            'Reveal safe tiles to increase your prize. **Cash Out** before finding a '
            f'{VOLTORB_TEXT} Voltorb, or lose your entry fee.\n\n'
            f'🎟️ **Entry fee:** {fmt(ENTRY_FEE)} coins\n'
            f'🏆 **Maximum payout:** {fmt(MAX_PRIZE)} coins\n'
            f'💰 **Wallet balance:** {fmt(balance)} coins\n'
            f'💳 **Balance after entry:** {fmt(balance - ENTRY_FEE) if can_afford else "Insufficient coins"}\n\n'
            'Each safe tile raises the available payout. You can cash out at any time '
            'after your first safe tile.'
        ),
        color=discord.Color.gold() if can_afford else discord.Color.red())
    e.set_footer(text='No coins are deducted until you confirm.')
    return e


class BuyInView(discord.ui.View):
    def __init__(self, owner_id, guild_id, *, replace_message, can_afford):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.replace_message = replace_message
        self.processing = False
        self.confirm_button.disabled = not can_afford

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=error('Start your own game with **/voltorbsweeper**.'), ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Confirm & Play', emoji='🎮', style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction, button):
        if self.processing:
            await interaction.response.send_message(embed=error('Please wait...'), ephemeral=True)
            return
        self.processing = True
        try:
            await start_game(interaction, replace_message=True)
        finally:
            self.processing = False

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(title='VoltorbSweeper · Cancelled',
                description='No coins were deducted.', color=discord.Color.greyple()), view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        self.stop()


async def show_buyin_prompt(interaction: discord.Interaction, *, replace_message=False):
    key = (interaction.guild_id, interaction.user.id)
    if key in START_LOCKS or (key in ACTIVE_GAMES and not ACTIVE_GAMES[key].finished):
        await interaction.response.send_message(
            embed=error('You already have a game in progress or starting.'), ephemeral=True)
        return
    async with interaction.client.db.acquire() as conn:
        balance = await conn.fetchval('''SELECT coin_balance FROM users
            WHERE user_id=$1 AND guild_id=$2''', interaction.user.id, interaction.guild_id)
    balance = balance or 0
    view = BuyInView(interaction.user.id, interaction.guild_id,
                     replace_message=replace_message, can_afford=balance >= ENTRY_FEE)
    if replace_message:
        await interaction.response.edit_message(embed=buyin_embed(balance), view=view)
    else:
        await interaction.response.send_message(embed=buyin_embed(balance), view=view)


async def start_game(interaction: discord.Interaction, *, replace_message=False):
    # Start a fresh game via slash command or Play Again.
    key = (interaction.guild_id, interaction.user.id)
    if key in START_LOCKS:
        await interaction.response.send_message(embed=error('Your game is already starting.'), ephemeral=True)
        return
    existing = ACTIVE_GAMES.get(key)
    if existing and not existing.finished:
        await interaction.response.send_message(
            embed=error('You already have a VoltorbSweeper game in progress.'), ephemeral=True)
        return
    START_LOCKS.add(key)
    charged = False
    view = None
    try:
        async with interaction.client.db.acquire() as conn:
            balance = await conn.fetchval('''
                UPDATE users SET coin_balance=coin_balance-$1
                WHERE user_id=$2 AND guild_id=$3 AND coin_balance >= $1
                RETURNING coin_balance
            ''', ENTRY_FEE, interaction.user.id, interaction.guild_id)
        if balance is None:
            await interaction.response.send_message(
                embed=error(f'You need **{fmt(ENTRY_FEE)} coins** to play.'), ephemeral=True)
            return
        charged = True
        board = [0] * VOLTORB_COUNT + [random.choice((1, 1, 1, 2, 2, 3)) for _ in range(12)]
        random.shuffle(board)
        view = VoltorbView(interaction.user.id, interaction.guild_id, board)
        view.bot = interaction.client
        ACTIVE_GAMES[key] = view
        if replace_message:
            await interaction.response.edit_message(embed=view.embed(), view=view)
            view.message = interaction.message
        else:
            await interaction.response.send_message(embed=view.embed(), view=view)
            view.message = await interaction.original_response()
    except Exception:
        if view and ACTIVE_GAMES.get(key) is view:
            ACTIVE_GAMES.pop(key, None)
        if charged:
            async with interaction.client.db.acquire() as conn:
                await conn.execute('''UPDATE users SET coin_balance=coin_balance+$1
                    WHERE user_id=$2 AND guild_id=$3''', ENTRY_FEE, interaction.user.id, interaction.guild_id)
        raise
    finally:
        START_LOCKS.discard(key)


class VoltorbSweeper(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='voltorbsweeper', description='Flip safe tiles, avoid Voltorbs, and cash out up to 100,000 coins!')
    @app_commands.guild_only()
    async def voltorbsweeper(self, interaction: discord.Interaction):
        await show_buyin_prompt(interaction)

    @app_commands.command(name='voltorbsweeperrules', description='Learn how to play VoltorbSweeper and see the prize ladder.')
    @app_commands.guild_only()
    async def voltorbsweeperrules(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=rules_embed(), ephemeral=True)


async def setup(bot):
    await bot.add_cog(VoltorbSweeper(bot))
