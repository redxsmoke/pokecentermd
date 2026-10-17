import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio

MAX_BERRIES_PER_ENCOUNTER = 5

POKEDRILL_BASE = "https://sprites.pokedrill.com/sprites/official"

# ---------------------------------------------------------
def build_progress_bar(current, total, length=30):
    if total == 0:
        return "No data"

    ratio = current / total
    filled = int(ratio * length)
    empty = length - filled

    return f"{'▰' * filled}{'▱' * empty}"


class CatchPokemon(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------------------------------------------------------
    # REGION COMPLETION CHECKER
    # ---------------------------------------------------------
    async def check_region_completion(self, interaction, region):
        async with self.bot.db.acquire() as conn:

            caught_unique = await conn.fetchval("""
                SELECT COUNT(DISTINCT pokedex_id)
                FROM user_pokemon
                WHERE user_id = $1
                AND LOWER(pokemon_region) = LOWER($2)
            """, interaction.user.id, region)

            region_total = await conn.fetchval("""
                SELECT COUNT(*)
                FROM cd_pokemon
                WHERE LOWER(pokemon_region) = LOWER($1)
            """, region)

        if caught_unique == region_total:
            badge_name = f"{region.title()} Master"

            async with self.bot.db.acquire() as conn:
                badge = await conn.fetchrow("""
                    SELECT badge_id, name, badge_url
                    FROM badges
                    WHERE LOWER(name) = LOWER($1)
                """, badge_name)

            if badge:
                await self.bot.badgedb.award_badge(
                    interaction.user.id,
                    badge["badge_id"],
                    interaction.guild.id
                )

                embed = discord.Embed(
                    title="🎉 Badge Awarded!",
                    description=f"{interaction.user.mention} earned the **{badge['name']}** badge!",
                    color=discord.Color.gold()
                )

                # Use badge_url instead of emoji
                embed.set_thumbnail(url=badge["badge_url"])

                await interaction.channel.send(embed=embed)

    @app_commands.command(
        name="catchpokemon",
        description="Encounter a random Pokémon and try to catch it!"
    )
    async def catchpokemon(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT pokedex_id, pokemon_name, catch_rate, pokemon_region
                FROM cd_pokemon
                ORDER BY RANDOM()
                LIMIT 1;
            """)

        if not row:
            embed = discord.Embed(
                title="❌ Error",
                description="No Pokémon found in the database.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # CHECK USER HAS ANY POKÉ BALLS (EMBEDDED ERROR)
        async with self.bot.db.acquire() as conn:
            ball_count = await conn.fetchval("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM user_pokemon_catch_items
                WHERE user_id = $1 AND guild_id = $2
            """, interaction.user.id, interaction.guild.id)

        if ball_count == 0:
            embed = discord.Embed(
                title="<:Pokeball1:1540418809939099818> No Poké Balls",
                description="You do not have any pokeballs, use **/daily** to get some",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        pokedex_id = row["pokedex_id"]
        pokemon_name = row["pokemon_name"].title()
        catch_rate = row["catch_rate"]
        pokemon_region = row["pokemon_region"]

        image_url = f"{POKEDRILL_BASE}/{pokedex_id}.png"

        embed = discord.Embed(
            title="Pokémon Encounter",
            description=f"A wild **{pokemon_name}** appeared!",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=image_url)

        view = EncounterView(
            bot=self.bot,
            pokemon_name=pokemon_name,
            image_url=image_url,
            catch_rate=catch_rate,
            pokedex_id=pokedex_id,
            pokemon_region=pokemon_region
        )

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class EncounterView(discord.ui.View):
    def __init__(self, bot, pokemon_name, image_url, catch_rate, pokedex_id, pokemon_region):
        super().__init__(timeout=60)
        self.bot = bot
        self.pokemon_name = pokemon_name.title()
        self.image_url = image_url
        self.catch_rate = catch_rate
        self.pokedex_id = pokedex_id
        self.pokemon_region = pokemon_region

    @discord.ui.button(label="Catch Pokémon", style=discord.ButtonStyle.success)
    async def catch(self, interaction: discord.Interaction, button: discord.ui.Button):

        embed = discord.Embed(
            title="🎯 Catch Attempt",
            description=f"Trying to catch **{self.pokemon_name}**...",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=self.image_url)

        view = CatchAttemptView(
            bot=self.bot,
            pokemon_name=self.pokemon_name,
            image_url=self.image_url,
            catch_rate=self.catch_rate,
            pokedex_id=self.pokedex_id,
            pokemon_region=self.pokemon_region
        )

        await view.build_ball_buttons(interaction)

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="Flee", style=discord.ButtonStyle.danger)
    async def flee(self, interaction: discord.Interaction, button: discord.ui.Button):

        embed = discord.Embed(
            title="🏃 You Fled",
            description=f"You fled from **{self.pokemon_name}**!",
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=self.image_url)

        await interaction.response.send_message(embed=embed, ephemeral=True)


class CatchAttemptView(discord.ui.View):
    def __init__(self, bot, pokemon_name, image_url, catch_rate, pokedex_id, pokemon_region, owner_id=None):
        super().__init__(timeout=120)
        self.bot = bot
        self.pokemon_name = pokemon_name.title()
        self.image_url = image_url
        self.catch_rate = catch_rate
        self.pokedex_id = pokedex_id
        self.pokemon_region = pokemon_region

        self.attempts = 0
        self.max_attempts = random.randint(2, 10)
        self.flee_chance = 0.10
        self.finished = False
        self.owner_id = owner_id
        self.berries_used = 0
        self.berry_bonus = 0
        self.action_lock = asyncio.Lock()

        self.miss_messages = [
            f"**{self.pokemon_name}** broke free!",
            f"**{self.pokemon_name}** broke free! Almost had it!",
            f"**{self.pokemon_name}** broke free! It appeared to be captured!",
            f"**{self.pokemon_name}** broke free! So close!"
        ]

    async def load_user_balls(self, interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("""
                SELECT i.item_id, i.item_name, i.catch_modifier, i.emoji_name, i.emoji_id, u.quantity
                FROM catch_pokemon_items i
                JOIN user_pokemon_catch_items u
                ON i.item_id = u.item_id
                WHERE u.user_id = $1 AND u.guild_id = $2
                ORDER BY i.item_id ASC
            """, interaction.user.id, interaction.guild.id)

        return rows

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is not None and interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⚠️ Not Your Encounter",
                    description="Only the trainer who started this encounter can use these items.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return False
        return True

    async def load_berry_count(self, interaction):
        async with self.bot.db.acquire() as conn:
            return await conn.fetchval("""
                SELECT COALESCE(ui.quantity, 0)
                FROM cd_items i
                LEFT JOIN user_items ui
                  ON ui.cd_item_id = i.cd_item_id
                 AND ui.user_id = $1 AND ui.guild_id = $2
                WHERE i.item_name = 'Razz Berry'
            """, interaction.user.id, interaction.guild.id) or 0

    async def load_berry_emoji(self):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT emoji_name, emoji_id
                FROM cd_items
                WHERE item_name = 'Razz Berry'
            """)
        if row and row["emoji_name"] and row["emoji_id"]:
            return discord.PartialEmoji(name=row["emoji_name"], id=int(row["emoji_id"]))
        return None

    async def build_ball_buttons(self, interaction):
        self.clear_items()
        balls = await self.load_user_balls(interaction)

        for ball in balls:
            if ball["quantity"] <= 0:
                continue

            button = discord.ui.Button(
                label=f"Throw {ball['item_name']} ({ball['quantity']})",
                style=discord.ButtonStyle.primary,
                row=0,
                emoji=discord.PartialEmoji(
                    name=ball["emoji_name"],
                    id=ball["emoji_id"]
                )
            )

            async def callback(inter, b=ball):
                await self.throw_ball(inter, b)

            button.callback = callback
            self.add_item(button)

        berry_count = await self.load_berry_count(interaction)
        berry_button = discord.ui.Button(
            label=f"Use Razz Berry ({berry_count}) • {self.berries_used}/{MAX_BERRIES_PER_ENCOUNTER}",
            style=discord.ButtonStyle.success,
            emoji=await self.load_berry_emoji(),
            row=1,
            disabled=(berry_count <= 0 or self.berries_used >= MAX_BERRIES_PER_ENCOUNTER or self.finished),
        )
        berry_button.callback = self.use_razz_berry
        self.add_item(berry_button)

    async def use_razz_berry(self, interaction: discord.Interaction):
        async with self.action_lock:
            if self.finished or self.berries_used >= MAX_BERRIES_PER_ENCOUNTER:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="⚠️ Berry Limit",
                        description="You cannot use any more Razz Berries in this encounter.",
                        color=discord.Color.orange(),
                    ), ephemeral=True,
                )
                return

            # Consume exactly one berry, only if it is still owned.
            async with self.bot.db.acquire() as conn:
                consumed = await conn.fetchval("""
                    UPDATE user_items
                    SET quantity = quantity - 1, updated_timestamp = NOW()
                    WHERE user_id = $1 AND guild_id = $2
                      AND cd_item_id = (
                          SELECT cd_item_id FROM cd_items WHERE item_name = 'Razz Berry'
                      )
                      AND quantity > 0
                    RETURNING quantity
                """, interaction.user.id, interaction.guild.id)

            if consumed is None:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="🍓 No Razz Berries",
                        description="You don't have any Razz Berries. Visit **/pokemart** to buy some.",
                        color=discord.Color.red(),
                    ), ephemeral=True,
                )
                return

            self.berries_used += 1
            self.berry_bonus = self.berries_used * 3
            await self.build_ball_buttons(interaction)
            embed = discord.Embed(
                title="🍓 Razz Berry Used!",
                description=(
                    f"You fed a Razz Berry to **{self.pokemon_name}**!\n"
                    f"Catch bonus: **+{self.berry_bonus} percentage points** "
                    f"({self.berries_used}/{MAX_BERRIES_PER_ENCOUNTER} Berries used).\n"
                    "The bonus applies to every remaining throw in this encounter."
                ),
                color=discord.Color.green(),
            )
            embed.set_thumbnail(url=self.image_url)
            await interaction.response.edit_message(embed=embed, view=self)

    async def throw_ball(self, interaction: discord.Interaction, ball):

        if self.finished:
            embed = discord.Embed(
                title="⚠️ Encounter Over",
                description="This encounter has already ended.",
                color=discord.Color.orange()
            )
            embed.set_thumbnail(url=self.image_url)
            await interaction.response.edit_message(embed=embed, view=None)
            return

        # Consume ball
        async with self.bot.db.acquire() as conn:
            remaining = await conn.fetchval("""
                UPDATE user_pokemon_catch_items
                SET quantity = quantity - 1
                WHERE user_id = $1 AND guild_id = $2 AND item_id = $3
                  AND quantity > 0
                RETURNING quantity
            """, interaction.user.id, interaction.guild.id, ball["item_id"])

        if remaining is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⚠️ No Poké Balls",
                    description="You no longer have that Poké Ball.",
                    color=discord.Color.red(),
                ), ephemeral=True,
            )
            return

        self.attempts += 1

        # Apply catch modifier
        final_rate = min(self.catch_rate + ball["catch_modifier"] + self.berry_bonus, 100)
        roll = random.randint(1, 100)

        # Successful catch
        if roll <= final_rate:

            # Insert Pokémon
            async with self.bot.db.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_pokemon (user_id, username, guild_id, pokedex_id, pokemon_name, pokemon_region, quantity)
                    VALUES ($1, $2, $3, $4, $5, $6, 1)
                    ON CONFLICT (user_id, guild_id, pokedex_id)
                    DO UPDATE SET quantity = user_pokemon.quantity + 1;
                """,
                interaction.user.id,
                interaction.user.name,
                interaction.guild.id,
                self.pokedex_id,
                self.pokemon_name,
                self.pokemon_region
                )

            # ⭐ Award +10 EXP
            async with self.bot.db.acquire() as conn:
                await conn.execute("""
                    UPDATE users
                    SET exp = exp + 10
                    WHERE user_id = $1 AND guild_id = $2
                """, interaction.user.id, interaction.guild.id)

            # ⭐ Fetch updated XP (THIS FIXES THE CRASH)
            async with self.bot.db.acquire() as conn:
                new_xp = await conn.fetchval("""
                    SELECT exp
                    FROM users
                    WHERE user_id = $1 AND guild_id = $2
                """, interaction.user.id, interaction.guild.id)

            # ⭐ LEVEL-UP CHECK
            await self.bot.level_up_manager.check_level_up(
                interaction.user.id,
                new_xp,
                interaction.channel
            )

            # Region completion check
            await self.bot.get_cog("CatchPokemon").check_region_completion(interaction, self.pokemon_region)

            # Fetch updated stats
            async with self.bot.db.acquire() as conn:
                caught_unique_region = await conn.fetchval("""
                    SELECT COUNT(DISTINCT pokedex_id)
                    FROM user_pokemon
                    WHERE user_id = $1
                    AND LOWER(pokemon_region) = LOWER($2)
                """, interaction.user.id, self.pokemon_region)

                region_total = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM cd_pokemon
                    WHERE LOWER(pokemon_region) = LOWER($1)
                """, self.pokemon_region)

                total_unique_all = await conn.fetchval("""
                    SELECT COUNT(DISTINCT pokedex_id)
                    FROM user_pokemon
                    WHERE user_id = $1 AND guild_id = $2
                """, interaction.user.id, interaction.guild.id)

                total_caught_all = await conn.fetchval("""
                    SELECT COALESCE(SUM(quantity), 0)
                    FROM user_pokemon
                    WHERE user_id = $1 AND guild_id = $2
                """, interaction.user.id, interaction.guild.id)

                total_pokedex_count = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM cd_pokemon
                """)

            progress_bar = build_progress_bar(caught_unique_region, region_total)
            progress_bar = f"{progress_bar}\u200B"

            embed = discord.Embed(
                title="🎉 Pokémon Caught!",
                description=(
                    f"**{self.pokemon_name}** was caught using a **{ball['item_name']}**!\n"
                    f"Attempts: **{self.attempts}**\n"
                    f"🍓 Razz Berries used: **{self.berries_used}** (+{self.berry_bonus} catch chance)\n"
                    f"⭐ **You earned 10 EXP!**\n\n"
                    f"**📊 {self.pokemon_region.title()} Progress — {caught_unique_region}/{region_total}**\n"
                    f"`{progress_bar}`\n\n"
                    f"**📈 Stats**\n"
                    f"• **Total Unique Pokémon Caught:** {total_unique_all} / {total_pokedex_count}\n"
                    f"• **Total Pokémon Caught:** {total_caught_all}"
                ),
                color=discord.Color.green()
            )

            self.finished = True
            await interaction.response.edit_message(embed=embed, view=None)

            # ---------------------------------------------------------
            # 🔥 Reward System
            # ---------------------------------------------------------
            from .pokemon_rewards_config import process_catch_rewards

            async with self.bot.db.acquire() as conn:
                await conn.execute("SELECT 1")

            reward_messages = await process_catch_rewards(self.bot, interaction)

            if reward_messages:
                reward_embed = discord.Embed(
                    title="🎁 Reward Unlocked!",
                    description="\n".join(reward_messages),
                    color=discord.Color.gold()
                )
                await interaction.followup.send(embed=reward_embed, ephemeral=True)

            return

        # Failed catch — flee check
        if random.random() < self.flee_chance:
            embed = discord.Embed(
                title="💨 Pokémon Fled!",
                description=f"**{self.pokemon_name}** fled after **{self.attempts}** attempts!",
                color=discord.Color.red()
            )
            embed.set_thumbnail(url=self.image_url)

            self.finished = True
            await interaction.response.edit_message(embed=embed, view=None)
            return

        # Missed — Pokémon stays
        miss_line = random.choice(self.miss_messages)

        embed = discord.Embed(
            title="❌ Missed!",
            description=miss_line,
            color=discord.Color.orange()
        )
        embed.set_thumbnail(url=self.image_url)

        if self.attempts >= self.max_attempts:
            embed = discord.Embed(
                title="💨 Pokémon Escaped!",
                description=f"**{self.pokemon_name}** escaped after resisting all attempts!",
                color=discord.Color.red()
            )
            embed.set_thumbnail(url=self.image_url)

            self.finished = True
            await interaction.response.edit_message(embed=embed, view=None)
            return

        # Refresh this same view so Berry bonuses, attempt count, and flee limit persist.
        if self.berries_used:
            embed.add_field(
                name="🍓 Razz Berry Bonus",
                value=f"+{self.berry_bonus} percentage points ({self.berries_used}/5 used)",
                inline=False,
            )
        await self.build_ball_buttons(interaction)
        await interaction.response.edit_message(embed=embed, view=self)



async def setup(bot):
    await bot.add_cog(CatchPokemon(bot))
