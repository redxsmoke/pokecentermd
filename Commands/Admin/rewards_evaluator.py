import asyncpg
import discord
import datetime
from typing import Optional, Dict, Any


# ---------------------------------------------------------
# MAIN ENTRY POINT — APPLY REWARDS DURING CHECKOUT
# ---------------------------------------------------------
async def apply_rewards(
    db,
    guild_id: int,
    user_id: int,
    user_level: int,
    order_total: float,
    shipping_cost: float
) -> Dict[str, Any]:
    """
    Evaluates all active rewards for a guild and applies the best one.
    Returns:
        {
            "final_total": float,
            "final_shipping": float,
            "applied_reward": {...} or None
        }
    """

    rewards = await fetch_active_rewards(db, guild_id)

    best_reward = None
    best_new_total = order_total
    best_new_shipping = shipping_cost

    for reward in rewards:
        if not await reward_is_eligible(db, reward, user_id, guild_id, user_level, order_total):
            continue

        new_total, new_shipping = apply_reward_action(
            reward,
            order_total,
            shipping_cost
        )

        # Pick the reward that gives the lowest final total
        if new_total < best_new_total or (new_total == best_new_total and new_shipping < best_new_shipping):
            best_reward = reward
            best_new_total = new_total
            best_new_shipping = new_shipping

    # Track usage if needed
    if best_reward:
        await track_reward_usage(db, best_reward, user_id, guild_id)

    return {
        "final_total": round(best_new_total, 2),
        "final_shipping": round(best_new_shipping, 2),
        "applied_reward": best_reward
    }


# ---------------------------------------------------------
# FETCH ACTIVE REWARDS
# ---------------------------------------------------------
async def fetch_active_rewards(db, guild_id: int):
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT reward_id, guild_id, name, category, type, value,
                   required_level, expiration_date, max_uses, min_order_total
            FROM guild_rewards
            WHERE guild_id = $1 AND active = TRUE
            """,
            guild_id
        )

    return rows


# ---------------------------------------------------------
# CHECK ELIGIBILITY
# ---------------------------------------------------------
async def reward_is_eligible(
    db,
    reward,
    user_id: int,
    guild_id: int,
    user_level: int,
    order_total: float
) -> bool:

    category = reward["category"]

    # -----------------------------
    # Level Locked Rewards
    # -----------------------------
    if category == "level_locked":
        required_level = reward["required_level"]
        if required_level is None or user_level < required_level:
            return False

    # -----------------------------
    # Limited Time Promotion
    # -----------------------------
    elif category == "timed":
        expires_at = reward["expiration_date"]
        if expires_at is None:
            return False
        if expires_at.replace(tzinfo=datetime.timezone.utc) < discord.utils.utcnow():
            return False

    # -----------------------------
    # Limited Use Promotion
    # -----------------------------
    elif category == "limited_use":
        max_uses = reward["max_uses"]
        if max_uses is None:
            return False

        # Check usage count
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT times_used
                FROM user_rewards
                WHERE user_id = $1 AND guild_id = $2 AND reward_id = $3
                """,
                user_id,
                guild_id,
                reward["reward_id"]
            )

        if row and row["times_used"] >= max_uses:
            return False

    # -----------------------------
    # Order Minimum
    # -----------------------------
    min_order_total = reward["min_order_total"]
    if min_order_total is not None and order_total < float(min_order_total):
        return False

    return True


# ---------------------------------------------------------
# APPLY REWARD ACTION
# ---------------------------------------------------------
def apply_reward_action(reward, order_total: float, shipping_cost: float):
    reward_type = reward["type"]
    value = reward["value"]

    new_total = order_total
    new_shipping = shipping_cost

    if reward_type == "free_shipping":
        new_shipping = 0.0

    elif reward_type == "percent_off":
        pct = float(value) / 100.0
        discount = order_total * pct
        new_total = max(order_total - discount, 0.0)

    elif reward_type == "flat_off":
        discount = float(value)
        new_total = max(order_total - discount, 0.0)

    return new_total, new_shipping


# ---------------------------------------------------------
# TRACK USAGE FOR LIMITED USE PROMOTIONS
# ---------------------------------------------------------
async def track_reward_usage(db, reward, user_id: int, guild_id: int):
    if reward["category"] != "limited_use":
        return

    reward_id = reward["reward_id"]

    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_rewards (user_id, guild_id, reward_id, times_used, last_used_at)
            VALUES ($1, $2, $3, 1, NOW())
            ON CONFLICT (user_id, guild_id, reward_id)
            DO UPDATE SET
                times_used = user_rewards.times_used + 1,
                last_used_at = NOW()
            """,
            user_id,
            guild_id,
            reward_id
        )
