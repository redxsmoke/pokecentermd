"""Discord /vendorcalculator, with PostgreSQL transaction recording.

Install vendor_sales_schema.sql before loading this extension.
Requires bot.db (asyncpg pool) and guild_settings(guild_id, admin_id).
All money is stored in integer cents. No coins are moved.
"""

import asyncio
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import discord
from discord import app_commands
from discord.ext import commands

MAX_CARDS = 40
CENT = Decimal('0.01')


def parse_money(value: str) -> int:
    cleaned = value.strip().replace(',', '').replace('$', '')
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError('Enter a valid dollar amount, such as 125.50.') from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal('100000000'):
        raise ValueError('Enter a non-negative amount of no more than $100,000,000.')
    if amount != amount.quantize(CENT):
        raise ValueError('Amounts can have at most two decimal places.')
    return int(amount * 100)


def parse_optional_money(value: str):
    return parse_money(value) if value.strip() else None


def parse_percent(value: str) -> Decimal:
    try:
        percent = Decimal(value.strip().replace('%', ''))
    except InvalidOperation as exc:
        raise ValueError('Enter a percentage such as 82.5.') from exc
    if not percent.is_finite() or not (Decimal('0') <= percent <= Decimal('100')):
        raise ValueError('Percentage must be between 0 and 100.')
    if percent.as_tuple().exponent < -2:
        raise ValueError('Use no more than two decimal places for percentages.')
    return percent


def trade_cents(market_cents: int, percent: Decimal) -> int:
    return int((Decimal(market_cents) * percent / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def dollars(cents: int) -> str:
    return f'${Decimal(cents) / 100:,.2f}'


def pct(percent: Decimal) -> str:
    return f'{percent.normalize():f}%'


def parse_quantity(value: str) -> int:
    try:
        quantity = int(value.strip() or '1')
    except ValueError as exc:
        raise ValueError('Quantity must be a whole number between 1 and 999.') from exc
    if not 1 <= quantity <= 999:
        raise ValueError('Quantity must be between 1 and 999.')
    return quantity


def safe(value: str) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(value))


@dataclass
class Card:
    name: str
    market_cents: int
    percent: Decimal
    trade_cents: int
    quantity: int = 1


@dataclass
class SaleCard:
    name: str
    sale_cents: int
    market_cents: int | None = None
    quantity: int = 1


class VendorSession:
    def __init__(self, owner_id: int, guild_id: int, customer_name: str):
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.customer_name = customer_name
        self.mode: str | None = None  # trade, buy (vendor buys), sale (vendor sells)
        self.cards: list[Card] = []
        self.sale_cards: list[SaleCard] = []
        self.pending_name: str | None = None
        self.pending_market: int | None = None
        self.pending_quantity: int = 1
        self.original_sale_cents: int | None = None
        self.sale_total_cents: int = 0
        self.preview = False
        self.completed = False
        self.cancelled = False
        self.transaction_id: int | None = None
        self.session_id = uuid.uuid4()
        self.complete_lock = asyncio.Lock()
        self.adjusted_net_cents: int | None = None

    @property
    def total_trade(self):
        return sum(c.trade_cents * c.quantity for c in self.cards)

    @property
    def total_market(self):
        return sum(c.market_cents * c.quantity for c in self.cards)

    @property
    def total_sale(self):
        return sum(c.sale_cents * c.quantity for c in self.sale_cards)

    @property
    def net(self):
        return self.adjusted_net_cents if self.adjusted_net_cents is not None else self.total_sale - self.total_trade

    @property
    def adjustment_cents(self):
        return self.net - (self.total_sale - self.total_trade)

    def _description(self, *, heading=None, include_totals=False):
        lines = [f'**Customer:** {safe(self.customer_name)}']
        if heading:
            lines.extend(['', heading])
        if self.cards:
            lines.extend(['', '**CUSTOMER CARDS**', '━━━━━━━━━━━━━━━━━━━━'])
            for i, c in enumerate(self.cards, 1):
                lines.extend([f'**{i}. {safe(c.name)}** × {c.quantity}',
                              f'Market: {dollars(c.market_cents)} each | Rate: {pct(c.percent)} | **Offer: {dollars(c.trade_cents * c.quantity)}**', ''])
        if self.sale_cards:
            lines.extend(['', '**YOUR SALE CARDS**', '━━━━━━━━━━━━━━━━━━━━'])
            for i, c in enumerate(self.sale_cards, 1):
                line = f'**{i}. {safe(c.name)}** × {c.quantity} — {dollars(c.sale_cents * c.quantity)} ({dollars(c.sale_cents)} each)'
                if c.market_cents is not None:
                    line += f' (market: {dollars(c.market_cents)} each)'
                lines.append(line)
        if include_totals:
            lines.extend(['', '━━━━━━━━━━━━━━━━━━━━'])
            if self.mode != 'sale':
                lines.extend([f'**Total customer card market value:** {dollars(self.total_market)}',
                              f'**Total vendor offer / trade value:** {dollars(self.total_trade)}', ''])
            if self.mode != 'buy':
                lines.extend([f'**Your sale value:** {dollars(self.total_sale)}', ''])
            if self.adjusted_net_cents is not None:
                lines.extend([f'**Original net cash:** {"+" if self.total_sale - self.total_trade >= 0 else "-"}{dollars(abs(self.total_sale - self.total_trade))}',
                              f'**Manual adjustment:** {"+" if self.adjustment_cents >= 0 else "-"}{dollars(abs(self.adjustment_cents))}', ''])
            if self.net > 0:
                lines.append(f'**💵 CUSTOMER OWES: {dollars(self.net)}**')
            elif self.net < 0:
                label = '💰 VENDOR WILL PAY' if self.mode == 'buy' else '💸 YOU OWE'
                lines.append(f'**{label}: {dollars(-self.net)}**')
            else:
                lines.append('**✅ EVEN TRANSACTION: $0.00**')
        return '\n'.join(lines).strip()

    def embed(self, title='🧮 Vendor Calculator', heading=None, *, final=False, completed=False):
        description = self._description(heading=heading, include_totals=final)
        embed = discord.Embed(title=title, color=discord.Color.green() if final else discord.Color.blurple())
        # Discord embed descriptions are limited to 4096 chars; fields are limited to 1024.
        if len(description) <= 4096:
            embed.description = description
        else:
            blocks = description.split('\n\n')
            embed.description = ''
            for block in blocks:
                if len(embed.description) + len(block) + 2 <= 3900:
                    embed.description += ('\n\n' if embed.description else '') + block
                else:
                    for start in range(0, len(block), 1000):
                        embed.add_field(name='Cards (continued)', value=block[start:start+1000] or '—', inline=False)
        if completed:
            embed.add_field(name='✅ Transaction completed', value=f'**Transaction #{self.transaction_id}**', inline=False)
        elif final:
            embed.set_footer(text='Review amounts, then select Complete Transaction to save to the database.')
        return embed


class OwnerView(discord.ui.View):
    def __init__(self, session: VendorSession):
        super().__init__(timeout=900)
        self.session = session

    async def interaction_check(self, interaction):
        if interaction.user.id != self.session.owner_id:
            await interaction.response.send_message('Only the admin who started this calculator can use its controls.', ephemeral=True)
            return False
        if self.session.completed or self.session.cancelled:
            await interaction.response.send_message('This calculator session has ended.', ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        # Keep the public preview visible, but no longer allow saving after expiry.
        self.session.cancelled = True
        self.stop()


class CustomerNameModal(discord.ui.Modal, title='Vendor Calculator · Customer'):
    customer_name = discord.ui.TextInput(label='Customer Name (Optional)', required=False,
                                          placeholder='Leave blank for Walk-in Customer', max_length=100)

    def __init__(self, owner_id, guild_id):
        super().__init__()
        self.owner_id, self.guild_id = owner_id, guild_id

    async def on_submit(self, interaction):
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message('This session is not yours.', ephemeral=True)
            return
        session = VendorSession(self.owner_id, self.guild_id,
                                str(self.customer_name).strip() or 'Walk-in Customer')
        await interaction.response.send_message(embed=session.embed(heading=(
            '**Select a transaction type**\n'
            '🔄 **Trade-In:** Customer trades cards toward a purchase.\n'
            '💵 **Customer Selling:** You buy cards from the customer.\n'
            '🛒 **No Trade:** Customer buys cards from you without a trade-in.')),
            view=StartView(session), ephemeral=False)


class StartView(OwnerView):
    @discord.ui.button(label='Trading', emoji='🔄', style=discord.ButtonStyle.primary)
    async def trade(self, interaction, button):
        self.session.mode = 'trade'
        await interaction.response.send_modal(CustomerCardModal(self.session))

    @discord.ui.button(label='Buying', emoji='💵', style=discord.ButtonStyle.success)
    async def buy(self, interaction, button):
        self.session.mode = 'buy'
        await interaction.response.send_modal(CustomerCardModal(self.session))

    @discord.ui.button(label='Selling', emoji='🛒', style=discord.ButtonStyle.secondary)
    async def sale(self, interaction, button):
        self.session.mode = 'sale'
        await interaction.response.send_modal(SaleCardModal(self.session))

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        self.session.cancelled = True
        await interaction.response.edit_message(embed=self.session.embed('Vendor Calculator · Cancelled'), view=None)


class CustomerCardModal(discord.ui.Modal, title='Enter Customer Card'):
    card_name = discord.ui.TextInput(label='Card Name', required=False, max_length=100)
    market_price = discord.ui.TextInput(label='Market Price per Card ($)', required=True, placeholder='e.g. 125.50', max_length=20)
    quantity = discord.ui.TextInput(label='Quantity', required=False, default='1', max_length=3)

    def __init__(self, session):
        super().__init__()
        self.session = session

    async def on_submit(self, interaction):
        s = self.session
        if s.preview or s.completed or s.cancelled or interaction.user.id != s.owner_id or s.mode not in ('trade', 'buy'):
            await interaction.response.send_message('This session is no longer accepting cards.', ephemeral=True)
            return
        if len(s.cards) >= MAX_CARDS:
            await interaction.response.send_message('Card limit reached.', ephemeral=True)
            return
        try:
            market = parse_money(str(self.market_price))
            quantity = parse_quantity(str(self.quantity))
        except ValueError as exc:
            await interaction.response.send_message(f'❌ {exc}', ephemeral=True)
            return
        s.pending_name = str(self.card_name).strip() or f'Card {len(s.cards)+1}'
        s.pending_market = market
        s.pending_quantity = quantity
        await interaction.response.edit_message(embed=s.embed('Select Buying / Trading Percentage',
            f'**{safe(s.pending_name)}** × {quantity} · Market: {dollars(market)} each\nChoose the percentage to offer.'),
            view=PercentView(s))


class PercentView(OwnerView):
    async def choose(self, interaction, percentage):
        s = self.session
        if s.completed or s.cancelled:
            await interaction.response.send_message('This session has ended.', ephemeral=True)
            return
        if s.preview or s.pending_market is None or len(s.cards) >= MAX_CARDS:
            await interaction.response.send_message('No card is awaiting a percentage.', ephemeral=True)
            return
        s.cards.append(Card(s.pending_name, s.pending_market, percentage,
                            trade_cents(s.pending_market, percentage), s.pending_quantity))
        s.pending_name = s.pending_market = None
        s.pending_quantity = 1
        await interaction.response.edit_message(embed=s.embed('Customer Card Added',
            'Add another customer card or finish.'), view=AfterCustomerCardView(s))

    @discord.ui.button(label='70%', row=0, style=discord.ButtonStyle.primary)
    async def p70(self, i, b): await self.choose(i, Decimal(70))
    @discord.ui.button(label='75%', row=0, style=discord.ButtonStyle.primary)
    async def p75(self, i, b): await self.choose(i, Decimal(75))
    @discord.ui.button(label='80%', row=0, style=discord.ButtonStyle.primary)
    async def p80(self, i, b): await self.choose(i, Decimal(80))
    @discord.ui.button(label='85%', row=0, style=discord.ButtonStyle.primary)
    async def p85(self, i, b): await self.choose(i, Decimal(85))
    @discord.ui.button(label='90%', row=0, style=discord.ButtonStyle.primary)
    async def p90(self, i, b): await self.choose(i, Decimal(90))
    @discord.ui.button(label='Custom', row=1, style=discord.ButtonStyle.secondary)
    async def custom(self, i, b): await i.response.send_modal(CustomPercentModal(self.session))


class CustomPercentModal(discord.ui.Modal, title='Custom Percentage'):
    percent = discord.ui.TextInput(label='Percentage (%)', required=True, placeholder='e.g. 82.5', max_length=12)
    def __init__(self, session):
        super().__init__()
        self.session = session
    async def on_submit(self, interaction):
        if interaction.user.id != self.session.owner_id or self.session.completed or self.session.cancelled:
            await interaction.response.send_message('This session is no longer available.', ephemeral=True)
            return
        try:
            rate = parse_percent(str(self.percent))
        except ValueError as exc:
            await interaction.response.send_message(f'❌ {exc}', ephemeral=True)
            return
        await PercentView(self.session).choose(interaction, rate)


class RemoveCardSelect(discord.ui.Select):
    """Choose a card by its current number and name (25 options per page)."""
    def __init__(self, session, card_type, page):
        cards = session.cards if card_type == 'customer' else session.sale_cards
        start = page * 25
        options = [discord.SelectOption(
            label=f'{idx + 1}. {card.name}'[:100],
            value=str(idx),
            description=f'Quantity: {card.quantity}'
        ) for idx, card in enumerate(cards) if start <= idx < start + 25]
        super().__init__(placeholder='Select the card to remove...', options=options, row=0)
        self.card_type = card_type

    async def callback(self, interaction):
        view = self.view
        session = view.session
        cards = session.cards if self.card_type == 'customer' else session.sale_cards
        index = int(self.values[0])
        if index >= len(cards):
            await interaction.response.send_message('That card is no longer in the cart.', ephemeral=True)
            return
        removed = cards.pop(index)
        # Return to the appropriate cart with updated totals and card numbers.
        if self.card_type == 'customer':
            next_view = AfterCustomerCardView(session)
            title = 'Customer Card Removed'
        else:
            next_view = AfterSaleCardView(session) if cards else (TradeSaleStartView(session) if session.mode == 'trade' else SaleCartEmptyView(session))
            title = 'Sale Card Removed'
        await interaction.response.edit_message(
            embed=session.embed(title, f'Removed **{safe(removed.name)}** × {removed.quantity}.\nAdd another card, remove a card, or finish.'),
            view=next_view)


class RemoveCardView(OwnerView):
    def __init__(self, session, card_type, page=0):
        super().__init__(session)
        self.card_type = card_type
        cards = session.cards if card_type == 'customer' else session.sale_cards
        self.page = max(0, min(page, (len(cards) - 1) // 25))
        self.add_item(RemoveCardSelect(session, card_type, self.page))
        self.previous.disabled = self.page == 0
        self.next.disabled = (self.page + 1) * 25 >= len(cards)

    @discord.ui.button(label='Previous', emoji='◀️', style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, interaction, button):
        await interaction.response.edit_message(
            embed=self.session.embed('Remove Card', 'Select the card you want to remove.'),
            view=RemoveCardView(self.session, self.card_type, self.page - 1))

    @discord.ui.button(label='Next', emoji='▶️', style=discord.ButtonStyle.secondary, row=1)
    async def next(self, interaction, button):
        await interaction.response.edit_message(
            embed=self.session.embed('Remove Card', 'Select the card you want to remove.'),
            view=RemoveCardView(self.session, self.card_type, self.page + 1))

    @discord.ui.button(label='Back to Cart', emoji='↩️', style=discord.ButtonStyle.primary, row=1)
    async def back(self, interaction, button):
        if self.card_type == 'customer':
            view = AfterCustomerCardView(self.session)
        else:
            view = AfterSaleCardView(self.session)
        await interaction.response.edit_message(
            embed=self.session.embed('Vendor Calculator · Cart', 'Continue adding cards or finish.'), view=view)


class SaleCartEmptyView(OwnerView):
    @discord.ui.button(label='Add Sale Card', emoji='➕', style=discord.ButtonStyle.primary)
    async def add(self, interaction, button):
        await interaction.response.send_modal(SaleCardModal(self.session))

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        self.session.cancelled = True
        await interaction.response.edit_message(embed=self.session.embed('Vendor Calculator · Cancelled'), view=None)


class AfterCustomerCardView(OwnerView):
    @discord.ui.button(label='Remove Card', emoji='🗑️', style=discord.ButtonStyle.secondary)
    async def remove(self, i, b):
        if not self.session.cards:
            await i.response.send_message('There are no customer cards to remove.', ephemeral=True)
            return
        await i.response.edit_message(embed=self.session.embed('Remove Customer Card',
            'Choose the card number and name to remove.'), view=RemoveCardView(self.session, 'customer'))

    @discord.ui.button(label='Add Another Card', emoji='➕', style=discord.ButtonStyle.primary)
    async def add(self, i, b):
        if len(self.session.cards) >= MAX_CARDS:
            await i.response.send_message('Maximum number of cards reached.', ephemeral=True)
            return
        await i.response.send_modal(CustomerCardModal(self.session))

    @discord.ui.button(label='Finish', emoji='✅', style=discord.ButtonStyle.success)
    async def finish(self, i, b):
        s = self.session
        if not s.cards:
            await i.response.send_message('Enter at least one customer card before finishing.', ephemeral=True)
            return
        if s.mode == 'trade':
            await i.response.edit_message(embed=s.embed('🔄 Trade-In · Your Sale Cards',
                'Now enter each card you are selling to the customer.'), view=TradeSaleStartView(s))
        else:
            s.preview = True
            await i.response.edit_message(embed=s.embed('💵 Customer Selling · Review', final=True), view=CompleteView(s))

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, i, b):
        self.session.cancelled = True
        await i.response.edit_message(embed=self.session.embed('Vendor Calculator · Cancelled'), view=None)


class TradeSaleStartView(OwnerView):
    @discord.ui.button(label='Enter Sale Card', emoji='➕', style=discord.ButtonStyle.primary)
    async def add(self, i, b):
        await i.response.send_modal(SaleCardModal(self.session))

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, i, b):
        self.session.cancelled = True
        await i.response.edit_message(embed=self.session.embed('Vendor Calculator · Cancelled'), view=None)


class SaleCardModal(discord.ui.Modal, title='Enter Your Sale Card'):
    card_name = discord.ui.TextInput(label='Card Name (Optional)', required=False, max_length=100)
    sale_price = discord.ui.TextInput(label='Selling Price per Card ($)', required=True, max_length=20)
    market_price = discord.ui.TextInput(label='Market Price per Card ($) — Optional', required=False, max_length=20)
    quantity = discord.ui.TextInput(label='Quantity', required=False, default='1', max_length=3)
    def __init__(self, session):
        super().__init__()
        self.session = session
    async def on_submit(self, interaction):
        s = self.session
        if interaction.user.id != s.owner_id or s.completed or s.cancelled or s.preview or s.mode not in ('sale', 'trade'):
            await interaction.response.send_message('This session is no longer available.', ephemeral=True)
            return
        if len(s.sale_cards) >= MAX_CARDS:
            await interaction.response.send_message('Card limit reached.', ephemeral=True)
            return
        try:
            amount = parse_money(str(self.sale_price))
            market = parse_optional_money(str(self.market_price))
            quantity = parse_quantity(str(self.quantity))
        except ValueError as exc:
            await interaction.response.send_message(f'❌ {exc}', ephemeral=True)
            return
        s.sale_cards.append(SaleCard(str(self.card_name).strip() or f'Card {len(s.sale_cards)+1}', amount, market, quantity))
        await interaction.response.edit_message(embed=s.embed('🛒 Your Sale Cards',
            'Add another sale card or finish.'), view=AfterSaleCardView(s))


class AfterSaleCardView(OwnerView):
    @discord.ui.button(label='Remove Card', emoji='🗑️', style=discord.ButtonStyle.secondary)
    async def remove(self, i, b):
        if not self.session.sale_cards:
            await i.response.send_message('There are no sale cards to remove.', ephemeral=True)
            return
        await i.response.edit_message(embed=self.session.embed('Remove Sale Card',
            'Choose the card number and name to remove.'), view=RemoveCardView(self.session, 'sale'))

    @discord.ui.button(label='Add Another Card', emoji='➕', style=discord.ButtonStyle.primary)
    async def add(self, i, b):
        if len(self.session.sale_cards) >= MAX_CARDS:
            await i.response.send_message('Maximum number of cards reached.', ephemeral=True)
            return
        await i.response.send_modal(SaleCardModal(self.session))

    @discord.ui.button(label='Finish', emoji='✅', style=discord.ButtonStyle.success)
    async def finish(self, i, b):
        if not self.session.sale_cards:
            await i.response.send_message('Enter at least one sale card.', ephemeral=True)
            return
        self.session.preview = True
        title = '🔄 Trade-In · Review' if self.session.mode == 'trade' else '🛒 Customer Buying · Review'
        await i.response.edit_message(embed=self.session.embed(title, final=True),
                                      view=CompleteView(self.session))

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, i, b):
        self.session.cancelled = True
        await i.response.edit_message(embed=self.session.embed('Vendor Calculator · Cancelled'), view=None)


async def save_transaction(bot, s: VendorSession) -> int:
    """Atomically insert summary + item rows; unique session ID makes retries idempotent."""
    async with bot.db.acquire() as conn:
        async with conn.transaction():
            transaction_id = await conn.fetchval('''
                INSERT INTO sales (session_id, guild_id, admin_id, customer_name, transaction_type,
                    original_price_cents, market_price_cents, purchase_price_cents,
                    sale_price_cents, net_amount_cents, adjustment_cents)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (session_id) DO UPDATE SET session_id = EXCLUDED.session_id
                RETURNING transaction_id
            ''', s.session_id, s.guild_id, s.owner_id, s.customer_name, s.mode,
                None,
                s.total_market, s.total_trade, s.total_sale, s.net, s.adjustment_cents)
            # The unique constraint also protects item rows against retry inserts.
            for idx, card in enumerate(s.cards, 1):
                await conn.execute('''
                    INSERT INTO sales_items (transaction_id, item_number, item_type, card_name,
                        market_price_cents, original_price_cents, rate, final_price_cents, quantity)
                    VALUES ($1,$2,'acquired',$3,$4,NULL,$5,$6,$7)
                    ON CONFLICT (transaction_id, item_type, item_number) DO NOTHING
                ''', transaction_id, idx, card.name, card.market_cents, card.percent, card.trade_cents, card.quantity)
            for idx, card in enumerate(s.sale_cards, 1):
                await conn.execute('''
                    INSERT INTO sales_items (transaction_id, item_number, item_type, card_name,
                        market_price_cents, original_price_cents, rate, final_price_cents, quantity)
                    VALUES ($1,$2,'sold',$3,$4,$5,NULL,$6,$7)
                    ON CONFLICT (transaction_id, item_type, item_number) DO NOTHING
                ''', transaction_id, idx, card.name, card.market_cents, None, card.sale_cents, card.quantity)
            return transaction_id


class AdjustFinalAmountModal(discord.ui.Modal, title='Adjust Final Amount'):
    amount = discord.ui.TextInput(label='Final amount ($)', placeholder='e.g. 25.00', required=True, max_length=18)
    direction = discord.ui.TextInput(label='Who pays? (CUSTOMER / VENDOR / EVEN)',
                                     placeholder='CUSTOMER, VENDOR, or EVEN', required=True, max_length=10)

    def __init__(self, session: VendorSession):
        super().__init__()
        self.session = session
        self.amount.default = f'{abs(session.net) / 100:.2f}'
        self.direction.default = 'CUSTOMER' if session.net > 0 else 'VENDOR' if session.net < 0 else 'EVEN'

    async def on_submit(self, interaction: discord.Interaction):
        s = self.session
        if s.completed or s.cancelled or not s.preview or interaction.user.id != s.owner_id:
            await interaction.response.send_message('This transaction cannot be adjusted.', ephemeral=True)
            return
        try:
            amount = parse_money(str(self.amount))
            direction = str(self.direction).strip().upper()
            if direction not in ('CUSTOMER', 'VENDOR', 'EVEN'):
                raise ValueError('Who pays must be CUSTOMER, VENDOR, or EVEN.')
            if direction == 'EVEN' and amount != 0:
                raise ValueError('Set the final amount to 0 for an even transaction.')
            if direction != 'EVEN' and amount == 0:
                direction = 'EVEN'
            s.adjusted_net_cents = amount if direction == 'CUSTOMER' else -amount if direction == 'VENDOR' else 0
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=s.embed('🧾 Vendor Transaction · Adjusted Review', final=True),
            view=CompleteView(s))


class CompleteView(OwnerView):
    @discord.ui.button(label='Adjust Final Amount', emoji='✏️', style=discord.ButtonStyle.primary)
    async def adjust(self, interaction, button):
        await interaction.response.send_modal(AdjustFinalAmountModal(self.session))

    @discord.ui.button(label='Complete Transaction', emoji='💾', style=discord.ButtonStyle.success)
    async def complete(self, interaction, button):
        s = self.session
        if not s.preview:
            await interaction.response.send_message('Finish entering cards first.', ephemeral=True)
            return
        async with s.complete_lock:
            if s.completed:
                await interaction.response.send_message(f'Transaction #{s.transaction_id} is already saved.', ephemeral=True)
                return
            await interaction.response.defer()  # Public message; DB writes may take time.
            try:
                # Revalidate the configured guild admin before writing.
                async with interaction.client.db.acquire() as conn:
                    admin_id = await conn.fetchval('SELECT admin_id FROM guild_settings WHERE guild_id=$1', s.guild_id)
                if str(admin_id) != str(s.owner_id):
                    await interaction.followup.send('⛔ Guild admin permissions have changed. Nothing was saved.', ephemeral=True)
                    return
                transaction_id = await save_transaction(interaction.client, s)
            except Exception:
                await interaction.followup.send('❌ Database save failed. No new transaction was confirmed. You can retry.', ephemeral=True)
                return
            s.transaction_id = transaction_id
            s.completed = True
            self.stop()
            try:
                await interaction.edit_original_response(embed=s.embed('✅ Vendor Transaction · Completed',
                    final=True, completed=True), view=None)
            except discord.HTTPException:
                # Data was saved even if Discord couldn't update the receipt.
                await interaction.followup.send(f'✅ Transaction #{transaction_id} saved, but the receipt could not be updated.', ephemeral=True)

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        self.session.cancelled = True
        self.stop()
        await interaction.response.edit_message(embed=self.session.embed('Vendor Calculator · Cancelled'), view=None)


class VendorCalculator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='vendorcalculator', description='Track card sales, trade-ins, and purchases.')
    @app_commands.guild_only()
    async def vendorcalculator(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            admin_id = await conn.fetchval('SELECT admin_id FROM guild_settings WHERE guild_id=$1', interaction.guild_id)
        if admin_id is None or str(admin_id) != str(interaction.user.id):
            await interaction.response.send_message(
                '⛔ Only the guild admin configured in guild_settings.admin_id can use this command.', ephemeral=True)
            return
        await interaction.response.send_modal(CustomerNameModal(interaction.user.id, interaction.guild_id))


async def setup(bot):
    await bot.add_cog(VendorCalculator(bot))
