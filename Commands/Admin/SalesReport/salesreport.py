"""Interactive /salesreport for the vendorcalculator sales + sales_items schema.
Requires discord.py 2.x, asyncpg bot.db, matplotlib; guild_settings(guild_id, admin_id).
Install: pip install matplotlib
Extension: Commands.SalesReport.salesreport
All money stored as integer cents. Reports reflect cash flow, not accounting profit.
"""
import asyncio
import csv
import io
import calendar
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
except ImportError:
    plt = None

PAGE_SIZE = 8
MAX_EXPORT_ROWS = 10000
MODES = ('Overview', 'Cash Flow', 'Trades', 'Transactions', 'Top Cards')
PERIODS = ('Today', 'Week', 'Month', 'Year', 'All Time', 'Custom')


def money(cents):
    return f'${abs(int(cents or 0)) / 100:,.2f}'


def signed(cents):
    return ('+' if cents >= 0 else '-') + money(cents)


def clean(s):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(s or 'Unnamed Card')))


def truncate(s, length=36):
    return s if len(s) <= length else s[:length - 1] + '…'


def window(period, tz, custom=None):
    """Half-open time bounds in UTC, with calendar periods in selected local timezone."""
    if period == 'All Time':
        return None, None
    if period == 'Custom':
        if not custom:
            raise ValueError('Choose a custom date range first.')
        a, b = custom
        return (datetime.combine(a, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc),
                datetime.combine(b + timedelta(days=1), datetime.min.time(), tzinfo=tz).astimezone(timezone.utc))
    today = datetime.now(tz).date()
    if period == 'Today':
        start = today
        end = today + timedelta(days=1)
    elif period == 'Week':
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
    elif period == 'Month':
        start = today.replace(day=1)
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    elif period == 'Year':
        start, end = date(today.year, 1, 1), date(today.year + 1, 1, 1)
    else:
        raise ValueError('Unknown period')
    return (datetime.combine(start, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc),
            datetime.combine(end, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc))


async def fetch_report(pool, guild_id, start, end, tz_name):
    """One guild, half-open date range; every query uses bound parameters."""
    args = (guild_id, start, end)
    where = 'guild_id=$1 AND ($2::timestamptz IS NULL OR transaction_date >= $2) AND ($3::timestamptz IS NULL OR transaction_date < $3)'
    async with pool.acquire() as con:
        totals = await con.fetchrow(f'''
            SELECT COUNT(*)::bigint AS transactions,
                   COUNT(*) FILTER (WHERE transaction_type='trade')::bigint AS trades,
                   COUNT(*) FILTER (WHERE transaction_type='buy')::bigint AS buys,
                   COUNT(*) FILTER (WHERE transaction_type='sale')::bigint AS sales,
                   COALESCE(SUM(sale_price_cents),0)::bigint AS gross_sales,
                   COALESCE(SUM(purchase_price_cents),0)::bigint AS acquired_cost,
                   COALESCE(SUM(net_amount_cents),0)::bigint AS net_cash,
                   COALESCE(SUM(sale_price_cents) FILTER (WHERE transaction_type='trade'),0)::bigint AS trade_sales,
                   COALESCE(SUM(purchase_price_cents) FILTER (WHERE transaction_type='trade'),0)::bigint AS trade_credit,
                   COALESCE(SUM(purchase_price_cents) FILTER (WHERE transaction_type='buy'),0)::bigint AS cash_buys,
                   COALESCE(SUM(sale_price_cents) FILTER (WHERE transaction_type='sale'),0)::bigint AS cash_sales,
                   COALESCE(SUM(market_price_cents) FILTER (WHERE transaction_type IN ('buy','trade')),0)::bigint AS acquired_market,
                   COALESCE(AVG(net_amount_cents),0)::numeric AS avg_net
            FROM sales WHERE {where}
        ''', *args)
        # Database timezone conversion is explicit; bucket by date in configured reporting timezone.
        trend = await con.fetch(f'''
            SELECT (transaction_date AT TIME ZONE $4)::date AS day,
                   COALESCE(SUM(sale_price_cents),0)::bigint AS sold,
                   COALESCE(SUM(purchase_price_cents),0)::bigint AS bought,
                   COALESCE(SUM(net_amount_cents),0)::bigint AS net,
                   COUNT(*)::bigint AS count
            FROM sales WHERE {where}
            GROUP BY 1 ORDER BY 1
        ''', *args, tz_name)
        recent = await con.fetch(f'''
            SELECT transaction_id, transaction_date, customer_name, transaction_type,
                   sale_price_cents, purchase_price_cents, net_amount_cents
            FROM sales WHERE {where}
            ORDER BY transaction_date DESC, transaction_id DESC LIMIT 1000
        ''', *args)
        trade = await con.fetchrow(f'''
            SELECT COUNT(*)::bigint AS item_count,
                   COALESCE(SUM(i.market_price_cents * i.quantity),0)::bigint AS market,
                   COALESCE(SUM(i.final_price_cents * i.quantity),0)::bigint AS paid,
                   COALESCE(SUM(i.market_price_cents * i.quantity) FILTER (WHERE i.rate IS NOT NULL),0)::bigint AS rated_market,
                   COALESCE(SUM(i.final_price_cents * i.quantity) FILTER (WHERE i.rate IS NOT NULL),0)::bigint AS rated_paid
            FROM sales_items i JOIN sales s ON s.transaction_id=i.transaction_id
            WHERE s.guild_id=$1 AND ($2::timestamptz IS NULL OR s.transaction_date >= $2)
              AND ($3::timestamptz IS NULL OR s.transaction_date < $3)
              AND i.item_type='acquired' AND s.transaction_type='trade'
        ''', *args)
        cards = await con.fetch(f'''
            SELECT i.card_name, i.item_type, SUM(i.quantity)::bigint AS qty,
                   COALESCE(SUM(i.final_price_cents * i.quantity),0)::bigint AS total
            FROM sales_items i JOIN sales s ON s.transaction_id=i.transaction_id
            WHERE s.guild_id=$1 AND ($2::timestamptz IS NULL OR s.transaction_date >= $2)
              AND ($3::timestamptz IS NULL OR s.transaction_date < $3)
            GROUP BY i.card_name, i.item_type ORDER BY total DESC LIMIT 15
        ''', *args)
    return {'totals': dict(totals), 'trend': [dict(x) for x in trend],
            'recent': [dict(x) for x in recent], 'trade': dict(trade), 'cards': [dict(x) for x in cards]}


def chart_png(rows, period, start=None, end=None, tz_name='America/New_York'):
    # Fill gaps and chart cumulative totals to avoid isolated single-day dots.
    if plt is None or not rows:
        return None
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    first = start.astimezone(tz).date() if start else min(r['day'] for r in rows)
    last = (end.astimezone(tz) - timedelta(microseconds=1)).date() if end else max(r['day'] for r in rows)
    if period == 'Today':
        # One-day reports still need two x-axis positions to show a line.
        first, last = today - timedelta(days=1), today
    elif first == last:
        first -= timedelta(days=1)
    # Limit plotted points for very large custom/all-time windows.
    span = (last - first).days + 1
    step = max(1, (span + 729) // 730)
    daily = {r['day']: r for r in rows}
    x, sold, bought, net = [], [], [], []
    s_total = b_total = n_total = 0
    for offset in range(span):
        day = first + timedelta(days=offset)
        r = daily.get(day)
        if r:
            s_total += r['sold']
            b_total += r['bought']
            n_total += r['net']
        if offset % step == 0 or offset == span - 1:
            x.append(day)
            sold.append(s_total / 100)
            bought.append(b_total / 100)
            net.append(n_total / 100)
    fig, ax = plt.subplots(figsize=(10, 4), dpi=145)
    fig.patch.set_facecolor('#121923')
    ax.set_facecolor('#121923')
    for series, color, label in (
        (sold, '#50d7b0', 'Cumulative sales'),
        (bought, '#f7b45c', 'Cumulative acquisitions'),
        (net, '#80a7ff', 'Cumulative net cash'),
    ):
        ax.plot(x, series, color=color, linewidth=2.5, label=label)
    ax.axhline(0, color='#566276', linewidth=0.8)
    ax.grid(alpha=.12)
    ax.tick_params(colors='#cbd5e1', labelsize=9)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.yaxis.set_major_formatter(lambda value, _: f'${value:,.0f}')
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax.legend(facecolor='#202a38', edgecolor='none', labelcolor='white', loc='upper left', fontsize=8)
    ax.set_title(f'Cumulative sales · acquisitions · cash flow  |  {period}', color='white', loc='left', pad=14)
    ax.set_xlim(x[0], x[-1])
    fig.autofmt_xdate(rotation=0)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor(), bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


async def fetch_transaction_details(pool, guild_id, transaction_id):
    async with pool.acquire() as con:
        sale = await con.fetchrow('''
            SELECT transaction_id, transaction_date, customer_name, transaction_type,
                   original_price_cents, market_price_cents, purchase_price_cents,
                   sale_price_cents, net_amount_cents, admin_id
            FROM sales WHERE guild_id=$1 AND transaction_id=$2
        ''', guild_id, transaction_id)
        if not sale:
            return None, []
        items = await con.fetch('''
            SELECT item_number, item_type, card_name, market_price_cents,
                   original_price_cents, rate, final_price_cents, quantity
            FROM sales_items WHERE transaction_id=$1
            ORDER BY CASE item_type WHEN 'acquired' THEN 0 ELSE 1 END, item_number
        ''', transaction_id)
    return dict(sale), [dict(i) for i in items]


def transaction_embed(sale, items, tz_name):
    local = sale['transaction_date'].astimezone(ZoneInfo(tz_name))
    e = discord.Embed(title=f"🧾 Transaction #{sale['transaction_id']}",
                      description=f"**{clean(sale['customer_name'])}** · {sale['transaction_type'].title()}\n"
                                  f"{discord.utils.format_dt(sale['transaction_date'], 'F')}",
                      color=discord.Color.green() if sale['net_amount_cents'] >= 0 else discord.Color.orange())
    if not items:
        e.add_field(name='Cards', value='No itemized cards recorded.', inline=False)
    else:
        sections = [('acquired', '📥 Cards acquired'), ('sold', '📤 Cards sold')]
        for kind, title in sections:
            matches = [i for i in items if i['item_type'] == kind]
            if not matches:
                continue
            lines = []
            for item in matches:
                label = truncate(clean(item['card_name']), 65) + f" × {item['quantity']}"
                parts = []
                if item['market_price_cents'] is not None:
                    parts.append('Market ' + money(item['market_price_cents']))
                if item['rate'] is not None:
                    parts.append(f"Rate {item['rate']}%")
                parts.append(('Paid ' if kind == 'acquired' else 'Sold ') + money(item['final_price_cents'] * item['quantity']) + f" ({money(item['final_price_cents'])} each)")
                lines.append(f"**{item['item_number']}. {label}**\n" + ' · '.join(parts))
            # Discord fields have a 1024 character limit. Split into chunks.
            chunk = ''
            for line in lines:
                if len(chunk) + len(line) + 2 > 1000:
                    e.add_field(name=title, value=chunk, inline=False)
                    chunk = ''
                    title = 'Continued'
                chunk += ('\n\n' if chunk else '') + line
            if chunk:
                e.add_field(name=title, value=chunk, inline=False)
    e.add_field(name='Sale value', value=money(sale['sale_price_cents']))
    e.add_field(name='Card acquisition value', value=money(sale['purchase_price_cents']))
    amount = sale['net_amount_cents']
    result = 'CUSTOMER PAID' if amount > 0 else 'VENDOR PAID' if amount < 0 else 'EVEN TRANSACTION'
    e.add_field(name=result, value=money(amount), inline=False)
    e.set_footer(text=f"Guild transaction · {local.strftime('%Y-%m-%d %I:%M %p %Z')}")
    return e


class TransactionSearch(discord.ui.Modal, title='Find Sales Transaction'):
    query = discord.ui.TextInput(
        label='Transaction ID or date (YYYY-MM-DD)',
        placeholder='Example: 42 or 2026-10-24', required=True, max_length=32)

    def __init__(self, report_view):
        super().__init__()
        self.report_view = report_view

    async def on_submit(self, interaction):
        raw = str(self.query.value).strip()
        view = self.report_view
        if raw.isdigit():
            await interaction.response.defer(thinking=True, ephemeral=True)
            sale, items = await fetch_transaction_details(view.bot.db, view.guild_id, int(raw))
            if sale is None:
                await interaction.followup.send(f'No transaction #{raw} was found in this server.', ephemeral=True)
                return
            await interaction.followup.send(embed=transaction_embed(sale, items, view.tz_name), ephemeral=True)
            return
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            await interaction.response.send_message('Enter a transaction ID or a date in YYYY-MM-DD format.', ephemeral=True)
            return
        start = datetime.combine(day, datetime.min.time(), tzinfo=view.tz).astimezone(timezone.utc)
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=view.tz).astimezone(timezone.utc)
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with view.bot.db.acquire() as con:
            rows = await con.fetch('''
                SELECT transaction_id, customer_name, transaction_type, net_amount_cents,
                       transaction_date FROM sales
                WHERE guild_id=$1 AND transaction_date >= $2 AND transaction_date < $3
                ORDER BY transaction_date DESC, transaction_id DESC LIMIT 100
            ''', view.guild_id, start, end)
        if not rows:
            await interaction.followup.send(f'No transactions recorded on {day.isoformat()}.', ephemeral=True)
            return
        selector = TransactionResultsView(view.bot, view.guild_id, view.owner_id, view.tz_name, rows)
        await interaction.followup.send(embed=selector.embed(), view=selector, ephemeral=True)


class TransactionResultsSelect(discord.ui.Select):
    def __init__(self, rows):
        options = [discord.SelectOption(
            label=f"#{r['transaction_id']} · {truncate(r['customer_name'], 48)}"[:100],
            description=f"{r['transaction_type'].title()} · {signed(r['net_amount_cents'])}"[:100],
            value=str(r['transaction_id'])) for r in rows]
        super().__init__(placeholder='Select a transaction to view its cards', options=options)

    async def callback(self, interaction):
        view = self.view
        await interaction.response.defer(thinking=True, ephemeral=True)
        sale, items = await fetch_transaction_details(view.bot.db, view.guild_id, int(self.values[0]))
        if not sale:
            await interaction.followup.send('That transaction is no longer available.', ephemeral=True)
            return
        await interaction.followup.send(embed=transaction_embed(sale, items, view.tz_name), ephemeral=True)


class TransactionResultsView(discord.ui.View):
    def __init__(self, bot, guild_id, owner_id, tz_name, rows):
        super().__init__(timeout=600)
        self.bot, self.guild_id, self.owner_id, self.tz_name = bot, guild_id, owner_id, tz_name
        self.rows = rows
        self.page = 0
        self.update_controls()

    def update_controls(self):
        self.clear_items()
        chunk = self.rows[self.page * 25:(self.page + 1) * 25]
        self.add_item(TransactionResultsSelect(chunk))
        self.previous.disabled = self.page == 0
        self.next_page.disabled = (self.page + 1) * 25 >= len(self.rows)
        self.add_item(self.previous)
        self.add_item(self.next_page)

    def embed(self):
        e = discord.Embed(title='🔎 Transactions on selected date',
                          description=f"Found **{len(self.rows)}** transaction(s). Choose one below to see its cards.",
                          color=discord.Color.blurple())
        e.set_footer(text=f"Page {self.page + 1}/{(len(self.rows) + 24)//25} · Showing up to 100 matches")
        return e

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('Only the admin who opened this report can use it.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='◀ Previous', style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, interaction, button):
        self.page = max(0, self.page - 1)
        self.update_controls()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label='Next ▶', style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction, button):
        self.page = min((len(self.rows) - 1)//25, self.page + 1)
        self.update_controls()
        await interaction.response.edit_message(embed=self.embed(), view=self)


class CustomDates(discord.ui.Modal, title='Custom Sales Date Range'):
    start_date = discord.ui.TextInput(label='Start date (YYYY-MM-DD)', placeholder='2026-10-01', max_length=10)
    end_date = discord.ui.TextInput(label='End date (YYYY-MM-DD)', placeholder='2026-10-31', max_length=10)

    def __init__(self, view):
        super().__init__()
        self.report_view = view

    async def on_submit(self, interaction):
        try:
            a, b = date.fromisoformat(str(self.start_date)), date.fromisoformat(str(self.end_date))
            if a > b or (b - a).days > 3660:
                raise ValueError()
        except ValueError:
            await interaction.response.send_message('Enter valid dates (YYYY-MM-DD), start before end, within 10 years.', ephemeral=True)
            return
        self.report_view.custom = (a, b)
        self.report_view.period = 'Custom'
        self.report_view.page = 0
        await self.report_view.render(interaction, edit=False)


class PeriodSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder='📅 Date filter', row=1,
                         options=[discord.SelectOption(label=p, value=p) for p in PERIODS])

    async def callback(self, interaction):
        view = self.view
        if self.values[0] == 'Custom':
            await interaction.response.send_modal(CustomDates(view))
            return
        view.period = self.values[0]
        view.page = 0
        await view.render(interaction)


class ModeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder='📊 Report view', row=2,
                         options=[discord.SelectOption(label=m, value=m) for m in MODES])

    async def callback(self, interaction):
        self.view.mode = self.values[0]
        self.view.page = 0
        await self.view.render(interaction)


class ReportView(discord.ui.View):
    def __init__(self, bot, guild_id, owner_id, tz_name):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.tz_name = tz_name
        self.tz = ZoneInfo(tz_name)
        self.period = 'Month'
        self.mode = 'Overview'
        self.custom = None
        self.page = 0
        self.data = None
        self.message = None
        self.busy = asyncio.Lock()
        self.add_item(PeriodSelect())
        self.add_item(ModeSelect())

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('Only the admin who opened this report can use these controls.', ephemeral=True)
            return False
        return True

    def embed(self):
        d = self.data
        t = d['totals']
        e = discord.Embed(title=f'📊 Vendor Sales • {self.mode}',
                          description=f'**{self.period}** · <t:{int(datetime.now(timezone.utc).timestamp())}:f>\n'
                                      f'Guild report · All values in USD', color=discord.Color.blurple())
        if self.mode == 'Overview':
            e.add_field(name='💵 Gross sales', value=money(t['gross_sales']))
            e.add_field(name='🛒 Card acquisitions', value=money(t['acquired_cost']))
            e.add_field(name='📈 Net cash flow', value=signed(t['net_cash']))
            e.add_field(name='🧾 Transactions', value=f"{t['transactions']:,}")
            e.add_field(name='💱 Trades', value=f"{t['trades']:,}")
            e.add_field(name='💰 Cash purchases / sales', value=f"{t['buys']:,} / {t['sales']:,}")
            e.add_field(name='📦 Acquired market value', value=money(t['acquired_market']), inline=True)
            e.add_field(name='🎟️ Avg. net / transaction', value=signed(round(t['avg_net'])), inline=True)
            e.set_footer(text='Net cash flow ≠ profit. Acquisitions include trade credits and direct buys.')
        elif self.mode == 'Cash Flow':
            e.add_field(name='🟢 Direct sales', value=money(t['cash_sales']))
            e.add_field(name='🔵 Trade-related sales', value=money(t['trade_sales']))
            e.add_field(name='🟠 Direct purchases', value=money(t['cash_buys']))
            e.add_field(name='🟣 Trade credits', value=money(t['trade_credit']))
            e.add_field(name='💵 Total cash in', value=money(t['gross_sales']))
            e.add_field(name='💸 Total cash out / credits', value=money(t['acquired_cost']))
            e.add_field(name='📈 Net cash movement', value=signed(t['net_cash']), inline=False)
            e.set_footer(text='Trade credits are non-cash consideration; net is the cash settlement.')
        elif self.mode == 'Trades':
            tr = d['trade']
            rate = (100 * tr['rated_paid'] / tr['rated_market']) if tr['rated_market'] else 0
            e.add_field(name='🔄 Trade transactions', value=f"{t['trades']:,}")
            e.add_field(name='📦 Cards acquired', value=f"{tr['item_count']:,}")
            e.add_field(name='💰 Trade credits issued', value=money(t['trade_credit']))
            e.add_field(name='🏷️ Acquired card market value', value=money(tr['market']))
            e.add_field(name='📉 Weighted buying rate', value=f'{rate:.2f}%' if tr['rated_market'] else 'N/A')
            e.add_field(name='🛍️ Cards sold in trades', value=money(t['trade_sales']))
            e.add_field(name='💵 Net cash from trades', value=signed(t['trade_sales'] - t['trade_credit']), inline=False)
            e.set_footer(text='Weighted rate uses only trade-in cards with saved rates and market values.')
        elif self.mode == 'Transactions':
            rows = d['recent']
            pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
            self.page = min(self.page, pages - 1)
            selected = rows[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
            if not selected:
                e.add_field(name='No transactions', value='Nothing recorded for this period.', inline=False)
            else:
                lines = []
                for r in selected:
                    when = int(r['transaction_date'].timestamp())
                    lines.append(f"**#{r['transaction_id']}** · {r['transaction_type'].title()} · <t:{when}:d>\n"
                                 f"{truncate(clean(r['customer_name']), 45)} · **{signed(r['net_amount_cents'])}**")
                e.description += '\n\n' + '\n\n'.join(lines)
            e.set_footer(text=f'Page {self.page+1}/{pages} · Showing up to 1,000 most recent records. Use CSV for full period.')
        elif self.mode == 'Top Cards':
            if not d['cards']:
                e.add_field(name='No cards', value='No itemized cards in this period.', inline=False)
            else:
                lines = []
                for i, r in enumerate(d['cards'], 1):
                    icon = '🔽' if r['item_type'] == 'acquired' else '🔼'
                    lines.append(f"**{i}.** {icon} {truncate(clean(r['card_name']), 44)}\n"
                                 f"{r['qty']} item(s) · {money(r['total'])}")
                e.description += '\n\n' + '\n\n'.join(lines)
            e.set_footer(text='Top 15 card names by total item value. 🔽 acquired / 🔼 sold.')
        return e

    async def render(self, interaction, edit=True):
        await interaction.response.defer(thinking=not edit, ephemeral=True)
        async with self.busy:
            try:
                start, end = window(self.period, self.tz, self.custom)
                self.data = await fetch_report(self.bot.db, self.guild_id, start, end, self.tz_name)
                embed = self.embed()
                graph = chart_png(self.data['trend'], self.period, start, end, self.tz_name) if self.mode in ('Overview', 'Cash Flow') else None
                if graph:
                    embed.set_image(url='attachment://sales_chart.png')
                if edit:
                    # Editing with attachments=[] removes stale charts when switching views.
                    kwargs = {'embed': embed, 'view': self, 'attachments': [discord.File(graph, filename='sales_chart.png')] if graph else []}
                    await interaction.edit_original_response(**kwargs)
                else:
                    kwargs = {'embed': embed, 'view': self}
                    if graph:
                        kwargs['file'] = discord.File(graph, filename='sales_chart.png')
                    self.message = await interaction.followup.send(**kwargs, wait=True, ephemeral=True)
            except Exception:
                await interaction.followup.send('Could not load the sales report. Check your database tables and bot logs.', ephemeral=True)
                raise

    @discord.ui.button(label='◀ Previous', style=discord.ButtonStyle.secondary, row=0)
    async def previous(self, interaction, button):
        self.page = max(0, self.page - 1)
        await self.render(interaction)

    @discord.ui.button(label='Next ▶', style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, interaction, button):
        if self.data:
            self.page = min(self.page + 1, max(0, (len(self.data['recent']) - 1) // PAGE_SIZE))
        await self.render(interaction)

    @discord.ui.button(label='🔄 Refresh', style=discord.ButtonStyle.primary, row=0)
    async def refresh(self, interaction, button):
        await self.render(interaction)

    @discord.ui.button(label='📄 Export CSV', style=discord.ButtonStyle.success, row=0)
    async def export(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        start, end = window(self.period, self.tz, self.custom)
        sql = '''SELECT transaction_id, transaction_date, customer_name, transaction_type,
                        market_price_cents, purchase_price_cents, sale_price_cents, net_amount_cents
                 FROM sales WHERE guild_id=$1 AND ($2::timestamptz IS NULL OR transaction_date >= $2)
                   AND ($3::timestamptz IS NULL OR transaction_date < $3)
                 ORDER BY transaction_date DESC, transaction_id DESC LIMIT $4'''
        async with self.bot.db.acquire() as con:
            rows = await con.fetch(sql, self.guild_id, start, end, MAX_EXPORT_ROWS + 1)
        if len(rows) > MAX_EXPORT_ROWS:
            await interaction.followup.send('More than 10,000 transactions match. Narrow the date range before exporting.', ephemeral=True)
            return
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Transaction ID', 'Date (UTC)', 'Customer', 'Type', 'Market USD', 'Acquisition USD', 'Sales USD', 'Net Cash USD'])
        for r in rows:
            writer.writerow([r['transaction_id'], r['transaction_date'].isoformat(), r['customer_name'], r['transaction_type'],
                             f"{r['market_price_cents']/100:.2f}", f"{r['purchase_price_cents']/100:.2f}",
                             f"{r['sale_price_cents']/100:.2f}", f"{r['net_amount_cents']/100:.2f}"])
        b = io.BytesIO(output.getvalue().encode('utf-8-sig'))
        await interaction.followup.send(file=discord.File(b, filename='sales_report.csv'), ephemeral=True)

    @discord.ui.button(label='🔎 Find Transaction', style=discord.ButtonStyle.secondary, row=3)
    async def find_transaction(self, interaction, button):
        await interaction.response.send_modal(TransactionSearch(self))

    @discord.ui.button(label='✖ Close', style=discord.ButtonStyle.danger, row=0)
    async def close(self, interaction, button):
        for child in self.children:
            child.disabled = True
        self.stop()
        await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class SalesReport(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='salesreport', description='Interactive sales, purchases, trades and cash-flow dashboard.')
    @app_commands.guild_only()
    async def salesreport(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as con:
            admin_id = await con.fetchval('SELECT admin_id FROM guild_settings WHERE guild_id=$1', interaction.guild_id)
        if admin_id is None or int(admin_id) != interaction.user.id:
            await interaction.response.send_message('Only the registered guild admin can open sales reports.', ephemeral=True)
            return
        # Reporting timezone defaults to Eastern; change this constant for other locations.
        view = ReportView(self.bot, interaction.guild_id, interaction.user.id, 'America/New_York')
        await view.render(interaction, edit=False)


async def setup(bot):
    await bot.add_cog(SalesReport(bot))
