
import asyncio
import random

import discord
from discord import app_commands


TEST_MODE = False  # Set to True to guarantee a Legendary win; False = normal random gameplay.

ENTRY_FEE = 50_000
FULL_COLLECTION_REWARD = 1_000_000
LEGENDARY_OFFER_VALUE = 1_000_000
TIMEOUT_SECONDS = 900
CONFIRMATION_TIMEOUT = 120

POKEBALL = discord.PartialEmoji(
    name="Pokeball1",
    id=1540904892195930182,
)

GIOVANNI = discord.PartialEmoji(
    name="giovanni",
    id=1559392555731394641,
)

ROCKETLOGO = discord.PartialEmoji(
    name="rocketlogo",
    id=1559409894023495700,
)

COIN_PRIZES = [
    1_000,
    2_500,
    5_000,
    10_000,
    15_000,
    25_000,
    35_000,
    50_000,
    75_000,
    100_000,
    150_000,
    250_000,
    350_000,
    500_000,
]

# Opens 13 cases, leaving two cases for the finale.
ROUND_SIZES = [4, 3, 2, 2, 2]

OFFER_FACTORS = [0.50, 0.60, 0.70, 0.80, 0.90]

LEGENDARY_IDS = [
    144, 145, 146, 150,
    243, 244, 245, 249, 250,
    377, 378, 379, 380, 381, 382, 383, 384,
    480, 481, 482, 483, 484, 485, 486, 487, 488,
    638, 639, 640, 641, 642, 643, 644, 645, 646,
    716, 717, 718,
    785, 786, 787, 788, 789, 790, 791, 792,
    888, 889, 890, 891, 892, 894, 895, 896, 897, 898,
    1001, 1002, 1003, 1004, 1007, 1008,
    1020, 1021, 1022, 1023, 1024, 1025,
]

# Active games exist only in memory.
# A bot restart clears this dictionary.
active_games = {}

# Prevents repeated Start Game clicks while a game is being created.
starting_games = set()


# ---------------------------------------------------------
# EMBED HELPERS
# ---------------------------------------------------------

def make_embed(description, title=None, color=None):
    return discord.Embed(
        title=title,
        description=description,
        color=color or discord.Color.blurple(),
    )


async def send_error(interaction, description):
    embed = make_embed(
        description,
        title="Unable to Continue",
        color=discord.Color.red(),
    )

    if interaction.response.is_done():
        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )


# ---------------------------------------------------------
# RESULT HISTORY (completed games only)
# ---------------------------------------------------------

CREATE_RESULTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS deal_or_no_deal_results (
    game_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    wager_amount BIGINT NOT NULL,
    case_chosen INTEGER NOT NULL,
    final_case INTEGER NOT NULL,
    prize BIGINT NOT NULL,
    legendary TEXT NOT NULL CHECK (legendary IN ('yes', 'no')),
    created_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


async def record_result(conn, user_id, guild_id, case_chosen, final_case, prize, legendary):
    await conn.execute(
        """
        INSERT INTO deal_or_no_deal_results (
            user_id, guild_id, wager_amount, case_chosen,
            final_case, prize, legendary
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        user_id,
        guild_id,
        ENTRY_FEE,
        case_chosen,
        final_case,
        prize,
        "yes" if legendary else "no",
    )


# ---------------------------------------------------------
# PRIZE HELPERS
# ---------------------------------------------------------

def prize_label(prize):
    if prize["type"] == "legendary":
        return "Legendary Pokémon"

    return f"{prize['amount']:,} coins"


def prize_value(prize):
    if prize["type"] == "legendary":
        return LEGENDARY_OFFER_VALUE

    return prize["amount"]


def new_state(legendary):
    prizes = [
        {"type": "coins", "amount": amount}
        for amount in COIN_PRIZES
    ]

    if legendary:
        prizes.append({"type": "legendary"})
    else:
        prizes.append({
            "type": "coins",
            "amount": FULL_COLLECTION_REWARD,
        })

    indices = list(range(15))
    random.shuffle(indices)

    return {
        "phase": "choose_case",
        "prizes": prizes,
        "case_prizes": {
            str(number): index
            for number, index in zip(range(1, 16), indices)
        },
        "opened_cases": [],
        "selected_case": None,
        "round_index": 0,
        "round_remaining": ROUND_SIZES[0],
        "current_offer": None,
        "legendary": legendary,
        "final_case": None,
        "final_choice": None,
    }


def calculate_offer(state):
    opened = set(state["opened_cases"])

    remaining_cases = [
        number
        for number in range(1, 16)
        if number not in opened
    ]

    values = [
        prize_value(
            state["prizes"][
                int(state["case_prizes"][str(number)])
            ]
        )
        for number in remaining_cases
    ]

    mean_value = sum(values) / len(values)
    factor = OFFER_FACTORS[state["round_index"]]

    return max(
        1_000,
        int(round(mean_value * factor / 1_000)) * 1_000,
    )


# ---------------------------------------------------------
# CONFIRMATION VIEW
# ---------------------------------------------------------

class ConfirmationView(discord.ui.View):

    def __init__(
        self,
        bot,
        user_id,
        username,
        guild_id,
        legendary,
        test_mode=False,
    ):
        super().__init__(timeout=CONFIRMATION_TIMEOUT)

        self.bot = bot
        self.user_id = user_id
        self.username = username
        self.guild_id = guild_id
        self.legendary = legendary
        self.test_mode = test_mode
        self.message = None
        self.completed = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await send_error(
                interaction,
                "This confirmation belongs to another player.",
            )
            return False

        return True

    @discord.ui.button(
        label="Start Game",
        emoji=ROCKETLOGO,
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def start_button(self, interaction, button):
        if self.completed:
            await send_error(
                interaction,
                "This confirmation has already expired or been used.",
            )
            return

        if (
            self.user_id in active_games
            or self.user_id in starting_games
        ):
            await send_error(
                interaction,
                "You already have an active game. Finish it first.",
            )
            return

        starting_games.add(self.user_id)
        self.completed = True

        try:
            # Acknowledge the click before accessing the database.
            await interaction.response.defer()

            # Deduct the entry fee atomically.
            async with self.bot.db.acquire() as conn:
                async with conn.transaction():
                    balance = await conn.fetchval(
                        """
                        SELECT coin_balance
                        FROM users
                        WHERE user_id = $1
                          AND guild_id = $2
                        FOR UPDATE
                        """,
                        self.user_id,
                        self.guild_id,
                    )

                    if balance is None:
                        raise ValueError("account")

                    if balance < ENTRY_FEE:
                        raise ValueError("funds")

                    await conn.execute(
                        """
                        UPDATE users
                        SET coin_balance = coin_balance - $1
                        WHERE user_id = $2
                          AND guild_id = $3
                        """,
                        ENTRY_FEE,
                        self.user_id,
                        self.guild_id,
                    )

            state = new_state(self.legendary)
            state["test_mode"] = self.test_mode

            game = DealView(
                self.bot,
                self.user_id,
                self.username,
                self.guild_id,
                state,
            )

            active_games[self.user_id] = game

            try:
                await interaction.message.edit(
                    embed=game.embed(
                        (
                            f"Your **{ENTRY_FEE:,}-coin** entry fee "
                            "has been paid. Choose your case to begin."
                        )
                    ),
                    view=game,
                )

                game.message = interaction.message
                await game.send_side_message(
                    embed=make_embed("**Select your case to begin.**")
                )

            except Exception:
                active_games.pop(self.user_id, None)
                game.completed = True

                # If the game board cannot be created, refund the fee.
                async with self.bot.db.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE users
                        SET coin_balance = coin_balance + $1
                        WHERE user_id = $2
                          AND guild_id = $3
                        """,
                        ENTRY_FEE,
                        self.user_id,
                        self.guild_id,
                    )

                raise

        except ValueError as exc:
            if str(exc) == "funds":
                message = (
                    f"You need **{ENTRY_FEE:,} coins** to play, "
                    "but your current balance is too low."
                )
            else:
                message = "Your server account could not be found."

            try:
                await interaction.message.edit(
                    embed=make_embed(
                        message,
                        title="Unable to Start",
                        color=discord.Color.red(),
                    ),
                    view=None,
                )
            except discord.HTTPException:
                pass

        except Exception:
            try:
                await interaction.message.edit(
                    embed=make_embed(
                        (
                            "An error prevented the game from starting. "
                            "Please try again."
                        ),
                        title="Game Error",
                        color=discord.Color.red(),
                    ),
                    view=None,
                )
            except discord.HTTPException:
                pass

            raise

        finally:
            starting_games.discard(self.user_id)

    @discord.ui.button(
        label="Cancel Game",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def cancel_button(self, interaction, button):
        if self.completed:
            await send_error(
                interaction,
                "This confirmation has already expired or been used.",
            )
            return

        self.completed = True
        self.stop()

        await interaction.response.edit_message(
            embed=make_embed(
                "No coins were deducted.",
                title="Game Cancelled",
                color=discord.Color.red(),
            ),
            view=None,
        )

    async def on_timeout(self):
        if self.completed:
            return

        self.completed = True

        if self.message:
            try:
                await self.message.edit(
                    embed=make_embed(
                        (
                            "The game was not started, "
                            "and no coins were deducted."
                        ),
                        title="Confirmation Expired",
                        color=discord.Color.dark_grey(),
                    ),
                    view=None,
                )
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                pass


# ---------------------------------------------------------
# GAME VIEW
# ---------------------------------------------------------

class DealView(discord.ui.View):

    def __init__(
        self,
        bot,
        user_id,
        username,
        guild_id,
        state,
    ):
        super().__init__(timeout=TIMEOUT_SECONDS)

        self.bot = bot
        self.user_id = user_id
        self.username = username
        self.guild_id = guild_id
        self.state = state

        self.message = None
        self.side_messages = []
        self.completed = False

        self.rebuild()

    # -----------------------------------------------------
    # MAIN EMBED
    # -----------------------------------------------------

    def embed(self, note=None, color=None):
        state = self.state

        embed = discord.Embed(
            title=f"{GIOVANNI} Giovanni's Deal or No Deal",
            description=None,
            color=color or discord.Color.blurple(),
        )

        eliminated = {
            int(state["case_prizes"][str(number)])
            for number in state["opened_cases"]
        }

        board = []

        for index, prize in enumerate(state["prizes"]):
            text = prize_label(prize)

            if index in eliminated:
                text = f"~~{text}~~"

            board.append(f"• {text}")

        embed.add_field(
            name="💰 Prize Board",
            value="\n".join(board[:8]),
            inline=True,
        )

        embed.add_field(
            name="💰 Prize Board",
            value="\n".join(board[8:]),
            inline=True,
        )

        if state["selected_case"]:
            embed.add_field(
                name="🔒 Your Case",
                value=(
                    f"Case **{state['selected_case']}** "
                    "is reserved for you."
                ),
                inline=False,
            )

        # Prompts, updates, and reveals are sent in separate embeds.
        # Keep only the prize board and the player's reserved case here.

        return embed

    # -----------------------------------------------------
    # SIDE MESSAGE HELPERS
    # -----------------------------------------------------

    async def clear_side_messages(self):
        messages = self.side_messages[:]
        self.side_messages.clear()

        for message in messages:
            try:
                await message.delete()
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                # Deletion failures must not interrupt gameplay.
                pass

    async def delete_side_message(self, message):
        if message is None:
            return

        if message in self.side_messages:
            self.side_messages.remove(message)

        try:
            await message.delete()
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass

    async def send_side_message(self, content=None, embed=None):
        if not self.message:
            return None

        # All side messages are embeds, including text-only messages.
        if embed is None and content is not None:
            embed = make_embed(content)

        if embed is None:
            return None

        try:
            message = await self.message.channel.send(embed=embed)
            self.side_messages.append(message)
            return message

        except (
            discord.Forbidden,
            discord.HTTPException,
        ):
            # The game continues even if Discord rejects the message.
            return None

    # -----------------------------------------------------
    # BUTTONS
    # -----------------------------------------------------

    def rebuild(self):
        self.clear_items()

        state = self.state
        opened = set(state["opened_cases"])

        for number in range(1, 16):
            selected = number == state["selected_case"]

            disabled = (
                self.completed
                or state["phase"] in (
                    "offer",
                    "finale",
                    "completed",
                    "forfeited",
                )
                or number in opened
                or selected
            )

            style = (
                discord.ButtonStyle.success
                if selected
                else discord.ButtonStyle.secondary
            )

            self.add_item(
                CaseButton(number, disabled, style)
            )

        if state["phase"] == "offer" and not self.completed:
            self.add_item(DealButton())
            self.add_item(NoDealButton())

        elif state["phase"] == "finale" and not self.completed:
            self.add_item(KeepButton())
            self.add_item(SwitchButton())

    async def check_player(self, interaction):
        if interaction.user.id != self.user_id:
            await send_error(
                interaction,
                "This game belongs to another player.",
            )
            return False

        if self.completed:
            await send_error(
                interaction,
                "This game has already ended.",
            )
            return False

        return True

    async def update_board(self, interaction, note=None, color=None):
        self.rebuild()

        await interaction.response.edit_message(
            embed=self.embed(note, color),
            view=self,
        )

    # -----------------------------------------------------
    # CASE SELECTION / REVEAL
    # -----------------------------------------------------

    async def choose_or_open(self, interaction, number):
        if not await self.check_player(interaction):
            return

        state = self.state
        phase = state["phase"]

        if phase == "choose_case":
            await self.clear_side_messages()

            state["selected_case"] = number

            # Test mode guarantees the held case contains the Legendary.
            # All other game rules, offers and database awards stay the same.
            if state.get("test_mode"):
                legendary_index = next(
                    i for i, prize in enumerate(state["prizes"])
                    if prize["type"] == "legendary"
                )
                held_index = state["case_prizes"][str(number)]
                legendary_case = next(
                    case for case, index in state["case_prizes"].items()
                    if index == legendary_index
                )
                state["case_prizes"][str(number)] = legendary_index
                state["case_prizes"][legendary_case] = held_index

            state["phase"] = "opening"

            await self.update_board(
                interaction,
                (
                    f"You selected case **{number}**. "
                    "It will remain sealed until the finale."
                ),
            )

            await self.send_side_message(
                embed=make_embed(
                    f"**Select {state['round_remaining']} cases to open.**"
                )
            )
            return

        if phase != "opening":
            await send_error(
                interaction,
                "You cannot select a case at this stage.",
            )
            return

        if (
            number == state["selected_case"]
            or number in state["opened_cases"]
        ):
            await send_error(
                interaction,
                "That case is unavailable.",
            )
            return

        await self.clear_side_messages()

        prize = state["prizes"][
            int(state["case_prizes"][str(number)])
        ]

        state["opened_cases"].append(number)
        state["round_remaining"] -= 1

        offer_ready = state["round_remaining"] == 0

        if prize["type"] == "legendary":
            reveal_text = (
                f"{POKEBALL} **Case {number} opened!**\n\n"
                "It contained the **Legendary Pokémon** prize. "
                "That prize has been eliminated."
            )
        else:
            reveal_text = (
                f"{POKEBALL} **Case {number} opened!**\n\n"
                f"It contained **{prize['amount']:,} coins**. "
                "That prize has been eliminated."
            )

        if offer_ready:
            reveal_text += "\n\nThat was the last case in this round."
        else:
            reveal_text += "\n\n**Select another case to open.**"

        reveal_embed = make_embed(
            reveal_text,
            color=discord.Color.blurple(),
        )

        if offer_ready:
            state["current_offer"] = calculate_offer(state)
            state["phase"] = "offer"

        # The main board is edited in place.
        await self.update_board(interaction)

        # The case reveal is a separate embedded message.
        reveal_message = await self.send_side_message(
            embed=reveal_embed
        )

        if not offer_ready:
            return

        # Keep the final reveal visible for three seconds.
        await asyncio.sleep(3)
        await self.delete_side_message(reveal_message)

        # Giovanni's dramatic phone-call announcement.
        calling_embed = make_embed(
            f"{GIOVANNI} **Giovanni is calling ☎️.....**",
            color=discord.Color.dark_red(),
        )

        calling_message = await self.send_side_message(
            embed=calling_embed
        )

        await asyncio.sleep(3)
        await self.delete_side_message(calling_message)

        # Send Giovanni's actual offer as a separate embedded message.
        offer_embed = discord.Embed(
            title=f"{GIOVANNI} Giovanni's Offer",
            description=(
                f"{ROCKETLOGO} **Giovanni offered you "
                f"{state['current_offer']:,} coins!**\n\n"
                "Will you accept his offer, or risk it all?"
            ),
            color=discord.Color.gold(),
        )

        offer_embed.set_footer(
            text="Choose Deal or No Deal on the game board."
        )

        await self.send_side_message(embed=offer_embed)

    # -----------------------------------------------------
    # DEAL
    # -----------------------------------------------------

    async def deal(self, interaction):
        if not await self.check_player(interaction):
            return

        if self.state["phase"] != "offer":
            await send_error(
                interaction,
                "There is no active offer.",
            )
            return

        await self.clear_side_messages()

        amount = int(self.state["current_offer"])
        self.state["phase"] = "completed"

        async with self.bot.db.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE users
                    SET coin_balance = coin_balance + $1
                    WHERE user_id = $2
                      AND guild_id = $3
                    """,
                    amount,
                    self.user_id,
                    self.guild_id,
                )
                await record_result(
                    conn,
                    self.user_id,
                    self.guild_id,
                    self.state["selected_case"],
                    self.state["selected_case"],
                    amount,
                    False,
                )

        self.finish_local()

        await interaction.response.edit_message(
            embed=self.embed(
                f"You accepted Giovanni's offer and won "
                f"**{amount:,} coins**!",
                discord.Color.green(),
            ),
            view=self,
        )

        accepted_embed = make_embed(
            (
                f"{GIOVANNI} **You accepted Giovanni's offer "
                f"of {amount:,} coins!**\n\n"
                "The winnings have been added to your balance."
            ),
            color=discord.Color.green(),
        )

        await self.send_side_message(embed=accepted_embed)

    # -----------------------------------------------------
    # NO DEAL
    # -----------------------------------------------------

    async def no_deal(self, interaction):
        if not await self.check_player(interaction):
            return

        state = self.state

        if state["phase"] != "offer":
            await send_error(
                interaction,
                "There is no active offer.",
            )
            return

        # Delete Giovanni's previous offer message.
        await self.clear_side_messages()

        if state["round_index"] == len(ROUND_SIZES) - 1:
            remaining = [
                number
                for number in range(1, 16)
                if number not in state["opened_cases"]
            ]

            if len(remaining) != 2:
                await send_error(
                    interaction,
                    (
                        "Game state error. "
                        "Please contact an administrator."
                    ),
                )
                return

            state["final_case"] = next(
                number for number in remaining
                if number != state["selected_case"]
            )

            state["phase"] = "finale"

            note = (
                "You rejected Giovanni's final offer. "
                "Keep your case or switch."
            )

            message_text = (
                f"{GIOVANNI} **Giovanni is not happy with your decision!**\n\n"
                f"Choose to keep case **{state['selected_case']}** "
                f"or switch to case **{state['final_case']}**."
            )

        else:
            state["round_index"] += 1
            state["round_remaining"] = ROUND_SIZES[
                state["round_index"]
            ]
            state["current_offer"] = None
            state["phase"] = "opening"

            note = (
                f"No Deal! Open **{state['round_remaining']}** "
                f"cases in round {state['round_index'] + 1}."
            )

            message_text = (
                f"{GIOVANNI} **Giovanni is not happy with your decision!**\n\n"
                f"Select **{state['round_remaining']} more cases** "
                "to open."
            )

        await self.update_board(interaction, note)

        await self.send_side_message(
            embed=make_embed(
                message_text,
                color=discord.Color.dark_red(),
            )
        )

    # -----------------------------------------------------
    # FINALE / SWITCH CASE
    # -----------------------------------------------------

    async def final_choice(self, interaction, switch):
        if not await self.check_player(interaction):
            return

        state = self.state

        if state["phase"] != "finale":
            await send_error(
                interaction,
                "The finale is not ready.",
            )
            return

        await self.clear_side_messages()

        original = state["selected_case"]
        other = state["final_case"]
        chosen = other if switch else original

        # In test mode, either finale choice wins the Legendary.
        if state.get("test_mode") and switch:
            state["case_prizes"][str(original)], state["case_prizes"][str(other)] = (
                state["case_prizes"][str(other)],
                state["case_prizes"][str(original)],
            )

        original_prize = state["prizes"][
            int(state["case_prizes"][str(original)])
        ]
        other_prize = state["prizes"][
            int(state["case_prizes"][str(other)])
        ]

        winner = other_prize if switch else original_prize
        image_url = None

        async with self.bot.db.acquire() as conn:
            async with conn.transaction():

                if winner["type"] == "legendary":
                    pokemon = state["legendary"]

                    existing_quantity = await conn.fetchval(
                        """
                        SELECT quantity
                        FROM user_pokemon
                        WHERE user_id = $1
                          AND guild_id = $2
                          AND pokedex_id = $3
                        FOR UPDATE
                        """,
                        self.user_id,
                        self.guild_id,
                        pokemon["pokedex_id"],
                    )

                    if existing_quantity and existing_quantity > 0:
                        # Never award a duplicate Legendary.
                        amount = FULL_COLLECTION_REWARD

                        await conn.execute(
                            """
                            UPDATE users
                            SET coin_balance = coin_balance + $1
                            WHERE user_id = $2
                              AND guild_id = $3
                            """,
                            amount,
                            self.user_id,
                            self.guild_id,
                        )

                        won_text = (
                            f"You already own **{pokemon['pokemon_name']}**, "
                            f"so you received **{amount:,} coins** instead."
                        )

                    else:
                        await conn.execute(
                            """
                            INSERT INTO user_pokemon (
                                user_id,
                                username,
                                guild_id,
                                pokedex_id,
                                pokemon_name,
                                pokemon_region,
                                quantity
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, 1)
                            ON CONFLICT (user_id, guild_id, pokedex_id)
                            DO UPDATE SET
                                quantity = GREATEST(
                                    user_pokemon.quantity, 1
                                ),
                                username = EXCLUDED.username,
                                pokemon_name = EXCLUDED.pokemon_name,
                                pokemon_region = EXCLUDED.pokemon_region
                            """,
                            self.user_id,
                            self.username,
                            self.guild_id,
                            pokemon["pokedex_id"],
                            pokemon["pokemon_name"],
                            pokemon["pokemon_region"],
                        )

                        won_text = (
                            f"🎉 You won **{pokemon['pokemon_name']}** "
                            f"({pokemon['pokemon_region']})!"
                        )

                        image_url = pokemon.get("pokemon_image")

                else:
                    amount = int(winner["amount"])

                    await conn.execute(
                        """
                        UPDATE users
                        SET coin_balance = coin_balance + $1
                        WHERE user_id = $2
                          AND guild_id = $3
                        """,
                        amount,
                        self.user_id,
                        self.guild_id,
                    )

                    won_text = f"🪙 You won **{amount:,} coins**!"

                await record_result(
                    conn,
                    self.user_id,
                    self.guild_id,
                    original,
                    chosen,
                    LEGENDARY_OFFER_VALUE if winner["type"] == "legendary" else int(winner["amount"]),
                    winner["type"] == "legendary",
                )

                state["phase"] = "completed"
                state["final_choice"] = "switch" if switch else "keep"

        self.finish_local()

        action = "switched to" if switch else "kept"

        result = (
            f"You {action} case **{chosen}**.\n\n"
            f"Original case **{original}** contained "
            f"**{prize_label(original_prize)}**.\n"
            f"Other case **{other}** contained "
            f"**{prize_label(other_prize)}**.\n\n"
            f"{won_text}"
        )

        # Leave the main board as the completed game board.
        # The final case reveal and reward are a separate message.
        await interaction.response.edit_message(
            embed=self.embed("Game completed!", discord.Color.green()),
            view=self,
        )

        reveal_embed = make_embed(
            result,
            title="Final Case Reveal",
            color=discord.Color.green(),
        )

        if winner["type"] == "legendary" and image_url:
            reveal_embed.set_thumbnail(url=image_url)

        await self.send_side_message(embed=reveal_embed)

    # -----------------------------------------------------
    # CLEANUP / TIMEOUT
    # -----------------------------------------------------

    def finish_local(self):
        self.completed = True
        active_games.pop(self.user_id, None)
        self.stop()
        self.rebuild()

    async def on_timeout(self):
        if self.completed:
            return

        self.state["phase"] = "forfeited"
        self.finish_local()

        await self.clear_side_messages()

        if self.message:
            try:
                await self.message.edit(
                    embed=self.embed(
                        (
                            "Game forfeited due to inactivity. "
                            "The entry fee is not refunded."
                        ),
                        discord.Color.red(),
                    ),
                    view=self,
                )
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                pass


# ---------------------------------------------------------
# BUTTON CLASSES
# ---------------------------------------------------------

class CaseButton(discord.ui.Button):

    def __init__(self, number, disabled, style):
        super().__init__(
            label=str(number),
            emoji=POKEBALL,
            row=(number - 1) // 5,
            disabled=disabled,
            style=style,
        )

        self.number = number

    async def callback(self, interaction):
        await self.view.choose_or_open(interaction, self.number)


class DealButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label="Deal",
            emoji="🤝",
            style=discord.ButtonStyle.success,
            row=3,
        )

    async def callback(self, interaction):
        await self.view.deal(interaction)


class NoDealButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label="No Deal",
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            row=3,
        )

    async def callback(self, interaction):
        await self.view.no_deal(interaction)


class KeepButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label="Keep My Case",
            emoji="🔒",
            style=discord.ButtonStyle.success,
            row=3,
        )

    async def callback(self, interaction):
        await self.view.final_choice(interaction, False)


class SwitchButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label="Switch Case",
            emoji="🔄",
            style=discord.ButtonStyle.primary,
            row=3,
        )

    async def callback(self, interaction):
        await self.view.final_choice(interaction, True)


# ---------------------------------------------------------
# SLASH COMMAND
# ---------------------------------------------------------

@app_commands.command(
    name="dealornodeal",
    description="Play Giovanni's Pokémon Deal or No Deal for 50,000 coins.",
)
async def dealornodeal(interaction: discord.Interaction):

    if interaction.guild is None:
        await interaction.response.send_message(
            embed=make_embed(
                "Play this game in a server.",
                title="Server Only",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )
        return

    user_id = interaction.user.id
    guild_id = interaction.guild.id

    if user_id in active_games or user_id in starting_games:
        await interaction.response.send_message(
            embed=make_embed(
                "You already have an active game. Finish it first.",
                title="Game Already Active",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )
        return

    async with interaction.client.db.acquire() as conn:
        await conn.execute(CREATE_RESULTS_TABLE_SQL)
        pokemon_rows = await conn.fetch(
            """
            SELECT cd_pokemon_id,
                   pokedex_id,
                   pokemon_name,
                   pokemon_region,
                   pokemon_image
            FROM cd_pokemon
            WHERE cd_pokemon_id = ANY($1::int[])
            """,
            LEGENDARY_IDS,
        )

        owned_rows = await conn.fetch(
            """
            SELECT DISTINCT p.cd_pokemon_id
            FROM user_pokemon up
            JOIN cd_pokemon p
              ON p.pokedex_id = up.pokedex_id
            WHERE up.user_id = $1
              AND up.guild_id = $2
              AND p.cd_pokemon_id = ANY($3::int[])
              AND COALESCE(up.quantity, 0) > 0
            """,
            user_id,
            guild_id,
            LEGENDARY_IDS,
        )

        balance = await conn.fetchval(
            """
            SELECT coin_balance
            FROM users
            WHERE user_id = $1
              AND guild_id = $2
            """,
            user_id,
            guild_id,
        )

    if not pokemon_rows:
        await interaction.response.send_message(
            embed=make_embed(
                "No configured Legendary IDs were found in `cd_pokemon`.",
                title="Legendary Data Missing",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )
        return

    if balance is None:
        await interaction.response.send_message(
            embed=make_embed(
                "Your server account was not found in `users`.",
                title="Account Not Found",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )
        return

    if balance < ENTRY_FEE:
        await interaction.response.send_message(
            embed=make_embed(
                (
                    f"This game costs **{ENTRY_FEE:,} coins**; "
                    f"your balance is **{balance:,} coins**."
                ),
                title="Not Enough Coins",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )
        return

    owned_ids = {
        row["cd_pokemon_id"]
        for row in owned_rows
    }

    eligible = [
        row for row in pokemon_rows
        if row["cd_pokemon_id"] not in owned_ids
    ]

    if TEST_MODE and not eligible:
        await send_error(
            interaction,
            "Test mode requires at least one Legendary Pokémon you do not own.",
        )
        return

    # Every eligible Legendary has an equal chance of selection.
    selected = random.choice(eligible) if eligible else None

    legendary = None

    if selected:
        legendary = {
            "cd_pokemon_id": selected["cd_pokemon_id"],
            "pokedex_id": selected["pokedex_id"],
            "pokemon_name": selected["pokemon_name"],
            "pokemon_region": selected["pokemon_region"],
            "pokemon_image": selected["pokemon_image"],
        }

    embed = discord.Embed(
        title=f"{GIOVANNI} Giovanni's Deal or No Deal",
        description=(
            f"Ready to risk **{ENTRY_FEE:,} coins**?\n\n"
            "Choose **Start Game** to pay the entry fee and begin.\n"
            "Choose **Cancel Game** if you change your mind.\n\n"
            "Your entry fee is not refunded if you start a game "
            "and later forfeit it."
        ),
        color=discord.Color.gold(),
    )

    if TEST_MODE:
        embed.add_field(
            name="🧪 Legendary Test Mode",
            value=(
                "Your selected case will contain the Legendary Pokémon. "
                "Reject every offer; either finale choice wins the Legendary. "
                "The normal entry fee and real Pokémon award still apply."
            ),
            inline=False,
        )


    view = ConfirmationView(
        interaction.client,
        user_id,
        interaction.user.name,
        guild_id,
        legendary,
        test_mode=TEST_MODE,
    )

    await interaction.response.send_message(
        embed=embed,
        view=view,
    )

    view.message = await interaction.original_response()


# ---------------------------------------------------------
# EXTENSION SETUP
# ---------------------------------------------------------

async def setup(bot):
    # Active game state remains in memory; completed results are logged in PostgreSQL.
    bot.tree.add_command(dealornodeal)
