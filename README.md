# Arzmania's Card Bot
A french discord bot which manage a trade card game with custom cards.

### Requirements :

- Python 3.10+
- Discord account
- A Discord bot application
- Internet connection

### Dependencies :

- discord.py
- aiosqlite
- python-dotenv
- psutil
- aiohttp

> Use : **pip install discord.py** (for example)

### Discord Bot Permissions :

The bot needs the following permissions :
- Send Messages
- Embed Links
- Attach Files
- Use Slash Commands

### Set-Up :

First, you need to create a **.env** file and set the discord bot token in it, along with your GitHub token used to host card images :

> **DISCORD_BOT_TOKEN={your token}**
> **GITHUB_TOKEN={your token}**
> **GITHUB_REPO={your username/repo}**
> **GITHUB_BRANCH={your branch, default : main}**

Then, you'll need to host the bot on your pc or on a hosting service and run it with the correct token.

---

### How to Use : 

Once the Set-Up part is completed and the bot runs correctly, you can do the **/status** command to check some informations like : 

- **Status :** Online
- **Version :** The current version
- **Ping :** The time of response from the bot
- **Uptime :** Timer who starts when running the bot
- **Serveurs :** The number of servers where the bot is running
- **CPU :** The using percentage of the processor
- **RAM :** The using percentage of the memory

To see all the commands avaible, you can do the **/help** command :

🎮 **Players :**
- **/help** — Display the list of the commands
- **/loot** — Loot a random card
- **/sploot** <event> — Loot a special card tied to an ongoing event (with pity system)
- **/eventpity** <event> — Check your pity progression on an event
- **/show** <name> — Display a card in your inventory
- **/inv** — Display your inventory
- **/list** — Display all the cards in the game with the progression
- **/profile** <member> — Show your profile or someone else profile
- **/fav** <card_name> — Define your favorite card
- **/duel** <opponent> <your_card> <opponent_card> — Challenge another player to a card duel !
- **/duelstats** <member> — Show your duel statistics or another player
- **/give** <member> <card_name> — Give a card to a player

👑 **Admin :**
- **/db** — Display all the cards avaible on the database
- **/status** — Display the status and the bot performances
- **/refresh** <member> — Refresh the looting cooldown of a player
- **/addcard** <name> <rarity> <power> <protection> <image_url> <image_file> — Add a card to the database
- **/delcard** <name> — Delete a card to the database
- **/givecard** <name> — Give a card to your inventory
- **/backup** — Create a save of the database
- **/fixcardimage** <card_name> <new_image> — Fix the image of a card
- **/refreshallimages** — Refresh all card image URLs (fix Discord's image cache)
- **/eventcreate** <name> <duration_hours> <pity_threshold> — Create a new special loot event
- **/eventaddcard** <event_name> <card_name> <drop_rate> — Add or update a boosted card in an event
- **/eventremovecard** <event_name> <card_name> — Remove a boosted card from an event
- **/eventsetpity** <event_name> <pity_threshold> — Change the pity threshold of an existing event
- **/eventresetpity** <event_name> <member> — Reset a player's pity counter on an event
- **/eventdelete** <event_name> — Delete an event
- **/eventlist** — See all events (active and ended) and their boosted cards

---

### Cards :

Each card has :
- **Name**
- **Rarity**
- **Image**
- **Power** (1-6)
- **Protection** (1-6)
- **Drop rate** (based on rarity)

Rarity affects the probability of looting a card :

| Rarity | Drop Rate |
|---|---|
| C | 35% |
| R | 30% |
| SR | 20% |
| SSR | 10% |
| UR | 4% |
| LR | 0,9% |
| ??? | 0,1% |

---

### Events & Pity System :

Admins can create timed **events** (`/eventcreate`) that unlock the **/sploot** command for players, alongside a dedicated **pity system** to guarantee a boosted card over time.

**How it works :**

- Each event has a **duration** and a **pity threshold** (default : 15 failed attempts).
- Admins can attach one or more **boosted cards** to an event (`/eventaddcard`), each with its own **drop rate** (%).
- On each `/sploot`, every boosted card is rolled independently against its own drop rate.
- If none of them hit, the player's personal pity counter for that event increases by 1.
- Once the counter reaches the event's pity threshold, the **next** `/sploot` guarantees a boosted card — picked randomly, weighted by each card's drop rate if there are several.
- Landing a boosted card (naturally or via pity) resets the counter back to 0.

**Cooldown :**

`/sploot` shares the **same cooldown** as `/loot` (2h for normal players, 1h for server boosters) — it does not stack on top of the regular loot cooldown.

**Checking your progress :**

Players can check their pity counter anytime with **/eventpity <event>**, which shows how many more failed sploots remain before the guarantee triggers.

---

### Fighting System :

**How it works :**

Round 1: Pure Power comparison → Higher wins
Round 2: Pure Protection comparison → Higher wins
Round 3: (Power + Protection) total → Higher wins
Best of 3 rounds wins the duel

**Example :**

Card A: Power 6, Protection 2 (Total: 8)
Card B: Power 4, Protection 4 (Total: 8)
Round 1: A wins (6 > 4)
Round 2: B wins (4 > 2)
Round 3: Draw (8 = 8) → Coin flip or random