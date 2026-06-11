import discord
from discord import app_commands
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

def run_webserver():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyServer)
    server.serve_forever()

TOKEN = None
try:
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("DISCORD_TOKEN="):
                TOKEN = line.strip().split("=", 1)[1]
except FileNotFoundError:
    TOKEN = os.environ.get("DISCORD_TOKEN")

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

client = MyClient()


def darf_moderieren(member: discord.Member):
    return any(role.name in ["Geschäftsführer", "Tom"] for role in member.roles)


@client.event
async def on_ready():
    print(f"Bot ist online: {client.user}")


@client.event
async def on_member_join(member: discord.Member):
    print(f"JOIN WORKS: {member}")
    channel = discord.utils.get(member.guild.text_channels, name="👋・𝕎𝕚𝕝𝕝𝕜𝕠𝕞𝕞𝕖𝕟")

    if channel:
embed = discord.Embed(
    title="Willkommen",
    color=discord.Color.green(),
    description=f"""..."""
)
            color=discord.Color.green()
        )
        await channel.send(embed=embed)


async def log(guild, title, desc, color):
    channel = discord.utils.get(guild.text_channels, name="logs")

    if channel:
        embed = discord.Embed(
            title=title,
            description=desc,
            color=color
        )
        await channel.send(embed=embed)


@client.tree.command(name="ban", description="Benutzer bannen")
async def ban(interaction: discord.Interaction, member: discord.Member, grund: str = "Kein Grund"):
    if not darf_moderieren(interaction.user):
        return await interaction.response.send_message("❌ Keine Rechte", ephemeral=True)

    await member.ban(reason=grund)

    embed = discord.Embed(
        title="Gebannt",
        description=f"{member.mention} wurde gebannt\nGrund: {grund}",
        color=discord.Color.red()
    )

    await interaction.response.send_message(embed=embed)
    await log(interaction.guild, "BAN", f"{member} wurde gebannt", discord.Color.red())


@client.tree.command(name="kick", description="Benutzer kicken")
async def kick(interaction: discord.Interaction, member: discord.Member, grund: str = "Kein Grund"):
    if not darf_moderieren(interaction.user):
        return await interaction.response.send_message("❌ Keine Rechte", ephemeral=True)

    await member.kick(reason=grund)

    embed = discord.Embed(
        title=" Gekickt",
        description=f"{member.mention} wurde gekickt\nGrund: {grund}",
        color=discord.Color.orange()
    )

    await interaction.response.send_message(embed=embed)
    await log(interaction.guild, "KICK", f"{member} wurde gekickt", discord.Color.orange())


@client.tree.command(name="clear", description="Chat löschen")
async def clear(interaction: discord.Interaction, anzahl: int):
    if not darf_moderieren(interaction.user):
        return await interaction.response.send_message("❌ Keine Rechte", ephemeral=True)

    await interaction.response.send_message(f"Lösche {anzahl} Nachrichten...", ephemeral=True)
    await interaction.channel.purge(limit=anzahl)


if TOKEN:
    threading.Thread(target=run_webserver, daemon=True).start()
    client.run(TOKEN)
else:
    print("Tom du hast dein token nicht eingetragen")
