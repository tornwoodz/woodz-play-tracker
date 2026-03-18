from __future__ import annotations

import discord
from .utils import american_profit


class TrackedPlayView(discord.ui.View):
    def __init__(self, bot, play_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.play_id = play_id

        for label, emoji, style, action in [
            ("Tail", "✅", discord.ButtonStyle.success, "tail"),
            ("Watch", "👀", discord.ButtonStyle.secondary, "watch"),
            ("Win", "🏁", discord.ButtonStyle.success, "win"),
            ("Loss", "❌", discord.ButtonStyle.danger, "loss"),
            ("Void", "⚪", discord.ButtonStyle.secondary, "void"),
            ("Cashout", "💸", discord.ButtonStyle.primary, "cashout"),
        ]:
            self.add_item(ActionButton(bot, play_id, label, emoji, style, action))


class CashoutModal(discord.ui.Modal, title="Enter cashout units"):
    cashout_units = discord.ui.TextInput(label="Profit or loss in units", placeholder="Examples: +0.60 or -0.30", required=True)

    def __init__(self, bot, play_id: int):
        super().__init__()
        self.bot = bot
        self.play_id = play_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.bot.owner_user_id:
            await interaction.response.send_message("Only the owner can grade official plays.", ephemeral=True)
            return
        try:
            value = float(str(self.cashout_units))
        except ValueError:
            await interaction.response.send_message("Enter a valid number like +0.6 or -0.3.", ephemeral=True)
            return
        await self.bot.db.grade_play(self.play_id, "CASHOUT", value)
        await interaction.response.send_message(f"Play #{self.play_id} graded as CASHOUT: {value:+.2f}U", ephemeral=True)


class ActionButton(discord.ui.Button):
    def __init__(self, bot, play_id: int, label: str, emoji: str, style: discord.ButtonStyle, action: str):
        super().__init__(label=label, emoji=emoji, style=style, custom_id=f"play:{play_id}:{action}")
        self.bot = bot
        self.play_id = play_id
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        if self.action in {"tail", "watch"}:
            await self.bot.db.add_tail(self.play_id, interaction.user.id, "TAIL" if self.action == "tail" else "WATCH")
            await interaction.response.send_message(f"Marked you as {self.action.upper()} for play #{self.play_id}.", ephemeral=True)
            return

        if interaction.user.id != self.bot.owner_user_id:
            await interaction.response.send_message("Only the owner can grade official plays.", ephemeral=True)
            return

        play = await self.bot.db.get_play(self.play_id)
        if not play:
            await interaction.response.send_message("Play not found.", ephemeral=True)
            return

        odds = play[9]
        units = float(play[10])
        if self.action == "win":
            profit = american_profit(odds, units)
            await self.bot.db.grade_play(self.play_id, "WIN", profit)
            await interaction.response.send_message(f"Play #{self.play_id} graded WIN: +{profit:.2f}U", ephemeral=True)
        elif self.action == "loss":
            await self.bot.db.grade_play(self.play_id, "LOSS", -units)
            await interaction.response.send_message(f"Play #{self.play_id} graded LOSS: -{units:.2f}U", ephemeral=True)
        elif self.action == "void":
            await self.bot.db.grade_play(self.play_id, "VOID", 0.0)
            await interaction.response.send_message(f"Play #{self.play_id} graded VOID.", ephemeral=True)
        elif self.action == "cashout":
            await interaction.response.send_modal(CashoutModal(self.bot, self.play_id))
