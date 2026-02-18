import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
from datetime import datetime, timedelta, timezone
import random
import platform
import psutil
import os
import io
import base64
import aiohttp
from dotenv import load_dotenv

load_dotenv()

start_time = datetime.now(timezone.utc)

BOT_VERSION = "0.10.2"

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
COOLDOWN_HOURS = 2

if TOKEN is None:
    raise ValueError("Le token Discord n'est pas défini !")
if GITHUB_TOKEN is None:
    raise ValueError("Le token GitHub n'est pas défini !")
if GITHUB_REPO is None:
    raise ValueError("Le repo GitHub n'est pas défini !")

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

async def upload_image_to_github(image_data: bytes, filename: str) -> str | None:
    """
    Upload an image to the /cards/ folder of the GitHub repo.
    Returns the permanent githubusercontent.com CDN URL, or None on failure.
    """
    safe_name = filename.replace(" ", "_")
    path = f"cards/{safe_name}"
    
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    async with aiohttp.ClientSession() as session:
        sha = None
        async with session.get(api_url, headers=headers) as resp:
            if resp.status == 200:
                existing = await resp.json()
                sha = existing.get("sha")
        
        payload = {
            "message": f"Add card image: {safe_name}",
            "content": base64.b64encode(image_data).decode("utf-8"),
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha
        
        async with session.put(api_url, headers=headers, json=payload) as resp:
            if resp.status in (200, 201):
                result = await resp.json()
                download_url = result.get("content", {}).get("download_url")
                if download_url:
                    return download_url
                return f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{path}"
            else:
                error = await resp.text()
                print(f"[GitHub Upload Error] {resp.status}: {error}")
                return None

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

def calculate_duel_winner(card1, card2):
    rounds = []
    card1_wins = 0
    card2_wins = 0
    
    if card1['power'] > card2['power']:
        rounds.append({'round': 1, 'type': 'Power', 'winner': 1, 'card1_stat': card1['power'], 'card2_stat': card2['power']})
        card1_wins += 1
    elif card2['power'] > card1['power']:
        rounds.append({'round': 1, 'type': 'Power', 'winner': 2, 'card1_stat': card1['power'], 'card2_stat': card2['power']})
        card2_wins += 1
    else:
        rounds.append({'round': 1, 'type': 'Power', 'winner': 0, 'card1_stat': card1['power'], 'card2_stat': card2['power']})
    
    if card1['protection'] > card2['protection']:
        rounds.append({'round': 2, 'type': 'Protection', 'winner': 1, 'card1_stat': card1['protection'], 'card2_stat': card2['protection']})
        card1_wins += 1
    elif card2['protection'] > card1['protection']:
        rounds.append({'round': 2, 'type': 'Protection', 'winner': 2, 'card1_stat': card1['protection'], 'card2_stat': card2['protection']})
        card2_wins += 1
    else:
        rounds.append({'round': 2, 'type': 'Protection', 'winner': 0, 'card1_stat': card1['protection'], 'card2_stat': card2['protection']})
    
    total1 = card1['power'] + card1['protection']
    total2 = card2['power'] + card2['protection']
    
    if total1 > total2:
        rounds.append({'round': 3, 'type': 'Total', 'winner': 1, 'card1_stat': total1, 'card2_stat': total2})
        card1_wins += 1
    elif total2 > total1:
        rounds.append({'round': 3, 'type': 'Total', 'winner': 2, 'card1_stat': total1, 'card2_stat': total2})
        card2_wins += 1
    else:
        tiebreaker = random.choice([1, 2])
        rounds.append({'round': 3, 'type': 'Total (Égalité - Tirage au sort)', 'winner': tiebreaker, 'card1_stat': total1, 'card2_stat': total2})
        if tiebreaker == 1:
            card1_wins += 1
        else:
            card2_wins += 1
    
    if card1_wins > card2_wins:
        overall_winner = 1
    elif card2_wins > card1_wins:
        overall_winner = 2
    else:
        overall_winner = random.choice([1, 2])
    
    return overall_winner, rounds, card1_wins, card2_wins

@bot.event
async def on_ready():
    global cards_cache
    await bot.tree.sync()
    print(f"Slash commands Synchronisées | {bot.user}")
    async with aiosqlite.connect("db.sqlite") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INT PRIMARY KEY,
                last_loot TEXT,
                loot_count INT DEFAULT 0,
                favorite_card INT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INT PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                rarity TEXT,
                image_url TEXT,
                power INT DEFAULT 1,
                protection INT DEFAULT 1
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS duel_history (
                player1_id INT,
                player2_id INT,
                player1_wins INT DEFAULT 0,
                player2_wins INT DEFAULT 0,
                total_duels INT DEFAULT 0,
                last_duel TEXT,
                PRIMARY KEY (player1_id, player2_id)
            )
        """)
        
        for alter in [
            "ALTER TABLE users ADD COLUMN loot_count INT DEFAULT 0",
            "ALTER TABLE users ADD COLUMN favorite_card INT",
            "ALTER TABLE cards ADD COLUMN power INT DEFAULT 1",
            "ALTER TABLE cards ADD COLUMN protection INT DEFAULT 1",
        ]:
            try:
                await db.execute(alter)
            except:
                pass
        
        await db.commit()

        async with db.execute("SELECT id, name, rarity, image_url, power, protection FROM cards") as cursor:
            rows = await cursor.fetchall()
        cards_cache = [{"id": r[0], "name": r[1], "rarity": r[2], "image_url": r[3], "power": r[4], "protection": r[5]} for r in rows]

    print(f"Bot prêt ! Connecté en tant que {bot.user}")

async def admin_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.",
            ephemeral=True
        )

@bot.tree.command(name="help", description="Affiche la liste des commandes")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Commandes d'Arzmania's Card Game", color=0x3498db)

    player_commands = []
    admin_commands = []

    ADMIN_COMMANDS = {"db", "refresh", "addcard", "delcard", "givecard", "status", "backup", "fixcardimage", "refreshallimages"}

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
        embed.add_field(name="🎮 Joueurs", value="\n".join(player_commands), inline=False)
    if admin_commands:
        embed.add_field(name="👑​ Administrateurs", value="\n".join(admin_commands), inline=False)

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
                await interaction.response.send_message(f"⏳ Attends encore **{h}h {m}m {s}s**", ephemeral=True)
                return

        card = get_loot(cards_cache)

        await db.execute(
            "INSERT OR REPLACE INTO users(user_id, last_loot, loot_count) VALUES (?, ?, COALESCE((SELECT loot_count FROM users WHERE user_id = ?), 0) + 1)",
            (user_id, now.isoformat(), user_id)
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
        description=f"**Rareté :** {card['rarity']}\n⚔️ **Power :** {card['power']}/6\n🛡️ **Protection :** {card['protection']}/6",
        color=RARITY_COLORS.get(card["rarity"])
    )
    if card["image_url"]:
        embed.set_image(url=card["image_url"])
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="show", description="Afficher une carte de ton inventaire")
@app_commands.describe(name="Affiche la carte demandée (utilise l'autocomplétion)")
async def show(interaction: discord.Interaction, name: str):
    user_id = interaction.user.id

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            """
            SELECT c.name, c.rarity, c.image_url, uc.quantity, c.power, c.protection
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.id
            WHERE uc.user_id = ? AND LOWER(c.name) = LOWER(?)
            """, (user_id, name)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        await interaction.response.send_message(
            f"❌ {interaction.user.mention} tu ne possèdes pas la carte **{name}**", ephemeral=True
        )
        return
    
    card_name, rarity, image_url, quantity, power, protection = row

    embed = discord.Embed(
        title=card_name,
        description=f"**Rareté :** {rarity}\n**Quantité :** {quantity}\n⚔️ **Power :** {power}/6\n🛡️ **Protection :** {protection}/6",
        color=RARITY_COLORS.get(rarity, 0x95a5a6)
    )
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"Inventaire de {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

@show.autocomplete('name')
async def show_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    user_id = interaction.user.id
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            "SELECT c.name, c.rarity, uc.quantity FROM user_cards uc JOIN cards c ON uc.card_id = c.id WHERE uc.user_id = ? AND uc.quantity > 0 ORDER BY c.name ASC",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    matches = [(n, r, q) for n, r, q in rows if current.lower() in n.lower()]
    return [app_commands.Choice(name=f"{n} ({r}) × {q}", value=n) for n, r, q in matches[:25]]


@bot.tree.command(name="inv", description="Afficher ton inventaire complet")
async def inv(interaction: discord.Interaction):
    user_id = interaction.user.id

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("""
            SELECT c.name, uc.quantity, c.rarity
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.id
            WHERE uc.user_id = ?
            ORDER BY CASE c.rarity WHEN '???' THEN 1 WHEN 'LR' THEN 2 WHEN 'UR' THEN 3 WHEN 'SSR' THEN 4 WHEN 'SR' THEN 5 WHEN 'R' THEN 6 WHEN 'C' THEN 7 ELSE 8 END, c.name ASC
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message(f"{interaction.user.mention} ton inventaire est vide... 😢", ephemeral=True)
        return

    rarity_titles = {"???": "​♾️​ **SECRET**", "LR": "🟨 **LR**", "UR": "🟥 **UR**", "SSR": "🟪 **SSR**", "SR": "🟦 **SR**", "R": "🟩​ **R**", "C": "⬜ **C**"}
    rarity_emojis = {"???": "​♾️​", "LR": "🟨", "UR": "🟥​", "SSR": "🟪", "SR": "🟦", "R": "🟩​", "C": "⬜"}

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

    embed = discord.Embed(title=f"🎒 Inventaire de {interaction.user.display_name}", description="\n".join(lines), color=0x2ecc71)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="list", description="Afficher toutes les cartes du jeu avec ta progression")
async def list_cards(interaction: discord.Interaction):
    user_id = interaction.user.id

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("""
            SELECT c.id, c.name, c.rarity FROM cards c
            ORDER BY CASE c.rarity WHEN '???' THEN 1 WHEN 'LR' THEN 2 WHEN 'UR' THEN 3 WHEN 'SSR' THEN 4 WHEN 'SR' THEN 5 WHEN 'R' THEN 6 WHEN 'C' THEN 7 ELSE 8 END, c.name ASC
        """) as cursor:
            all_cards = await cursor.fetchall()

        async with db.execute("SELECT card_id, quantity FROM user_cards WHERE user_id = ?", (user_id,)) as cursor:
            owned_cards = {row[0]: row[1] for row in await cursor.fetchall()}

    if not all_cards:
        await interaction.response.send_message("📭 Aucune carte dans la base de données.", ephemeral=True)
        return

    rarity_titles = {"???": "​♾️​ **SECRET**", "LR": "🟨 **LR**", "UR": "🟥 **UR**", "SSR": "🟪 **SSR**", "SR": "🟦 **SR**", "R": "🟩​ **R**", "C": "⬜ **C**"}
    rarity_emojis = {"???": "​♾️​", "LR": "🟨", "UR": "🟥​", "SSR": "🟪", "SR": "🟦", "R": "🟩​", "C": "⬜"}

    lines = []
    last_rarity = None
    rarity_stats = {}

    for card_id, name, rarity in all_cards:
        if rarity not in rarity_stats:
            rarity_stats[rarity] = {"total": 0, "owned": 0}
        rarity_stats[rarity]["total"] += 1

        if rarity != last_rarity:
            if last_rarity is not None:
                lines.append("")
            lines.append(rarity_titles.get(rarity, "❓ **AUTRES**"))
            lines.append("═══════════════════╢")
            last_rarity = rarity

        if card_id in owned_cards:
            lines.append(f"{rarity_emojis.get(rarity, '❓')} {name} × {owned_cards[card_id]}")
            rarity_stats[rarity]["owned"] += 1
        else:
            lines.append(f"{rarity_emojis.get(rarity, '❓')} ??? (Non possédée)")

    total_cards = sum(s["total"] for s in rarity_stats.values())
    owned_total = sum(s["owned"] for s in rarity_stats.values())
    overall_completion = (owned_total / total_cards * 100) if total_cards > 0 else 0

    embed = discord.Embed(title=f"📋 Collection complète - {interaction.user.display_name}", description="\n".join(lines), color=0xe67e22)
    embed.set_footer(text=f"Collection totale: {owned_total}/{total_cards} cartes ({overall_completion:.1f}%)")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="profile", description="Afficher ton profil de collectionneur ou celui d'un autre joueur")
@app_commands.describe(member="Le joueur dont tu veux voir le profil (optionnel)")
async def profile(interaction: discord.Interaction, member: discord.Member = None):
    await interaction.response.defer()
    target = member or interaction.user
    user_id = target.id

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("SELECT loot_count, favorite_card FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user_row = await cursor.fetchone()
        loot_count = user_row[0] if user_row and user_row[0] else 0
        favorite_card_id = user_row[1] if user_row and user_row[1] else None

        async with db.execute("SELECT SUM(quantity) FROM user_cards WHERE user_id = ?", (user_id,)) as cursor:
            total_cards = (await cursor.fetchone())[0] or 0

        async with db.execute("SELECT COUNT(DISTINCT card_id) FROM user_cards WHERE user_id = ?", (user_id,)) as cursor:
            unique_cards = (await cursor.fetchone())[0] or 0

        async with db.execute("SELECT COUNT(*) FROM cards") as cursor:
            total_db_cards = (await cursor.fetchone())[0] or 1

        completion = (unique_cards / total_db_cards * 100) if total_db_cards > 0 else 0

        async with db.execute("""
            SELECT c.name, c.rarity FROM user_cards uc JOIN cards c ON uc.card_id = c.id WHERE uc.user_id = ?
            ORDER BY CASE c.rarity WHEN '???' THEN 1 WHEN 'LR' THEN 2 WHEN 'UR' THEN 3 WHEN 'SSR' THEN 4 WHEN 'SR' THEN 5 WHEN 'R' THEN 6 WHEN 'C' THEN 7 ELSE 8 END LIMIT 1
        """, (user_id,)) as cursor:
            rarest_row = await cursor.fetchone()
        rarest_card = f"{rarest_row[0]} ({rarest_row[1]})" if rarest_row else "Aucune"

        favorite_card_name = "Aucune"
        if favorite_card_id:
            async with db.execute("SELECT name, rarity FROM cards WHERE id = ?", (favorite_card_id,)) as cursor:
                fav_row = await cursor.fetchone()
            if fav_row:
                favorite_card_name = f"{fav_row[0]} ({fav_row[1]})"

    embed = discord.Embed(title=f"📊 Profil de {target.display_name}", color=0xe74c3c)
    embed.add_field(name="📦 Total de cartes", value=f"{total_cards} cartes", inline=True)
    embed.add_field(name="📚 Collection", value=f"{unique_cards}/{total_db_cards} ({completion:.1f}%)", inline=True)
    embed.add_field(name="🎰 Loots effectués", value=f"{loot_count}", inline=True)
    embed.add_field(name="💎 Carte la plus rare", value=rarest_card, inline=False)
    embed.add_field(name="⭐ Carte favorite", value=favorite_card_name, inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.set_footer(text="Utilise /fav pour définir ta carte favorite" if target.id == interaction.user.id else f"Profil consulté par {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="fav", description="Définir ta carte favorite")
@app_commands.describe(card_name="Nom de la carte (utilise l'autocomplétion)")
async def fav(interaction: discord.Interaction, card_name: str):
    user_id = interaction.user.id
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            "SELECT c.id, c.name, c.rarity FROM cards c JOIN user_cards uc ON c.id = uc.card_id WHERE uc.user_id = ? AND LOWER(c.name) = LOWER(?)",
            (user_id, card_name)
        ) as cursor:
            card_row = await cursor.fetchone()
        if not card_row:
            await interaction.response.send_message("❌ Tu ne possèdes pas cette carte", ephemeral=True)
            return
        card_id, actual_name, rarity = card_row
        await db.execute("UPDATE users SET favorite_card = ? WHERE user_id = ?", (card_id, user_id))
        await db.execute("INSERT OR IGNORE INTO users(user_id, favorite_card) VALUES (?, ?)", (user_id, card_id))
        await db.commit()
    await interaction.response.send_message(f"⭐ **{actual_name}** ({rarity}) est maintenant ta carte favorite !")

@fav.autocomplete('card_name')
async def fav_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    user_id = interaction.user.id
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            "SELECT c.name, c.rarity FROM user_cards uc JOIN cards c ON uc.card_id = c.id WHERE uc.user_id = ? AND uc.quantity > 0 ORDER BY c.name ASC",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    matches = [(n, r) for n, r in rows if current.lower() in n.lower()]
    return [app_commands.Choice(name=f"{n} ({r})", value=n) for n, r in matches[:25]]


@bot.tree.command(name="duel", description="Défier un autre joueur en duel de cartes !")
@app_commands.describe(
    opponent="Le joueur que tu veux défier",
    your_card="Ta carte pour le duel (utilise l'autocomplétion)",
    opponent_card="La carte de ton adversaire (optionnel - sinon aléatoire)"
)
async def duel(interaction: discord.Interaction, opponent: discord.Member, your_card: str, opponent_card: str = None):
    challenger_id = interaction.user.id
    opponent_id = opponent.id

    if challenger_id == opponent_id:
        await interaction.response.send_message("❌ Tu ne peux pas te défier toi-même !", ephemeral=True)
        return
    if opponent.bot:
        await interaction.response.send_message("❌ Tu ne peux pas défier un bot !", ephemeral=True)
        return

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            "SELECT c.id, c.name, c.rarity, c.power, c.protection, c.image_url FROM cards c JOIN user_cards uc ON c.id = uc.card_id WHERE uc.user_id = ? AND LOWER(c.name) = LOWER(?)",
            (challenger_id, your_card)
        ) as cursor:
            card1_data = await cursor.fetchone()
        if not card1_data:
            await interaction.response.send_message(f"❌ Tu ne possèdes pas la carte **{your_card}**", ephemeral=True)
            return
        card1 = {'id': card1_data[0], 'name': card1_data[1], 'rarity': card1_data[2], 'power': card1_data[3], 'protection': card1_data[4], 'image_url': card1_data[5]}

        if opponent_card:
            async with db.execute(
                "SELECT c.id, c.name, c.rarity, c.power, c.protection, c.image_url FROM cards c JOIN user_cards uc ON c.id = uc.card_id WHERE uc.user_id = ? AND LOWER(c.name) = LOWER(?)",
                (opponent_id, opponent_card)
            ) as cursor:
                card2_data = await cursor.fetchone()
            if not card2_data:
                await interaction.response.send_message(f"❌ {opponent.mention} ne possède pas la carte **{opponent_card}**", ephemeral=True)
                return
        else:
            async with db.execute(
                "SELECT c.id, c.name, c.rarity, c.power, c.protection, c.image_url FROM cards c JOIN user_cards uc ON c.id = uc.card_id WHERE uc.user_id = ? ORDER BY RANDOM() LIMIT 1",
                (opponent_id,)
            ) as cursor:
                card2_data = await cursor.fetchone()
            if not card2_data:
                await interaction.response.send_message(f"❌ {opponent.mention} n'a aucune carte dans son inventaire !", ephemeral=True)
                return
        card2 = {'id': card2_data[0], 'name': card2_data[1], 'rarity': card2_data[2], 'power': card2_data[3], 'protection': card2_data[4], 'image_url': card2_data[5]}

    winner, rounds, card1_wins, card2_wins = calculate_duel_winner(card1, card2)

    async with aiosqlite.connect("db.sqlite") as db:
        if challenger_id < opponent_id:
            p1_id, p2_id = challenger_id, opponent_id
            p1_won = (winner == 1)
        else:
            p1_id, p2_id = opponent_id, challenger_id
            p1_won = (winner == 2)

        async with db.execute("SELECT player1_wins, player2_wins, total_duels FROM duel_history WHERE player1_id = ? AND player2_id = ?", (p1_id, p2_id)) as cursor:
            history = await cursor.fetchone()

        if history:
            p1_wins, p2_wins, total = history
            if p1_won: p1_wins += 1
            else: p2_wins += 1
            total += 1
            await db.execute("UPDATE duel_history SET player1_wins = ?, player2_wins = ?, total_duels = ?, last_duel = ? WHERE player1_id = ? AND player2_id = ?",
                (p1_wins, p2_wins, total, datetime.now(timezone.utc).isoformat(), p1_id, p2_id))
        else:
            p1_wins = 1 if p1_won else 0
            p2_wins = 0 if p1_won else 1
            total = 1
            await db.execute("INSERT INTO duel_history (player1_id, player2_id, player1_wins, player2_wins, total_duels, last_duel) VALUES (?, ?, ?, ?, ?, ?)",
                (p1_id, p2_id, p1_wins, p2_wins, total, datetime.now(timezone.utc).isoformat()))
        await db.commit()

        challenger_total_wins = p1_wins if challenger_id < opponent_id else p2_wins
        opponent_total_wins = p2_wins if challenger_id < opponent_id else p1_wins

    embed = discord.Embed(title="⚔️ DUEL DE CARTES ⚔️", color=0xe74c3c if winner == 1 else 0x3498db)
    embed.add_field(name=f"🔴 {interaction.user.display_name}", value=f"**{card1['name']}** ({card1['rarity']})\n⚔️ Power: {card1['power']}/6\n🛡️ Protection: {card1['protection']}/6", inline=True)
    embed.add_field(name=f"🔵 {opponent.display_name}", value=f"**{card2['name']}** ({card2['rarity']})\n⚔️ Power: {card2['power']}/6\n🛡️ Protection: {card2['protection']}/6", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=False)

    round_emojis = {1: "🥇", 2: "🥈", 3: "🥉"}
    for round_info in rounds:
        rn = round_info['round']
        rw = round_info['winner']
        result = "⚖️ Égalité" if rw == 0 else (f"🔴 {interaction.user.display_name} gagne" if rw == 1 else f"🔵 {opponent.display_name} gagne")
        embed.add_field(name=f"{round_emojis[rn]} Round {rn}: {round_info['type']}", value=f"{round_info['card1_stat']} vs {round_info['card2_stat']}\n{result}", inline=True)

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    if winner == 1:
        embed.add_field(name="🏆 VAINQUEUR", value=f"**{interaction.user.display_name}** remporte le duel {card1_wins}-{card2_wins} !\n\n📊 **Historique vs {opponent.display_name}:**\n{interaction.user.display_name}: {challenger_total_wins} victoires\n{opponent.display_name}: {opponent_total_wins} victoires\n*Total: {total} duels*", inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
    else:
        embed.add_field(name="🏆 VAINQUEUR", value=f"**{opponent.display_name}** remporte le duel {card2_wins}-{card1_wins} !\n\n📊 **Historique vs {interaction.user.display_name}:**\n{opponent.display_name}: {opponent_total_wins} victoires\n{interaction.user.display_name}: {challenger_total_wins} victoires\n*Total: {total} duels*", inline=False)
        embed.set_thumbnail(url=opponent.display_avatar.url)

    await interaction.response.send_message(embed=embed)

@duel.autocomplete('your_card')
async def duel_your_card_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    user_id = interaction.user.id
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            "SELECT c.name, c.rarity, c.power, c.protection FROM user_cards uc JOIN cards c ON uc.card_id = c.id WHERE uc.user_id = ? AND uc.quantity > 0 ORDER BY c.name ASC",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    matches = [(n, r, p, pr) for n, r, p, pr in rows if current.lower() in n.lower()]
    return [app_commands.Choice(name=f"{n} ({r}) - ⚔️{p} 🛡️{pr}", value=n) for n, r, p, pr in matches[:25]]

@duel.autocomplete('opponent_card')
async def duel_opponent_card_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    namespace = interaction.namespace
    opponent = namespace.opponent if hasattr(namespace, 'opponent') else None
    if not opponent:
        return [app_commands.Choice(name="Sélectionne d'abord un adversaire", value="")]
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            "SELECT c.name, c.rarity, c.power, c.protection FROM user_cards uc JOIN cards c ON uc.card_id = c.id WHERE uc.user_id = ? AND uc.quantity > 0 ORDER BY c.name ASC",
            (opponent.id,)
        ) as cursor:
            rows = await cursor.fetchall()
    matches = [(n, r, p, pr) for n, r, p, pr in rows if current.lower() in n.lower()]
    return [app_commands.Choice(name=f"{n} ({r}) - ⚔️{p} 🛡️{pr}", value=n) for n, r, p, pr in matches[:25]]


@bot.tree.command(name="duelstats", description="Voir tes statistiques de duels ou celles d'un autre joueur")
@app_commands.describe(member="Le joueur dont tu veux voir les stats (optionnel)")
async def duelstats(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    user_id = target.id
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("SELECT player2_id, player1_wins, player2_wins, total_duels FROM duel_history WHERE player1_id = ?", (user_id,)) as cursor:
            as_player1 = await cursor.fetchall()
        async with db.execute("SELECT player1_id, player2_wins, player1_wins, total_duels FROM duel_history WHERE player2_id = ?", (user_id,)) as cursor:
            as_player2 = await cursor.fetchall()

    all_duels = as_player1 + as_player2
    if not all_duels:
        await interaction.response.send_message(f"📊 **{target.display_name}** n'a encore participé à aucun duel !", ephemeral=True)
        return

    total_wins = sum(d[1] for d in all_duels)
    total_losses = sum(d[2] for d in all_duels)
    total_duels = sum(d[3] for d in all_duels)
    win_rate = (total_wins / total_duels * 100) if total_duels > 0 else 0

    embed = discord.Embed(title=f"⚔️ Statistiques de Duels - {target.display_name}", color=0xf39c12)
    embed.add_field(name="📊 Statistiques Globales", value=f"**Total de duels :** {total_duels}\n**Victoires :** {total_wins} 🏆\n**Défaites :** {total_losses} 💀\n**Taux de victoire :** {win_rate:.1f}%", inline=False)

    rivalries = []
    for opponent_id, wins, losses, total in all_duels:
        try:
            opponent = await bot.fetch_user(opponent_id)
            rivalries.append({'name': opponent.display_name, 'wins': wins, 'losses': losses, 'total': total})
        except:
            continue

    if rivalries:
        rivalries.sort(key=lambda x: x['total'], reverse=True)
        rivalry_text = [f"**{i}. {r['name']}**\n   {r['wins']}W - {r['losses']}L ({r['total']} duels)" for i, r in enumerate(rivalries[:5], 1)]
        embed.add_field(name="🎯 Top Rivalités", value="\n".join(rivalry_text), inline=False)

    embed.set_thumbnail(url=target.display_avatar.url)
    embed.set_footer(text=f"Demandé par {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="give", description="Donner une carte à un joueur")
@app_commands.describe(member="Le joueur qui reçoit la carte", card_name="Nom de la carte (utilise l'autocomplétion)")
async def give(interaction: discord.Interaction, member: discord.Member, card_name: str):
    giver_id = interaction.user.id
    receiver_id = member.id

    if giver_id == receiver_id:
        await interaction.response.send_message("❌ Tu ne peux pas te donner une carte", ephemeral=True)
        return

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("SELECT id, name, rarity FROM cards WHERE LOWER(name) = LOWER(?)", (card_name,)) as cursor:
            card = await cursor.fetchone()
        if not card:
            await interaction.response.send_message("❌ Carte inconnue", ephemeral=True)
            return
        card_id, actual_name, rarity = card

        async with db.execute("SELECT quantity FROM user_cards WHERE user_id = ? AND card_id = ?", (giver_id, card_id)) as cursor:
            row = await cursor.fetchone()
        if not row or row[0] <= 0:
            await interaction.response.send_message("❌ Tu ne possèdes pas cette carte", ephemeral=True)
            return

        new_quantity = row[0] - 1
        if new_quantity == 0:
            await db.execute("DELETE FROM user_cards WHERE user_id = ? AND card_id = ?", (giver_id, card_id))
        else:
            await db.execute("UPDATE user_cards SET quantity = ? WHERE user_id = ? AND card_id = ?", (new_quantity, giver_id, card_id))

        await db.execute("INSERT INTO user_cards (user_id, card_id, quantity) VALUES (?, ?, 1) ON CONFLICT(user_id, card_id) DO UPDATE SET quantity = quantity + 1", (receiver_id, card_id))
        await db.commit()

    await interaction.response.send_message(f"🎁 **{interaction.user.display_name}** a donné **{actual_name}** ({rarity}) à **{member.display_name}**")

@give.autocomplete('card_name')
async def give_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    user_id = interaction.user.id
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(
            "SELECT c.name, c.rarity, uc.quantity FROM user_cards uc JOIN cards c ON uc.card_id = c.id WHERE uc.user_id = ? AND uc.quantity > 0 ORDER BY c.name ASC",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    matches = [(n, r, q) for n, r, q in rows if current.lower() in n.lower()]
    return [app_commands.Choice(name=f"{n} ({r}) × {q}", value=n) for n, r, q in matches[:25]]


@bot.tree.command(name="db", description="Afficher toutes les cartes disponibles du jeu")
@app_commands.checks.has_permissions(administrator=True)
async def db_cmd(interaction: discord.Interaction):
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("""
            SELECT name, rarity FROM cards
            ORDER BY CASE rarity WHEN '???' THEN 1 WHEN 'LR' THEN 2 WHEN 'UR' THEN 3 WHEN 'SSR' THEN 4 WHEN 'SR' THEN 5 WHEN 'R' THEN 6 WHEN 'C' THEN 7 ELSE 8 END, name ASC
        """) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message("📭 Aucune carte enregistrée dans la base de données.", ephemeral=True)
        return

    rarity_titles = {"???": "♾️ **SECRET**", "LR": "🟨 **LR**", "UR": "🟥 **UR**", "SSR": "🟪 **SSR**", "SR": "🟦 **SR**", "R": "🟩 **R**", "C": "⬜ **C**"}
    rarity_emojis = {"???": "♾️", "LR": "🟨", "UR": "🟥", "SSR": "🟪", "SR": "🟦", "R": "🟩", "C": "⬜"}

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

    footer_stats = " • ".join(f"{r}: {c}" for r, c in rarity_count.items())
    embed = discord.Embed(title="📚 Base de données des cartes", description="\n".join(lines), color=0x7289da)
    embed.set_footer(text=f"{len(rows)} cartes au total • {footer_stats}")
    await interaction.response.send_message(embed=embed)

db_cmd.error(admin_error)


@bot.tree.command(name="status", description="Afficher le statut et les performances du bot")
@app_commands.checks.has_permissions(administrator=True)
async def status(interaction: discord.Interaction):
    now = datetime.now(timezone.utc)
    uptime = now - start_time
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    embed = discord.Embed(title="🔹 Statut de Arzmania's Card Game", color=0x3498db, timestamp=now)
    embed.add_field(name="Statut", value="✅ En ligne", inline=True)
    embed.add_field(name="Version", value=BOT_VERSION, inline=True)
    embed.add_field(name="Ping", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Uptime", value=f"{hours}h {minutes}m {seconds}s", inline=True)
    embed.add_field(name="Serveurs", value=len(bot.guilds), inline=True)
    embed.add_field(name="CPU", value=f"{psutil.cpu_percent(interval=0.5)} %", inline=True)
    embed.add_field(name="RAM", value=f"{psutil.virtual_memory().percent} %", inline=True)
    embed.set_footer(text=f"Demandé par {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

status.error(admin_error)


@bot.tree.command(name="refresh", description="Réinitialiser le cooldown de loot d'un joueur")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(member="Joueur dont le cooldown doit être réinitialisé")
async def refresh(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    user_id = target.id
    reset_time = (datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS + 1)).isoformat()

    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row:
            await db.execute("UPDATE users SET last_loot = ? WHERE user_id = ?", (reset_time, user_id))
        else:
            await db.execute("INSERT INTO users(user_id, last_loot) VALUES (?, ?)", (user_id, reset_time))
        await db.commit()

    await interaction.response.send_message(f"✅ Cooldown de loot réinitialisé pour **{target.display_name}**")

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

@bot.tree.command(name="addcard", description="Ajouter une carte à la base de données")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    name="Nom de la carte",
    rarity="Rareté de la carte",
    power="Niveau de puissance (1-6)",
    protection="Niveau de protection (1-6)",
    image_url="URL de l'image (optionnel si vous joignez une image)",
    image_file="Fichier image à envoyer (optionnel si URL fournie)"
)
@app_commands.choices(rarity=RARITY_CHOICES)
async def addcard(
    interaction: discord.Interaction,
    name: str,
    rarity: app_commands.Choice[str],
    power: int,
    protection: int,
    image_url: str = None,
    image_file: discord.Attachment = None
):
    if not (1 <= power <= 6):
        await interaction.response.send_message("❌ Le niveau de puissance doit être entre 1 et 6", ephemeral=True)
        return
    if not (1 <= protection <= 6):
        await interaction.response.send_message("❌ Le niveau de protection doit être entre 1 et 6", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    image_url_final = ""

    try:
        if image_file is not None:
            image_data = await image_file.read()
            ext = image_file.filename.split('.')[-1]
            filename = f"{name}.{ext}"
            github_url = await upload_image_to_github(image_data, filename)
            if not github_url:
                await interaction.followup.send("❌ Échec de l'upload de l'image sur GitHub.", ephemeral=True)
                return
            image_url_final = github_url

        elif image_url is not None:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(f"❌ Impossible de télécharger l'image (Status: {resp.status})", ephemeral=True)
                        return
                    image_data = await resp.read()
            ext = image_url.split('.')[-1].split('?')[0]
            if ext not in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                ext = 'png'
            filename = f"{name}.{ext}"
            github_url = await upload_image_to_github(image_data, filename)
            if not github_url:
                await interaction.followup.send("❌ Échec de l'upload de l'image sur GitHub.", ephemeral=True)
                return
            image_url_final = github_url

        async with aiosqlite.connect("db.sqlite") as db:
            await db.execute(
                "INSERT INTO cards (name, rarity, image_url, power, protection) VALUES (?, ?, ?, ?, ?)",
                (name, rarity.value, image_url_final, power, protection)
            )
            await db.commit()

            global cards_cache
            async with db.execute("SELECT id, name, rarity, image_url, power, protection FROM cards") as cursor:
                rows = await cursor.fetchall()
            cards_cache = [{"id": r[0], "name": r[1], "rarity": r[2], "image_url": r[3], "power": r[4], "protection": r[5]} for r in rows]

        await interaction.followup.send(
            f"✅ Carte **{name}** ajoutée ({rarity.value}) - ⚔️ {power}/6 | 🛡️ {protection}/6",
            ephemeral=True
        )

    except Exception as e:
        await interaction.followup.send(f"❌ Erreur : {str(e)}", ephemeral=True)

addcard.error(admin_error)


@bot.tree.command(name="fixcardimage", description="Réparer l'image d'une carte existante")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    card_name="Nom de la carte (utilise l'autocomplétion)",
    new_image="Nouvelle image à uploader"
)
async def fixcardimage(interaction: discord.Interaction, card_name: str, new_image: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    try:
        image_data = await new_image.read()
        ext = new_image.filename.split('.')[-1]
        filename = f"{card_name}.{ext}"

        github_url = await upload_image_to_github(image_data, filename)
        if not github_url:
            await interaction.followup.send("❌ Échec de l'upload sur GitHub.", ephemeral=True)
            return

        async with aiosqlite.connect("db.sqlite") as db:
            await db.execute(
                "UPDATE cards SET image_url = ? WHERE LOWER(name) = LOWER(?)",
                (github_url, card_name)
            )
            await db.commit()

            global cards_cache
            async with db.execute("SELECT id, name, rarity, image_url, power, protection FROM cards") as cursor:
                rows = await cursor.fetchall()
            cards_cache = [{"id": r[0], "name": r[1], "rarity": r[2], "image_url": r[3], "power": r[4], "protection": r[5]} for r in rows]

        await interaction.followup.send(f"✅ Image mise à jour pour **{card_name}**\n🔗 {github_url}", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"❌ Erreur : {str(e)}", ephemeral=True)

fixcardimage.error(admin_error)

@fixcardimage.autocomplete('card_name')
async def fixcardimage_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("SELECT name, rarity FROM cards ORDER BY name ASC") as cursor:
            rows = await cursor.fetchall()
    matches = [(n, r) for n, r in rows if current.lower() in n.lower()]
    return [app_commands.Choice(name=f"{n} ({r})", value=n) for n, r in matches[:25]]


@bot.tree.command(name="refreshallimages", description="Rafraîchir toutes les URLs d'images de cartes (fix Discord cache)")
@app_commands.checks.has_permissions(administrator=True)
async def refreshallimages(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    try:
        async with aiosqlite.connect("db.sqlite") as db:
            async with db.execute("SELECT id, name, image_url FROM cards WHERE image_url != ''") as cursor:
                cards = await cursor.fetchall()
        
        if not cards:
            await interaction.followup.send("❌ Aucune carte avec image trouvée.", ephemeral=True)
            return
        
        updated = 0
        failed = []
        
        for card_id, name, old_url in cards:
            if not old_url or "raw.githubusercontent.com" not in old_url:
                continue
            
            import re
            match = re.search(r'github\.com/[^/]+/[^/]+/[^/]+/(.+)$', old_url)
            if match:
                file_path = match.group(1)
                new_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{file_path}?v={int(datetime.now(timezone.utc).timestamp())}"
                
                async with aiosqlite.connect("db.sqlite") as db:
                    await db.execute("UPDATE cards SET image_url = ? WHERE id = ?", (new_url, card_id))
                    await db.commit()
                
                updated += 1
            else:
                failed.append(name)
        
        async with aiosqlite.connect("db.sqlite") as db:
            async with db.execute("SELECT id, name, rarity, image_url, power, protection FROM cards") as cursor:
                rows = await cursor.fetchall()
        global cards_cache
        cards_cache = [{"id": r[0], "name": r[1], "rarity": r[2], "image_url": r[3], "power": r[4], "protection": r[5]} for r in rows]
        
        result_msg = f"✅ **{updated}** URLs d'images rafraîchies avec succès!"
        if failed:
            result_msg += f"\n⚠️ Impossible de rafraîchir: {', '.join(failed)}"
        
        await interaction.followup.send(result_msg, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Erreur: {str(e)}", ephemeral=True)

refreshallimages.error(admin_error)


@bot.tree.command(name="delcard", description="Supprimer une carte de la base de données")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(name="Nom de la carte (utilise l'autocomplétion)")
async def delcard(interaction: discord.Interaction, name: str):
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("SELECT id, rarity FROM cards WHERE LOWER(name) = LOWER(?)", (name,)) as cursor:
            card = await cursor.fetchone()
        if not card:
            await interaction.response.send_message(f"❌ Aucune carte trouvée avec le nom **{name}**", ephemeral=True)
            return
        card_id, rarity = card
        await db.execute("DELETE FROM user_cards WHERE card_id = ?", (card_id,))
        await db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        await db.commit()

        global cards_cache
        async with db.execute("SELECT id, name, rarity, image_url, power, protection FROM cards") as cursor:
            rows = await cursor.fetchall()
        cards_cache = [{"id": r[0], "name": r[1], "rarity": r[2], "image_url": r[3], "power": r[4], "protection": r[5]} for r in rows]

    await interaction.response.send_message(f"🗑️ Carte supprimée : **{name}** ({rarity})")

delcard.error(admin_error)

@delcard.autocomplete('name')
async def delcard_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("SELECT name, rarity FROM cards ORDER BY name ASC") as cursor:
            rows = await cursor.fetchall()
    matches = [(n, r) for n, r in rows if current.lower() in n.lower()]
    return [app_commands.Choice(name=f"{n} ({r})", value=n) for n, r in matches[:25]]


@bot.tree.command(name="givecard", description="Donner une carte à votre inventaire (admin)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(name="Nom de la carte (utilise l'autocomplétion)")
async def givecard(interaction: discord.Interaction, name: str):
    user_id = interaction.user.id
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("SELECT id, name, rarity FROM cards WHERE LOWER(name) = LOWER(?)", (name,)) as cursor:
            card = await cursor.fetchone()
        if not card:
            await interaction.response.send_message(f"❌ Carte **{name}** introuvable", ephemeral=True)
            return
        card_id, actual_name, rarity = card
        await db.execute("INSERT INTO user_cards (user_id, card_id, quantity) VALUES (?, ?, 1) ON CONFLICT(user_id, card_id) DO UPDATE SET quantity = quantity + 1", (user_id, card_id))
        await db.commit()
    await interaction.response.send_message(f"🎁 **{interaction.user.display_name}** a reçu **{actual_name}** ({rarity})")

givecard.error(admin_error)

@givecard.autocomplete('name')
async def givecard_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute("SELECT name, rarity FROM cards ORDER BY name ASC") as cursor:
            rows = await cursor.fetchall()
    matches = [(n, r) for n, r in rows if current.lower() in n.lower()]
    return [app_commands.Choice(name=f"{n} ({r})", value=n) for n, r in matches[:25]]


@bot.tree.command(name="backup", description="Créer une sauvegarde de la base de données")
@app_commands.checks.has_permissions(administrator=True)
async def backup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    import shutil
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_filename = f"backup_db_{timestamp}.sqlite"
    backup_path = f"/tmp/{backup_filename}"

    try:
        shutil.copy2("db.sqlite", backup_path)
        file = discord.File(backup_path, filename=backup_filename)

        async with aiosqlite.connect("db.sqlite") as db:
            async with db.execute("SELECT COUNT(*) FROM cards") as cursor:
                card_count = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                user_count = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM duel_history") as cursor:
                duel_count = (await cursor.fetchone())[0]

        embed = discord.Embed(title="💾 Sauvegarde de la base de données", description=f"Sauvegarde créée avec succès !\n**Fichier :** {backup_filename}", color=0x2ecc71, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="📊 Statistiques", value=f"**Cartes :** {card_count}\n**Utilisateurs :** {user_count}\n**Historique de duels :** {duel_count}", inline=False)
        embed.set_footer(text=f"Sauvegarde créée par {interaction.user.display_name}")

        await interaction.followup.send(embed=embed, file=file, ephemeral=True)
        os.remove(backup_path)

    except Exception as e:
        await interaction.followup.send(f"❌ Erreur lors de la création de la sauvegarde : {str(e)}", ephemeral=True)

backup.error(admin_error)

bot.run(TOKEN)