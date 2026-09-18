import discord
import datetime
from discord import app_commands

# ---------------------------------------------------------
# /myrewards COMMAND
# ---------------------------------------------------------
@app_commands.command(name="myrewards", description="View your earned rewards.")
async def myrewards(interaction: discord.Interaction):
    async with interaction.client.db.acquire() as conn:
        rows = await conn.fetch(
            """
            (
                SELECT
                    ur.reward_id,
                    COALESCE(ur.max_uses, gr.max_uses) AS max_uses,
                    ur.times_used,
                    ur.last_used_at,
                    gr.name,
                    gr.type,
                    gr.value,
                    gr.min_order_total,
                    gr.expiration_date
                FROM user_rewards ur
                JOIN guild_rewards gr ON ur.reward_id = gr.reward_id
                WHERE ur.user_id = $1 AND ur.guild_id = $2
            )
            UNION ALL
            (
                SELECT
                    gr.reward_id,
                    gr.max_uses,
                    0 AS times_used,
                    NULL AS last_used_at,
                    gr.name,
                    gr.type,
                    gr.value,
                    gr.min_order_total,
                    gr.expiration_date
                FROM guild_rewards gr
                WHERE gr.guild_id = $2
                  AND gr.active = TRUE
                  AND (gr.required_level IS NULL OR gr.required_level = 0)
                  AND gr.reward_id NOT IN (
                        SELECT reward_id
                        FROM user_rewards
                        WHERE user_id = $1 AND guild_id = $2
                  )
            )
            ORDER BY expiration_date
            """,
            interaction.user.id,
            interaction.guild.id
        )

    # ---------------------------------------------------------
    # NO REWARDS → RED EMBED
    # ---------------------------------------------------------
    if not rows:
        embed = discord.Embed(
            title="No Rewards Found",
            description=(
                "You currently have no rewards.\n\n"
                "Earn rewards by participating in server activities, leveling up, "
                "or redeeming special promotions."
            ),
            color=discord.Color.red()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )
        return

    # ---------------------------------------------------------
    # REWARD LIST EMBED
    # ---------------------------------------------------------
    embed = discord.Embed(
        title="🎁 Your Rewards",
        color=discord.Color.gold()
    )

    embed.description = (
        "To use your reward(s), add item(s) to your cart and run **/cart**. "
        "During checkout, you’ll be shown any available reward options before submitting your order."
    )

    # ---------------------------------------------------------
    # List rewards
    # ---------------------------------------------------------
    for r in rows:
        # Build reward description
        if r["type"] == "percent_off":
            reward_text = f"{r['value']}% off"
        elif r["type"] == "flat_off":
            reward_text = f"${r['value']} off"
        elif r["type"] == "free_shipping":
            reward_text = "Free Shipping"
        else:
            reward_text = r["name"]

        # Add order condition
        if r["min_order_total"]:
            reward_text += f" orders over ${r['min_order_total']}"
        else:
            reward_text += " on any order"

        # Expiration
        exp = r["expiration_date"]
        exp_str = exp.strftime("%m/%d/%Y") if exp else "N/A"

        # Max uses
        if r["max_uses"] is None:
            uses_str = "Unlimited"
        else:
            uses_str = f"{r['max_uses']} (Used {r['times_used']})"

        # Last Used
        if r["last_used_at"]:
            last_used_str = r["last_used_at"].strftime("%m/%d/%Y %I:%M %p")
        else:
            last_used_str = "Never"

        embed.add_field(
            name=reward_text,
            value=(
                f"**Expires:** {exp_str}\n"
                f"**Max Uses:** {uses_str}\n"
                f"**Last Used:** {last_used_str}"
            ),
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )



# ---------------------------------------------------------
# EXTENSION SETUP
# ---------------------------------------------------------
async def setup(bot):
    bot.tree.add_command(myrewards)
