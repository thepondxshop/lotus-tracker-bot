import os
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"{bot.user} is online!")

@bot.tree.command(name="ping", description="Check Lotus Tracker Bot")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🏓 Lotus Tracker Bot is online!"
    )

@bot.event
async def setup_hook():
    await bot.tree.sync()

bot.run(TOKEN)