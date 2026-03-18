# Woodz Play Tracker Bot

Custom Discord bot for tracking official Woodz plays, separating VIP vs PUB stats, daily recaps, and a tailing leaderboard.

## Features
- Auto-tracks only the owner's posts in configured play channels
- VIP vs PUB split tracking
- Play types by channel: Hammer, Parlay, Live, Weekly Lock
- Grade options: Win, Loss, Void, Cashout
- Units + optional dollar display (`1U = $50` by default)
- Daily recap channel
- Separate tailing leaderboard for members
- Owner-only grading
- Slash commands for records, pending plays, recap, and settings

## Quick start
1. Create a Discord application and bot in the Discord Developer Portal.
2. Invite the bot to your server with these permissions:
   - View Channels
   - Send Messages
   - Embed Links
   - Read Message History
   - Use Slash Commands
   - Add Reactions
3. Copy `.env.example` to `.env` and fill in your values.
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
5. Run the bot:
   ```bash
   python -m bot.main
   ```

## Best production setup
- Keep the code in GitHub
- Deploy to Railway or Render
- Add your `.env` values as environment variables on the host

## Important
- Do not share your Discord bot token.
- Set `OWNER_USER_ID` to your Discord user ID so only you can grade official plays.
- Buttons are restored on restart for pending plays.

## Commands
- `/record [scope] [mode]` - overall or VIP/PUB stats, in units or dollars
- `/pending` - list all pending official plays
- `/recap [days] [mode]` - recent recap
- `/tailboard` - tailing leaderboard
- `/grade play_id result [cashout_units]` - owner-only manual grading
- `/settings show`
- `/settings set_unit_value amount`
- `/settings set_recap_channel channel`
- `/settings toggle_dollars enabled`
- `/settings set_owner user`

## Notes
This bot is built to use channel names by default:
- VIP tracked: `live-bets`, `hammers-aka-singles`, `parlays`
- PUB tracked: `weekly-locks`

You can change the behavior inside `bot/config.py` or with settings commands.
