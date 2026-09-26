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
    shipping_cost: float,
    subtotal: float,
    reward
) -> Dict[str, Any]:
    """
    Applies ONLY the reward selected by the user.
    """

    ok = await reward_is_eligible(
        db,
        reward,
        user_id,
        guild_id,
        user_level,
        order_total
    )

    if not ok:
        return {
            "final_total": round(order_total, 2),
            "final_shipping": round(shipping_cost, 2),
            "applied_reward": None
        }

    new_total, new_shipping = apply_reward_action(
        reward,
        order_total,
        shipping_cost,
        subtotal
    )

    # Track usage for ALL rewards (FIXED)
    await track_reward_usage(db, reward, user_id, guild_id)

    return {
        "final_total": round(new_total, 2),
        "final_shipping": round(new_shipping, 2),
        "applied_reward": reward
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
async def reward_is_eligible(db, reward, user_id, guild_id, user_level, order_total):
    reward_id = reward["reward_id"]
    category = reward.get("category")
    r_type = reward.get("type")

    required_level = reward.get("required_level")
    expiration_date = reward.get("expiration_date")
    max_uses = reward.get("max_uses")
    min_order_total = reward.get("min_order_total")

    # EXPIRATION (NULL = valid)
    if expiration_date:
        now = datetime.datetime.utcnow()
        if expiration_date < now:
            return False

    async with db.acquire() as conn:

        # LEVEL LOCKED (NULL = no requirement)
        if category == "level_locked":
            if required_level is not None and user_level < required_level:
                return False

        # LIMITED USE (NULL = unlimited)
        if category == "limited_use":
            if max_uses is not None:
                used = await conn.fetchval(
                    """
                    SELECT times_used
                    FROM user_rewards
                    WHERE user_id = $1 AND guild_id = $2 AND reward_id = $3
                    """,
                    user_id,
                    guild_id,
                    reward_id
                ) or 0

                if used >= max_uses:
                    return False

        # MIN ORDER TOTAL (NULL = no minimum)
        if min_order_total is not None and order_total < min_order_total:
            return False

    # FREE SHIPPING / PERCENT / FLAT OFF NULL VALUE FIX
    if r_type in ("percent_off", "flat_off") and reward.get("value") is None:
        reward["value"] = 0

    return True


# ---------------------------------------------------------
# APPLY REWARD ACTION
# ---------------------------------------------------------
def apply_reward_action(reward, order_total: float, shipping_cost: float, subtotal: float):
    reward_type = reward["type"]
    value = reward["value"]

    new_total = order_total
    new_shipping = shipping_cost

    if reward_type == "free_shipping":
        new_shipping = 0.0

    elif reward_type == "percent_off":
        pct = float(value) / 100.0
        discount = subtotal * pct
        new_total = max(subtotal - discount, 0.0)

    elif reward_type == "flat_off":
        discount = float(value)
        new_total = max(subtotal - discount, 0.0)

    return new_total, new_shipping


# ---------------------------------------------------------
# TRACK USAGE — FIXED TO TRACK ALL REWARDS
# ---------------------------------------------------------
async def track_reward_usage(db, reward, user_id: int, guild_id: int):
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
