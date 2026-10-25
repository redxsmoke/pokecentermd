"""Vendor trade / purchase calculator for discord.py 2.x.

Extension: adjust the load_extension path to match your bot's folder structure.
Requires bot.db (asyncpg pool) and guild_settings(guild_id, admin_id).
No new database tables are required. All calculations are session-only.
"""

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
        raise ValueError('Market prices can have at most two decimal places.')
    return int(amount * 100)


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
    return int((Decimal(market_cents) * percent / Decimal(100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def dollars(cents: int) -> str:
    return f'${cents / 100:,.2f}'


def pct(percent: Decimal) -> str:
    return f'{percent.normalize():f}%'


@dataclass
class Card:
    name: str
    market_cents: int
    percent: Decimal
    trade_cents: int


class VendorSession:
    def __init__(self, owner_id: int, guild_id: int):
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.cards: list[Card] = []
        self.sale_cards: list[tuple[str, int]] = []
        self.mode = "trade"  # trade, buy, or sell
        self.pending_name: str | None = None
        self.pending_market: int | None = None
        self.finished = False
        self.cancelled = False

    @property
    def total_trade(self) -> int:
        return sum(card.trade_cents for card in self.cards)

    def _card_blocks(self) -> list[str]:
        """Use one embed text block rather than separate fields per card.

        Discord adds large padding around embed fields, but not between lines
        within the same description.
        """
        blocks = []
        for i, card in enumerate(self.cards, 1):
            name = discord.utils.escape_markdown(card.name[:55] or f'Card {i}')
            blocks.append(
                f'**{i}. {name}**\n'
                f'Market: {dollars(card.market_cents)}  |  '
                f'Rate: {pct(card.percent)}  |  '
                f'**Trade: {dollars(card.trade_cents)}**'
            )
        return blocks

    def _add_card_details(self, embed: discord.Embed, *, instructions=None):
        # A single description avoids Discord's automatic spacing between fields.
        parts = []
        if instructions:
            parts.append(instructions)
        if self.cards:
            parts.append('**CUSTOMER CARDS**\n━━━━━━━━━━━━━━━━━━━━')
            parts.extend(self._card_blocks())
        else:
            parts.append('No customer cards entered yet.')

        description = ''
        for part in parts:
            separator = '\n\n' if description else ''
            if len(description) + len(separator) + len(part) <= 3900:
                description += separator + part
            else:
                # Only very large 40-card carts overflow the description limit.
                # Keep full card records intact in a continuation field.
                if not embed.description:
                    embed.description = description
                embed.add_field(name='Customer cards (continued)', value=part[:1024], inline=False)
        if not embed.description:
            embed.description = description

    def summary(self, *, heading='Vendor Calculator', instructions=None) -> discord.Embed:
        embed = discord.Embed(title=heading, color=discord.Color.blurple())
        self._add_card_details(embed, instructions=instructions)
        total_label = 'Total vendor offer' if self.mode == 'sell' else 'Total customer trade value'
        if self.mode != 'buy':
            embed.add_field(name=total_label, value=f'**{dollars(self.total_trade)}**', inline=False)
        return embed

    def buying_result(self) -> discord.Embed:
        embed = discord.Embed(title='🛒 Vendor Calculator · Customer Buying', color=discord.Color.green())
        lines = []
        for i, (name, price) in enumerate(self.sale_cards, 1):
            safe_name = discord.utils.escape_markdown(name[:55] or f'Card {i}')
            lines.append(f'**{i}. {safe_name}** — {dollars(price)}')
        batch = []
        size = 0
        for line in lines:
            if batch and size + len(line) + 1 > 1000:
                embed.add_field(name='Sale cards' if not embed.fields else 'Sale cards (continued)',
                                value='\n'.join(batch), inline=False)
                batch, size = [], 0
            batch.append(line)
            size += len(line) + 1
        if batch:
            embed.add_field(name='Sale cards' if not embed.fields else 'Sale cards (continued)',
                            value='\n'.join(batch), inline=False)
        total = sum(price for _, price in self.sale_cards)
        embed.add_field(name='💵 CUSTOMER OWES', value=f'**{dollars(total)}**', inline=False)
        embed.set_footer(text=f'{len(self.sale_cards)} card(s) · No trade-in applied.')
        return embed

    def buying_summary(self, instructions=None) -> discord.Embed:
        embed = discord.Embed(title='🛒 Customer Buying · Sale Cart', color=discord.Color.blurple(),
                              description=instructions)
        if self.sale_cards:
            lines = [f'**{i}. {discord.utils.escape_markdown(name[:55])}** — {dollars(price)}'
                     for i, (name, price) in enumerate(self.sale_cards, 1)]
            batch, size = [], 0
            for line in lines:
                if batch and size + len(line) + 1 > 1000:
                    embed.add_field(name='Sale cards' if not embed.fields else 'Sale cards (continued)',
                                    value='\n'.join(batch), inline=False)
                    batch, size = [], 0
                batch.append(line)
                size += len(line) + 1
            if batch:
                embed.add_field(name='Sale cards' if not embed.fields else 'Sale cards (continued)',
                                value='\n'.join(batch), inline=False)
        embed.add_field(name='Current sale total',
                        value=f'**{dollars(sum(price for _, price in self.sale_cards))}**', inline=False)
        return embed

    def selling_result(self) -> discord.Embed:
        embed = self.summary(heading='💵 Vendor Calculator · Customer Selling')
        embed.add_field(name='💰 VENDOR WILL PAY', value=f'**{dollars(self.total_trade)}**', inline=False)
        embed.color = discord.Color.green()
        embed.set_footer(text='Offer based on each card’s selected percentage of market value.')
        return embed

    def result(self, sale_cents: int) -> discord.Embed:
        difference = sale_cents - self.total_trade
        if difference > 0:
            balance_label, balance_value = '💵 CUSTOMER OWES', dollars(difference)
            color = discord.Color.green()
        elif difference < 0:
            balance_label, balance_value = '💸 YOU OWE', dollars(-difference)
            color = discord.Color.orange()
        else:
            balance_label, balance_value = '✅ EVEN TRADE', '$0.00 owed by either party'
            color = discord.Color.green()

        embed = discord.Embed(title='🧾 Vendor Calculator · Final Breakdown', color=color)
        self._add_card_details(embed)
        totals = (
            '━━━━━━━━━━━━━━━━━━━━\n'
            f'**Total customer trade value:**  {dollars(self.total_trade)}\n\n'
            f'**Your sale value:**  {dollars(sale_cents)}\n\n'
            '━━━━━━━━━━━━━━━━━━━━\n'
            f'**{balance_label}: {balance_value}**'
        )
        # Totals share the same description as the cards when space allows,
        # ensuring intentional, consistent spacing without embed field padding.
        if len(embed.description or '') + len(totals) + 2 <= 4096 and not embed.fields:
            embed.description += '\n\n' + totals
        else:
            embed.add_field(name='Transaction totals', value=totals, inline=False)
        embed.set_footer(text='Each card is rounded to the nearest cent before totals are calculated.')
        return embed


class OwnerView(discord.ui.View):
    def __init__(self, session: VendorSession):
        super().__init__(timeout=900)
        self.session = session

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.session.owner_id:
            await interaction.response.send_message('This calculator belongs to another user.', ephemeral=True)
            return False
        if self.session.finished or self.session.cancelled:
            await interaction.response.send_message('This calculator session has ended.', ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        self.session.cancelled = True
        self.stop()


class StartView(OwnerView):
    @discord.ui.button(label='Trade-In', style=discord.ButtonStyle.primary, emoji='🔄')
    async def trade_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.session.mode = 'trade'
        await interaction.response.send_modal(CardModal(self.session))

    @discord.ui.button(label='Customer Selling', style=discord.ButtonStyle.success, emoji='💵')
    async def customer_selling(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.session.mode = 'sell'
        await interaction.response.send_modal(CardModal(self.session))

    @discord.ui.button(label='No Trade', style=discord.ButtonStyle.secondary, emoji='🛒')
    async def no_trade(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.session.mode = 'buy'
        await interaction.response.send_modal(BuyCardModal(self.session))

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.session.cancelled = True
        self.stop()
        await interaction.response.edit_message(embed=discord.Embed(title='Vendor Calculator · Cancelled', color=discord.Color.red()), view=None)


class BuyCardModal(discord.ui.Modal, title='Enter Sale Card'):
    card_name = discord.ui.TextInput(label='Card Name', placeholder='Optional — e.g. Charizard ex',
                                     required=False, max_length=100)
    sale_price = discord.ui.TextInput(label='Sale Price ($)', placeholder='e.g. 125.50',
                                      required=True, max_length=20)

    def __init__(self, session: VendorSession):
        super().__init__()
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        if (interaction.user.id != self.session.owner_id or self.session.finished
                or self.session.cancelled or self.session.mode != 'buy'):
            await interaction.response.send_message('This calculator session is no longer available.', ephemeral=True)
            return
        if len(self.session.sale_cards) >= MAX_CARDS:
            await interaction.response.send_message(f'Maximum {MAX_CARDS} cards per calculation.', ephemeral=True)
            return
        try:
            price = parse_money(str(self.sale_price))
        except ValueError as exc:
            await interaction.response.send_message(f'❌ {exc} Please select Add Another Card and retry.', ephemeral=True)
            return
        name = str(self.card_name).strip() or f'Card {len(self.session.sale_cards) + 1}'
        self.session.sale_cards.append((name, price))
        await interaction.response.edit_message(
            embed=self.session.buying_summary('Add another sale card or finish to calculate the total.'),
            view=BuyAfterCardView(self.session))


class BuyAfterCardView(OwnerView):
    @discord.ui.button(label='Add Another Card', style=discord.ButtonStyle.primary, emoji='➕')
    async def add_another(self, interaction, button):
        if len(self.session.sale_cards) >= MAX_CARDS:
            await interaction.response.send_message(f'The limit is {MAX_CARDS} cards. Please finish.', ephemeral=True)
            return
        await interaction.response.send_modal(BuyCardModal(self.session))

    @discord.ui.button(label='Finish', style=discord.ButtonStyle.success, emoji='✅')
    async def finish(self, interaction, button):
        self.session.finished = True
        await interaction.response.edit_message(embed=self.session.buying_result(), view=None)

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        self.session.cancelled = True
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(title='Vendor Calculator · Cancelled', color=discord.Color.red()), view=None)


class CardModal(discord.ui.Modal, title='Enter Customer Card'):
    card_name = discord.ui.TextInput(label='Card Name', placeholder='Optional — e.g. Charizard ex', required=False, max_length=100)
    market_price = discord.ui.TextInput(label='Market Price ($)', placeholder='e.g. 125.50', required=True, max_length=20)

    def __init__(self, session: VendorSession):
        super().__init__()
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        if self.session.finished or self.session.cancelled or interaction.user.id != self.session.owner_id:
            await interaction.response.send_message('This calculator session is no longer available.', ephemeral=True)
            return
        if len(self.session.cards) >= MAX_CARDS:
            await interaction.response.send_message(f'Maximum {MAX_CARDS} cards per calculation.', ephemeral=True)
            return
        try:
            market = parse_money(str(self.market_price))
        except ValueError as exc:
            await interaction.response.send_message(f'❌ {exc} Please choose Enter Customer Card again.', ephemeral=True)
            return
        self.session.pending_name = str(self.card_name).strip() or f'Card {len(self.session.cards) + 1}'
        self.session.pending_market = market
        embed = self.session.summary(heading='Select Buying / Trading Percentage', instructions=(
            f'**{discord.utils.escape_markdown(self.session.pending_name)}**\n'
            f'Market price: **{dollars(market)}**\n\n'
            'Please select the percentage you will pay for this card.' if self.session.mode == 'sell'
            else 'Please select your buying/trading percentage for this card.'
        ))
        await interaction.response.edit_message(embed=embed, view=PercentView(self.session))


class PercentView(OwnerView):
    async def choose(self, interaction: discord.Interaction, percent: Decimal):
        if self.session.pending_market is None:
            await interaction.response.send_message('No card is waiting for a percentage.', ephemeral=True)
            return
        self.session.cards.append(Card(
            self.session.pending_name or f'Card {len(self.session.cards) + 1}',
            self.session.pending_market,
            percent,
            trade_cents(self.session.pending_market, percent)
        ))
        self.session.pending_name = None
        self.session.pending_market = None
        card = self.session.cards[-1]
        embed = self.session.summary(heading='Card Added', instructions=(
            f'Added **{discord.utils.escape_markdown(card.name)}** at **{pct(percent)}** '
            f'of {dollars(card.market_cents)} = **{dollars(card.trade_cents)}**.\n\n'
            'Add another card, finish, or cancel.'
        ))
        await interaction.response.edit_message(embed=embed, view=AfterCardView(self.session))

    @discord.ui.button(label='70%', style=discord.ButtonStyle.primary, row=0)
    async def p70(self, interaction, button):
        await self.choose(interaction, Decimal(70))

    @discord.ui.button(label='75%', style=discord.ButtonStyle.primary, row=0)
    async def p75(self, interaction, button):
        await self.choose(interaction, Decimal(75))

    @discord.ui.button(label='80%', style=discord.ButtonStyle.primary, row=0)
    async def p80(self, interaction, button):
        await self.choose(interaction, Decimal(80))

    @discord.ui.button(label='85%', style=discord.ButtonStyle.primary, row=0)
    async def p85(self, interaction, button):
        await self.choose(interaction, Decimal(85))

    @discord.ui.button(label='90%', style=discord.ButtonStyle.primary, row=0)
    async def p90(self, interaction, button):
        await self.choose(interaction, Decimal(90))

    @discord.ui.button(label='Custom', style=discord.ButtonStyle.secondary, row=1)
    async def custom(self, interaction, button):
        await interaction.response.send_modal(CustomPercentModal(self.session))


class CustomPercentModal(discord.ui.Modal, title='Custom Buying / Trading Percentage'):
    percent = discord.ui.TextInput(label='Percentage (%)', placeholder='e.g. 82.5', required=True, max_length=12)

    def __init__(self, session: VendorSession):
        super().__init__()
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.session.owner_id or self.session.finished or self.session.cancelled:
            await interaction.response.send_message('This session is no longer available.', ephemeral=True)
            return
        try:
            value = parse_percent(str(self.percent))
        except ValueError as exc:
            await interaction.response.send_message(f'❌ {exc} Please select Custom again.', ephemeral=True)
            return
        await PercentView(self.session).choose(interaction, value)


class AfterCardView(OwnerView):
    @discord.ui.button(label='Add Another Card', style=discord.ButtonStyle.primary, emoji='➕')
    async def add_another(self, interaction, button):
        if len(self.session.cards) >= MAX_CARDS:
            await interaction.response.send_message(f'The limit is {MAX_CARDS} cards. Please finish.', ephemeral=True)
            return
        await interaction.response.send_modal(CardModal(self.session))

    @discord.ui.button(label='Finish', style=discord.ButtonStyle.success, emoji='✅')
    async def finish(self, interaction, button):
        if self.session.mode == 'sell':
            self.session.finished = True
            await interaction.response.edit_message(embed=self.session.selling_result(), view=None)
        else:
            await interaction.response.send_modal(SaleModal(self.session))

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        self.session.cancelled = True
        self.stop()
        await interaction.response.edit_message(embed=discord.Embed(title='Vendor Calculator · Cancelled', color=discord.Color.red()), view=None)


class SaleModal(discord.ui.Modal, title='Enter Your Sale Value'):
    sale_value = discord.ui.TextInput(
        label='Total Value of Cards You Are Selling ($)',
        placeholder='e.g. 250.00', required=True, max_length=20
    )

    def __init__(self, session: VendorSession):
        super().__init__()
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.session.owner_id or self.session.finished or self.session.cancelled:
            await interaction.response.send_message('This session is no longer available.', ephemeral=True)
            return
        try:
            sale_cents = parse_money(str(self.sale_value))
        except ValueError as exc:
            await interaction.response.send_message(f'❌ {exc} Please select No Trade or Finish again.', ephemeral=True)
            return
        self.session.finished = True
        if self.session.mode == 'buy':
            embed = discord.Embed(title='🛒 Vendor Calculator · Customer Buying', color=discord.Color.green())
            embed.add_field(name='💵 CUSTOMER OWES', value=f'**{dollars(sale_cents)}**', inline=False)
        else:
            embed = self.session.result(sale_cents)
        await interaction.response.edit_message(embed=embed, view=None)


class VendorCalculator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='vendorcalculator', description='Calculate card buy/trade values and amounts owed.')
    @app_commands.guild_only()
    async def vendorcalculator(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            admin_id = await conn.fetchval(
                'SELECT admin_id FROM guild_settings WHERE guild_id = $1', interaction.guild_id
            )
        if admin_id is None or str(admin_id) != str(interaction.user.id):
            await interaction.response.send_message(
                '⛔ Only the guild admin configured in `guild_settings.admin_id` can use this command.',
                ephemeral=True
            )
            return
        session = VendorSession(interaction.user.id, interaction.guild_id)
        embed = session.summary(
            heading='🧮 Vendor Calculator',
            instructions=(
                'Choose the type of transaction:\n\n'
                '**🔄 Trade-In:** Enter customer cards, set trade percentages, then compare against your sale value.\n'
                '**💵 Customer Selling:** Enter customer cards and buying percentages to calculate your total cash offer.\n'
                '**🛒 No Trade:** Customer is only buying from you; enter each sale card and its price, then finish to total the cart.'
            )
        )
        await interaction.response.send_message(embed=embed, view=StartView(session), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VendorCalculator(bot))
