import math
import logging
import discord
from discord.ext import commands
from Commands.Cart.cart import CheckoutStartView

log = logging.getLogger('inventory')
GALLERY_PAGE_SIZE = 6
SORTS = {
    'price_asc': 'price ASC NULLS LAST, inventory_id ASC',
    'price_desc': 'price DESC NULLS LAST, inventory_id ASC',
    'name': 'pokemon_name ASC NULLS LAST, inventory_id ASC',
    'newest': 'inventory_id DESC',  # approximate arrival order; change if a date-added column exists
}
ALLOWED_FILTERS = {'condition', 'series', 'set_name', 'variant', 'rarity', 'illustrator'}


def money(value):
    return f'${value:,.2f}' if value is not None else '—'


class SearchModal(discord.ui.Modal):
    def __init__(self, gallery, field):
        super().__init__(title='Search Pokémon' if field == 'pokemon_name' else 'Search Illustrator')
        self.gallery = gallery
        self.field = field
        self.term = discord.ui.TextInput(label='Pokémon name' if field == 'pokemon_name' else 'Illustrator', max_length=100, required=False, placeholder='Leave blank to remove search')
        self.add_item(self.term)

    async def on_submit(self, interaction):
        term = self.term.value.strip()
        changes = {self.field: term or None}
        await self.gallery.apply_changes(interaction, changes)


class JumpModal(discord.ui.Modal, title='Jump to Page'):
    def __init__(self, gallery):
        super().__init__()
        self.gallery = gallery
        self.number = discord.ui.TextInput(label=f'Page (1–{gallery.total_pages})', max_length=8)
        self.add_item(self.number)

    async def on_submit(self, interaction):
        try:
            page = int(self.number.value)
        except ValueError:
            await interaction.response.send_message('Please enter a valid page number.', ephemeral=True)
            return
        if not 1 <= page <= self.gallery.total_pages:
            await interaction.response.send_message(f'Enter a page between 1 and {self.gallery.total_pages}.', ephemeral=True)
            return
        self.gallery.page = page - 1
        await interaction.response.defer(ephemeral=True)
        await self.gallery.refresh()
        await self.gallery.update_panel('home', notice=f'Moved to page {page}.')


class ControlPanel(discord.ui.View):
    """One reusable ephemeral message for filters, sorting, and card details."""
    def __init__(self, gallery, screen='home', field=None, choices=None, choice_page=0, card=None):
        super().__init__(timeout=900)
        self.gallery = gallery
        self.screen = screen
        self.field = field
        self.choices = choices or []
        self.choice_page = choice_page
        self.card = card
        if screen == 'home':
            self.add_item(discord.ui.Button(label='Filters', custom_id='panel_filters', style=discord.ButtonStyle.primary, row=0))
            self.add_item(discord.ui.Button(label='Sorting', custom_id='panel_sort', style=discord.ButtonStyle.secondary, row=0))
            self.add_item(discord.ui.Button(label='Search Pokémon', custom_id='panel_search', style=discord.ButtonStyle.secondary, row=1))
            self.add_item(discord.ui.Button(label='Search Illustrator', custom_id='panel_illustrator', style=discord.ButtonStyle.secondary, row=1))
            for item in self.children:
                action = item.custom_id
                async def handler(interaction, action=action):
                    if action == 'panel_filters':
                        await self.gallery.show_panel(interaction, 'filters')
                    elif action == 'panel_sort':
                        await self.gallery.show_panel(interaction, 'sort')
                    else:
                        await interaction.response.send_modal(SearchModal(self.gallery, 'pokemon_name' if action == 'panel_search' else 'illustrator'))
                item.callback = handler
        elif screen == 'filters':
            select = discord.ui.Select(placeholder='Choose a filter', row=0, options=[
                discord.SelectOption(label=label, value=field) for field, label in [
                    ('pokemon_name','Pokémon Name'), ('condition','Condition'), ('series','Series'),
                    ('set_name','Set'), ('variant','Variant'), ('rarity','Rarity'), ('illustrator','Illustrator')]])
            async def choose(interaction):
                field = select.values[0]
                if field in ('pokemon_name', 'illustrator'):
                    await interaction.response.send_modal(SearchModal(self.gallery, field))
                    return
                values = await self.gallery.cog.get_distinct_values(field, self.gallery.guild_id)
                await self.gallery.show_panel(interaction, 'values', field=field, choices=values)
            select.callback = choose
            self.add_item(select)
        elif screen == 'sort':
            select = discord.ui.Select(placeholder='Sort cards', row=0, options=[
                discord.SelectOption(label='Price: Low to High', value='price_asc'),
                discord.SelectOption(label='Price: High to Low', value='price_desc'),
                discord.SelectOption(label='Pokémon: A–Z', value='name'),
                discord.SelectOption(label='Recently Added', value='newest')])
            async def choose(interaction):
                self.gallery.sort = select.values[0]
                self.gallery.page = 0
                await interaction.response.defer()
                await self.gallery.refresh()
                await self.gallery.update_panel('home', notice='Sorting updated.')
            select.callback = choose
            self.add_item(select)
        elif screen == 'cart':
            another = discord.ui.Button(label='➕ Add Another Card', style=discord.ButtonStyle.primary, row=0)
            empty = discord.ui.Button(label='🗑️ Empty Cart', style=discord.ButtonStyle.danger, row=0)
            checkout = discord.ui.Button(label='Checkout', style=discord.ButtonStyle.success, row=0)

            async def add_another(interaction):
                await self.gallery.show_panel(interaction, 'home')

            async def empty_cart(interaction):
                await interaction.response.defer()
                async with self.gallery.bot.db.acquire() as conn:
                    await conn.execute('''DELETE FROM cart_items WHERE user_id=$1 AND inventory_id IN
                        (SELECT inventory_id FROM inventory WHERE guild_id=$2)''',
                        self.gallery.owner_id, self.gallery.guild_id)
                await self.gallery.update_panel('home', notice='Your cart has been emptied.')

            async def begin_checkout(interaction):
                checkout_view = CheckoutStartView(self.gallery.bot, interaction.user.id)
                ok = await checkout_view.async_init(interaction)
                if ok is False:
                    return
                await self.gallery.update_panel('checkout', checkout_view=checkout_view)

            another.callback = add_another
            empty.callback = empty_cart
            checkout.callback = begin_checkout
            self.add_item(another)
            self.add_item(empty)
            self.add_item(checkout)
        elif screen == 'values':
            chunk = self.choices[choice_page*24:(choice_page+1)*24]
            opts = [discord.SelectOption(label='All / Clear', value='__clear__')]
            opts.extend(discord.SelectOption(label=str(v)[:100], value=str(v)[:100]) for v in chunk)
            select = discord.ui.Select(placeholder=f'Select {field.replace("_", " ")}', options=opts, row=0)
            async def choose(interaction):
                value = select.values[0]
                await self.gallery.apply_changes(interaction, {field: None if value == '__clear__' else value})
            select.callback = choose
            self.add_item(select)
            if choice_page > 0:
                prev = discord.ui.Button(label='◀ Choices', style=discord.ButtonStyle.secondary, row=1)
                async def previous(interaction):
                    await self.gallery.show_panel(interaction, 'values', field=field, choices=self.choices, choice_page=choice_page-1)
                prev.callback = previous
                self.add_item(prev)
            if (choice_page+1)*24 < len(self.choices):
                nxt = discord.ui.Button(label='Choices ▶', style=discord.ButtonStyle.secondary, row=1)
                async def next_page(interaction):
                    await self.gallery.show_panel(interaction, 'values', field=field, choices=self.choices, choice_page=choice_page+1)
                nxt.callback = next_page
                self.add_item(nxt)
        if screen not in ('home', 'cart', 'checkout'):
            back = discord.ui.Button(label='⬅ Back to Filters' if screen in ('values','details') else '⬅ Back', style=discord.ButtonStyle.secondary, row=4)
            async def go_back(interaction):
                await self.gallery.show_panel(interaction, 'filters' if screen in ('values','details') else 'home')
            back.callback = go_back
            self.add_item(back)

    async def interaction_check(self, interaction):
        return await self.gallery.interaction_check(interaction)


class InventoryGallery(discord.ui.View):
    def __init__(self, cog, owner_id, guild_id, pokemon_name=None, set_name=None):
        super().__init__(timeout=900)
        self.cog, self.bot = cog, cog.bot
        self.owner_id, self.guild_id = owner_id, guild_id
        self.filters = {}
        if pokemon_name:
            self.filters['pokemon_name'] = pokemon_name
        if set_name:
            self.filters['set_name'] = set_name
        self.sort = 'price_asc'
        self.page = 0
        self.total = 0
        self.total_pages = 1
        self.rows = []
        self.message = None
        self.panel_message = None
        self.panel_screen = "home"
        self.rebuild()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message('This is not your browsing session. Use `/shop singles` to open your own.', ephemeral=True)
            return False
        return True

    def rebuild(self):
        self.clear_items()
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page + 1 >= self.total_pages
        self.add_item(self.previous)
        self.add_item(self.next)
        self.add_item(self.jump)
        self.add_item(self.filter_button)
        self.add_item(self.sort_button)
        self.add_item(self.clear_button)
        if self.rows:
            options = [discord.SelectOption(label=f"{str(r['pokemon_name'] or 'Card')[:45]} · #{r['card_number'] or '?'} · {money(r['price'])}"[:100], value=str(r['inventory_id'])) for r in self.rows]
            add = discord.ui.Select(placeholder='🛒 Add a card to cart', options=options, row=2)
            details = discord.ui.Select(placeholder='🔎 More card details', options=options, row=3)
            async def add_callback(interaction):
                await self.add_to_cart(interaction, int(add.values[0]))
            async def details_callback(interaction):
                await self.more_info(interaction, int(details.values[0]))
            add.callback, details.callback = add_callback, details_callback
            self.add_item(add)
            self.add_item(details)

    def embeds(self):
        header = discord.Embed(title='🛍️ Pokémon Singles', description=f'**{self.total:,} matching listings** · Page **{self.page + 1:,} / {self.total_pages:,}**\nSort: **{self.sort.replace("_", " ").title()}**' + ('\nFilters: ' + ', '.join(f'**{k.replace("_", " ")}**: {v}' for k, v in self.filters.items()) if self.filters else ''), color=discord.Color.gold())
        if not self.rows:
            header.add_field(name='No matching cards', value='Try clearing or changing your filters.')
            return [header]
        embeds = [header]
        # Discord allows at most 10 embeds per message: header + 6 cards = 7.
        for r in self.rows:
            card = discord.Embed(title=str(r['pokemon_name'] or 'Unnamed card'), description=f"**Set:** {r['set_name'] or '—'}", color=discord.Color.gold())
            card.add_field(name='Price', value=money(r['price']))
            card.add_field(name='Condition', value=r['condition'] or '—')
            card.add_field(name='Variant', value=r['variant'] or '—')
            if r['image_link']:
                card.set_thumbnail(url=r['image_link'])
            embeds.append(card)
        return embeds

    def panel_embed(self, screen='home', notice=None, card=None, field=None):
        titles = {'home':'🛍️ Browse Options', 'filters':'🔎 Filter Cards', 'sort':'↕️ Sort Cards', 'values':'🔎 Choose Filter Value', 'details':'🃏 Card Details', 'cart':'🛒 Cart Updated', 'checkout':'🛒 Checkout'}
        desc = {
            'home':'Choose a search, filter, or sorting option. Your six-card gallery stays above.',
            'filters':'Select a category below. Your gallery stays visible.',
            'sort':'Select how your results should be ordered.',
            'values':f'Select a value for **{(field or "filter").replace("_", " ")}**.',
            'details':'Use **Back to Filters** to return to your filter options.',
            'cart':'Your card was added to the cart. Continue shopping or checkout.',
            'checkout':'Select shipping and payment method:'
        }[screen]
        if notice:
            desc = f'**{notice}**\n\n' + desc
        embed = discord.Embed(title=titles[screen], description=desc, color=discord.Color.blurple())
        if screen == 'home':
            embed.add_field(name='Current Sort', value=self.sort.replace('_',' ').title(), inline=False)
            embed.add_field(name='Active Filters', value=', '.join(f'{k}: {v}' for k,v in self.filters.items()) or 'None', inline=False)
        if screen == 'details' and card:
            embed.title = card['pokemon_name'] or 'Card Details'
            embed.description = (f"**Series:** {card['series'] or '—'}\n**Set:** {card['set_name'] or '—'}\n"
                f"**Card #:** {card['card_number'] or '—'}\n**Variant:** {card['variant'] or '—'}\n"
                f"**Rarity:** {card['rarity'] or '—'}\n**Condition:** {card['condition'] or '—'}\n"
                f"**Illustrator:** {card['illustrator'] or '—'}\n**Price:** {money(card['price'])}\n"
                f"**Available:** {card['quantity_available']}")
            if card['image_link']:
                embed.set_image(url=card['image_link'])
        return embed

    async def update_panel(self, screen='home', notice=None, **kwargs):
        self.panel_screen = screen
        if self.panel_message:
            if screen == 'checkout':
                await self.panel_message.edit(
                    embed=self.panel_embed('checkout'), view=kwargs['checkout_view'])
            else:
                embed = self.panel_embed(screen, notice, kwargs.get('card'), kwargs.get('field'))
                if screen == 'cart':
                    count, subtotal = await self.cart_summary()
                    embed.set_footer(text=f'{count:,} card(s) in cart • Subtotal: {money(subtotal)}')
                await self.panel_message.edit(embed=embed, view=ControlPanel(self, screen, **kwargs))

    async def show_panel(self, interaction, screen, **kwargs):
        self.panel_screen = screen
        await interaction.response.edit_message(embed=self.panel_embed(screen, field=kwargs.get('field')),
                                                view=ControlPanel(self, screen, **kwargs))

    async def load(self):
        self.total = await self.cog.count_query(self.filters, self.guild_id)
        self.total_pages = max(1, math.ceil(self.total / GALLERY_PAGE_SIZE))
        self.page = min(self.page, self.total_pages - 1)
        self.rows = await self.cog.page_query(self.filters, self.guild_id, self.sort, self.page)
        self.rebuild()

    async def refresh(self):
        await self.load()
        if self.message:
            await self.message.edit(embeds=self.embeds(), view=self)

    async def apply_changes(self, interaction, changes):
        proposed = dict(self.filters)
        for field, value in changes.items():
            if value is None:
                proposed.pop(field, None)
            else:
                proposed[field] = value
        count = await self.cog.count_query(proposed, self.guild_id)
        if not count:
            await interaction.response.defer(ephemeral=True)
            await self.update_panel('home', notice='No cards matched. Previous results were kept.')
            return
        self.filters, self.page = proposed, 0
        await interaction.response.defer(ephemeral=True)
        await self.refresh()
        await self.update_panel('home', notice=f'Gallery updated: {count:,} matching listings.')

    @discord.ui.button(label='⬅ Previous', style=discord.ButtonStyle.primary, row=0)
    async def previous(self, interaction, button):
        self.page = max(0, self.page - 1)
        await interaction.response.defer()
        await self.refresh()

    @discord.ui.button(label='Next ➡', style=discord.ButtonStyle.primary, row=0)
    async def next(self, interaction, button):
        self.page = min(self.total_pages - 1, self.page + 1)
        await interaction.response.defer()
        await self.refresh()

    @discord.ui.button(label='Jump to Page', style=discord.ButtonStyle.secondary, row=0)
    async def jump(self, interaction, button):
        await interaction.response.send_modal(JumpModal(self))

    @discord.ui.button(label='Filters', style=discord.ButtonStyle.secondary, row=1)
    async def filter_button(self, interaction, button):
        await interaction.response.defer()
        await self.update_panel('filters')

    @discord.ui.button(label='Sort', style=discord.ButtonStyle.secondary, row=1)
    async def sort_button(self, interaction, button):
        await interaction.response.defer()
        await self.update_panel('sort')

    @discord.ui.button(label='Clear Filters', style=discord.ButtonStyle.secondary, row=1)
    async def clear_button(self, interaction, button):
        self.filters.clear()
        self.page = 0
        await interaction.response.defer()
        await self.refresh()
        await self.update_panel('home', notice='Filters cleared.')

    async def cart_summary(self):
        """Totals for this collector's cart items belonging to the current vendor."""
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT COALESCE(SUM(ci.quantity), 0) AS card_count,
                       COALESCE(SUM(ci.quantity * i.price), 0) AS subtotal
                FROM cart_items ci
                JOIN inventory i ON i.inventory_id = ci.inventory_id
                WHERE ci.user_id = $1 AND i.guild_id = $2
            """, self.owner_id, self.guild_id)
        return int(row['card_count']), row['subtotal']

    async def add_to_cart(self, interaction, inventory_id):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db.acquire() as conn:
            async with conn.transaction():
                inv = await conn.fetchrow("""
                    SELECT pokemon_name, set_name, quantity_available
                    FROM inventory
                    WHERE inventory_id=$1 AND guild_id=$2 AND is_active=TRUE
                      AND quantity_available > 0 AND csv_id IS DISTINCT FROM 'sealed_add'
                    FOR UPDATE
                """, inventory_id, self.guild_id)
                if not inv:
                    await self.update_panel('home', notice='This card is no longer available.')
                    return
                cart = await conn.fetchrow("""
                    SELECT quantity FROM cart_items
                    WHERE user_id=$1 AND inventory_id=$2 FOR UPDATE
                """, self.owner_id, inventory_id)
                if (cart['quantity'] if cart else 0) >= inv['quantity_available']:
                    await self.update_panel('home', notice='You already have the maximum available quantity of this card in your cart.')
                    return
                await conn.execute("""
                    INSERT INTO cart_items (user_id, inventory_id, quantity)
                    VALUES ($1,$2,1)
                    ON CONFLICT (user_id, inventory_id)
                    DO UPDATE SET quantity=cart_items.quantity+1
                """, self.owner_id, inventory_id)
        await self.update_panel('cart', notice=f"Added **{inv['pokemon_name']} — {inv['set_name']}** to your cart.")

    async def more_info(self, interaction, inventory_id):
        async with self.bot.db.acquire() as conn:
            r = await conn.fetchrow("SELECT pokemon_name, series, set_name, card_number, variant, rarity, condition, illustrator, price, quantity_available, image_link FROM inventory WHERE inventory_id=$1 AND guild_id=$2 AND is_active=TRUE AND csv_id IS DISTINCT FROM 'sealed_add'", inventory_id, self.guild_id)
        if not r:
            await interaction.response.send_message('Card not found.', ephemeral=True)
            return
        embed = discord.Embed(title=r['pokemon_name'] or 'Card details', description=f"**Series:** {r['series'] or '—'}\n**Set:** {r['set_name'] or '—'}\n**Card #:** {r['card_number'] or '—'}\n**Variant:** {r['variant'] or '—'}\n**Rarity:** {r['rarity'] or '—'}\n**Condition:** {r['condition'] or '—'}\n**Illustrator:** {r['illustrator'] or '—'}\n**Price:** {money(r['price'])}\n**Available:** {r['quantity_available']}", color=discord.Color.blue())
        if r['image_link']:
            embed.set_image(url=r['image_link'])
        await interaction.response.defer()
        await self.update_panel('details', card=r)


class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def where(self, filters, guild_id):
        clauses = ['guild_id = $1', 'is_active = TRUE', 'quantity_available >= 1', "csv_id IS DISTINCT FROM 'sealed_add'"]
        params = [guild_id]
        for field, value in (filters or {}).items():
            if field not in ALLOWED_FILTERS and field != 'pokemon_name':
                raise ValueError(f'Unsupported filter: {field}')
            if not value:
                continue
            param = f'${len(params) + 1}'
            if field in ('pokemon_name', 'illustrator'):
                clauses.append(f'LOWER({field}) LIKE LOWER({param})')
                params.append(f'%{value}%')
            else:
                clauses.append(f'{field} = {param}')
                params.append(value)
        return ' AND '.join(clauses), params

    async def count_query(self, filters, guild_id):
        where, params = self.where(filters, guild_id)
        async with self.bot.db.acquire() as conn:
            return await conn.fetchval(f'SELECT COUNT(*) FROM inventory WHERE {where}', *params)

    async def page_query(self, filters, guild_id, sort, page):
        where, params = self.where(filters, guild_id)
        order = SORTS.get(sort, SORTS['price_asc'])
        params.extend([GALLERY_PAGE_SIZE, page * GALLERY_PAGE_SIZE])
        async with self.bot.db.acquire() as conn:
            return await conn.fetch(f'SELECT inventory_id,pokemon_name,series,set_name,card_number,variant,rarity,price,quantity_available,condition,illustrator,image_link FROM inventory WHERE {where} ORDER BY {order} LIMIT ${len(params)-1} OFFSET ${len(params)}', *params)

    async def get_distinct_values(self, column_name, guild_id):
        if column_name not in ALLOWED_FILTERS:
            raise ValueError('Invalid filter column')
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(f"SELECT DISTINCT {column_name} FROM inventory WHERE guild_id=$1 AND is_active=TRUE AND quantity_available>=1 AND csv_id IS DISTINCT FROM 'sealed_add' AND {column_name} IS NOT NULL ORDER BY {column_name}", guild_id)
        return [r[column_name] for r in rows if str(r[column_name]).strip()]

    async def start_singles_inventory(self, interaction, pokemon_name, set_name):
        gallery = InventoryGallery(self, interaction.user.id, interaction.guild.id, pokemon_name, set_name)
        await gallery.load()
        gallery.message = await interaction.followup.send(embeds=gallery.embeds(), view=gallery, ephemeral=True, wait=True)
        gallery.panel_message = await interaction.followup.send(embed=gallery.panel_embed(), view=ControlPanel(gallery), ephemeral=True, wait=True)


async def setup(bot):
    await bot.add_cog(Inventory(bot))
