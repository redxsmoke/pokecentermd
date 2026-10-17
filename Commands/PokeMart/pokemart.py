import discord
from discord import app_commands
from discord.ext import commands

CATEGORIES = {
    'all': 'All Items', 'consumable': 'Consumables', 'egg': 'Eggs',
    'collectible': 'Collectibles', 'mystery': 'Mystery Items',
    'ticket': 'Tickets & Vouchers', 'special': 'Special Items',
}


def item_emoji_text(item):
    """Discord custom emoji markup from the item catalog."""
    name = item.get("emoji_name") if isinstance(item, dict) else item["emoji_name"]
    emoji_id = item.get("emoji_id") if isinstance(item, dict) else item["emoji_id"]
    return f"<:{name}:{emoji_id}> " if name and emoji_id else ""


def item_button_emoji(item):
    name = item.get("emoji_name") if isinstance(item, dict) else item["emoji_name"]
    emoji_id = item.get("emoji_id") if isinstance(item, dict) else item["emoji_id"]
    return discord.PartialEmoji(name=name, id=int(emoji_id)) if name and emoji_id else None


def money(n):
    return f'{n:,}'


def notice_embed(message, *, success=False):
    return discord.Embed(
        description=message,
        color=discord.Color.green() if success else discord.Color.red(),
    )


def item_embed(item, quantity=1):
    stock = item['stock_remaining']
    maximum = 'Unlimited' if stock is None else f'{stock:,} items'
    e = discord.Embed(title=f"🛒 {item['item_name']}", description=item['description'] or 'No description.', color=discord.Color.blue())
    e.add_field(name='Bundle', value=f"{item['quantity_per_purchase']:,} items")
    e.add_field(name='Price per bundle', value=f"{money(item['price'])} coins")
    e.add_field(name='Stock', value=maximum)
    e.add_field(name='Selected purchase', value=f"{quantity} bundle(s) • {quantity * item['quantity_per_purchase']:,} items\n**{money(quantity * item['price'])} coins**", inline=False)
    return e


MAX_BUNDLES = 10000


class CustomQuantityModal(discord.ui.Modal, title='Custom Purchase Quantity'):
    amount = discord.ui.TextInput(
        label='Number of bundles', placeholder='Enter a whole number',
        min_length=1, max_length=8, required=True
    )

    def __init__(self, purchase_view):
        super().__init__()
        self.purchase_view = purchase_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.amount.value.strip().replace(',', '')
        if not raw.isdigit() or not 1 <= int(raw) <= MAX_BUNDLES:
            await interaction.response.send_message(
                embed=notice_embed(f'Enter a whole number from 1 to {MAX_BUNDLES:,}.'),
                ephemeral=True,
            )
            return
        await self.purchase_view.select_quantity(interaction, int(raw), from_modal=True)


class QuantityButton(discord.ui.Button):
    def __init__(self, quantity):
        super().__init__(label=str(quantity), style=discord.ButtonStyle.secondary, row=0)
        self.quantity = quantity

    async def callback(self, interaction: discord.Interaction):
        await self.view.select_quantity(interaction, self.quantity)


class PurchaseView(discord.ui.View):
    def __init__(self, owner_id, guild_id, item):
        super().__init__(timeout=180)
        self.owner_id, self.guild_id, self.item = owner_id, guild_id, item
        self.quantity = None
        self.processing = False
        self.menu_message = None
        for amount in (1, 10, 25, 50, 100):
            self.add_item(QuantityButton(amount))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=notice_embed('This purchase menu belongs to another player.'),
                ephemeral=True,
            )
            return False
        return True

    def purchase_embed(self):
        embed = item_embed(self.item, self.quantity or 1)
        embed.title = f"{item_emoji_text(self.item)}{self.item['item_name']}"
        if self.quantity is None:
            embed.set_field_at(
                3, name='Select a quantity',
                value='Choose **1, 10, 25, 50, 100**, or **Custom Amount** below.\n'
                      'Quantities are in **bundles**, not individual items.',
                inline=False,
            )
        else:
            embed.set_footer(text='Confirm your purchase or choose another quantity.')
        return embed

    async def select_quantity(self, interaction, quantity, *, from_modal=False):
        if self.processing:
            await interaction.response.send_message(
                embed=notice_embed('A purchase is already processing.'), ephemeral=True
            )
            return
        if quantity < 1 or quantity > MAX_BUNDLES:
            await interaction.response.send_message(
                embed=notice_embed(f'Maximum {MAX_BUNDLES:,} bundles per purchase.'), ephemeral=True
            )
            return
        required = quantity * self.item['quantity_per_purchase']
        stock = self.item['stock_remaining']
        if stock is not None and required > stock:
            await interaction.response.send_message(
                embed=notice_embed(f'Only {stock:,} items remain in stock.'), ephemeral=True
            )
            return
        self.quantity = quantity
        self.confirm.disabled = False
        if from_modal:
            # The modal response edits the original ephemeral purchase menu.
            await interaction.response.defer(ephemeral=True)
            if self.menu_message is not None:
                await self.menu_message.edit(embed=self.purchase_embed(), view=self)
        else:
            await interaction.response.edit_message(embed=self.purchase_embed(), view=self)

    @discord.ui.button(label='Custom Amount', style=discord.ButtonStyle.primary, emoji='🔢', row=1)
    async def custom_amount(self, interaction, button):
        await interaction.response.send_modal(CustomQuantityModal(self))

    @discord.ui.button(label='Confirm Purchase', style=discord.ButtonStyle.success,
                       emoji='🛒', row=1, disabled=True)
    async def confirm(self, interaction, button):
        if self.processing or self.quantity is None:
            await interaction.response.send_message(
                embed=notice_embed('Select a quantity first.'), ephemeral=True
            )
            return
        self.processing = True
        await interaction.response.defer()
        success = False
        try:
            async with interaction.client.db.acquire() as conn:
                async with conn.transaction():
                    balance = await conn.fetchval(
                        'SELECT coin_balance FROM users WHERE user_id=$1 AND guild_id=$2 FOR UPDATE',
                        self.owner_id, self.guild_id,
                    )
                    if balance is None:
                        result = 'No coin account was found for you.'
                    else:
                        listing = await conn.fetchrow('''
                            SELECT m.price, m.quantity_per_purchase, m.stock_remaining,
                                   i.item_name, i.cd_item_id, i.emoji_name, i.emoji_id
                            FROM mart_items m JOIN cd_items i ON i.cd_item_id=m.cd_item_id
                            WHERE m.mart_item_id=$1 AND m.is_active AND i.is_active
                            FOR UPDATE OF m
                        ''', self.item['mart_item_id'])
                        if listing is None:
                            result = 'This item is no longer for sale.'
                        else:
                            received = self.quantity * listing['quantity_per_purchase']
                            cost = self.quantity * listing['price']
                            if listing['stock_remaining'] is not None and received > listing['stock_remaining']:
                                result = 'There is not enough stock left for that purchase.'
                            elif balance < cost:
                                result = (f'Not enough coins. You need **{money(cost)}** '
                                          f'and have **{money(balance)}**.')
                            else:
                                await conn.execute('''
                                    UPDATE users SET coin_balance=coin_balance-$1
                                    WHERE user_id=$2 AND guild_id=$3
                                ''', cost, self.owner_id, self.guild_id)
                                await conn.execute('''
                                    INSERT INTO user_items (user_id,guild_id,cd_item_id,quantity)
                                    VALUES ($1,$2,$3,$4)
                                    ON CONFLICT (user_id,guild_id,cd_item_id)
                                    DO UPDATE SET quantity=user_items.quantity+EXCLUDED.quantity,
                                                  updated_timestamp=NOW()
                                ''', self.owner_id, self.guild_id, listing['cd_item_id'], received)
                                if listing['stock_remaining'] is not None:
                                    await conn.execute('''
                                        UPDATE mart_items SET stock_remaining=stock_remaining-$1
                                        WHERE mart_item_id=$2
                                    ''', received, self.item['mart_item_id'])
                                await conn.execute('''
                                    INSERT INTO mart_transactions
                                        (user_id,guild_id,cd_item_id,bundles_purchased,items_received,total_cost)
                                    VALUES ($1,$2,$3,$4,$5,$6)
                                ''', self.owner_id, self.guild_id, listing['cd_item_id'],
                                     self.quantity, received, cost)
                                result = (f"Purchased {item_emoji_text(listing)}"
                                          f"**{listing['item_name']} (x{received:,})** "
                                          f"for **{money(cost)} coins**!\n"
                                          f"Remaining balance: **{money(balance - cost)} coins**.")
                                success = True
            if success:
                self.stop()
                await interaction.edit_original_response(
                    embed=notice_embed('✅ ' + result, success=True), view=None
                )
            else:
                await interaction.followup.send(embed=notice_embed(result), ephemeral=True)
        except Exception:
            await interaction.followup.send(
                embed=notice_embed('Purchase could not be completed. Please try again.'),
                ephemeral=True,
            )
            raise
        finally:
            self.processing = False

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(
            embed=notice_embed('Purchase cancelled.'), view=None
        )


class QuickBuyButton(discord.ui.Button):
    # Opens a private quantity selector; no coins are deducted yet.
    def __init__(self, item):
        self.item = item
        super().__init__(
            label=f"Purchase {item['item_name']}",
            emoji=item_button_emoji(item),
            style=discord.ButtonStyle.success,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        purchase_view = PurchaseView(interaction.user.id, interaction.guild_id, self.item)
        await interaction.response.send_message(
            embed=purchase_view.purchase_embed(),
            view=purchase_view,
            ephemeral=True,
        )
        purchase_view.menu_message = await interaction.original_response()


class CategorySelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=label, value=value) for value, label in CATEGORIES.items()]
        super().__init__(placeholder='Filter by category...', options=options, row=2)

    async def callback(self, interaction):
        view = self.view
        view.category = self.values[0]
        view.page = 0
        await view.refresh(interaction)


class MartView(discord.ui.View):
    def __init__(self, bot, owner_id):
        super().__init__(timeout=180)
        self.bot, self.owner_id = bot, owner_id
        self.category, self.page = 'all', 0
        self.processing = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(embed=notice_embed('Use /pokemart to open your own shop.'), ephemeral=True)
            return False
        return True

    async def build(self):
        async with self.bot.db.acquire() as conn:
            records = await conn.fetch('''
                SELECT m.mart_item_id, m.price, m.quantity_per_purchase, m.stock_remaining,
                       i.cd_item_id, i.item_name, i.description, i.image_url, i.item_type, i.emoji_name, i.emoji_id
                FROM mart_items m JOIN cd_items i ON i.cd_item_id=m.cd_item_id
                WHERE m.is_active AND i.is_active
                  AND (m.stock_remaining IS NULL OR m.stock_remaining >= m.quantity_per_purchase)
                  AND ($1::text='all' OR i.item_type=$1)
                ORDER BY i.item_name''', self.category)
        items = [dict(r) for r in records]
        total_pages = max(1, (len(items) + 5) // 6)
        self.page = min(self.page, total_pages - 1)
        shown = items[self.page * 6:(self.page + 1) * 6]
        self.clear_items()
        if shown:
            # One purchase button per listing; Discord allows five buttons per row.
            for index, item in enumerate(shown):
                button = QuickBuyButton(item)
                button.row = index // 5
                self.add_item(button)
        self.add_item(CategorySelect())
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page >= total_pages - 1
        self.add_item(self.previous)
        self.add_item(self.next)
        # Embed 1: shop header and selected category.
        header = discord.Embed(
            title='<:Mart:1559747613631451146> Poké Mart',
            description=CATEGORIES.get(self.category, self.category.title()),
            color=discord.Color.blue(),
        )

        # Embed 2: descriptions are part of the embed body, not optional fields.
        listings = discord.Embed(color=discord.Color.blue())
        if shown:
            parts = []
            for item in shown:
                berry_emoji = item_emoji_text(item)
                description = (item["description"] or "No description available.").strip()
                parts.append(
                    f"{berry_emoji}**{item['item_name']} (x{item['quantity_per_purchase']:,})**\n"
                    f"{description}\n"
                    f"• **{money(item['price'])} coins**"
                )
            listings.description = "\n\n".join(parts)
        else:
            listings.description = 'No items available. Try another category.'
        listings.set_footer(text=f'Page {self.page + 1} of {total_pages} • {len(items)} available listings')
        # Discord renders these as TWO distinct embeds in the same message.
        return [header, listings]

    async def refresh(self, interaction):
        embeds = await self.build()
        await interaction.response.edit_message(embeds=embeds, view=self)

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.secondary, row=3)
    async def previous(self, interaction, button):
        self.page = max(0, self.page - 1)
        await self.refresh(interaction)

    @discord.ui.button(label='Next', style=discord.ButtonStyle.secondary, row=3)
    async def next(self, interaction, button):
        self.page += 1
        await self.refresh(interaction)


class InventoryCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=label, value=value) for value, label in CATEGORIES.items()]
        super().__init__(placeholder='Filter by category...', options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.category = self.values[0]
        view.page = 0
        await view.refresh(interaction)


class InventoryView(discord.ui.View):
    def __init__(self, bot, owner_id, guild_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.category = 'all'
        self.page = 0

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=notice_embed('This inventory belongs to another player.'),
                ephemeral=True,
            )
            return False
        return True

    async def build(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch('''
                SELECT i.item_name, i.description, i.item_type, i.emoji_name, i.emoji_id, u.quantity
                FROM user_items u
                JOIN cd_items i ON i.cd_item_id = u.cd_item_id
                WHERE u.user_id = $1 AND u.guild_id = $2 AND u.quantity > 0
                  AND ($3::text = 'all' OR i.item_type = $3)
                ORDER BY i.item_type, i.item_name
            ''', self.owner_id, self.guild_id, self.category)

        total_pages = max(1, (len(rows) + 5) // 6)
        self.page = min(max(self.page, 0), total_pages - 1)
        shown = rows[self.page * 6:(self.page + 1) * 6]

        self.clear_items()
        self.add_item(InventoryCategorySelect())
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page >= total_pages - 1
        self.add_item(self.previous)
        self.add_item(self.next)

        embed = discord.Embed(
            title='🎒 My Items',
            color=discord.Color.gold(),
        )
        if shown:
            parts = []
            for item in shown:
                emoji = item_emoji_text(item)
                description = (item['description'] or 'No description available.').strip()
                parts.append(
                    f"{emoji}**{item['item_name']} (x{item['quantity']:,})**\n"
                    f"{description}"
                )
            embed.description = (
                f"**{CATEGORIES.get(self.category, 'All Items')}**\n\n"
                + '\n\n'.join(parts)
            )
        else:
            embed.description = (
                f"**{CATEGORIES.get(self.category, 'All Items')}**\n\n"
                + ('Your inventory is empty. Visit `/pokemart`!'
                   if self.category == 'all'
                   else 'You have no items in this category.')
            )
        embed.set_footer(text=f'Page {self.page + 1} of {total_pages} • {len(rows)} item types')
        return embed

    async def refresh(self, interaction: discord.Interaction):
        embed = await self.build()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await self.refresh(interaction)

    @discord.ui.button(label='Next', style=discord.ButtonStyle.secondary, row=1)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self.refresh(interaction)


class PokeMart(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='pokemart', description='Browse and buy items from the Poké Mart')
    @app_commands.guild_only()
    async def pokemart(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        view = MartView(self.bot, interaction.user.id)
        embeds = await view.build()
        await interaction.followup.send(embeds=[embeds[0], embeds[1]], view=view, ephemeral=False)

    @app_commands.command(name='myitems', description='View your Poké Mart inventory')
    @app_commands.guild_only()
    async def myitems(self, interaction: discord.Interaction):
        view = InventoryView(self.bot, interaction.user.id, interaction.guild_id)
        embed = await view.build()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(PokeMart(bot))
