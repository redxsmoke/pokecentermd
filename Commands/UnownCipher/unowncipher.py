import discord
from discord import app_commands
from LevelManager.level_up_manager import LevelUpManager



# ---------------------------------------------------------
# SYMBOL MAP & HELPERS
# ---------------------------------------------------------
SYMBOL_MAP = {
    'A': '◆', 'B': '◇', 'C': '■', 'D': '□', 'E': '▲', 'F': '△', 'G': '▼',
    'H': '▽', 'I': '●', 'J': '○', 'K': '◐', 'L': '◑', 'M': '◒', 'N': '◓',
    'O': '◖', 'P': '◗', 'Q': '◘', 'R': '◙', 'S': '◢', 'T': '◣', 'U': '◤',
    'V': '◥', 'W': '⌑', 'X': '⌖', 'Y': '⌘', 'Z': '¤'
}

def encode_pokemon_name(name: str) -> str:
    cleaned = ''.join(ch for ch in name.upper() if ch.isalpha())
    return ''.join(SYMBOL_MAP[ch] for ch in cleaned)

def normalize_name(name: str) -> str:
    return ''.join(ch for ch in name.lower() if ch.isalpha())


# ---------------------------------------------------------
# MODAL FOR ANSWER INPUT
# ---------------------------------------------------------
class CipherAnswerModal(discord.ui.Modal, title="Unown Cipher Answer"):
    answer = discord.ui.TextInput(
        label="Your guess",
        placeholder="Type the Pokémon name",
        required=True
    )

    def __init__(self, correct_name: str, pokemon_image: str, view_ref, interaction):
        super().__init__()
        self.correct_name = correct_name
        self.pokemon_image = pokemon_image
        self.view_ref = view_ref
        self.interaction = interaction  # needed for DB access

    async def on_submit(self, interaction: discord.Interaction):
        user_answer = normalize_name(self.answer.value)
        correct = normalize_name(self.correct_name)

        # ---------------------------------------------------------
        # CORRECT ANSWER
        # ---------------------------------------------------------
        if user_answer == correct:

            # ---------------------------------------------------------
            # XP CALCULATION
            # ---------------------------------------------------------
            letters_only = ''.join(ch for ch in self.correct_name if ch.isalpha())
            xp_earned = 25 * len(letters_only)

            # ---------------------------------------------------------
            # UPDATE USERS TABLE (user_id)
            # ---------------------------------------------------------
            async with interaction.client.db.acquire() as conn:
                current_exp = await conn.fetchval(
                    """
                    SELECT exp
                    FROM users
                    WHERE user_id = $1 AND guild_id = $2
                    """,
                    interaction.user.id,
                    interaction.guild.id
                )

                if current_exp is None:
                    current_exp = 0

                new_exp = current_exp + xp_earned

                await conn.execute(
                    """
                    UPDATE users
                    SET exp = $1
                    WHERE user_id = $2 AND guild_id = $3
                    """,
                    new_exp,
                    interaction.user.id,
                    interaction.guild.id
                )

                # ---------------------------------------------------------
                # UPDATE LEADERBOARD TABLE
                # ---------------------------------------------------------
                await conn.execute(
                    """
                    INSERT INTO unown_cipher_leaders (user_id, guild_id, ciphers_solved)
                    VALUES ($1, $2, 1)
                    ON CONFLICT (user_id, guild_id)
                    DO UPDATE SET
                        ciphers_solved = unown_cipher_leaders.ciphers_solved + 1,
                        last_solved_date = NOW();
                    """,
                    interaction.user.id,
                    interaction.guild.id
                )

            # ---------------------------------------------------------
            # LEVEL UP CHECK
            # ---------------------------------------------------------
            from LevelManager.level_up_manager import LevelUpManager
            level_manager = LevelUpManager(interaction.client, interaction.client.db)

            await level_manager.check_level_up(
                user_id=interaction.user.id,
                new_xp=new_exp,
                channel=interaction.channel
            )

            # ---------------------------------------------------------
            # SUCCESS EMBED (THUMBNAIL FIXED)
            # ---------------------------------------------------------
            embed = discord.Embed(
                title="🎉 Correct!",
                description=(
                    f"You solved the cipher!\n\n"
                    f"The Pokémon was **{self.correct_name}**.\n\n"
                    f"**EXP Earned:** `{xp_earned}`"
                ),
                color=discord.Color.green()
            )

            # Thumbnail ALWAYS shows now because we send a NEW message
            if self.pokemon_image:
                embed.set_thumbnail(url=self.pokemon_image)

            # Disable button on original puzzle message
            for child in self.view_ref.children:
                child.disabled = True

            # ---------------------------------------------------------
            # FIX: Send a NEW message so Discord loads the thumbnail
            # ---------------------------------------------------------
            await interaction.response.send_message(embed=embed)

            # Update original puzzle message to disable button
            try:
                await interaction.message.edit(view=self.view_ref)
            except:
                pass

            return

        # ---------------------------------------------------------
        # INCORRECT ANSWER
        # ---------------------------------------------------------
        self.view_ref.attempts += 1

        # ---------------------------------------------------------
        # THIRD FAILED ATTEMPT → GAME OVER
        # ---------------------------------------------------------
        if self.view_ref.attempts >= 3:
            for child in self.view_ref.children:
                child.disabled = True

            embed = discord.Embed(
                title="❌ Game Over",
                description=(
                    f"You have used all **3 attempts**.\n\n"
                    f"The correct answer was **{self.correct_name}**."
                ),
                color=discord.Color.red()
            )

            await interaction.response.send_message(embed=embed, ephemeral=False)

            try:
                await interaction.message.edit(view=self.view_ref)
            except:
                pass

            return

        # ---------------------------------------------------------
        # ATTEMPTS 1 AND 2 → EPHEMERAL INCORRECT MESSAGE
        # ---------------------------------------------------------
        embed = discord.Embed(
            title="❌ Incorrect",
            description=(
                f"Your guess: `{self.answer.value}`\n\n"
                f"Attempts used: **{self.view_ref.attempts}/3**"
            ),
            color=discord.Color.orange()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------------------------------------------------------
# VIEW WITH SUBMIT BUTTON
# ---------------------------------------------------------
class CipherView(discord.ui.View):
    def __init__(self, correct_name: str, pokemon_image: str, interaction):
        super().__init__(timeout=900)
        self.correct_name = correct_name
        self.pokemon_image = pokemon_image
        self.interaction = interaction
        self.attempts = 0

    @discord.ui.button(label="Submit Answer", style=discord.ButtonStyle.primary)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            CipherAnswerModal(self.correct_name, self.pokemon_image, self, self.interaction)
        )


# ---------------------------------------------------------
# /unowncipher COMMAND
# ---------------------------------------------------------
@app_commands.command(
    name="unowncipher",
    description="Solve an Unown symbol cipher for a random Pokémon."
)
async def unowncipher(interaction: discord.Interaction):

    async with interaction.client.db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pokemon_name, pokemon_image
            FROM cd_pokemon
            ORDER BY RANDOM()
            LIMIT 1
            """
        )

    if not row:
        embed = discord.Embed(
            title="❌ Error",
            description="No Pokémon found in cd_pokemon.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    pokemon_name = row["pokemon_name"]
    pokemon_image = row["pokemon_image"]

    encoded = encode_pokemon_name(pokemon_name)
    spaced = " ".join(encoded)

    embed = discord.Embed(
        title="Unown Cipher Puzzle",
        color=discord.Color.purple()
    )

    embed.description = (
        "Decode the Pokémon name from the symbols.\n\n"
        "**Cipher:**\n"
        f"```\n{spaced}\n```"
        "\nUse the Unown legend below to map symbols → letters."
    )

    embed.set_image(
        url="https://cdn.discordapp.com/attachments/1540905804293607435/1556861555990073455/card.jpg"
    )

    view = CipherView(correct_name=pokemon_name, pokemon_image=pokemon_image, interaction=interaction)

    await interaction.response.send_message(
        embed=embed,
        view=view,
        ephemeral=False
    )


# ---------------------------------------------------------
# EXTENSION SETUP
# ---------------------------------------------------------
async def setup(bot):
    bot.tree.add_command(unowncipher)
