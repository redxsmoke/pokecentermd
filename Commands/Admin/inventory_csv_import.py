import discord
from discord.ext import commands
import csv
import io
from datetime import datetime

VALID_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def decode_csv_bytes(data: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            pass
    raise UnicodeDecodeError("Unable to decode CSV file with common encodings.")


class InventoryCSVImport(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start_csv_upload(self, interaction: discord.Interaction):
        """
        NEW FLOW:
        CSV upload now happens IN THE ADMIN CHANNEL.
        """

        guild_id = interaction.guild.id

        embed = discord.Embed(
            title="📄 CSV Upload Mode",
            description=(
                "Please upload your **CSV file** in this channel.\n\n"
                "**Supported formats:**\n"
                "• UTF‑16 CSV\n"
                "• UTF‑8 CSV\n"
                "• Semicolon‑delimited CSV\n\n"
                "**Required column headers:**\n"
                "• Name\n"
                "• Series\n"
                "• Set\n"
                "• Quantity\n"
                "• Price\n\n"
                "**Optional column headers:**\n"
                "• Variant\n"
                "• Rarity\n"
                "• Condition\n"
                "• ImageURL *(must be a direct image link ending in .jpg, .jpeg, .png, .gif, or .webp)*\n\n"
                "**ID Handling:**\n"
                "• You do **NOT** need to include an `Id` column.\n"
                "• The bot automatically assigns an ID based on the **CSV filename**.\n"
                "• All cards imported from the same CSV share this ID.\n\n"
                "**Inventory Display Rules:**\n"
                "• `/inventory` only displays cards where **Quantity ≥ 1**.\n"
                "• If you sell a card and want to keep the record, set **Quantity = 0**.\n"
                "• When you obtain a new copy, update Quantity back to **1** and your stored image will display again.\n\n"
                "**Image Notes:**\n"
                "• For images uploaded within Discord, **do NOT delete the message** containing the image.\n"
                "• If the message is deleted, the Discord CDN link breaks and the image will no longer display.\n\n"
                "Please upload your CSV file now."
            ),
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Wait for CSV upload IN THIS CHANNEL
        def check(message: discord.Message):
            return (
                message.guild is not None
                and message.guild.id == guild_id
                and message.author.id == interaction.user.id
                and message.attachments
                and message.attachments[0].filename.lower().endswith(".csv")
            )

        try:
            csv_msg = await self.bot.wait_for("message", check=check, timeout=300)
        except Exception:
            timeout_embed = discord.Embed(
                title="⏰ Upload Timed Out",
                description="No CSV file was uploaded within 5 minutes. Please try again.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=timeout_embed, ephemeral=True)
            return

        attachment = csv_msg.attachments[0]
        csv_bytes = await attachment.read()
        csv_text = decode_csv_bytes(csv_bytes)

        await self.process_csv(csv_msg, csv_text, attachment.filename)

    async def process_csv(self, msg: discord.Message, csv_text: str, filename: str):

        guild_id = msg.guild.id  # ✔ ALWAYS VALID NOW

        csv_id = filename.rsplit(".", 1)[0]

        reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
        rows = list(reader)

        if not rows:
            embed = discord.Embed(
                title="❌ CSV Error",
                description="Your CSV file contains no data.",
                color=discord.Color.red()
            )
            await msg.reply(embed=embed, mention_author=False)
            return

        invalid_image_found = False
        valid_image_found = False

        async with self.bot.db.acquire() as conn:
            for idx, row in enumerate(rows, start=2):
                if all(not (v and v.strip()) for v in row.values()):
                    continue

                pokemon_name = (row.get("Name") or "").strip()
                series = (row.get("Series") or "").strip()
                set_name = (row.get("Set") or "").strip()
                variant = (row.get("Variant") or "").strip()
                rarity = (row.get("Rarity") or "").strip()

                raw_id = (row.get("Id") or "").strip()
                if raw_id and "-" in raw_id:
                    card_number = raw_id.split("-")[-1].strip()
                elif raw_id:
                    card_number = raw_id
                else:
                    card_number = ""

                if not pokemon_name or not series or not set_name or not card_number:
                    embed = discord.Embed(
                        title="❌ CSV Row Error",
                        description=f"Row {idx} is missing required fields: **Name**, **Series**, **Set**, **Id/Card Number**.",
                        color=discord.Color.red()
                    )
                    await msg.reply(embed=embed, mention_author=False)
                    return

                qty_raw = (row.get("Quantity") or "").strip()
                try:
                    quantity_available = int(qty_raw)
                except:
                    quantity_available = 0

                price_raw = (row.get("Price") or "").replace("$", "").strip()
                try:
                    price = float(price_raw)
                except:
                    price = None

                raw_condition = (row.get("Condition") or "").strip()
                condition_map = {
                    "nm": "Near Mint",
                    "near mint": "Near Mint",
                    "lp": "Lightly Played",
                    "lightly played": "Lightly Played",
                    "mp": "Moderately Played",
                    "moderately played": "Moderately Played",
                    "hp": "Heavily Played",
                    "heavily played": "Heavily Played",
                    "dmg": "Damaged",
                    "damaged": "Damaged"
                }
                condition = condition_map.get(raw_condition.lower(), "Near Mint") if raw_condition else "Near Mint"

                raw_image = (row.get("ImageURL") or "").strip()
                if raw_image:
                    lower = raw_image.lower()
                    if lower.endswith(VALID_IMAGE_EXTENSIONS):
                        image_link = raw_image
                        valid_image_found = True
                    else:
                        image_link = None
                        invalid_image_found = True
                else:
                    image_link = None

                # ✔ UPDATED — SELECT now filters by guild_id
                existing = await conn.fetchrow(
                    """
                    SELECT *
                    FROM inventory
                    WHERE guild_id = $1
                      AND LOWER(pokemon_name) = LOWER($2)
                      AND LOWER(card_number) = LOWER($3)
                      AND LOWER(set_name) = LOWER($4)
                      AND LOWER(series) = LOWER($5)
                      AND LOWER(variant) = LOWER($6)
                    """,
                    guild_id, pokemon_name, card_number, set_name, series, variant
                )

                if existing:
                    await conn.execute(
                        """
                        UPDATE inventory
                        SET quantity_available = $1,
                            price = $2
                        WHERE inventory_id = $3
                          AND guild_id = $4
                        """,
                        quantity_available,
                        price,
                        existing["inventory_id"],
                        guild_id
                    )

                else:
                    await conn.execute(
                        """
                        INSERT INTO inventory (
                            guild_id,
                            csv_id, pokemon_name, series, set_name, card_number,
                            variant, rarity, price, graded, grading_company, grade,
                            quantity_available, image_link, condition,
                            reserved, reserved_until, date_added
                        )
                        VALUES (
                            $1,
                            $2,$3,$4,$5,$6,
                            $7,$8,$9,NULL,NULL,NULL,
                            $10,$11,'Near Mint',
                            0,NULL,$12
                        )
                        """,
                        guild_id,
                        csv_id,
                        pokemon_name,
                        series,
                        set_name,
                        card_number,
                        variant,
                        rarity,
                        price,
                        quantity_available,
                        image_link,
                        datetime.now().date()
                    )

        if invalid_image_found and valid_image_found:
            warn_embed = discord.Embed(
                title="⚠️ Image URL Warning",
                description=(
                    "Some images were **not uploaded** because they were not in a valid format.\n\n"
                    "**Images must be direct links ending in:**\n"
                    "`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`"
                ),
                color=discord.Color.orange()
            )
            await msg.reply(embed=warn_embed, mention_author=False)

        success_embed = discord.Embed(
            title="✅ CSV Processed",
            description="Your inventory has been updated successfully.",
            color=discord.Color.green()
        )
        await msg.reply(embed=success_embed, mention_author=False)


async def setup(bot):
    await bot.add_cog(InventoryCSVImport(bot))
