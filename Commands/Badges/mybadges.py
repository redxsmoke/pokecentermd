import discord
from discord import app_commands
from discord.ext import commands

GALLERY_PAGE_SIZE = 6


class MyBadges(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def build_badge_pages(self, rows, first_partner_numbers, interaction: discord.Interaction):
        pages = []
        current_embeds = []

        for row in rows:
            guild_emoji = interaction.guild.get_emoji(row["emoji_id"]) if row["emoji_id"] else None
            emoji = f"{guild_emoji}" if guild_emoji else ""

            quantity = row["quantity"]

            # FIRST PARTNER BADGE
            if row["badge_id"] == 1:
                badge_number = first_partner_numbers[row["badge_award_id"]]
                display_name = f"{row['name']} (#{badge_number}/100)"

            # BUG CATCHER BADGE
            elif row["badge_id"] == 14:
                display_name = f"{row['name']} x{quantity}"

            # ALL OTHER BADGES
            else:
                display_name = f"{row['name']} x{quantity}"

            embed = discord.Embed(
                title=f"{emoji} {display_name}",
                description=row["description"],
                color=discord.Color.gold()
            )

            embed.add_field(
                name="Awarded",
                value=row["awarded_at"].strftime('%b %d, %Y'),
                inline=False
            )

            # Badge thumbnail (top-right)
            if row["badge_url"]:
                embed.set_thumbnail(url=row["badge_url"])

            current_embeds.append(embed)

            if len(current_embeds) == GALLERY_PAGE_SIZE:
                pages.append(current_embeds)
                current_embeds = []

        if current_embeds:
            pages.append(current_embeds)

        return pages

    class BadgeView(discord.ui.View):
        def __init__(self, pages):
            super().__init__(timeout=180)
            self.pages = pages
            self.page = 0
            self.update_button_states()

        def update_button_states(self):
            total_pages = len(self.pages)

            # Disable both if only one page
            if total_pages == 1:
                self.previous.disabled = True
                self.next.disabled = True
                return

            # First page
            self.previous.disabled = (self.page == 0)

            # Last page
            self.next.disabled = (self.page == total_pages - 1)

        async def update(self, interaction: discord.Interaction):
            embeds = self.pages[self.page]
            self.update_button_states()

            await interaction.response.edit_message(
                embeds=embeds,
                view=self
            )

        @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.primary, row=0)
        async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page > 0:
                self.page -= 1
            await self.update(interaction)

        @discord.ui.button(label="Next ➡", style=discord.ButtonStyle.primary, row=0)
        async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page < len(self.pages) - 1:
                self.page += 1
            await self.update(interaction)

    @app_commands.command(name="mybadges", description="View all badges you have earned.")
    async def mybadges(self, interaction: discord.Interaction):
        if interaction.guild is None:
            embed = discord.Embed(
                title="Cannot Run in DMs",
                description="❌ The **/mybadges** command must be used inside a server.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ub.badge_award_id,
                       ub.quantity,
                       b.badge_id,
                       b.name,
                       b.description,
                       b.emoji_name,
                       b.emoji_id,
                       b.badge_url,
                       ub.awarded_at
                FROM user_badges ub
                JOIN badges b ON b.badge_id = ub.badge_id
                WHERE ub.user_id = $1
                ORDER BY ub.awarded_at ASC
            """, interaction.user.id)

            first_partner_numbers = {}
            for row in rows:
                if row["badge_id"] == 1:
                    first_partner_numbers[row["badge_award_id"]] = await conn.fetchval("""
                        SELECT COUNT(*)
                        FROM user_badges
                        WHERE badge_id = $1
                          AND badge_award_id <= $2
                    """, row["badge_id"], row["badge_award_id"])

        if not rows:
            embed = discord.Embed(
                title=f"{interaction.user.display_name}'s Badges",
                description="📭 You have no badges yet.",
                color=discord.Color.gold()
            )

            if interaction.user.avatar:
                embed.set_thumbnail(url=interaction.user.avatar.url)
            else:
                embed.set_thumbnail(url=interaction.user.default_avatar.url)

            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        pages = self.build_badge_pages(rows, first_partner_numbers, interaction)
        view = self.BadgeView(pages)

        await interaction.followup.send(
            embeds=pages[0],
            view=view,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(MyBadges(bot))
