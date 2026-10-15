"""Pick Trax — Don't Sweat Picks HQ. discord.py 2.x.
Environment: DISCORD_TOKEN, TRUECAPPER_WEBHOOK_ID, TRUECAPPER_INBOX_CHANNEL_ID,
OWNER_ID, DATA_FILE, CLEANUP_TIMEZONE.
"""
import os
import re
import json
import asyncio
import logging
import hmac
from aiohttp import web
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

CHANNEL_IDS = {
    'diamond': 1483435130235260928,
    'emerald': 1483433966227947619,
    'sapphire': 1483436117536542882,
    'approvals': 1560067350227853363,
    'control': 1484587775188664460,
    'test': 1484587826040275004,
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
DESTINATIONS = {'diamond': ('diamond',), 'emerald': ('emerald',),
                'sapphire': ('sapphire',), 'emerald_sapphire': ('emerald', 'sapphire')}

def blank_record():
    return {'wins': 0, 'losses': 0, 'pushes': 0, 'units': 0.0}

def default_data():
    return {'owner_id': OWNER_ID or None, 'unit_value': 100.0,
            'show_dollars': False, 'picks': [], 'graded_history': [],
            'next_id': 1, 'recap_message_ids': {}, 'seen_source_ids': [],
            'record': blank_record(),
            'channel_records': {k: blank_record() for k in TIERS},
            'approval_message_ids': {}, 'win_message_ids': []}

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
    for k, v in default_data().items():
        obj.setdefault(k, v)
    for tier in TIERS:
        obj['channel_records'].setdefault(tier, blank_record())
    obj['next_id'] = max([int(p.get('id', 0)) for p in obj['picks'] + obj['graded_history']]
                         + [int(obj.get('next_id', 1))-1]) + 1
    return obj

data = load()

def now():
    return datetime.now(timezone.utc).isoformat()

def get_channel(guild, key):
    if not guild:
        return None
    channel = guild.get_channel(CHANNEL_IDS.get(key))
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

def american_from_decimal(value):
    if value <= 1:
        raise ValueError('Decimal odds must be greater than 1')
    return round((value - 1) * 100) if value >= 2 else -round(100 / (value - 1))

def odds_from(text):
    text = text or ''
    m = re.search(r'\b(?:odds?|price)\s*[:=]?\s*([+-]\d{2,6})\b', text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r'\b(?:odds?|decimal\s*odds?|price)\s*[:=]?\s*(\d+\.\d+)\b', text, re.I)
    if m:
        return american_from_decimal(float(m.group(1)))
    m = re.search(r'@\s*([+-]\d{2,6})\b', text)
    return int(m.group(1)) if m else -110

def fmt_profit(value):
    if data['show_dollars']:
        return f"${value * data['unit_value']:+,.2f}"
    return f'{value:+.2f}U'

def find_pick(pid):
    return next((p for p in data['picks'] + data['graded_history'] if p['id'] == pid), None)

def pick_tiers(p):
    tiers = p.get('tiers')
    if tiers:
        return [t for t in TIERS if t in tiers]
    return [p['tier']] if p.get('tier') in TIERS else []

def tier_label(p):
    tiers = pick_tiers(p)
    return ' + '.join(t.title() for t in tiers) if tiers else str(p.get('tier', 'Unassigned')).title()

def make_pick(text, tier, source, status='pending', units=None, odds=None, attachments=None):
    pid = data['next_id']
    data['next_id'] += 1
    p = {'id': pid, 'bet': (text or 'Image pick')[:3500], 'tier': tier,
         'units': float(units if units is not None else units_from(text)),
         'odds': int(odds if odds is not None else odds_from(text)),
         'status': status, 'source_message_id': source.id,
         'source_channel_id': source.channel.id, 'source_jump_url': source.jump_url,
         'attachments': attachments if attachments is not None else
         [a.url for a in source.attachments if a.content_type and a.content_type.startswith('image/')],
         'created_at': now(), 'profit_units': 0.0}
    data['picks'].append(p)
    data['seen_source_ids'].append(source.id)
    save()
    return p

def pick_embed(p):
    colors = {'pending': discord.Color.blurple(), 'approval': discord.Color.orange(),
              'win': discord.Color.green(), 'loss': discord.Color.red(),
              'push': discord.Color.light_grey()}
    e = discord.Embed(title=f"DSP Pick #{p['id']} | {tier_label(p)}",
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
        if p.get('test') or not pick_tiers(p):
            continue
        status = p.get('status')
        if status not in ('win', 'loss', 'push'):
            continue
        for r in [data['record']] + [data['channel_records'][t] for t in pick_tiers(p)]:
            r[{'win': 'wins', 'loss': 'losses', 'push': 'pushes'}[status]] += 1
            r['units'] = round(r['units'] + float(p.get('profit_units', 0)), 4)
    save()

def grade_pick(p, result):
    if p['status'] != 'pending':
        return False
    u, odds = float(p['units']), int(p['odds'])
    p['profit_units'] = round((u * (odds / 100 if odds > 0 else 100 / abs(odds)))
                              if result == 'win' else (-u if result == 'loss' else 0), 4)
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
    # The overall record is a pinned, live card in #bot-control.
    for tier in ('overall',) + TIERS:
        channel = get_channel(guild, 'control' if tier == 'overall' else tier)
        if not channel:
            continue
        r = data['record'] if tier == 'overall' else data['channel_records'][tier]
        decisions = r['wins'] + r['losses']
        rate = 100 * r['wins'] / decisions if decisions else 0
        title = '📊 DSP Overall Official Record' if tier == 'overall' else f'📊 DSP {tier.title()} Record'
        e = discord.Embed(title=title, color=discord.Color.blue(),
                          description=f"**{r['wins']}-{r['losses']}-{r['pushes']}** (W-L-P)\n"
                                      f"Profit: **{fmt_profit(r['units'])}**\nWin rate: **{rate:.1f}%**")
        if tier == 'overall':
            e.set_footer(text='Unique picks counted once, even when shared to Emerald + Sapphire')
        key = f'{guild.id}:{tier}'
        msg = None
        if data['recap_message_ids'].get(key):
            try:
                msg = await channel.fetch_message(int(data['recap_message_ids'][key]))
            except discord.NotFound:
                pass
            except discord.HTTPException:
                log.exception('Recap fetch failed')
                continue
        try:
            if msg:
                await msg.edit(embed=e)
                if not msg.pinned:
                    await msg.pin(reason='DSP live record')
            else:
                msg = await channel.send(embed=e)
                data['recap_message_ids'][key] = msg.id
                save()
                await msg.pin(reason='DSP live record')
        except discord.HTTPException:
            log.exception('Could not refresh %s recap', tier)

async def refresh_published_cards(guild, p, remove_view=False):
    messages = p.get('published_messages') or (
        [{'channel_id': p['published_channel_id'], 'message_id': p['published_message_id']}]
        if p.get('published_channel_id') and p.get('published_message_id') else [])
    for entry in messages:
        channel = guild.get_channel(int(entry['channel_id'])) if guild else None
        if not channel:
            continue
        try:
            msg = await channel.fetch_message(int(entry['message_id']))
            await msg.edit(embed=pick_embed(p), view=None if remove_view else GradeView(p['id']))
        except discord.HTTPException:
            log.exception('Could not update published card for pick #%s', p['id'])

async def publish_pick(guild, p, destination):
    tiers = DESTINATIONS.get(destination)
    if not tiers:
        return False, 'Invalid destination.'
    missing = [t for t in tiers if not get_channel(guild, t)]
    if missing:
        return False, 'Cannot find ' + ', '.join('#' + CHANNELS[t][0] for t in missing)
    sent = []
    try:
        for tier in tiers:
            dest = get_channel(guild, tier)
            preview = dict(p, tier=tier, tiers=list(tiers), status='pending')
            msg = await dest.send(embed=pick_embed(preview), view=GradeView(p['id']))
            sent.append({'channel_id': dest.id, 'message_id': msg.id})
    except discord.HTTPException as e:
        for entry in sent:
            try:
                channel = guild.get_channel(entry['channel_id'])
                if channel:
                    await (await channel.fetch_message(entry['message_id'])).delete()
            except discord.HTTPException:
                log.exception('Rollback failed for pick #%s', p['id'])
        return False, f'Failed to post: {e}'
    p['tier'] = destination if len(tiers) > 1 else tiers[0]
    p['tiers'] = list(tiers)
    p['status'] = 'pending'
    p['published_messages'] = sent
    p['published_message_id'] = sent[0]['message_id']
    p['published_channel_id'] = sent[0]['channel_id']
    save()
    await refresh_recaps(guild)
    return True, f"Published Pick #{p['id']} to " + ' and '.join(get_channel(guild, t).mention for t in tiers)

class TierSelect(discord.ui.Select):
    def __init__(self, pid):
        self.pid = pid
        existing = find_pick(pid)
        self.pick_created_at = existing.get('created_at') if existing else None
        options = [discord.SelectOption(label='Emerald + Sapphire', value='emerald_sapphire', emoji='✅')]
        options += [discord.SelectOption(label=t.title(), value=t) for t in TIERS]
        super().__init__(placeholder='Choose where to publish', options=options, custom_id=f'dsp:tier:{pid}')
    async def callback(self, interaction):
        if not owner_guard(interaction):
            return await interaction.response.send_message('Owner only.', ephemeral=True)
        p = find_pick(self.pid)
        if not p or p['status'] != 'approval' or p.get('created_at') != self.pick_created_at:
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
        existing = find_pick(pid)
        self.pick_created_at = existing.get('created_at') if existing else None
        for child in self.children:
            child.custom_id = f'{child.custom_id}:{pid}'
    @discord.ui.button(label='Approve', style=discord.ButtonStyle.success, custom_id='dsp:approve')
    async def approve(self, interaction, button):
        if not owner_guard(interaction):
            return await interaction.response.send_message('Owner only.', ephemeral=True)
        p = find_pick(self.pid)
        if not p or p['status'] != 'approval' or p.get('created_at') != self.pick_created_at:
            return await interaction.response.send_message('Already handled.', ephemeral=True)
        await interaction.response.edit_message(content='Select a destination tier:', view=TierView(self.pid))
    @discord.ui.button(label='Reject', style=discord.ButtonStyle.danger, custom_id='dsp:reject')
    async def reject(self, interaction, button):
        if not owner_guard(interaction):
            return await interaction.response.send_message('Owner only.', ephemeral=True)
        p = find_pick(self.pid)
        if not p or p['status'] != 'approval' or p.get('created_at') != self.pick_created_at:
            return await interaction.response.send_message('Already handled.', ephemeral=True)
        data['picks'] = [x for x in data['picks'] if x['id'] != self.pid]
        save()
        await interaction.response.edit_message(content=f'❌ Rejected TrueCapper submission #{self.pid}', view=None)

async def announce_win(guild, p):
    if p.get('test'):
        return
    wins = get_channel(guild, 'wins')
    if wins:
        msg = await wins.send(embed=discord.Embed(
            title='🏆 DSP Official Win',
            description=f"Pick #{p['id']} | {tier_label(p)}\n{p['bet']}\n**{fmt_profit(p['profit_units'])}**",
            color=discord.Color.green()))
        data['win_message_ids'].append({'channel_id': wins.id, 'message_id': msg.id})
        save()

class GradeView(discord.ui.View):
    def __init__(self, pid):
        super().__init__(timeout=None)
        self.pid = pid
        existing = find_pick(pid)
        self.pick_created_at = existing.get('created_at') if existing else None
        for child in self.children:
            child.custom_id = f'{child.custom_id}:{pid}'
    async def perform(self, interaction, result):
        if not owner_guard(interaction):
            return await interaction.response.send_message('Owner only.', ephemeral=True)
        p = find_pick(self.pid)
        if not p or p['status'] != 'pending' or p.get('created_at') != self.pick_created_at:
            return await interaction.response.send_message('Pick is already graded or missing.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if not grade_pick(p, result):
            return await interaction.followup.send('Pick is already graded or missing.', ephemeral=True)
        await refresh_published_cards(interaction.guild, p, remove_view=True)
        if not p.get('published_messages'):
            try:
                await interaction.message.edit(embed=pick_embed(p), view=None)
            except discord.HTTPException:
                log.exception('Could not edit graded card')
        if result == 'win':
            await announce_win(interaction.guild, p)
        await refresh_recaps(interaction.guild)
        await interaction.followup.send(f'Pick #{p["id"]} graded {result.upper()}.', ephemeral=True)
    @discord.ui.button(label='Win', style=discord.ButtonStyle.success, custom_id='dsp:win')
    async def win(self, interaction, button):
        await self.perform(interaction, 'win')
    @discord.ui.button(label='Loss', style=discord.ButtonStyle.danger, custom_id='dsp:loss')
    async def loss(self, interaction, button):
        await self.perform(interaction, 'loss')
    @discord.ui.button(label='Push', style=discord.ButtonStyle.secondary, custom_id='dsp:push')
    async def push(self, interaction, button):
        await self.perform(interaction, 'push')

# Launch reset: only bot-created tracking cards and announcements are deleted.
# Original user messages and original TrueCapper webhook submissions are untouched.
async def delete_bot_message(guild, channel_id, message_id):
    channel = guild.get_channel(int(channel_id)) if guild else None
    if not isinstance(channel, discord.TextChannel):
        return False
    try:
        msg = await channel.fetch_message(int(message_id))
        if msg.author.id != bot.user.id:
            return False
        await msg.delete()
        return True
    except discord.NotFound:
        return True
    except discord.HTTPException:
        log.exception('Could not delete tracked bot message %s', message_id)
        return False

async def reset_launch(guild):
    picks = list(data['picks']) + list(data['graded_history'])
    targets = set()
    for p in picks:
        entries = p.get('published_messages') or (
            [{'channel_id': p['published_channel_id'], 'message_id': p['published_message_id']}]
            if p.get('published_channel_id') and p.get('published_message_id') else [])
        for entry in entries:
            targets.add((int(entry['channel_id']), int(entry['message_id'])))
        for key in ('tracking_message', 'approval_message'):
            entry = p.get(key)
            if isinstance(entry, dict) and entry.get('channel_id') and entry.get('message_id'):
                targets.add((int(entry['channel_id']), int(entry['message_id'])))
    for entry in data.get('approval_message_ids', {}).values():
        if isinstance(entry, dict) and entry.get('channel_id') and entry.get('message_id'):
            targets.add((int(entry['channel_id']), int(entry['message_id'])))
    for entry in data.get('win_message_ids', []):
        if isinstance(entry, dict) and entry.get('channel_id') and entry.get('message_id'):
            targets.add((int(entry['channel_id']), int(entry['message_id'])))
    deleted = 0
    failed = 0
    for cid, mid in targets:
        if await delete_bot_message(guild, cid, mid):
            deleted += 1
        else:
            failed += 1
    # Legacy cards without saved message IDs cannot be identified safely.
    # Do not indiscriminately delete other messages or pinned records.
    # Keep seen_source_ids to prevent re-importing old webhook messages.
    data['picks'] = []
    data['graded_history'] = []
    data['next_id'] = 1
    data['record'] = blank_record()
    data['channel_records'] = {t: blank_record() for t in TIERS}
    data['approval_message_ids'] = {}
    data['win_message_ids'] = []
    save()
    await refresh_recaps(guild)
    return deleted, failed

class ResetConfirmView(discord.ui.View):
    def __init__(self, requester_id):
        super().__init__(timeout=120)
        self.requester_id = requester_id
    @discord.ui.button(label='Confirm full reset', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        if interaction.user.id != self.requester_id or not owner_guard(interaction):
            return await interaction.response.send_message('Owner only.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        deleted, failed = await reset_launch(interaction.guild)
        await interaction.followup.send(
            f'✅ Launch reset complete. Overall + all tiers: 0-0-0; picks cleared; next pick #1. '
            f'Bot cards removed: {deleted}. Could not remove: {failed}. '
            'Pinned records refreshed. Older untracked cards may require manual deletion.', ephemeral=True)
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass
    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message('Owner only.', ephemeral=True)
        await interaction.response.edit_message(content='Reset cancelled. No records changed.', view=None)

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
        asyncio.create_task(cleanup_loop())
    for guild in bot.guilds:
        await refresh_recaps(guild)

@bot.event
async def on_message(message):
    if not message.guild:
        return
    if message.webhook_id:
        if not WEBHOOK_ID or not INBOX_ID or message.webhook_id != WEBHOOK_ID or message.channel.id != INBOX_ID:
            return
        if message.id in data['seen_source_ids']:
            return
        control = get_channel(message.guild, 'approvals')
        if not control:
            log.error('No #pick-trax-approvals channel for TrueCapper approvals')
            return
        parts = [message.content or '']
        for e in message.embeds:
            parts.extend([e.title or '', e.description or ''])
            parts.extend(f'{f.name}: {f.value}' for f in e.fields)
        text = '\n'.join(s for s in parts if s)
        image_urls = [a.url for a in message.attachments if a.content_type and a.content_type.startswith('image/')]
        for e in message.embeds:
            if e.image and e.image.url:
                image_urls.append(e.image.url)
        p = make_pick(text, 'unassigned', message, status='approval', attachments=image_urls)
        msg = await control.send(content=f'🔐 TrueCapper submission #{p["id"]} — owner approval required',
                                 embed=pick_embed(p), view=ApprovalView(p['id']))
        p['approval_message'] = {'channel_id': control.id, 'message_id': msg.id}
        data['approval_message_ids'][str(p['id'])] = p['approval_message']
        save()
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
            card = await message.channel.send(embed=pick_embed(p), view=GradeView(p['id']))
            p['tracking_message'] = {'channel_id': card.channel.id, 'message_id': card.id}
            save()
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
    lines = [f"#{p['id']} {tier_label(p)} | {p['units']:g}U @ {p['odds']:+d}" for p in ps[:35]]
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
        if -99 <= odds <= 99:
            return await interaction.response.send_message('Enter valid American odds (e.g. +134 or -110).', ephemeral=True)
        p['odds'] = odds
    save()
    await interaction.response.send_message(f"Updated #{pick_id}: {p['units']:g}U @ {p['odds']:+d}", ephemeral=True)
    if p['status'] == 'pending':
        await refresh_published_cards(interaction.guild, p)

@bot.tree.command(name='grade', description='Owner: grade a pick by its ID')
@app_commands.choices(result=[app_commands.Choice(name=x.title(), value=x) for x in ('win', 'loss', 'push')])
async def grade(interaction: discord.Interaction, pick_id: int, result: app_commands.Choice[str]):
    if not owner_guard(interaction):
        return await interaction.response.send_message('Owner only.', ephemeral=True)
    p = find_pick(pick_id)
    if not p or not grade_pick(p, result.value):
        return await interaction.response.send_message('Pending pick not found.', ephemeral=True)
    await interaction.response.send_message(f"Pick #{pick_id}: {result.value.upper()} | {fmt_profit(p['profit_units'])}")
    await refresh_published_cards(interaction.guild, p, remove_view=True)
    if result.value == 'win':
        await announce_win(interaction.guild, p)
    await refresh_recaps(interaction.guild)

@bot.tree.command(name='removeplay', description='Owner: remove an ungraded pick')
async def removeplay(interaction: discord.Interaction, pick_id: int):
    if not owner_guard(interaction):
        return await interaction.response.send_message('Owner only.', ephemeral=True)
    p = find_pick(pick_id)
    if not p or p['status'] not in ('pending', 'approval'):
        return await interaction.response.send_message('Ungraded pick not found.', ephemeral=True)
    data['picks'] = [x for x in data['picks'] if x['id'] != pick_id]
    save()
    await interaction.response.send_message(f'Removed #{pick_id}.', ephemeral=True)

@bot.tree.command(name='resetrecord', description='Owner: reset records and bot-tracked picks for launch')
async def resetrecord(interaction: discord.Interaction):
    if not owner_guard(interaction):
        return await interaction.response.send_message('Owner only.', ephemeral=True)
    await interaction.response.send_message(
        '⚠️ **FULL LAUNCH RESET**\nThis clears overall/tier results, pending and graded picks, '
        'resets numbering to #1, and deletes tracked bot-posted pick cards and win announcements. '
        'Original user posts and TrueCapper source messages stay untouched. Confirm?',
        view=ResetConfirmView(interaction.user.id), ephemeral=True)

@bot.tree.command(name='settings', description='Owner: show settings')
async def settings(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Owner: <@{data['owner_id']}>\n1U = ${data['unit_value']:g}\n"
        f"Dollar display: {data['show_dollars']}\nWebhook configured: {bool(WEBHOOK_ID and INBOX_ID)}", ephemeral=True)

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
    lines = [f"{'✅' if get_channel(interaction.guild,k) else '❌'} {k}: "
             f"{get_channel(interaction.guild,k).mention if get_channel(interaction.guild,k) else 'NOT FOUND'} "
             f"(configured ID {CHANNEL_IDS.get(k)})" for k in CHANNELS]
    await interaction.response.send_message('\n'.join(lines), ephemeral=True)

@bot.tree.command(name='updaterecaps', description='Owner: refresh overall and tier record cards')
async def updaterecaps(interaction: discord.Interaction):
    if not owner_guard(interaction):
        return await interaction.response.send_message('Owner only.', ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    await refresh_recaps(interaction.guild)
    await interaction.followup.send('Overall + tier recaps refreshed.', ephemeral=True)

async def cleanup_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        local = datetime.now(TZ)
        days = (6 - local.weekday()) % 7 or 7
        next_run = (local + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep(max(1, (next_run - local).total_seconds()))
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

# Pick Trax PRO v0.3: read-only HTTP API on the same event loop as Discord.
# The API reads the existing in-memory data and never writes to the records file.
def create_api():
    api_key = os.environ.get('PICKTRAX_API_KEY', '')
    if len(api_key) < 32:
        raise RuntimeError('Set PICKTRAX_API_KEY in Railway to a random secret of at least 32 characters')

    @web.middleware
    async def authorize(request, handler):
        if request.path == '/health':
            return await handler(request)
        if not hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + api_key):
            raise web.HTTPUnauthorized(text='Unauthorized')
        return await handler(request)

    app = web.Application(middlewares=[authorize])

    async def health(request):
        return web.json_response({'ok': True, 'bot_ready': bot.is_ready()},
                                 headers={'Cache-Control': 'no-store'})

    async def snapshot(request):
        def safe_record(r):
            return {k: r.get(k, 0) for k in ('wins', 'losses', 'pushes', 'units')}

        def safe_pick(p):
            allowed = ('id', 'bet', 'tier', 'tiers', 'units', 'odds',
                       'status', 'created_at', 'graded_at', 'profit_units')
            return {k: p[k] for k in allowed if k in p}

        return web.json_response({
            'version': '0.3',
            'connected': bot.is_ready(),
            'unit_value': data.get('unit_value', 100.0),
            'show_dollars': data.get('show_dollars', False),
            'record': safe_record(data.get('record', {})),
            'channel_records': {
                tier: safe_record(data.get('channel_records', {}).get(tier, {}))
                for tier in TIERS
            },
            'pending': [safe_pick(p) for p in data.get('picks', [])
                        if p.get('status') == 'pending'],
            'approvals': [safe_pick(p) for p in data.get('picks', [])
                          if p.get('status') == 'approval'],
            'graded_history': [safe_pick(p) for p in data.get('graded_history', [])[-100:]],
        }, headers={'Cache-Control': 'no-store'})

    app.router.add_get('/health', health)
    app.router.add_get('/api/v1/snapshot', snapshot)
    return app


async def main():
    async with bot:
        runner = web.AppRunner(create_api())
        await runner.setup()
        try:
            port = int(os.environ.get('PORT', '8080'))
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            log.info('Pick Trax PRO API listening on port %s', port)
            await bot.start(TOKEN)
        finally:
            await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())