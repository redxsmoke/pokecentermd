# pokemon_rewards.py
import random

# ---------------------------------------------------------
# WEIGHTED RANDOM REWARD GENERATOR
# ---------------------------------------------------------
def weighted_random_amount():
    weighted_table = [
        5, 5, 5, 5, 5, 5,
        10, 10, 10,
        20, 20,
        30,
        40,
        50
    ]
    return random.choice(weighted_table)

# ---------------------------------------------------------
# CONFIG FOR REWARD TYPES
# ---------------------------------------------------------
REWARD_INTERVALS = {
    "great_ball": {
        "interval": 25,
        "item_id": 2,
        "item_name": "Great Ball",
        "quantity_func": weighted_random_amount
    },
    "ultra_ball": {
        "interval": 75,
        "item_id": 3,
        "item_name": "Ultra Ball",
        "quantity_func": weighted_random_amount
    }
}

# ---------------------------------------------------------
# MAIN REWARD HANDLER
# ---------------------------------------------------------
async def process_catch_rewards(bot, interaction):
    """
    Called after a successful catch.
    Checks milestones, gives rewards, returns reward messages.
    """

    async with bot.db.acquire() as conn:

        # Total Pokémon caught (including duplicates)
        total_caught_all = await conn.fetchval("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM user_pokemon
            WHERE user_id = $1 AND guild_id = $2
        """, interaction.user.id, interaction.guild.id)

        reward_messages = []

        # Loop through configured rewards
        for key, reward in REWARD_INTERVALS.items():

            interval = reward["interval"]
            item_id = reward["item_id"]
            item_name = reward["item_name"]
            quantity_func = reward["quantity_func"]

            # Check milestone
            if total_caught_all % interval == 0:

                amount = quantity_func()

                # Update inventory
                await conn.execute("""
                    UPDATE user_pokemon_catch_items
                    SET quantity = quantity + $1
                    WHERE user_id = $2 AND guild_id = $3 AND item_id = $4
                """, amount, interaction.user.id, interaction.guild.id, item_id)

                # Fetch emoji
                emoji = await conn.fetchrow("""
                    SELECT emoji_name, emoji_id
                    FROM catch_pokemon_items
                    WHERE item_id = $1
                """, item_id)

                reward_messages.append(
                    f"You found **{amount}** {item_name}s "
                    f"<:{emoji['emoji_name']}:{emoji['emoji_id']}>!"
                )

        return reward_messages
