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

> Use : **pip install discord.py** (for example)

### Discord Bot Permissions :

The bot needs the following permissions :
- Send Messages
- Embed Links
- Attach Files
- Use Slash Commands

### Set-Up :

First, you need to create a **.env** file and set the discord bot token in it :

> **DISCORD_BOT_TOKEN={your token}**

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
- **/show** <name> — Display a card in your inventory
- **/inv** — Display your inventory
- **/list** — Display all the cards in the game with the progression
- **/profile** — Show your profile or someone else profile
- **/fav** — Define your favorite card
- **/give** <member> <card_name> — Give a card to a player

👑​ **Admin :**
- **/db** — Display all the cards avaible on the database
- **/status** — Display the status and the bot performances
- **/refresh** <member> — Refresh the looting cooldown of a player
- **/addcard** <name> <rarity> <image_url> <image_file> — Add a card to the database
- **/delcard** <name> — Delete a card to the database
- **/givecard** <name> — Give a card to your inventory

---

### Cards :

Each card has :
- **Name**
- **Rarity**
- **Image**
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
