"""Pick Trax — Don't Sweat Picks HQ.
Discord.py 2.x; environment: DISCORD_TOKEN, optional TRUECAPPER_WEBHOOK_ID,
TRUECAPPER_INBOX_CHANNEL_ID, OWNER_ID, DATA_FILE, CLEANUP_TIMEZONE.

Channel IDs are preferred, with channel-name fallback.
For security, the TrueCapper webhook must be allowlisted by ID and an inbox channel.
"""
import os
import re
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('picktrax')

TOKEN = os.environ['DISCORD_TOKEN']
DATA_FILE = Path(os.getenv('DATA_FILE', '/data/dsp_fresh_records.json'))
OWNER_ID = int(os.getenv('OWNER_ID', '0'))
WEBHOOK_ID = int(os.getenv('TRUECAPPER_WEBHOOK_ID', '0'))
INBOX_ID = int(os.getenv('TRUECAPPER_INBOX_CHANNEL_ID', '1560067350227853363'))
TZ = ZoneInfo(os.getenv('CLEANUP_TIMEZONE', 'America/New_York'))

# Exact Discord channel IDs take priority; names are only a fallback.
CHANNEL_IDS = {
    'diamond': 1483435130235260928,
    'emerald': 1483433966227947619,
    'sapphire': 1483436117536542882,
    'approvals': 1560067350227853363,
    'control': 1484587775188664460,
    'test': 1484587826040275004,  # Prior ID; verify with /channelcheck
    'wins': 1483439779390427341,
    'vip_general': 1483436461423333376,
    'community': 1483435285231702137,
    'units': 1483927105992392865,
}
CHANNELS = {
    'diamond': ('dsp-diamond',),
    'emerald': ('dsp-emerald',),
    'sapphire': ('dsp-sapphire',),
    'approvals': ('pick-trax-approvals',),
    'control': ('bot-control',),
    'test': ('bot-testing',),
    'wins': ('post-your-wins',),
    'vip_general': ('vip-general-chatroom',),
    'community': ('share-plays',),
    'units': ('unit-management',),
}
TIERS = ('diamond', 'emerald', 'sapphire')

def blank_record():
    return {'wins': 0, 'losses': 0, 'pushes': 0, 'units': 0.0}

def default_data():
    return {'owner_id': OWNER_ID or None, 'unit_value': 100.0,
            'show_dollars': False, 'picks': [], 'graded_history': [],
            'next_id': 1, 'recap_message_ids': {},
            'seen_source_ids': [], 'record': blank_record(),
            'channel_records': {k: blank_record() for k in TIERS}}

def save():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = DATA_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temp.replace(DATA_FILE)

def load():
    if not DATA_FILE.exists():
        return default_data()
    try:
        obj = json.loads(DATA_FILE.read_text(encoding='utf-8'))
        if not isinstance(obj, dict):
            raise ValueError('Not a JSON object')
    except Exception:
        log.exception('Cannot read data; refusing to overwrite existing records')
        raise
    # Migrate old records without discarding history. Old channel stats remain in JSON.
    for k, v in default_data().items():
        obj.setdefault(k, v)
    for tier in TIERS:
        obj['channel_records'].setdefault(tier, blank_record())
    obj['next_id'] = max([int(p.get('id', 0)) for p in obj['picks'] + obj['graded_history']] + [int(obj.get('next_id', 1))-1]) + 1
    return obj

data = load()

def now():
    return datetime.now(timezone.utc).isoformat()

def get_channel(guild, key):
    if not guild:
        return None
    channel_id = CHANNEL_IDS.get(key)
    channel = guild.get_channel(channel_id) if channel_id else None
    if isinstance(channel, discord.TextChannel):
        return channel
    for c in guild.text_channels:
        if any(c.name.lower().startswith(name) for name in CHANNELS[key]):
            return c
    return None

def tier_for_channel(channel):
    if channel:
        for tier in TIERS:
            if channel.id == CHANNEL_IDS[tier] or any(channel.name.lower().startswith(n) for n in CHANNELS[tier]):
                return tier
    return None

def owner(user):
    return bool(data.get('owner_id')) and user.id == int(data['owner_id'])

def owner_guard(interaction):
    return owner(interaction.user)

def is_test(channel):
    return bool(channel and (channel.id == CHANNEL_IDS['test'] or channel.name.lower().startswith('bot-testing')))

def units_from(text):
    m = re.search(r'(?<!\w)(\d+(?:\.\d+)?)\s*(?:u|units?)\b', text or '', re.I)
    return float(m.group(1)) if m else 1.0

def odds_from(text):
    m = re.search(r'(?:odds?\s*[:=]?\s*|@\s*)([+-]\d{2,6})\b', text or '', re.I)
    return int(m.group(1)) if m else -110

def fmt_profit(value):
    if data['show_dollars']:
        return f"${value * data['unit_value']:+,.2f}"
    return f'{value:+.2f}U'

def find_pick(pid):
    return next((p for p in data['picks'] + data['graded_history'] if p['id'] == pid), None)

def make_pick(text, tier, source, status='pending', units=None, odds=None, attachments=None):
    pid = data['next_id']
    data['next_id'] += 1
    p = {'id': pid, 'bet': (text or 'Image pick')[:3500], 'tier': tier,
         'units': float(units if units is not None else units_from(text)),
         'odds': int(odds if odds is not None else odds_from(text)),
         'status': status, 'source_message_id': source.id,
         'source_channel_id': source.channel.id,
         'source_jump_url': source.jump_url,
         'attachments': attachments if attachments is not None else [a.url for a in source.attachments if a.content_type and a.content_type.startswith('image/')],
         'created_at': now(), 'profit_units': 0.0}
    data['picks'].append(p)
    data['seen_source_ids'].append(source.id)
    save()
    return p

def pick_embed(p):
    colors = {'pending': discord.Color.blurple(), 'approval': discord.Color.orange(),
              'win': discord.Color.green(), 'loss': discord.Color.red(),
              'push': discord.Color.light_grey()}
    e = discord.Embed(title=f"DSP Pick #{p['id']} | {p['tier'].title()}",
                      description=p['bet'][:4000], color=colors.get(p['status'], discord.Color.blue()))
    e.add_field(name='Units', value=f"{p['units']:g}U")
    e.add_field(name='Odds', value=f"{p['odds']:+d}")
    e.add_field(name='Status', value=p['status'].upper())
    if p['status'] in ('win', 'loss', 'push'):
        e.add_field(name='Profit', value=fmt_profit(p['profit_units']))
    if p.get('source_jump_url'):
        e.add_field(name='Original', value=f"[Open message]({p['source_jump_url']})", inline=False)
    if p.get('attachments'):
        e.set_image(url=p['attachments'][0])
    return e

def rebuild_records():
    data['record'] = blank_record()
    for t in TIERS:
        data['channel_records'][t] = blank_record()
    for p in data['graded_history']:
        if p.get('test') or p.get('tier') not in TIERS:
            continue
        status = p.get('status')
        if status not in ('win', 'loss', 'push'):
            continue
        for r in (data['record'], data['channel_records'][p['tier']]):
            r[{'win': 'wins', 'loss': 'losses', 'push': 'pushes'}[status]] += 1
            r['units'] = round(r['units'] + float(p.get('profit_units', 0)), 4)
    save()

def grade_pick(p, result):
    if p['status'] != 'pending':
        return False
    u, odds = float(p['units']), int(p['odds'])
    p['profit_units'] = round((u * (odds / 100 if odds > 0 else 100 / abs(odds))) if result == 'win' else (-u if result == 'loss' else 0), 4)
    p['status'] = result
    p['graded_at'] = now()
    data['picks'] = [x for x in data['picks'] if x['id'] != p['id']]
    data['graded_history'].append(p)
    rebuild_records()
    return True

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

async def refresh_recaps(guild):
    for tier in TIERS:
        channel = get_channel(guild, tier)
        if not channel:
            continue
        r = data['channel_records'][tier]
        decisions = r['wins'] + r['losses']
        rate = 100 * r['wins'] / decisions if decisions else 0
        e = discord.Embed(title=f'📊 DSP {tier.title()} Record', color=discord.Color.blue(),
                          description=f"**{r['wins']}-{r['losses']}-{r['pushes']}** (W-L-P)\nProfit: **{fmt_profit(r['units'])}**\nWin rate: **{rate:.1f}%**")
        key = f'{guild.id}:{tier}'
        msg = None
        if data['recap_message_ids'].get(key):
            try:
                msg = await channel.fetch_message(int(data['recap_message_ids'][key]))
            except discord.NotFound:
                pass
            except discord.HTTPException:
                log.exception('Recap fetch failed')
        try:
            if msg:
                await msg.edit(embed=e)
            else:
                msg = await channel.send(embed=e)
                data['recap_message_ids'][key] = msg.id
                save()
                await msg.pin(reason='DSP live record')
        except discord.HTTPException:
            log.exception('Could not refresh %s recap', tier)

async def publish_pick(guild, p, tier):
    dest = get_channel(guild, tier)
    if not dest:
        return False, f'Cannot find #{CHANNELS[tier][0]}'
    p['tier'] = tier
    p['status'] = 'pending'
    try:
        msg = await dest.send(embed=pick_embed(p), view=GradeView(p['id']))
    except discord.HTTPException as e:
        return False, f'Failed to post: {e}'
    p['published_message_id'] = msg.id
    p['published_channel_id'] = dest.id
    save()
    await refresh_recaps(guild)
    return True, f'Published Pick #{p["id"]} to {dest.mention}'

class TierSelect(discord.ui.Select):
    def __init__(self, pid):
        self.pid = pid
        super().__init__(placeholder='Choose where to publish', options=[discord.SelectOption(label=t.title(), value=t) for t in TIERS], custom_id=f'dsp:tier:{pid}')
    async def callback(self, interaction):
        if not owner_guard(interaction):
            return await interaction.response.send_message('Owner only.', ephemeral=True)
        p = find_pick(self.pid)
        if not p or p['status'] != 'approval':
            return await interaction.response.send_message('Already handled or missing.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        ok, result = await publish_pick(interaction.guild, p, self.values[0])
        if ok:
            await interaction.message.edit(content=f'✅ {result}', embed=pick_embed(p), view=None)
        await interaction.followup.send(result, ephemeral=True)

class TierView(discord.ui.View):
    def __init__(self, pid):
        super().__init__(timeout=None)
        self.add_item(TierSelect(pid))

class ApprovalView(discord.ui.View):
    def __init__(self, pid):
        super().__init__(timeout=None)
        self.pid = pid
        for child in self.children:
            child.custom_id = f'{child.custom_id}:{pid}'
    @discord.ui.button(label='Approve', style=discord.ButtonStyle.success, custom_id='dsp:approve')
    async def approve(self, interaction, button):
        if not owner_guard(interaction):
            return await interaction.response.send_message('Owner only.', ephemeral=True)
        p = find_pick(self.pid)
        if not p or p['status'] != 'approval':
            return await interaction.response.send_message('Already handled.', ephemeral=True)
        await interaction.response.edit_message(content='Select a destination tier:', view=TierView(self.pid))
    @discord.ui.button(label='Reject', style=discord.ButtonStyle.danger, custom_id='dsp:reject')
    async def reject(self, interaction, button):
        if not owner_guard(interaction):
            return await interaction.response.send_message('Owner only.', ephemeral=True)
        p = find_pick(self.pid)
        if not p or p['status'] != 'approval':
            return await interaction.response.send_message('Already handled.', ephemeral=True)
        data['picks'] = [x for x in data['picks'] if x['id'] != self.pid]
        save()
        await interaction.response.edit_message(content=f'❌ Rejected TrueCapper submission #{self.pid}', view=None)

class GradeView(discord.ui.View):
    def __init__(self, pid):
        super().__init__(timeout=None)
        self.pid = pid
        for child in self.children:
            child.custom_id = f'{child.custom_id}:{pid}'
    async def perform(self, interaction, result):
        if not owner_guard(interaction):
            return await interaction.response.send_message('Owner only.', ephemeral=True)
        p = find_pick(self.pid)
        if not p or not grade_pick(p, result):
            return await interaction.response.send_message('Pick is already graded or missing.', ephemeral=True)
        await interaction.response.edit_message(embed=pick_embed(p), view=None)
        if result == 'win' and not p.get('test'):
            wins = get_channel(interaction.guild, 'wins')
            if wins:
                await wins.send(embed=discord.Embed(title='🏆 DSP Official Win', description=f"Pick #{p['id']} | {p['tier'].title()}\n{p['bet']}\n**{fmt_profit(p['profit_units'])}**", color=discord.Color.green()))
        await refresh_recaps(interaction.guild)
    @discord.ui.button(label='Win', style=discord.ButtonStyle.success, custom_id='dsp:win')
    async def win(self, interaction, button):
        await self.perform(interaction, 'win')
    @discord.ui.button(label='Loss', style=discord.ButtonStyle.danger, custom_id='dsp:loss')
    async def loss(self, interaction, button):
        await self.perform(interaction, 'loss')
    @discord.ui.button(label='Push', style=discord.ButtonStyle.secondary, custom_id='dsp:push')
    async def push(self, interaction, button):
        await self.perform(interaction, 'push')

@bot.event
async def on_ready():
    log.info('Connected as %s', bot.user)
    if not getattr(bot, '_initialized', False):
        bot._initialized = True
        for p in data['picks']:
            if p['status'] == 'approval':
                bot.add_view(ApprovalView(p['id']))
                bot.add_view(TierView(p['id']))
            elif p['status'] == 'pending':
                bot.add_view(GradeView(p['id']))
        try:
            await bot.tree.sync()
        except Exception:
            log.exception('Slash sync failed')
        bot.loop.create_task(cleanup_loop())
    for guild in bot.guilds:
        await refresh_recaps(guild)

@bot.event
async def on_message(message):
    if not message.guild:
        return
    # Never trust a webhook merely because its display name is TrueCapper.
    if message.webhook_id:
        if not WEBHOOK_ID or not INBOX_ID or message.webhook_id != WEBHOOK_ID or message.channel.id != INBOX_ID:
            return
        if message.id in data['seen_source_ids']:
            return
        control = get_channel(message.guild, 'approvals')
        if not control:
            log.error('No #pick-trax-approvals channel for TrueCapper approvals')
            return
        text = message.content or '\n'.join(e.description or e.title or '' for e in message.embeds)
        image_urls = [a.url for a in message.attachments if a.content_type and a.content_type.startswith('image/')]
        for e in message.embeds:
            if e.image and e.image.url:
                image_urls.append(e.image.url)
        p = make_pick(text, 'unassigned', message, status='approval', attachments=image_urls)
        await control.send(content=f'🔐 TrueCapper submission #{p["id"]} — owner approval required', embed=pick_embed(p), view=ApprovalView(p['id']))
        return
    if message.author.bot:
        return
    if owner(message.author) and (tier_for_channel(message.channel) or is_test(message.channel)):
        if message.id not in data['seen_source_ids'] and (message.attachments or message.embeds):
            tier = tier_for_channel(message.channel) or 'test'
            p = make_pick(message.content, tier, message)
            p['test'] = is_test(message.channel)
            save()
            await message.add_reaction('📌')
            await message.channel.send(embed=pick_embed(p), view=GradeView(p['id']))
            if not p['test']:
                await refresh_recaps(message.guild)
    await bot.process_commands(message)

@bot.tree.command(name='record', description='Show DSP overall and tier records')
async def record(interaction: discord.Interaction):
    r = data['record']
    lines = [f"**Overall:** {r['wins']}-{r['losses']}-{r['pushes']} | {fmt_profit(r['units'])}"]
    for t in TIERS:
        x = data['channel_records'][t]
        lines.append(f"**{t.title()}:** {x['wins']}-{x['losses']}-{x['pushes']} | {fmt_profit(x['units'])}")
    await interaction.response.send_message('\n'.join(lines))

@bot.tree.command(name='pending', description='Show active DSP picks')
async def pending(interaction: discord.Interaction):
    ps = [p for p in data['picks'] if p['status'] == 'pending']
    lines = [f"#{p['id']} {p['tier']} | {p['units']:g}U @ {p['odds']:+d}" for p in ps[:35]]
    await interaction.response.send_message('\n'.join(lines) or 'No pending picks.', ephemeral=True)

@bot.tree.command(name='editplay', description='Owner: edit units or odds for a pending pick')
async def editplay(interaction: discord.Interaction, pick_id: int, units: float | None = None, odds: int | None = None):
    if not owner_guard(interaction):
        return await interaction.response.send_message('Owner only.', ephemeral=True)
    p = find_pick(pick_id)
    if not p or p['status'] not in ('pending', 'approval'):
        return await interaction.response.send_message('No editable pick found.', ephemeral=True)
    if units is not None:
        if units <= 0:
            return await interaction.response.send_message('Units must be positive.', ephemeral=True)
        p['units'] = round(units, 4)
    if odds is not None:
        if odds == 0:
            return await interaction.response.send_message('Odds cannot be zero.', ephemeral=True)
        p['odds'] = odds
    save()
    await interaction.response.send_message(f"Updated #{pick_id}: {p['units']:g}U @ {p['odds']:+d}", ephemeral=True)

@bot.tree.command(name='grade', description='Owner: grade a pick by its ID')
@app_commands.choices(result=[app_commands.Choice(name=x.title(), value=x) for x in ('win','loss','push')])
async def grade(interaction: discord.Interaction, pick_id: int, result: app_commands.Choice[str]):
    if not owner_guard(interaction):
        return await interaction.response.send_message('Owner only.', ephemeral=True)
    p = find_pick(pick_id)
    if not p or not grade_pick(p, result.value):
        return await interaction.response.send_message('Pending pick not found.', ephemeral=True)
    await interaction.response.send_message(f"Pick #{pick_id}: {result.value.upper()} | {fmt_profit(p['profit_units'])}")
    if result.value == 'win' and not p.get('test'):
        wins = get_channel(interaction.guild, 'wins')
        if wins:
            await wins.send(embed=discord.Embed(title='🏆 DSP Official Win', description=f"Pick #{p['id']} | {p['tier'].title()}\n{p['bet']}\n**{fmt_profit(p['profit_units'])}**", color=discord.Color.green()))
    await refresh_recaps(interaction.guild)

@bot.tree.command(name='removeplay', description='Owner: remove an ungraded pick')
async def removeplay(interaction: discord.Interaction, pick_id: int):
    if not owner_guard(interaction):
        return await interaction.response.send_message('Owner only.', ephemeral=True)
    p = find_pick(pick_id)
    if not p or p['status'] not in ('pending','approval'):
        return await interaction.response.send_message('Ungraded pick not found.', ephemeral=True)
    data['picks'] = [x for x in data['picks'] if x['id'] != pick_id]
    save()
    await interaction.response.send_message(f'Removed #{pick_id}.', ephemeral=True)

@bot.tree.command(name='settings', description='Owner: show settings')
async def settings(interaction: discord.Interaction):
    await interaction.response.send_message(f"Owner: <@{data['owner_id']}>\n1U = ${data['unit_value']:g}\nDollar display: {data['show_dollars']}\nWebhook configured: {bool(WEBHOOK_ID and INBOX_ID)}", ephemeral=True)

@bot.tree.command(name='setowner', description='Set owner (initial setup restricted to server owner)')
async def setowner(interaction: discord.Interaction, user: discord.Member):
    if data.get('owner_id'):
        permitted = owner_guard(interaction)
    else:
        permitted = bool(interaction.guild and interaction.user.id == interaction.guild.owner_id)
    if not permitted:
        return await interaction.response.send_message('Only current bot owner (or server owner for initial setup).', ephemeral=True)
    data['owner_id'] = user.id
    save()
    await interaction.response.send_message(f'Owner: {user.mention}', ephemeral=True)

@bot.tree.command(name='setunit', description='Owner: configure unit value and dollar display')
async def setunit(interaction: discord.Interaction, amount: float, show_dollars: bool = False):
    if not owner_guard(interaction):
        return await interaction.response.send_message('Owner only.', ephemeral=True)
    if amount <= 0:
        return await interaction.response.send_message('Amount must be positive.', ephemeral=True)
    data['unit_value'] = amount
    data['show_dollars'] = show_dollars
    save()
    await interaction.response.send_message(f'1U = ${amount:g}; dollars display {show_dollars}', ephemeral=True)
    await refresh_recaps(interaction.guild)

@bot.tree.command(name='channelcheck', description='Owner: verify required DSP channel names')
async def channelcheck(interaction: discord.Interaction):
    if not owner_guard(interaction):
        return await interaction.response.send_message('Owner only.', ephemeral=True)
    lines = [f"{'✅' if get_channel(interaction.guild,k) else '❌'} {k}: {get_channel(interaction.guild,k).mention if get_channel(interaction.guild,k) else 'NOT FOUND'} (configured ID {CHANNEL_IDS.get(k)})" for k in CHANNELS]
    await interaction.response.send_message('\n'.join(lines), ephemeral=True)

@bot.tree.command(name='updaterecaps', description='Owner: refresh tier record cards')
async def updaterecaps(interaction: discord.Interaction):
    if not owner_guard(interaction):
        return await interaction.response.send_message('Owner only.', ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    await refresh_recaps(interaction.guild)
    await interaction.followup.send('Recaps refreshed.', ephemeral=True)

async def cleanup_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        local = datetime.now(TZ)
        days = (6 - local.weekday()) % 7 or 7
        next_run = (local + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep(max(1, (next_run - local).total_seconds()))
        # Safety: only remove old bot tracking cards, not users' posts or locked picks.
        for guild in bot.guilds:
            test = get_channel(guild, 'test')
            if test:
                try:
                    async for msg in test.history(limit=200):
                        if msg.author.id == bot.user.id and not msg.pinned and msg.created_at < datetime.now(timezone.utc) - timedelta(days=7):
                            await msg.delete()
                            await asyncio.sleep(0.4)
                except discord.HTTPException:
                    log.exception('Cleanup failed')

bot.run(TOKEN)
