import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
from datetime import datetime, timedelta, timezone
import random
import platform
import psutil
import os
from dotenv import load_dotenv

load_dotenv()

start_time = datetime.now(timezone.utc)

BOT_VERSION = "0.4.1"

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
COOLDOWN_HOURS = 2

if TOKEN is None:
    raise ValueError("Le token Discord n'est pas défini !")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

cards_cache = []

RARITY_COLORS = {
    "C": 0x95a5a6,
    "R" : 0x40d200,
    "SR": 0x3498db,
    "SSR": 0x9b59b6,
    "UR" : 0xff0000,
    "LR": 0xf1c40f,
    "???": 0x00e8ff
}

def get_loot(cards):
    rates = {
        "C": 0.35,
        "R": 0.30,
        "SR": 0.20,
        "SSR": 0.10,
        "UR": 0.04,
        "LR": 0.009,
        "???": 0.001
    }

    r = random.random()
    cumulative = 0
    rarity_selected = "C"
    for rarity, rate in rates.items():
        cumulative += rate
        if r <= cumulative:
            rarity_selected = rarity
            break

    candidates = [card for card in cards if card["rarity"] == rarity_selected]
    if not candidates:
        return random.choice(cards)
    
    random.shuffle(candidates)
    return candidates[0]

@bot.event
async def on_ready():
    global cards_cache
    await bot.tree.sync()
    print(f"Slash commands Synchronisées | {bot.user}")
    async with aiosqlite.connect("db.sqlite") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INT PRIMARY KEY,
                last_loot TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INT PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                rarity TEXT,
                image_url TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_cards (
                user_id INT,
                card_id INT,
                quantity INT,
                PRIMARY KEY (user_id, card_id)
            )
        """)
        await db.commit()

        async with db.execute("SELECT id, name, rarity, image_url FROM cards") as cursor:
            rows = await cursor.fetchall()
        cards_cache = [{"id": r[0], "name": r[1], "rarity": r[2], "image_url": r[3]} for r in rows]

    print(f"Bot prêt ! Connecté en tant que {bot.user}")

async def admin_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.",
            ephemeral=True
        )

@bot.tree.command(name="help", description="Affiche la liste des commandes")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 Commandes d'Arzmania's Card Game",
        color=0x3498db
    )

    player_commands = []
    admin_commands = []

    ADMIN_COMMANDS = {
        "db",
        "refresh",
        "addcard",
        "delcard",
        "givecard",
        "status"
    }

    for cmd in bot.tree.get_commands():
        cmd_name = cmd.name
        cmd_desc = cmd.description or "Pas de description"

        options_text = ""
        if cmd.parameters:
            options_text = " " + " ".join(f"<{p.name}>" for p in cmd.parameters)

        entry = f"/{cmd_name}{options_text} — {cmd_desc}"

        if cmd_name in ADMIN_COMMANDS:
            admin_commands.append(entry)
        else:
            player_commands.append(entry)

    if player_commands:
        embed.add_field(
            name="🎮 Joueurs",
            value="\n".join(player_commands),
            inline=False
        )

    if admin_commands:
        embed.add_field(
            name="👑​ Administrateurs",
            value="\n".join(admin_commands),
            inline=False
        )

    embed.set_footer(text=f"Demandé par {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="loot", description="Loot une carte aléatoire")
async def loot(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = datetime.now(timezone.utc)

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("SELECT last_loot FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

        if row:
            last_loot = datetime.fromisoformat(row[0])
            if now - last_loot < timedelta(hours=COOLDOWN_HOURS):
                remaining = timedelta(hours=COOLDOWN_HOURS) - (now - last_loot)
                h, rem = divmod(int(remaining.total_seconds()), 3600)
                m, s = divmod(rem, 60)
                await interaction.response.send_message(
                    f"⏳ Attends encore **{h}h {m}m {s}s**",
                    ephemeral=True
                )
                return

        card = get_loot(cards_cache)

        await db.execute(
            "INSERT OR REPLACE INTO users(user_id, last_loot) VALUES (?, ?)",
            (user_id, now.isoformat())
        )
        await db.execute("""
            INSERT INTO user_cards(user_id, card_id, quantity)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, card_id)
            DO UPDATE SET quantity = quantity + 1
        """, (user_id, card["id"]))
        await db.commit()

    embed = discord.Embed(
        title=card["name"],
        description=f"Rareté : **{card['rarity']}**",
        color=RARITY_COLORS.get(card["rarity"])
    )

    if card["image_url"]:
        embed.set_image(url=card["image_url"])

    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="show",
    description="Afficher une carte de ton inventaire"
)
@app_commands.describe(name="Affiche la carte demandée (utilise l'autocomplétion)")
async def show(interaction: discord.Interaction, name: str):
    user_id = interaction.user.id

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            """
            SELECT c.name, c.rarity, c.image_url, uc.quantity
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.id
            WHERE uc.user_id = ?
            AND LOWER(c.name) = LOWER(?)
            """, (user_id, name)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        await interaction.response.send_message(
            f"❌ {interaction.user.mention} tu ne possèdes pas la carte **{name}**",
            ephemeral=True
        )
        return
    
    card_name, rarity, image_url, quantity = row 

    embed = discord.Embed(
        title=card_name,
        description=f"**Rareté :** {rarity}\n**Quantité :** {quantity}",
        color=RARITY_COLORS.get(rarity, 0x95a5a6)
    )

    if image_url:
        embed.set_image(url=image_url)

    embed.set_footer(text=f"Inventaire de {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)

@show.autocomplete('name')
async def show_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete pour afficher uniquement les cartes que le joueur possède"""
    user_id = interaction.user.id
    
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            """
            SELECT c.name, c.rarity, uc.quantity
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.id
            WHERE uc.user_id = ? AND uc.quantity > 0
            ORDER BY c.name ASC
            """, (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    
    # Filter based on what user is typing
    matches = [
        (name, rarity, qty) for name, rarity, qty in rows
        if current.lower() in name.lower()
    ]
    
    # Return up to 25 choices (Discord limit)
    return [
        app_commands.Choice(
            name=f"{name} ({rarity}) × {qty}",
            value=name
        )
        for name, rarity, qty in matches[:25]
    ]

@bot.tree.command(
    name="inv",
    description="Afficher ton inventaire complet"
)
async def inv(interaction: discord.Interaction):
    user_id = interaction.user.id

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("""
            SELECT c.name, uc.quantity, c.rarity
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.id
            WHERE uc.user_id = ?
            ORDER BY
                CASE c.rarity
                    WHEN '???' THEN 1
                    WHEN 'LR' THEN 2 
                    WHEN 'UR' THEN 3
                    WHEN 'SSR' THEN 4
                    WHEN 'SR' THEN 5
                    WHEN 'R' THEN 6
                    WHEN 'C' THEN 7
                    ELSE 8
                END,
                c.name ASC
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message(
            f"{interaction.user.mention} ton inventaire est vide... 😢",
            ephemeral=True
        )
        return

    rarity_titles = {
        "???": "​♾️​ **SECRET**",
        "LR": "🟨 **LR**",
        "UR": "🟥 **UR**",
        "SSR": "🟪 **SSR**",
        "SR": "🟦 **SR**",
        "R": "🟩​ **R**",
        "C": "⬜ **C**"
    }

    rarity_emojis = {
        "???": "​♾️​",
        "LR": "🟨",
        "UR": "🟥​",
        "SSR": "🟪",
        "SR": "🟦",
        "R": "🟩​",
        "C": "⬜"
    }

    lines = []
    last_rarity = None

    for name, qty, rarity in rows:
        if rarity != last_rarity:
            if last_rarity is not None:
                lines.append("")
            lines.append(rarity_titles.get(rarity, "❓ **AUTRES**"))
            lines.append("═══════════════════╢")
            last_rarity = rarity

        lines.append(f"{rarity_emojis.get(rarity, '❓')} {name} × {qty}")

    embed = discord.Embed(
        title=f"🎒 Inventaire de {interaction.user.display_name}",
        description="\n".join(lines),
        color=0x2ecc71
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(
    name="list",
    description="Afficher toutes les cartes du jeu avec ta progression"
)
async def list_cards(interaction: discord.Interaction):
    user_id = interaction.user.id

    async with aiosqlite.connect("db.sqlite") as db:
        # Get all cards from database
        async with db.execute("""
            SELECT c.id, c.name, c.rarity
            FROM cards c
            ORDER BY
                CASE c.rarity
                    WHEN '???' THEN 1
                    WHEN 'LR' THEN 2 
                    WHEN 'UR' THEN 3
                    WHEN 'SSR' THEN 4
                    WHEN 'SR' THEN 5
                    WHEN 'R' THEN 6
                    WHEN 'C' THEN 7
                    ELSE 8
                END,
                c.name ASC
        """) as cursor:
            all_cards = await cursor.fetchall()

        # Get user's owned cards
        async with db.execute("""
            SELECT card_id, quantity
            FROM user_cards
            WHERE user_id = ?
        """, (user_id,)) as cursor:
            owned_cards = {row[0]: row[1] for row in await cursor.fetchall()}

    if not all_cards:
        await interaction.response.send_message(
            "📭 Aucune carte dans la base de données.",
            ephemeral=True
        )
        return

    rarity_titles = {
        "???": "​♾️​ **SECRET**",
        "LR": "🟨 **LR**",
        "UR": "🟥 **UR**",
        "SSR": "🟪 **SSR**",
        "SR": "🟦 **SR**",
        "R": "🟩​ **R**",
        "C": "⬜ **C**"
    }

    rarity_emojis = {
        "???": "​♾️​",
        "LR": "🟨",
        "UR": "🟥​",
        "SSR": "🟪",
        "SR": "🟦",
        "R": "🟩​",
        "C": "⬜"
    }

    lines = []
    last_rarity = None
    
    # Track completion per rarity
    rarity_stats = {}

    for card_id, name, rarity in all_cards:
        # Initialize rarity stats if needed
        if rarity not in rarity_stats:
            rarity_stats[rarity] = {"total": 0, "owned": 0}
        
        rarity_stats[rarity]["total"] += 1
        
        # Add rarity header
        if rarity != last_rarity:
            if last_rarity is not None:
                lines.append("")
            
            # Add completion percentage for previous rarity
            if last_rarity and last_rarity in rarity_stats:
                stats = rarity_stats[last_rarity]
                completion = (stats["owned"] / stats["total"] * 100) if stats["total"] > 0 else 0
                lines[-1] = f"{lines[-1]} [{stats['owned']}/{stats['total']} - {completion:.0f}%]"
            
            lines.append(rarity_titles.get(rarity, "❓ **AUTRES**"))
            lines.append("═══════════════════╢")
            last_rarity = rarity

        # Check if user owns this card
        if card_id in owned_cards:
            qty = owned_cards[card_id]
            lines.append(f"{rarity_emojis.get(rarity, '❓')} {name} × {qty}")
            rarity_stats[rarity]["owned"] += 1
        else:
            lines.append(f"{rarity_emojis.get(rarity, '❓')} ??? (Non possédée)")

    # Add completion for last rarity
    if last_rarity and last_rarity in rarity_stats:
        stats = rarity_stats[last_rarity]
        completion = (stats["owned"] / stats["total"] * 100) if stats["total"] > 0 else 0
        lines.append("")
        lines.append(f"Progression: {stats['owned']}/{stats['total']} ({completion:.0f}%)")

    # Calculate overall completion
    total_cards = sum(stats["total"] for stats in rarity_stats.values())
    owned_total = sum(stats["owned"] for stats in rarity_stats.values())
    overall_completion = (owned_total / total_cards * 100) if total_cards > 0 else 0

    embed = discord.Embed(
        title=f"📋 Collection complète - {interaction.user.display_name}",
        description="\n".join(lines),
        color=0xe67e22
    )
    
    embed.set_footer(text=f"Collection totale: {owned_total}/{total_cards} cartes ({overall_completion:.1f}%)")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="give", description="Donner une carte à un joueur")
@app_commands.describe(
    member="Le joueur qui reçoit la carte",
    card_name="Nom de la carte (utilise l'autocomplétion)"
)
async def give(
    interaction: discord.Interaction,
    member: discord.Member,
    card_name: str
):
    giver_id = interaction.user.id
    receiver_id = member.id

    if giver_id == receiver_id:
        await interaction.response.send_message(
            "❌ Tu ne peux pas te donner une carte",
            ephemeral=True
        )
        return

    async with aiosqlite.connect("db.sqlite") as db:
        # Get card info
        async with db.execute(
            "SELECT id, name, rarity FROM cards WHERE LOWER(name) = LOWER(?)",
            (card_name,)
        ) as cursor:
            card = await cursor.fetchone()

        if not card:
            await interaction.response.send_message(
                "❌ Carte inconnue",
                ephemeral=True
            )
            return

        card_id, actual_name, rarity = card

        # Check if giver has the card
        async with db.execute(
            "SELECT quantity FROM user_cards WHERE user_id = ? AND card_id = ?",
            (giver_id, card_id)
        ) as cursor:
            row = await cursor.fetchone()

        if not row or row[0] <= 0:
            await interaction.response.send_message(
                "❌ Tu ne possèdes pas cette carte",
                ephemeral=True
            )
            return

        # Remove card from giver
        new_quantity = row[0] - 1
        if new_quantity == 0:
            # Delete row if quantity reaches 0
            await db.execute(
                "DELETE FROM user_cards WHERE user_id = ? AND card_id = ?",
                (giver_id, card_id)
            )
        else:
            # Otherwise just decrease quantity
            await db.execute(
                "UPDATE user_cards SET quantity = ? WHERE user_id = ? AND card_id = ?",
                (new_quantity, giver_id, card_id)
            )

        # Add card to receiver
        await db.execute(
            """
            INSERT INTO user_cards (user_id, card_id, quantity)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, card_id)
            DO UPDATE SET quantity = quantity + 1
            """,
            (receiver_id, card_id)
        )

        await db.commit()

    await interaction.response.send_message(
        f"🎁 **{interaction.user.display_name}** a donné **{actual_name}** ({rarity}) à **{member.display_name}**"
    )

@give.autocomplete('card_name')
async def give_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete pour afficher uniquement les cartes que le joueur possède"""
    user_id = interaction.user.id
    
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            """
            SELECT c.name, c.rarity, uc.quantity
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.id
            WHERE uc.user_id = ? AND uc.quantity > 0
            ORDER BY c.name ASC
            """, (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    
    # Filter based on what user is typing
    matches = [
        (name, rarity, qty) for name, rarity, qty in rows
        if current.lower() in name.lower()
    ]
    
    # Return up to 25 choices (Discord limit)
    return [
        app_commands.Choice(
            name=f"{name} ({rarity}) × {qty}",
            value=name
        )
        for name, rarity, qty in matches[:25]
    ]


@bot.tree.command(
    name="db",
    description="Afficher toutes les cartes disponibles du jeu"
)
@app_commands.checks.has_permissions(administrator=True)
async def db(interaction: discord.Interaction):

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            """
            SELECT name, rarity
            FROM cards
            ORDER BY
                CASE rarity
                    WHEN '???' THEN 1
                    WHEN 'LR' THEN 2
                    WHEN 'UR' THEN 3
                    WHEN 'SSR' THEN 4
                    WHEN 'SR' THEN 5
                    WHEN 'R' THEN 6
                    WHEN 'C' THEN 7
                    ELSE 8
                END,
                name ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message(
            "📭 Aucune carte enregistrée dans la base de données.",
            ephemeral=True
        )
        return

    rarity_titles = {
        "???": "♾️ **SECRET**",
        "LR": "🟨 **LR**",
        "UR": "🟥 **UR**",
        "SSR": "🟪 **SSR**",
        "SR": "🟦 **SR**",
        "R": "🟩 **R**",
        "C": "⬜ **C**"
    }

    rarity_emojis = {
        "???": "♾️",
        "LR": "🟨",
        "UR": "🟥",
        "SSR": "🟪",
        "SR": "🟦",
        "R": "🟩",
        "C": "⬜"
    }

    lines = []
    last_rarity = None
    rarity_count = {}

    for name, rarity in rows:
        rarity_count[rarity] = rarity_count.get(rarity, 0) + 1

        if rarity != last_rarity:
            if last_rarity is not None:
                lines.append("")
            lines.append(rarity_titles.get(rarity, "❓ **AUTRES**"))
            lines.append("═══════════════════╢")
            last_rarity = rarity

        lines.append(f"{rarity_emojis.get(rarity, '❓')} {name}")

    footer_stats = " • ".join(
        f"{rarity}: {count}"
        for rarity, count in rarity_count.items()
    )

    embed = discord.Embed(
        title="📚 Base de données des cartes",
        description="\n".join(lines),
        color=0x7289da
    )
    embed.set_footer(text=f"{len(rows)} cartes au total • {footer_stats}")

    await interaction.response.send_message(embed=embed)

db.error(admin_error)

@bot.tree.command(
    name="status",
    description="Afficher le statut et les performances du bot"
)
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):

    # Uptime
    now = datetime.now(timezone.utc)
    uptime = now - start_time
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    # Ping
    latency = round(bot.latency * 1000)

    # Nombre de serveurs
    guild_count = len(bot.guilds)

    # Infos système
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory().percent

    embed = discord.Embed(
        title="🔹 Statut de Arzmania's Card Game",
        color=0x3498db,
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(name="Statut", value="✅ En ligne", inline=True)
    embed.add_field(name="Version", value=BOT_VERSION, inline=True)
    embed.add_field(name="Ping", value=f"{latency} ms", inline=True)
    embed.add_field(name="Uptime", value=uptime_str, inline=True)
    embed.add_field(name="Serveurs", value=guild_count, inline=True)
    embed.add_field(name="CPU", value=f"{cpu} %", inline=True)
    embed.add_field(name="RAM", value=f"{ram} %", inline=True)

    embed.set_footer(text=f"Demandé par {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)

status.error(admin_error)

@bot.tree.command(
    name="refresh",
    description="Réinitialiser le cooldown de loot d'un joueur"
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(member="Joueur dont le cooldown doit être réinitialisé")
async def refresh(interaction: discord.Interaction, member: discord.Member | None = None):

    target = member or interaction.user
    user_id = target.id

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            "SELECT 1 FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

        reset_time = (datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS + 1)).isoformat()

        if row:
            await db.execute(
                "UPDATE users SET last_loot = ? WHERE user_id = ?",
                (reset_time, user_id)
            )
        else:
            await db.execute(
                "INSERT INTO users(user_id, last_loot) VALUES (?, ?)",
                (user_id, reset_time)
            )

        await db.commit()

    await interaction.response.send_message(
        f"✅ Cooldown de loot réinitialisé pour **{target.display_name}**"
    )

refresh.error(admin_error)

RARITY_CHOICES = [
    app_commands.Choice(name="C", value="C"),
    app_commands.Choice(name="R", value="R"),
    app_commands.Choice(name="SR", value="SR"),
    app_commands.Choice(name="SSR", value="SSR"),
    app_commands.Choice(name="UR", value="UR"),
    app_commands.Choice(name="LR", value="LR"),
    app_commands.Choice(name="SECRET (???)", value="???"),
]

@bot.tree.command(
    name="addcard",
    description="Ajouter une carte à la base de données"
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    name="Nom de la carte",
    rarity="Rareté de la carte",
    image_url="URL de l'image (optionnel si vous joignez une image)",
    image_file="Fichier image à envoyer (optionnel si URL fournie)"
)
@app_commands.choices(rarity=RARITY_CHOICES)
async def addcard(
    interaction: discord.Interaction,
    name: str,
    rarity: app_commands.Choice[str],
    image_url: str = None,
    image_file: discord.Attachment = None
):

    if image_file is not None:
        image_url_final = image_file.url
    elif image_url is not None:
        image_url_final = image_url
    else:
        image_url_final = ""

    async with aiosqlite.connect("db.sqlite") as db:
        await db.execute(
            "INSERT INTO cards (name, rarity, image_url) VALUES (?, ?, ?)",
            (name, rarity.value, image_url_final)
        )
        await db.commit()

        global cards_cache
        async with db.execute(
            "SELECT id, name, rarity, image_url FROM cards"
        ) as cursor:
            rows = await cursor.fetchall()

        cards_cache = [
            {"id": r[0], "name": r[1], "rarity": r[2], "image_url": r[3]}
            for r in rows
        ]

    await interaction.response.send_message(
        f"✅ Carte **{name}** ajoutée ({rarity.value})",
        ephemeral=True
    )

addcard.error(admin_error)

@bot.tree.command(
    name="delcard",
    description="Supprimer une carte de la base de données"
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(name="Nom de la carte (utilise l'autocomplétion)")
async def delcard(interaction: discord.Interaction, name: str):

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            "SELECT id, rarity FROM cards WHERE LOWER(name) = LOWER(?)",
            (name,)
        ) as cursor:
            card = await cursor.fetchone()

        if not card:
            await interaction.response.send_message(
                f"❌ Aucune carte trouvée avec le nom **{name}**",
                ephemeral=True
            )
            return

        card_id, rarity = card

        await db.execute(
            "DELETE FROM user_cards WHERE card_id = ?",
            (card_id,)
        )
        await db.execute(
            "DELETE FROM cards WHERE id = ?",
            (card_id,)
        )
        await db.commit()

        # refresh cache
        global cards_cache
        async with db.execute(
            "SELECT id, name, rarity, image_url FROM cards"
        ) as cursor:
            rows = await cursor.fetchall()

        cards_cache = [
            {"id": r[0], "name": r[1], "rarity": r[2], "image_url": r[3]}
            for r in rows
        ]

    await interaction.response.send_message(
        f"🗑️ Carte supprimée : **{name}** ({rarity})"
    )

delcard.error(admin_error)

@delcard.autocomplete('name')
async def delcard_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete pour afficher toutes les cartes de la base de données"""
    
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            """
            SELECT name, rarity
            FROM cards
            ORDER BY name ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()
    
    # Filter based on what user is typing
    matches = [
        (name, rarity) for name, rarity in rows
        if current.lower() in name.lower()
    ]
    
    # Return up to 25 choices (Discord limit)
    return [
        app_commands.Choice(
            name=f"{name} ({rarity})",
            value=name
        )
        for name, rarity in matches[:25]
    ]

@bot.tree.command(
    name="givecard",
    description="Donner une carte à votre inventaire (admin)"
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(name="Nom de la carte (utilise l'autocomplétion)")
async def givecard(interaction: discord.Interaction, name: str):

    user_id = interaction.user.id

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            "SELECT id, name, rarity FROM cards WHERE LOWER(name) = LOWER(?)",
            (name,)
        ) as cursor:
            card = await cursor.fetchone()

        if not card:
            await interaction.response.send_message(
                f"❌ Carte **{name}** introuvable",
                ephemeral=True
            )
            return

        card_id, actual_name, rarity = card

        await db.execute(
            """
            INSERT INTO user_cards (user_id, card_id, quantity)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, card_id)
            DO UPDATE SET quantity = quantity + 1
            """,
            (user_id, card_id)
        )

        await db.commit()

    await interaction.response.send_message(
        f"🎁 **{interaction.user.display_name}** a reçu **{actual_name}** ({rarity})"
    )

givecard.error(admin_error)

@givecard.autocomplete('name')
async def givecard_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete pour afficher toutes les cartes de la base de données"""
    
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            """
            SELECT name, rarity
            FROM cards
            ORDER BY name ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()
    
    # Filter based on what user is typing
    matches = [
        (name, rarity) for name, rarity in rows
        if current.lower() in name.lower()
    ]
    
    # Return up to 25 choices (Discord limit)
    return [
        app_commands.Choice(
            name=f"{name} ({rarity})",
            value=name
        )
        for name, rarity in matches[:25]
    ]

bot.run(TOKEN)