import discord
from discord.ext import commands
import os

GREEN = discord.Color.green()

class ReleaseNotes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def load_release_notes(self):
        path = os.path.join(os.getcwd(), "release_notes.md")
        if not os.path.exists(path):
            print("release_notes.md not found")
            return None

        with open(path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]

        # SEND FLAG
        if not lines[0].lower().startswith("send:"):
            return None

        send_flag = lines[0].split(":", 1)[1].strip().lower() == "true"
        if not send_flag:
            return None

        # VERSION — FIRST NON-EMPTY LINE AFTER SEND FLAG
        version = ""
        for line in lines[1:]:
            if line.strip():
                version = line.strip()
                break

        # SECTION TITLES (ORIGINAL FORMAT)
        TITLE_MAP = {
            "What's New": "whats_new",
            "New Commands": "commands",
            "How to Use": "how_to",
            "Additional Info": "additional",
            "Upcoming Features": "features"
        }

        sections = {
            "whats_new": "",
            "commands": "",
            "how_to": "",
            "additional": "",
            "features": ""
        }

        current = None

        # PARSE CONTENT
        for raw in lines:
            line = raw.strip()

            if line in TITLE_MAP:
                current = TITLE_MAP[line]
                continue

            if current:
                sections[current] += raw + "\n"

        return {"version": version, **sections}

    async def get_announcement_channel(self, guild: discord.Guild):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT announcement_channel_id
                FROM guild_settings
                WHERE guild_id = $1
            """, guild.id)

        if row and row["announcement_channel_id"]:
            channel = guild.get_channel(row["announcement_channel_id"])
            if channel and channel.permissions_for(guild.me).send_messages:
                return channel

        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                return channel

        return None

    async def send_release_embed(self, guild: discord.Guild):
        notes = await self.load_release_notes()
        if not notes:
            return

        embed = discord.Embed(
            title=notes["version"],  
            description="Latest release notes",
            color=GREEN
        )

        # SECTIONS — EXACT ORIGINAL FORMAT
        if notes["whats_new"].strip():
            embed.add_field(name="What's New", value=notes["whats_new"], inline=False)

        if notes["commands"].strip():
            embed.add_field(name="New Commands", value=notes["commands"], inline=False)

        if notes["how_to"].strip():
            embed.add_field(name="How to Use", value=notes["how_to"], inline=False)

        if notes["additional"].strip():
            embed.add_field(name="Additional Info", value=notes["additional"], inline=False)

        if notes["features"].strip():
            embed.add_field(name="Upcoming Features", value=notes["features"], inline=False)

        channel = await self.get_announcement_channel(guild)
        if channel:
            await channel.send(embed=embed)

    async def startup_send_release_notes(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self.send_release_embed(guild)


async def setup(bot):
    cog = ReleaseNotes(bot)
    await bot.add_cog(cog)
    bot.loop.create_task(cog.startup_send_release_notes())
