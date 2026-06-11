import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


# ---------------- KEEP ALIVE ----------------

class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), DummyServer).serve_forever()


# ---------------- BOT ----------------

TOKEN = os.environ.get("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

DB = "tickets.db"


# ---------------- DATABASE (NO INSTALL) ----------------

def db_init():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        guild_id INTEGER PRIMARY KEY,
        category_id INTEGER,
        log_channel_id INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS counters(
        guild_id INTEGER PRIMARY KEY,
        last_number INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()


def next_ticket(guild_id: int):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("SELECT last_number FROM counters WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()

    if row is None:
        number = 1
        cur.execute("INSERT INTO counters VALUES(?,?)", (guild_id, number))
    else:
        number = row[0] + 1
        cur.execute("UPDATE counters SET last_number=? WHERE guild_id=?", (number, guild_id))

    conn.commit()
    conn.close()
    return number


# ---------------- MODERATION ----------------

def can_mod(member: discord.Member):
    return any(role.permissions.administrator for role in member.roles)


# ---------------- LOG ----------------

async def log(guild, title, desc, color):
    ch = discord.utils.get(guild.text_channels, name="logs")
    if ch:
        await ch.send(embed=discord.Embed(title=title, description=desc, color=color))


# ---------------- TICKETS ----------------

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Ticket erstellen", style=discord.ButtonStyle.green)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):

        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT * FROM settings WHERE guild_id=?", (interaction.guild.id,))
        data = cur.fetchone()
        conn.close()

        if not data:
            return await interaction.response.send_message("Bot nicht eingerichtet (/setup)", ephemeral=True)

        number = next_ticket(interaction.guild.id)

        category = interaction.guild.get_channel(data[1])

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{number}",
            category=category,
            overwrites=overwrites
        )

        await channel.send(
            embed=discord.Embed(
                title=f"Ticket #{number}",
                description=f"Erstellt von {interaction.user.mention}",
                color=discord.Color.blurple()
            )
        )

        await interaction.response.send_message(f"Ticket erstellt: {channel.mention}", ephemeral=True)


# ---------------- SLASH COMMANDS ----------------

@bot.tree.command(name="setup")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction,
                category: discord.CategoryChannel,
                logs: discord.TextChannel):

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
    INSERT OR REPLACE INTO settings VALUES(?,?,?)
    """, (interaction.guild.id, category.id, logs.id))

    conn.commit()
    conn.close()

    await interaction.response.send_message("Setup fertig", ephemeral=True)


@bot.tree.command(name="ticketpanel")
async def ticketpanel(interaction: discord.Interaction):

    await interaction.channel.send(
        embed=discord.Embed(
            title="Ticketsystem",
            description="Drücke den Button um ein Ticket zu erstellen",
            color=discord.Color.green()
        ),
        view=TicketView()
    )

    await interaction.response.send_message("Panel gesendet", ephemeral=True)


@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction, amount: int):

    if not can_mod(interaction.user):
        return await interaction.response.send_message("Keine Rechte", ephemeral=True)

    await interaction.channel.purge(limit=amount)
    await interaction.response.send_message("Gelöscht", ephemeral=True)


@bot.tree.command(name="kick")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund"):

    if not can_mod(interaction.user):
        return await interaction.response.send_message("Keine Rechte", ephemeral=True)

    await member.kick(reason=reason)
    await interaction.response.send_message(f"{member} gekickt")


@bot.tree.command(name="ban")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund"):

    if not can_mod(interaction.user):
        return await interaction.response.send_message("Keine Rechte", ephemeral=True)

    await member.ban(reason=reason)
    await interaction.response.send_message(f"{member} gebannt")


# ---------------- READY ----------------

@bot.event
async def on_ready():
    db_init()

    bot.add_view(TicketView())

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)

    print(f"Online als {bot.user}")


# ---------------- START ----------------

if TOKEN:
    threading.Thread(target=run_web, daemon=True).start()
    bot.run(TOKEN)
else:
    print("Kein Token gesetzt")
