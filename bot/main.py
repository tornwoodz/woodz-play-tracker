import discord
from discord.ext import commands
from discord import app_commands
import os

# ====== INTENTS ======
intents = discord.Intents.default()

# ====== BOT SETUP ======
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== ON READY ======
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Sync error: {e}")

    print(f"🔥 Logged in as {bot.user}")

# ====== TEST COMMAND ======
@bot.tree.command(name="ping", description="Test if bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 pong")

# ====== RECORD COMMAND ======
@bot.tree.command(name="record", description="Show official record")
async def record(interaction: discord.Interaction):
    await interaction.response.send_message("📊 Record working")

# ====== SETTINGS SHOW ======
@bot.tree.command(name="settings_show", description="Show settings")
async def settings_show(interaction: discord.Interaction):
    await interaction.response.send_message("⚙️ Settings working")

# ====== ERROR HANDLER ======
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"❌ ERROR: {error}")

    try:
        if interaction.response.is_done():
            await interaction.followup.send(f"Error: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"Error: {error}", ephemeral=True)
    except Exception as e:
        print(f"❌ Failed to send error message: {e}")

# ====== RUN BOT ======
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
