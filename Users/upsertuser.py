import asyncpg
from typing import Optional, List, Dict, Any


class BadgeDB:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # ---------------------------------------------------------
    # USERS TABLE HELPERS
    # ---------------------------------------------------------

    async def ensure_user_exists(self, user, guild_id: int) -> bool:
        """
        Inserts user if missing, updates profile if existing.
        Returns True if the user was newly created.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO users (user_id, username, global_name, avatar_url, guild_id)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    global_name = EXCLUDED.global_name,
                    avatar_url = EXCLUDED.avatar_url,
                    guild_id = EXCLUDED.guild_id,
                    last_seen_at = NOW()
                RETURNING created_at;
            """,
            user.id,
            user.display_name,
            user.global_name,
            str(user.display_avatar.url),
            guild_id
            )

            return row is not None

    async def update_last_seen(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE users
                SET last_seen_at = NOW()
                WHERE user_id = $1;
            """, user_id)

    async def get_user(self, user_id: int) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("""
                SELECT *
                FROM users
                WHERE user_id = $1;
            """, user_id)

    async def upsert_user_profile(self, user, guild_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE users
                SET username = $2,
                    global_name = $3,
                    avatar_url = $4,
                    guild_id = $5,
                    last_seen_at = NOW()
                WHERE user_id = $1;
            """,
            user.id,
            user.display_name,
            user.global_name,
            str(user.display_avatar.url),
            guild_id
            )

    # ---------------------------------------------------------
    # BADGES TABLE HELPERS
    # ---------------------------------------------------------

    async def get_badge_by_name(self, name: str) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("""
                SELECT *
                FROM badges
                WHERE LOWER(name) = LOWER($1);
            """, name)

    async def get_badge_by_id(self, badge_id: int) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("""
                SELECT *
                FROM badges
                WHERE badge_id = $1;
            """, badge_id)

    # ---------------------------------------------------------
    # USER_BADGES TABLE HELPERS
    # ---------------------------------------------------------

    async def award_badge(self, user_id: int, badge_id: int, guild_id: Optional[int] = None):
        """
        Awards a badge. guild_id = None for global badges.
        ON CONFLICT prevents duplicates.
        """
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_badges (user_id, badge_id, guild_id)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING;
            """, user_id, badge_id, guild_id)

    async def has_badge(self, user_id: int, badge_id: int, guild_id: Optional[int] = None) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 1
                FROM user_badges
                WHERE user_id = $1
                  AND badge_id = $2
                  AND (guild_id = $3 OR ($3 IS NULL AND guild_id IS NULL));
            """, user_id, badge_id, guild_id)
            return row is not None

    async def get_user_badges(self, user_id: int, guild_id: Optional[int]) -> List[asyncpg.Record]:
        """
        Returns global badges + guild-specific badges.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT b.badge_id, b.name, b.emoji, b.description, b.global
                FROM user_badges ub
                JOIN badges b ON b.badge_id = ub.badge_id
                WHERE ub.user_id = $1
                  AND (b.global = TRUE OR ub.guild_id = $2);
            """, user_id, guild_id)

    # ---------------------------------------------------------
    # FIRST PARTNER BADGE LOGIC
    # ---------------------------------------------------------

    async def auto_award_first_partner(self, user_id: int):
        """
        Awards the First Partner badge to the first 100 users.
        """
        async with self.pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users;")

            if total_users <= 100:
                badge = await conn.fetchrow("""
                    SELECT badge_id FROM badges
                    WHERE LOWER(name) = 'first partner';
                """)

                if badge:
                    await conn.execute("""
                        INSERT INTO user_badges (user_id, badge_id, guild_id)
                        VALUES ($1, $2, NULL)
                        ON CONFLICT DO NOTHING;
                    """, user_id, badge["badge_id"])
