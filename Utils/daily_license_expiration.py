import asyncio
import datetime

async def get_exempt_guilds(bot):
    """Returns a set of guild_ids that should NEVER be deactivated."""
    async with bot.db.acquire() as conn:
        rows = await conn.fetch("""
            SELECT guild_id
            FROM license_free_guilds
            WHERE expiration_date IS NULL
               OR expiration_date > NOW()
        """)

    return {row["guild_id"] for row in rows}


async def expire_licenses(bot):
    """Checks all subscriptions and disables expired licenses, except exempt guilds."""
    exempt = await get_exempt_guilds(bot)

    async with bot.db.acquire() as conn:
        # Find expired subscriptions
        expired = await conn.fetch("""
            SELECT subscription_id
            FROM subscriptions
            WHERE current_period_end < NOW()
        """)

        for row in expired:
            sub_id = row["subscription_id"]

            # Deactivate all guilds tied to this subscription EXCEPT exempt ones
            await conn.execute("""
                UPDATE guild_settings
                SET license_active = FALSE
                WHERE subscription_id = $1
                  AND guild_id NOT IN (SELECT UNNEST($2::BIGINT[]))
            """, sub_id, list(exempt))

            print(f"[LICENSE] Subscription {sub_id} expired → non-exempt guilds deactivated")


async def daily_license_expiration_task(bot):
    """Runs expire_licenses() once per day at 3 AM."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        now = datetime.datetime.now()

        # Run at 3 AM server time
        run_time = now.replace(hour=3, minute=0, second=0, microsecond=0)

        # If 3 AM already passed today, schedule for tomorrow
        if now > run_time:
            run_time += datetime.timedelta(days=1)

        sleep_seconds = (run_time - now).total_seconds()
        await asyncio.sleep(sleep_seconds)

        await expire_licenses(bot)
