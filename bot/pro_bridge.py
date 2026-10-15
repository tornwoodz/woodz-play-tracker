"""Pick Trax PRO v0.3 read-only bridge + safe test-channel delivery.
Install in main.py immediately before bot.run(TOKEN):
    from pro_bridge import install_bridge
    install_bridge(bot, data, CHANNEL_IDS, get_channel)
Requires aiohttp and Railway variables PICKTRAX_API_KEY, PICKTRAX_ALLOWED_ORIGIN,
PORT (Railway sets PORT), optional PICKTRAX_TEST_CHANNEL_ID.
"""
import os
import hmac
import asyncio
import logging
from aiohttp import web

log = logging.getLogger('picktrax.bridge')

def install_bridge(bot, data, channel_ids, get_channel):
    key = os.environ.get('PICKTRAX_API_KEY', '')
    origin = os.environ.get('PICKTRAX_ALLOWED_ORIGIN', '').rstrip('/')
    if not key or len(key) < 32:
        raise RuntimeError('Set PICKTRAX_API_KEY to a random secret of at least 32 characters')
    if not origin.startswith('https://'):
        raise RuntimeError('PICKTRAX_ALLOWED_ORIGIN must be your HTTPS Vercel origin')
    port = int(os.environ.get('PORT', '8080'))
    app = web.Application(client_max_size=32 * 1024)

    @web.middleware
    async def guard(request, handler):
        if request.method == 'OPTIONS':
            response = web.Response(status=204)
        else:
            if not hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + key):
                return web.json_response({'error': 'Unauthorized'}, status=401)
            if request.method != 'GET' and request.headers.get('Origin', '').rstrip('/') != origin:
                return web.json_response({'error': 'Origin denied'}, status=403)
            response = await handler(request)
        if request.headers.get('Origin', '').rstrip('/') == origin:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Cache-Control'] = 'no-store'
        return response

    app.middlewares.append(guard)

    async def snapshot(request):
        picks = []
        for p in data.get('picks', []) + data.get('graded_history', []):
            picks.append({k: p.get(k) for k in ('id', 'bet', 'tier', 'tiers', 'units', 'odds', 'status', 'created_at', 'graded_at', 'profit_units', 'test')})
        return web.json_response({'online': bot.is_ready(), 'record': data.get('record', {}),
            'channel_records': data.get('channel_records', {}), 'unit_value': data.get('unit_value', 100),
            'picks': picks, 'pending_approvals': sum(p.get('status') == 'approval' for p in data.get('picks', []))})

    async def test_send(request):
        body = await request.json()
        text = str(body.get('text', '')).strip()
        if not text or len(text) > 1500:
            return web.json_response({'error': 'Text must be 1–1500 characters'}, status=400)
        channel_id = int(os.environ.get('PICKTRAX_TEST_CHANNEL_ID', str(channel_ids['test'])))
        guild = next((g for g in bot.guilds if g.get_channel(channel_id)), None)
        channel = guild.get_channel(channel_id) if guild else None
        if channel is None:
            return web.json_response({'error': 'Test channel unavailable'}, status=503)
        await channel.send('🧪 **Pick Trax PRO staging test — NOT an official pick**\n' + text, allowed_mentions=__import__('discord').AllowedMentions.none())
        return web.json_response({'ok': True, 'message': 'Test message delivered to #bot-testing'})

    app.router.add_get('/api/v1/snapshot', snapshot)
    app.router.add_post('/api/v1/test-message', test_send)
    app.router.add_route('OPTIONS', '/api/v1/{tail:.*}', lambda r: web.Response(status=204))

    async def start_bridge():
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        log.info('Pick Trax PRO bridge listening on port %s', port)

    async def setup_hook():
        await start_bridge()
    original = bot.setup_hook
    async def combined():
        await original()
        await setup_hook()
    bot.setup_hook = combined
