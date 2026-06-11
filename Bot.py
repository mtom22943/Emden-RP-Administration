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
        description=f"""Willkommen {member.mention} auf dem Server!
Bitte lies die Regeln."""
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

import discord
import aiosqlite
from discord.ext import commands
from discord import app_commands

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


# ---------------- UI ----------------

class TicketButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📌 Claim", style=discord.ButtonStyle.green, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.channel.topic and "CLAIMED:" in interaction.channel.topic:
            return await interaction.response.send_message(
                "Dieses Ticket wurde bereits übernommen.",
                ephemeral=True
            )

        await interaction.channel.edit(topic=f"CLAIMED:{interaction.user.id}")

        embed = discord.Embed(
            title="Ticket übernommen",
            description=f"{interaction.user.mention} bearbeitet dieses Ticket.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed)

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
                embed = discord.Embed(
                    title="Ticket geschlossen",
                    description=f"Ticket: {interaction.channel.name}\nGeschlossen von: {interaction.user.mention}",
                    color=discord.Color.red()
                )
                await log_channel.send(embed=embed)

        await interaction.response.send_message("Ticket wird gelöscht...", ephemeral=True)
        await interaction.channel.delete()


class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Allgemeine Frage", emoji="❓"),
            discord.SelectOption(label="Beschwerde", emoji="🚨"),
            discord.SelectOption(label="Kooperationsanfrage", emoji="🤝")
        ]

        super().__init__(
            placeholder="Tickettyp auswählen",
            options=options,
            custom_id="ticket_select"
        )

    async def callback(self, interaction: discord.Interaction):

        async with aiosqlite.connect(DB) as db:
            cur = await db.execute(
                "SELECT * FROM settings WHERE guild_id=?",
                (interaction.guild.id,)
            )
            settings = await cur.fetchone()

        if not settings:
            return await interaction.response.send_message(
                "Bitte zuerst /setup ausführen.",
                ephemeral=True
            )

        for channel in interaction.guild.channels:
            if isinstance(channel, discord.TextChannel):
                if channel.topic == f"OWNER:{interaction.user.id}":
                    return await interaction.response.send_message(
                        f"Du hast bereits ein Ticket: {channel.mention}",
                        ephemeral=True
                    )

        ticket_number = await next_ticket(interaction.guild.id)
        ticket_type = self.values[0]

        role_id = {
            "Allgemeine Frage": settings[3],
            "Beschwerde": settings[4],
            "Kooperationsanfrage": settings[5]
        }[ticket_type]

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
        }

        role = None
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True
                )

        category = interaction.guild.get_channel(settings[1])

        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{ticket_number:04d}",
            category=category,
            overwrites=overwrites,
            topic=f"OWNER:{interaction.user.id}"
        )

        embed = discord.Embed(
            title=f"🎫 Ticket #{ticket_number:04d}",
            description=f"**Typ:** {ticket_type}\n**Ersteller:** {interaction.user.mention}",
            color=discord.Color.blurple()
        )

        if role:
            await channel.send(role.mention)

        await channel.send(embed=embed, view=TicketButtons())

        await interaction.response.send_message(
            f"Ticket erstellt: {channel.mention}",
            ephemeral=True
        )


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


# ---------------- COG ----------------

class TicketSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        await db_init()
        self.bot.add_view(TicketView())
        self.bot.add_view(TicketButtons())

    @app_commands.command(name="setup")
    @app_commands.default_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction,
                    category: discord.CategoryChannel,
                    logs: discord.TextChannel):

        async with aiosqlite.connect(DB) as db:
            await db.execute("""
            INSERT OR REPLACE INTO settings(guild_id, category_id, log_channel_id)
            VALUES(?,?,?)
            """, (interaction.guild.id, category.id, logs.id))
            await db.commit()

        await interaction.response.send_message("Setup gespeichert.", ephemeral=True)

    @app_commands.command(name="ticketpanel")
    @app_commands.default_permissions(administrator=True)
    async def ticketpanel(self, interaction: discord.Interaction):

        embed = discord.Embed(
            title="🎫 Ticket System",
            description="❓ Frage\n🚨 Beschwerde\n🤝 Kooperation\n\nWähle unten einen Typ.",
            color=discord.Color.blurple()
        )

        await interaction.channel.send(embed=embed, view=TicketView())
        await interaction.response.send_message("Ticketpanel gesendet.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketSystem(bot))
