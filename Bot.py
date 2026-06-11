import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler


# ---------------- WEB SERVER ----------------

class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

def run_webserver():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyServer)
    server.serve_forever()


# ---------------- BOT ----------------

TOKEN = os.environ.get("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

DB = "tickets.db"


# ---------------- DATABASE ----------------

async def db_init():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            guild_id INTEGER PRIMARY KEY,
            category_id INTEGER,
            log_channel_id INTEGER,
            frage_role INTEGER,
            beschwerde_role INTEGER,
            kooperation_role INTEGER
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS counters(
            guild_id INTEGER PRIMARY KEY,
            last_number INTEGER DEFAULT 0
        )
        """)
        await db.commit()


async def next_ticket(guild_id: int):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT last_number FROM counters WHERE guild_id=?",
            (guild_id,)
        )
        row = await cur.fetchone()

        if row is None:
            number = 1
            await db.execute(
                "INSERT INTO counters(guild_id,last_number) VALUES(?,?)",
                (guild_id, number)
            )
        else:
            number = row[0] + 1
            await db.execute(
                "UPDATE counters SET last_number=? WHERE guild_id=?",
                (number, guild_id)
            )

        await db.commit()
        return number


# ---------------- MODERATION ----------------

def darf_moderieren(member: discord.Member):
    return any(role.name in ["Geschäftsführer", "Tom"] for role in member.roles)


# ---------------- LOG ----------------

async def log(guild, title, desc, color):
    channel = discord.utils.get(guild.text_channels, name="logs")
    if channel:
        await channel.send(embed=discord.Embed(title=title, description=desc, color=color))


# ---------------- TICKET SYSTEM ----------------

class TicketButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📌 Claim", style=discord.ButtonStyle.green, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.channel.topic and "CLAIMED:" in interaction.channel.topic:
            return await interaction.response.send_message("Schon übernommen.", ephemeral=True)

        await interaction.channel.edit(topic=f"CLAIMED:{interaction.user.id}")

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Ticket übernommen",
                description=f"{interaction.user.mention} bearbeitet das Ticket",
                color=discord.Color.green()
            )
        )

    @discord.ui.button(label="🔒 Close", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):

        async with aiosqlite.connect(DB) as db:
            cur = await db.execute(
                "SELECT log_channel_id FROM settings WHERE guild_id=?",
                (interaction.guild.id,)
            )
            row = await cur.fetchone()

        if row and row[0]:
            log_channel = interaction.guild.get_channel(row[0])
            if log_channel:
                await log_channel.send(
                    embed=discord.Embed(
                        title="Ticket geschlossen",
                        description=f"{interaction.channel.name}\nVon: {interaction.user.mention}",
                        color=discord.Color.red()
                    )
                )

        await interaction.response.send_message("Ticket wird gelöscht...", ephemeral=True)
        await interaction.channel.delete()


class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Allgemeine Frage", emoji="❓"),
            discord.SelectOption(label="Beschwerde", emoji="🚨"),
            discord.SelectOption(label="Kooperation", emoji="🤝")
        ]
        super().__init__(placeholder="Ticket auswählen", options=options)

    async def callback(self, interaction: discord.Interaction):

        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT * FROM settings WHERE guild_id=?", (interaction.guild.id,))
            settings = await cur.fetchone()

        if not settings:
            return await interaction.response.send_message("Bitte /setup machen", ephemeral=True)

        for channel in interaction.guild.channels:
            if isinstance(channel, discord.TextChannel):
                if channel.topic == f"OWNER:{interaction.user.id}":
                    return await interaction.response.send_message("Du hast schon ein Ticket", ephemeral=True)

        ticket_number = await next_ticket(interaction.guild.id)
        ticket_type = self.values[0]

        role_map = {
            "Allgemeine Frage": settings[3],
            "Beschwerde": settings[4],
            "Kooperation": settings[5]
        }

        role_id = role_map.get(ticket_type)

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True)

        category = interaction.guild.get_channel(settings[1])

        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{ticket_number:04d}",
            category=category,
            overwrites=overwrites,
            topic=f"OWNER:{interaction.user.id}"
        )

        await channel.send(
            embed=discord.Embed(
                title=f"Ticket #{ticket_number:04d}",
                description=f"Typ: {ticket_type}\nUser: {interaction.user.mention}",
                color=discord.Color.blurple()
            ),
            view=TicketButtons()
        )

        await interaction.response.send_message(f"Ticket erstellt: {channel.mention}", ephemeral=True)


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


# ---------------- SLASH COMMANDS ----------------

@bot.tree.command(name="setup")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction,
                category: discord.CategoryChannel,
                logs: discord.TextChannel):

    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT OR REPLACE INTO settings(guild_id, category_id, log_channel_id)
        VALUES(?,?,?)
        """, (interaction.guild.id, category.id, logs.id))
        await db.commit()

    await interaction.response.send_message("Setup gespeichert", ephemeral=True)


@bot.tree.command(name="ticketpanel")
@app_commands.default_permissions(administrator=True)
async def ticketpanel(interaction: discord.Interaction):

    embed = discord.Embed(
        title="Ticket System",
        description="❓ Frage\n🚨 Beschwerde\n🤝 Kooperation",
        color=discord.Color.blurple()
    )

    await interaction.channel.send(embed=embed, view=TicketView())
    await interaction.response.send_message("Panel gesendet", ephemeral=True)


@bot.tree.command(name="ban")
async def ban(interaction: discord.Interaction, member: discord.Member, grund: str = "Kein Grund"):

    if not darf_moderieren(interaction.user):
        return await interaction.response.send_message("❌ Keine Rechte", ephemeral=True)

    await member.ban(reason=grund)

    await interaction.response.send_message(
        embed=discord.Embed(title="Gebannt", description=f"{member} gebannt\nGrund: {grund}", color=discord.Color.red())
    )


@bot.tree.command(name="kick")
async def kick(interaction: discord.Interaction, member: discord.Member, grund: str = "Kein Grund"):

    if not darf_moderieren(interaction.user):
        return await interaction.response.send_message("❌ Keine Rechte", ephemeral=True)

    await member.kick(reason=grund)

    await interaction.response.send_message(
        embed=discord.Embed(title="Gekickt", description=f"{member} gekickt\nGrund: {grund}", color=discord.Color.orange())
    )


@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction, anzahl: int):

    if not darf_moderieren(interaction.user):
        return await interaction.response.send_message("❌ Keine Rechte", ephemeral=True)

    await interaction.response.send_message(f"Lösche {anzahl}", ephemeral=True)
    await interaction.channel.purge(limit=anzahl)


# ---------------- START ----------------

@bot.event
async def on_ready():
    await db_init()
    bot.add_view(TicketView())
    bot.add_view(TicketButtons())

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)

    print(f"Logged in as {bot.user}")


if TOKEN:
    threading.Thread(target=run_webserver, daemon=True).start()
    bot.run(TOKEN)
else:
    print("Kein Token")
