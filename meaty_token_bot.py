import os
import random
import re
import sqlite3
from dataclasses import dataclass
from typing import Optional

import discord
import psycopg
from discord import app_commands
from discord.ext import commands

# =========================================================
# Meaty Token Bot - Slash Command Casino / Token Tracker
# + Madden standings from shared Postgres
# + Weekly matchup channel creation from Postgres schedule
# =========================================================
# Setup:
# 1) pip install -U -r requirements.txt
# 2) Set DISCORD_BOT_TOKEN to your bot token
# 3) Optional: set GUILD_IDS to comma-separated server IDs for fast testing
# 4) Optional: set LOG_CHANNEL_ID for audit logging
# 5) Optional: set DATABASE_URL for Madden data (Railway Postgres)
# 6) Run: py meaty_token_bot.py
# =========================================================

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
GUILD_IDS_RAW = os.getenv("GUILD_IDS") or os.getenv("GUILD_ID", "")
GUILD_IDS = [int(x.strip()) for x in GUILD_IDS_RAW.split(",") if x.strip()]
TOKEN_DB_PATH = os.getenv("MEATY_TOKEN_DB", "meaty_tokens.db")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL", "")

ADMIN_ROLE_NAMES = {"Commissioner", "Admin", "COMMISH"}

PRIZE_WHEEL_COST = 2
BOOM_OR_BUST_COST = 5
MYSTERY_CRATE_COST = 8
ATTRIBUTE_COST = 3
NAME_CHANGE_COST = 5
ROOKIE_REVEAL_COST = 10
DEV_OPPORTUNITY_COST = 53
ROULETTE_MIN_BET = 1
ROULETTE_MAX_BET = 10

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# -----------------------------
# Token database helpers (SQLite)
# -----------------------------
class TokenDatabase:
    def __init__(self, path: str):
        self.path = path
        self._init_db()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    balance REAL NOT NULL DEFAULT 0,
                    total_earned REAL NOT NULL DEFAULT 0,
                    total_spent REAL NOT NULL DEFAULT 0,
                    casino_wins INTEGER NOT NULL DEFAULT 0,
                    casino_losses INTEGER NOT NULL DEFAULT 0,
                    bounty_wins INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    reason TEXT NOT NULL,
                    category TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS bounties (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    reward REAL NOT NULL,
                    created_by INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    claimed_by INTEGER,
                    claimed_at TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS shop_purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    cost REAL NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def ensure_user(self, user: discord.abc.User):
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,))
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO users (user_id, username) VALUES (?, ?)",
                    (user.id, str(user)),
                )
            else:
                cur.execute(
                    "UPDATE users SET username = ? WHERE user_id = ?",
                    (str(user), user.id),
                )
            conn.commit()

    def get_user(self, user: discord.abc.User):
        self.ensure_user(user)
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE user_id = ?", (user.id,))
            return cur.fetchone()

    def add_tokens(self, user: discord.abc.User, amount: float, reason: str, category: str):
        self.ensure_user(user)
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET balance = balance + ?, total_earned = total_earned + ? WHERE user_id = ?",
                (amount, max(amount, 0), user.id),
            )
            cur.execute(
                "INSERT INTO ledger (user_id, amount, reason, category) VALUES (?, ?, ?, ?)",
                (user.id, amount, reason, category),
            )
            conn.commit()

    def spend_tokens(self, user: discord.abc.User, amount: float, reason: str, category: str) -> bool:
        self.ensure_user(user)
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
            row = cur.fetchone()
            if row is None or row["balance"] < amount:
                return False
            cur.execute(
                "UPDATE users SET balance = balance - ?, total_spent = total_spent + ? WHERE user_id = ?",
                (amount, amount, user.id),
            )
            cur.execute(
                "INSERT INTO ledger (user_id, amount, reason, category) VALUES (?, ?, ?, ?)",
                (user.id, -amount, reason, category),
            )
            conn.commit()
            return True

    def record_shop_purchase(self, user: discord.abc.User, item_name: str, cost: float, notes: str = ""):
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO shop_purchases (user_id, item_name, cost, notes) VALUES (?, ?, ?, ?)",
                (user.id, item_name, cost, notes),
            )
            conn.commit()

    def update_casino_result(self, user: discord.abc.User, won: bool):
        self.ensure_user(user)
        with self.connect() as conn:
            cur = conn.cursor()
            field = "casino_wins" if won else "casino_losses"
            cur.execute(f"UPDATE users SET {field} = {field} + 1 WHERE user_id = ?", (user.id,))
            conn.commit()

    def leaderboard(self):
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE balance > 0 ORDER BY balance DESC, total_earned DESC")
            return cur.fetchall()

    def recent_ledger(self, user: discord.abc.User, limit: int = 10):
        self.ensure_user(user)
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM ledger WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user.id, limit),
            )
            return cur.fetchall()

    def create_bounty(self, title: str, description: str, reward: float, created_by: int):
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO bounties (title, description, reward, created_by) VALUES (?, ?, ?, ?)",
                (title, description, reward, created_by),
            )
            bounty_id = cur.lastrowid
            conn.commit()
            return bounty_id

    def list_active_bounties(self):
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM bounties WHERE is_active = 1 ORDER BY id DESC")
            return cur.fetchall()

    def claim_bounty(self, bounty_id: int, user: discord.abc.User) -> Optional[sqlite3.Row]:
        self.ensure_user(user)
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM bounties WHERE id = ? AND is_active = 1", (bounty_id,))
            bounty = cur.fetchone()
            if bounty is None:
                return None
            cur.execute(
                "UPDATE bounties SET is_active = 0, claimed_by = ?, claimed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (user.id, bounty_id),
            )
            cur.execute(
                "UPDATE users SET balance = balance + ?, total_earned = total_earned + ?, bounty_wins = bounty_wins + 1 WHERE user_id = ?",
                (bounty["reward"], bounty["reward"], user.id),
            )
            cur.execute(
                "INSERT INTO ledger (user_id, amount, reason, category) VALUES (?, ?, ?, ?)",
                (user.id, bounty["reward"], f"Claimed bounty #{bounty_id}: {bounty['title']}", "bounty"),
            )
            conn.commit()
            cur.execute("SELECT * FROM bounties WHERE id = ?", (bounty_id,))
            return cur.fetchone()

    def update_bounty_reward(self, bounty_id: int, reward: float) -> bool:
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE bounties SET reward = ? WHERE id = ?", (reward, bounty_id))
            conn.commit()
            return cur.rowcount > 0

    def get_bounty(self, bounty_id: int):
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM bounties WHERE id = ?", (bounty_id,))
            return cur.fetchone()


TOKEN_DB = TokenDatabase(TOKEN_DB_PATH)


# -----------------------------
# Utility helpers
# -----------------------------
def is_admin_member(member: discord.Member) -> bool:
    return any(role.name in ADMIN_ROLE_NAMES for role in member.roles)


def admin_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        if is_admin_member(interaction.user):
            return True
        raise app_commands.CheckFailure("You need the Commissioner or Admin role to use this command.")

    return app_commands.check(predicate)


def fmt_tokens(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def build_embed(title: str, description: str, color: int = 0x2F3136) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


async def send_log_message(message: str, embed: Optional[discord.Embed] = None):
    if not LOG_CHANNEL_ID:
        return

    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except Exception as exc:
            print(f"Failed to fetch log channel {LOG_CHANNEL_ID}: {exc}")
            return

    try:
        if embed is not None:
            await channel.send(content=message if message else None, embed=embed)
        else:
            await channel.send(message)
    except Exception as exc:
        print(f"Failed to send log message to channel {LOG_CHANNEL_ID}: {exc}")


def roulette_spin() -> tuple[int, str]:
    number = random.randint(0, 36)
    red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    if number == 0:
        color = "green"
    elif number in red_numbers:
        color = "red"
    else:
        color = "black"
    return number, color


def get_pg_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    return psycopg.connect(DATABASE_URL)


def fetch_standings_rows():
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.team_name,
                    t.conference_name,
                    t.division_name,
                    t.team_ovr,
                    s.wins,
                    s.losses,
                    s.ties,
                    s.win_pct,
                    s.seed,
                    s.pts_for,
                    s.pts_against,
                    s.turnover_diff
                FROM standings s
                JOIN teams t ON t.team_id = s.team_id
                ORDER BY s.wins DESC, s.win_pct DESC, s.pts_for DESC, t.team_name ASC
                """
            )
            return cur.fetchall()


def slugify_channel_name(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "team"


def normalize_team_name(value: str) -> str:
    value = value.lower().strip()
    value = value.replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def member_matches_team(member: discord.Member, team_name: str) -> bool:
    team_norm = normalize_team_name(team_name)

    possible_names = [
        member.display_name or "",
        member.name or "",
        getattr(member, "global_name", "") or "",
    ]

    for raw_name in possible_names:
        raw_norm = normalize_team_name(raw_name)
        if not raw_norm:
            continue
        if team_norm == raw_norm:
            return True
        if team_norm in raw_norm:
            return True

    return False


def find_member_for_team(guild: discord.Guild, team_name: str) -> Optional[discord.Member]:
    matches = [member for member in guild.members if member_matches_team(member, team_name)]

    if len(matches) == 1:
        return matches[0]

    exact_display_matches = [
        member
        for member in guild.members
        if normalize_team_name(member.display_name or "") == normalize_team_name(team_name)
    ]
    if len(exact_display_matches) == 1:
        return exact_display_matches[0]

    return None


def fetch_games_for_week(week: int):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    g.game_id,
                    g.week,
                    g.stage_index,
                    g.status,
                    away.team_name AS away_team_name,
                    home.team_name AS home_team_name,
                    g.away_team_id,
                    g.home_team_id
                FROM games g
                JOIN teams away ON away.team_id = g.away_team_id
                JOIN teams home ON home.team_id = g.home_team_id
                WHERE g.week = %s
                ORDER BY g.game_id ASC
                """,
                (week,),
            )
            return cur.fetchall()


@dataclass
class PrizeResult:
    title: str
    description: str
    payout: float = 0
    bonus_note: str = ""
    won: bool = False


# -----------------------------
# Bot events
# -----------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print(f"LOG_CHANNEL_ID: {LOG_CHANNEL_ID}")
    print(f"DATABASE_URL set: {'yes' if DATABASE_URL else 'no'}")
    try:
        if GUILD_IDS:
            for guild_id in GUILD_IDS:
                guild = discord.Object(id=guild_id)
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                print(f"Synced {len(synced)} guild commands to {guild_id}")
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global commands")
    except Exception as exc:
        print(f"Slash command sync failed: {exc}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        if interaction.response.is_done():
            await interaction.followup.send(str(error), ephemeral=True)
        else:
            await interaction.response.send_message(str(error), ephemeral=True)
        return

    if interaction.response.is_done():
        await interaction.followup.send(f"Something went wrong: {error}", ephemeral=True)
    else:
        await interaction.response.send_message(f"Something went wrong: {error}", ephemeral=True)


# -----------------------------
# Public commands
# -----------------------------
@bot.tree.command(name="ping", description="Check if the bot is online.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong. Meaty Token Bot is online.", ephemeral=True)


@bot.tree.command(name="standings", description="Show current league standings.")
async def standings(interaction: discord.Interaction):
    try:
        rows = fetch_standings_rows()
    except Exception as exc:
        await interaction.response.send_message(f"Failed to load standings: {exc}", ephemeral=True)
        return

    if not rows:
        await interaction.response.send_message("No standings data found.")
        return

    lines = []
    for idx, row in enumerate(rows, start=1):
        team_name = row[0]
        wins = row[4]
        losses = row[5]
        ties = row[6]
        win_pct = row[7] or 0
        seed = row[8] or 0
        team_ovr = row[3] or 0
        pts_for = row[9] or 0
        pts_against = row[10] or 0
        turnover_diff = row[11] or 0

        lines.append(
            f"**{idx}. {team_name}** ({wins}-{losses}-{ties}) | "
            f"Win%: {win_pct:.3f} | Seed: {seed} | Ovr: {team_ovr} | "
            f"PF: {pts_for} | PA: {pts_against} | TO: {turnover_diff}"
        )

    chunks = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > 3800:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))

    await interaction.response.send_message(
        embed=build_embed("🏈 League Standings", chunks[0], 0x5865F2)
    )
    for page_num, chunk in enumerate(chunks[1:], start=2):
        await interaction.followup.send(
            embed=build_embed(f"🏈 League Standings (Page {page_num})", chunk, 0x5865F2)
        )


@bot.tree.command(name="balance", description="Check your token balance.")
@app_commands.describe(user="Optional: check another user's balance")
async def balance(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    row = TOKEN_DB.get_user(target)
    embed = build_embed(
        f"💰 {target.display_name}'s Token Balance",
        (
            f"**Balance:** {fmt_tokens(row['balance'])}\n"
            f"**Total Earned:** {fmt_tokens(row['total_earned'])}\n"
            f"**Total Spent:** {fmt_tokens(row['total_spent'])}\n"
            f"**Casino Wins:** {row['casino_wins']}\n"
            f"**Casino Losses:** {row['casino_losses']}\n"
            f"**Bounties Claimed:** {row['bounty_wins']}"
        ),
        0x57F287,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Show everyone who currently has tokens.")
async def leaderboard(interaction: discord.Interaction):
    rows = TOKEN_DB.leaderboard()
    if not rows:
        await interaction.response.send_message("No users currently have tokens.")
        return

    lines = []
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"**{idx}.** <@{row['user_id']}> — {fmt_tokens(row['balance'])} tokens "
            f"(earned {fmt_tokens(row['total_earned'])}, spent {fmt_tokens(row['total_spent'])})"
        )

    chunks = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > 3800:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))

    await interaction.response.send_message(embed=build_embed("🏆 Token Leaderboard", chunks[0], 0xFEE75C))
    for page_num, chunk in enumerate(chunks[1:], start=2):
        await interaction.followup.send(
            embed=build_embed(f"🏆 Token Leaderboard (Page {page_num})", chunk, 0xFEE75C)
        )


@bot.tree.command(name="history", description="Show your most recent token activity.")
@app_commands.describe(user="Optional: check another user's recent ledger")
async def history(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    rows = TOKEN_DB.recent_ledger(target, 10)
    if not rows:
        await interaction.response.send_message(f"No token history found for {target.display_name}.")
        return

    lines = []
    for row in rows:
        sign = "+" if row["amount"] >= 0 else ""
        lines.append(
            f"`{row['created_at']}` {sign}{fmt_tokens(row['amount'])} — {row['reason']} ({row['category']})"
        )

    embed = build_embed(
        f"📜 {target.display_name}'s Recent Token History",
        "\n".join(lines),
        0x5865F2,
    )
    await interaction.response.send_message(embed=embed, ephemeral=(target == interaction.user))


@bot.tree.command(name="shop", description="Show the token shop.")
async def shop(interaction: discord.Interaction):
    embed = build_embed(
        "🛒 Token Shop",
        (
            f"**{ATTRIBUTE_COST}** — 1 attribute point *(attribute caps still apply)*\n"
            f"**{NAME_CHANGE_COST}** — Player name change\n"
            f"**{ROOKIE_REVEAL_COST}** — Rookie dev reveal\n"
            f"**{DEV_OPPORTUNITY_COST}** — Dev opportunity"
        ),
        0xEB459E,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="buy_attribute", description="Buy 1 attribute point from the token shop.")
@app_commands.describe(player_name="Player receiving the attribute point")
async def buy_attribute(interaction: discord.Interaction, player_name: str):
    ok = TOKEN_DB.spend_tokens(interaction.user, ATTRIBUTE_COST, f"Bought 1 attribute point for {player_name}", "shop")
    if not ok:
        await interaction.response.send_message("You do not have enough tokens for that purchase.", ephemeral=True)
        return
    TOKEN_DB.record_shop_purchase(interaction.user, "Attribute Point", ATTRIBUTE_COST, player_name)
    await interaction.response.send_message(
        f"✅ Purchase logged: **1 attribute point** for **{player_name}** for **{ATTRIBUTE_COST}** tokens."
    )
    await send_log_message(
        f"🛒 SHOP: {interaction.user.mention} bought **1 attribute point** for **{player_name}** for **{ATTRIBUTE_COST}** tokens."
    )


@bot.tree.command(name="buy_namechange", description="Buy a player name change from the token shop.")
@app_commands.describe(old_name="Current player name", new_name="Requested new player name")
async def buy_namechange(interaction: discord.Interaction, old_name: str, new_name: str):
    ok = TOKEN_DB.spend_tokens(interaction.user, NAME_CHANGE_COST, f"Name change {old_name} -> {new_name}", "shop")
    if not ok:
        await interaction.response.send_message("You do not have enough tokens for that purchase.", ephemeral=True)
        return
    TOKEN_DB.record_shop_purchase(interaction.user, "Player Name Change", NAME_CHANGE_COST, f"{old_name} -> {new_name}")
    await interaction.response.send_message(
        f"✅ Purchase logged: **{old_name}** will be changed to **{new_name}** for **{NAME_CHANGE_COST}** tokens."
    )
    await send_log_message(
        f"🛒 SHOP: {interaction.user.mention} bought a **name change** from **{old_name}** to **{new_name}** for **{NAME_CHANGE_COST}** tokens."
    )


@bot.tree.command(name="buy_rookiereveal", description="Buy a rookie dev reveal from the token shop.")
@app_commands.describe(player_name="Rookie player to reveal")
async def buy_rookiereveal(interaction: discord.Interaction, player_name: str):
    ok = TOKEN_DB.spend_tokens(interaction.user, ROOKIE_REVEAL_COST, f"Bought rookie dev reveal for {player_name}", "shop")
    if not ok:
        await interaction.response.send_message("You do not have enough tokens for that purchase.", ephemeral=True)
        return
    TOKEN_DB.record_shop_purchase(interaction.user, "Rookie Dev Reveal", ROOKIE_REVEAL_COST, player_name)
    await interaction.response.send_message(
        f"✅ Purchase logged: **Rookie dev reveal** for **{player_name}** for **{ROOKIE_REVEAL_COST}** tokens."
    )
    await send_log_message(
        f"🛒 SHOP: {interaction.user.mention} bought a **rookie dev reveal** for **{player_name}** for **{ROOKIE_REVEAL_COST}** tokens."
    )


@bot.tree.command(name="buy_devopportunity", description="Buy a dev opportunity from the token shop.")
@app_commands.describe(player_name="Player receiving the dev opportunity")
async def buy_devopportunity(interaction: discord.Interaction, player_name: str):
    ok = TOKEN_DB.spend_tokens(interaction.user, DEV_OPPORTUNITY_COST, f"Bought dev opportunity for {player_name}", "shop")
    if not ok:
        await interaction.response.send_message("You do not have enough tokens for that purchase.", ephemeral=True)
        return
    TOKEN_DB.record_shop_purchase(interaction.user, "Dev Opportunity", DEV_OPPORTUNITY_COST, player_name)
    await interaction.response.send_message(
        f"✅ Purchase logged: **Dev opportunity** for **{player_name}** for **{DEV_OPPORTUNITY_COST}** tokens."
    )
    await send_log_message(
        f"🛒 SHOP: {interaction.user.mention} bought a **dev opportunity** for **{player_name}** for **{DEV_OPPORTUNITY_COST}** tokens."
    )


@bot.tree.command(name="wheel", description="Spin the Prize Wheel.")
async def wheel(interaction: discord.Interaction):
    ok = TOKEN_DB.spend_tokens(interaction.user, PRIZE_WHEEL_COST, "Prize Wheel spin", "casino")
    if not ok:
        await interaction.response.send_message(
            f"You need **{PRIZE_WHEEL_COST}** tokens to spin the Prize Wheel.",
            ephemeral=True,
        )
        return

    roll = random.randint(1, 100)
    if roll <= 30:
        result = PrizeResult("No Prize", "The wheel lands on nothing. The house wins this round.", won=False)
    elif roll <= 55:
        result = PrizeResult("+1 Token", "Nice. The wheel gives you a small payout.", payout=1, won=True)
    elif roll <= 72:
        result = PrizeResult("+2 Tokens", "Solid hit. You won back the cost of the spin.", payout=2, won=True)
    elif roll <= 84:
        result = PrizeResult(
            "Free Name Change",
            "You won a cosmetic voucher. Commissioner can honor this manually.",
            won=True,
            bonus_note="Free Name Change Voucher",
        )
    elif roll <= 93:
        result = PrizeResult(
            "Free Rookie Dev Reveal",
            "Big hit. Commissioner can honor this manually.",
            won=True,
            bonus_note="Free Rookie Dev Reveal Voucher",
        )
    else:
        result = PrizeResult("Jackpot", "Huge spin. The wheel pays out +4 tokens.", payout=4, won=True)

    if result.payout > 0:
        TOKEN_DB.add_tokens(interaction.user, result.payout, f"Prize Wheel reward: {result.title}", "casino")
    TOKEN_DB.update_casino_result(interaction.user, result.won)

    extra = f"\n\n**Manual Bonus To Honor:** {result.bonus_note}" if result.bonus_note else ""
    embed = build_embed(
        f"🎡 Prize Wheel — {result.title}",
        f"**Cost:** {PRIZE_WHEEL_COST} tokens\n{result.description}{extra}",
        0xFEE75C if result.won else 0xED4245,
    )
    await interaction.response.send_message(embed=embed)
    await send_log_message(
        f"🎡 WHEEL: {interaction.user.mention} spun the Prize Wheel for **{PRIZE_WHEEL_COST}** tokens and got **{result.title}**.",
        embed=embed,
    )


@bot.tree.command(name="boomorbust", description="Risk tokens on a Boom or Bust roll.")
@app_commands.describe(player_name="Player attached to the gamble")
async def boomorbust(interaction: discord.Interaction, player_name: str):
    ok = TOKEN_DB.spend_tokens(interaction.user, BOOM_OR_BUST_COST, f"Boom or Bust on {player_name}", "casino")
    if not ok:
        await interaction.response.send_message(
            f"You need **{BOOM_OR_BUST_COST}** tokens to use Boom or Bust.",
            ephemeral=True,
        )
        return

    hit = random.randint(1, 100) <= 45
    TOKEN_DB.update_casino_result(interaction.user, hit)

    if hit:
        desc = (
            f"**BOOM.** {player_name} hit the upside roll.\n\n"
            "Commissioner reward suggestion: approve a modest player boost or 1-2 selected attribute points."
        )
        color = 0x57F287
        title = "💥 Boom or Bust — BOOM"
    else:
        desc = f"**BUST.** {player_name} gets nothing. The house keeps your tokens."
        color = 0xED4245
        title = "💀 Boom or Bust — BUST"

    embed = build_embed(title, f"**Cost:** {BOOM_OR_BUST_COST} tokens\n{desc}", color)
    await interaction.response.send_message(embed=embed)
    await send_log_message(
        f"💥 BOOM OR BUST: {interaction.user.mention} used Boom or Bust on **{player_name}** for **{BOOM_OR_BUST_COST}** tokens.",
        embed=embed,
    )


@bot.tree.command(name="mysterycrate", description="Open a Mystery Crate.")
async def mysterycrate(interaction: discord.Interaction):
    ok = TOKEN_DB.spend_tokens(interaction.user, MYSTERY_CRATE_COST, "Mystery Crate purchase", "casino")
    if not ok:
        await interaction.response.send_message(
            f"You need **{MYSTERY_CRATE_COST}** tokens to open a Mystery Crate.",
            ephemeral=True,
        )
        return

    roll = random.randint(1, 100)
    payout = 0
    bonus_note = ""
    won = True

    if roll <= 22:
        title = "Bust"
        desc = "The crate is empty. Brutal."
        won = False
    elif roll <= 42:
        title = "+2 Tokens"
        desc = "Small crate hit."
        payout = 2
    elif roll <= 57:
        title = "+4 Tokens"
        desc = "Good value crate."
        payout = 4
    elif roll <= 72:
        title = "Free Prize Wheel Spin"
        desc = "Commissioner can honor one free spin manually."
        bonus_note = "Free Prize Wheel Spin"
    elif roll <= 84:
        title = "Attribute Point Voucher"
        desc = "Commissioner can honor one free attribute point manually."
        bonus_note = "Free Attribute Point"
    elif roll <= 94:
        title = "Rookie Dev Reveal Voucher"
        desc = "Commissioner can honor one rookie dev reveal manually."
        bonus_note = "Free Rookie Dev Reveal"
    else:
        title = "Jackpot Crate"
        desc = "Massive crate. You win +8 tokens."
        payout = 8

    if payout > 0:
        TOKEN_DB.add_tokens(interaction.user, payout, f"Mystery Crate reward: {title}", "casino")
    TOKEN_DB.update_casino_result(interaction.user, won)

    extra = f"\n\n**Manual Bonus To Honor:** {bonus_note}" if bonus_note else ""
    embed = build_embed(
        f"📦 Mystery Crate — {title}",
        f"**Cost:** {MYSTERY_CRATE_COST} tokens\n{desc}{extra}",
        0x5865F2 if won else 0xED4245,
    )
    await interaction.response.send_message(embed=embed)
    await send_log_message(
        f"📦 MYSTERY CRATE: {interaction.user.mention} opened a Mystery Crate for **{MYSTERY_CRATE_COST}** tokens and got **{title}**.",
        embed=embed,
    )


@bot.tree.command(name="roulette", description="Bet tokens on roulette.")
@app_commands.describe(
    bet_type="Choose color, parity, range, or exact number",
    amount="How many tokens to bet",
    value="Use red/black, odd/even, low/high, or a number 0-36",
)
@app_commands.choices(
    bet_type=[
        app_commands.Choice(name="Color", value="color"),
        app_commands.Choice(name="Odd/Even", value="parity"),
        app_commands.Choice(name="Low/High", value="range"),
        app_commands.Choice(name="Exact Number", value="number"),
    ]
)
async def roulette(interaction: discord.Interaction, bet_type: app_commands.Choice[str], amount: float, value: str):
    if amount < ROULETTE_MIN_BET or amount > ROULETTE_MAX_BET:
        await interaction.response.send_message(
            f"Roulette bets must be between **{ROULETTE_MIN_BET}** and **{ROULETTE_MAX_BET}** tokens.",
            ephemeral=True,
        )
        return

    normalized = value.strip().lower()
    if bet_type.value == "color" and normalized not in {"red", "black"}:
        await interaction.response.send_message(
            "For color bets, value must be **red** or **black**.",
            ephemeral=True,
        )
        return
    if bet_type.value == "parity" and normalized not in {"odd", "even"}:
        await interaction.response.send_message(
            "For parity bets, value must be **odd** or **even**.",
            ephemeral=True,
        )
        return
    if bet_type.value == "range" and normalized not in {"low", "high"}:
        await interaction.response.send_message(
            "For range bets, value must be **low** or **high**.",
            ephemeral=True,
        )
        return
    if bet_type.value == "number":
        try:
            chosen_number = int(normalized)
        except ValueError:
            await interaction.response.send_message(
                "For number bets, value must be a whole number from **0** to **36**.",
                ephemeral=True,
            )
            return
        if not 0 <= chosen_number <= 36:
            await interaction.response.send_message(
                "For number bets, value must be between **0** and **36**.",
                ephemeral=True,
            )
            return
    else:
        chosen_number = None

    ok = TOKEN_DB.spend_tokens(interaction.user, amount, f"Roulette bet: {bet_type.value}={normalized}", "casino")
    if not ok:
        await interaction.response.send_message(
            "You do not have enough tokens for that roulette bet.",
            ephemeral=True,
        )
        return

    number, color = roulette_spin()
    won = False
    payout = 0.0

    if bet_type.value == "color":
        won = normalized == color
        if won:
            payout = amount * 2
    elif bet_type.value == "parity":
        if number != 0:
            result = "even" if number % 2 == 0 else "odd"
            won = normalized == result
            if won:
                payout = amount * 2
    elif bet_type.value == "range":
        if number != 0:
            result = "low" if 1 <= number <= 18 else "high"
            won = normalized == result
            if won:
                payout = amount * 2
    elif bet_type.value == "number":
        won = chosen_number == number
        if won:
            payout = amount * 10

    if payout > 0:
        TOKEN_DB.add_tokens(interaction.user, payout, f"Roulette payout: {bet_type.value}={normalized}", "casino")
    TOKEN_DB.update_casino_result(interaction.user, won)

    result_text = (
        f"**Wheel Result:** {number} ({color})\n"
        f"**Your Bet:** {bet_type.value} = {normalized}\n"
        f"**Bet Amount:** {fmt_tokens(amount)} tokens\n"
    )
    if won:
        result_text += f"**Outcome:** WIN — paid **{fmt_tokens(payout)}** tokens"
        color_code = 0x57F287
        title = "🎲 Roulette — WIN"
    else:
        result_text += "**Outcome:** LOSE — the house keeps your bet"
        color_code = 0xED4245
        title = "🎲 Roulette — LOSE"

    embed = build_embed(title, result_text, color_code)
    await interaction.response.send_message(embed=embed)
    await send_log_message(
        f"🎲 ROULETTE: {interaction.user.mention} bet **{fmt_tokens(amount)}** on **{bet_type.value}={normalized}**. Result: **{number} ({color})**.",
        embed=embed,
    )


@bot.tree.command(name="bounties", description="List all active bounties.")
async def bounties(interaction: discord.Interaction):
    rows = TOKEN_DB.list_active_bounties()
    if not rows:
        await interaction.response.send_message("There are no active bounties right now.")
        return

    lines = []
    for row in rows[:15]:
        lines.append(
            f"**#{row['id']} — {row['title']}**\n"
            f"Reward: **{fmt_tokens(row['reward'])}** tokens\n"
            f"{row['description']}"
        )

    embed = build_embed("🎯 Active Bounties", "\n\n".join(lines), 0xFEE75C)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="claimbounty", description="Claim an active bounty by ID.")
@app_commands.describe(bounty_id="The number shown on the bounty list")
async def claimbounty(interaction: discord.Interaction, bounty_id: int):
    bounty = TOKEN_DB.claim_bounty(bounty_id, interaction.user)
    if bounty is None:
        await interaction.response.send_message(
            "That bounty does not exist or has already been claimed.",
            ephemeral=True,
        )
        return

    embed = build_embed(
        f"🎯 Bounty Claimed — #{bounty['id']}",
        (
            f"**Title:** {bounty['title']}\n"
            f"**Reward:** {fmt_tokens(bounty['reward'])} tokens\n"
            f"**Claimed By:** {interaction.user.mention}"
        ),
        0x57F287,
    )
    await interaction.response.send_message(embed=embed)
    await send_log_message(
        f"🎯 BOUNTY CLAIMED: {interaction.user.mention} claimed bounty **#{bounty['id']} - {bounty['title']}** for **{fmt_tokens(bounty['reward'])}** tokens.",
        embed=embed,
    )


# -----------------------------
# Admin commands
# -----------------------------
@bot.tree.command(name="addtokens", description="Admin: add tokens to a user.")
@admin_only()
@app_commands.describe(user="User receiving tokens", amount="Amount to add", reason="Reason shown in the ledger")
async def addtokens(interaction: discord.Interaction, user: discord.Member, amount: float, reason: str):
    if amount <= 0:
        await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True)
        return
    TOKEN_DB.add_tokens(user, amount, reason, "admin")
    await interaction.response.send_message(
        f"✅ Added **{fmt_tokens(amount)}** tokens to {user.mention}.\n**Reason:** {reason}"
    )
    await send_log_message(
        f"💰 ADMIN: {interaction.user.mention} added **{fmt_tokens(amount)}** tokens to {user.mention}. Reason: **{reason}**"
    )


@bot.tree.command(name="removetokens", description="Admin: remove tokens from a user.")
@admin_only()
@app_commands.describe(user="User losing tokens", amount="Amount to remove", reason="Reason shown in the ledger")
async def removetokens(interaction: discord.Interaction, user: discord.Member, amount: float, reason: str):
    if amount <= 0:
        await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True)
        return

    row = TOKEN_DB.get_user(user)
    if row["balance"] < amount:
        await interaction.response.send_message(
            f"{user.mention} does not have enough tokens. Current balance: {fmt_tokens(row['balance'])}",
            ephemeral=True,
        )
        return

    success = TOKEN_DB.spend_tokens(user, amount, reason, "admin")
    if not success:
        await interaction.response.send_message("Failed to remove tokens.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ Removed **{fmt_tokens(amount)}** tokens from {user.mention}.\n**Reason:** {reason}"
    )
    await send_log_message(
        f"💸 ADMIN: {interaction.user.mention} removed **{fmt_tokens(amount)}** tokens from {user.mention}. Reason: **{reason}**"
    )


@bot.tree.command(name="createreward", description="Admin: quick-add standard token rewards.")
@admin_only()
@app_commands.describe(user="User receiving the reward", reward_type="Type of reward", notes="Optional notes")
@app_commands.choices(
    reward_type=[
        app_commands.Choice(name="Regular Stream Win (+1)", value="regular_win"),
        app_commands.Choice(name="Regular Stream Loss (+0.5)", value="regular_loss"),
        app_commands.Choice(name="GOTW Win (+2)", value="gotw_win"),
        app_commands.Choice(name="GOTW Loss (+1)", value="gotw_loss"),
        app_commands.Choice(name="Rival Win (+3)", value="rival_win"),
        app_commands.Choice(name="Rival Loss (+1.5)", value="rival_loss"),
        app_commands.Choice(name="Playoff Win (+3)", value="playoff_win"),
        app_commands.Choice(name="Playoff Loss (+1.5)", value="playoff_loss"),
        app_commands.Choice(name="Super Bowl Win (+4)", value="superbowl_win"),
        app_commands.Choice(name="Super Bowl Loss (+2)", value="superbowl_loss"),
        app_commands.Choice(name="Division Winner (+2)", value="division_winner"),
        app_commands.Choice(name="Award Win (+1.5)", value="award"),
        app_commands.Choice(name="Highlight of the Week (+0.5)", value="highlight"),
        app_commands.Choice(name="Recruit Bonus (+2)", value="recruit"),
    ]
)
async def createreward(
    interaction: discord.Interaction,
    user: discord.Member,
    reward_type: app_commands.Choice[str],
    notes: Optional[str] = None,
):
    reward_map = {
        "regular_win": (1, "Regular streamed game win"),
        "regular_loss": (0.5, "Regular streamed game loss"),
        "gotw_win": (2, "Game of the Week win"),
        "gotw_loss": (1, "Game of the Week loss"),
        "rival_win": (3, "Rival game win"),
        "rival_loss": (1.5, "Rival game loss"),
        "playoff_win": (3, "Playoff game win"),
        "playoff_loss": (1.5, "Playoff game loss"),
        "superbowl_win": (4, "Super Bowl win"),
        "superbowl_loss": (2, "Super Bowl loss"),
        "division_winner": (2, "Division winner"),
        "award": (1.5, "Award winner"),
        "highlight": (0.5, "Highlight of the Week"),
        "recruit": (2, "Recruit and retain bonus"),
    }
    amount, label = reward_map[reward_type.value]
    reason = label if not notes else f"{label} — {notes}"
    TOKEN_DB.add_tokens(user, amount, reason, "reward")
    await interaction.response.send_message(
        f"✅ Reward logged for {user.mention}: **{fmt_tokens(amount)}** tokens\n"
        f"**Type:** {label}\n"
        f"**Notes:** {notes or 'None'}"
    )
    await send_log_message(
        f"🏅 REWARD: {interaction.user.mention} awarded {user.mention} **{fmt_tokens(amount)}** tokens. Type: **{label}**. Notes: **{notes or 'None'}**"
    )


@bot.tree.command(name="createbounty", description="Admin: create a new bounty.")
@admin_only()
@app_commands.describe(title="Short bounty title", reward="Token reward", description="What must be done to claim it")
async def createbounty(interaction: discord.Interaction, title: str, reward: float, description: str):
    if reward <= 0:
        await interaction.response.send_message("Reward must be greater than 0.", ephemeral=True)
        return
    bounty_id = TOKEN_DB.create_bounty(title, description, reward, interaction.user.id)
    embed = build_embed(
        f"🎯 New Bounty Created — #{bounty_id}",
        f"**Title:** {title}\n**Reward:** {fmt_tokens(reward)} tokens\n**Objective:** {description}",
        0xFEE75C,
    )
    await interaction.response.send_message(embed=embed)
    await send_log_message(
        f"🎯 ADMIN: {interaction.user.mention} created bounty **#{bounty_id} - {title}** worth **{fmt_tokens(reward)}** tokens.",
        embed=embed,
    )


@bot.tree.command(name="updatebountyamount", description="Admin: change the reward amount for a specific bounty.")
@admin_only()
@app_commands.describe(bounty_id="Bounty number", reward="New token reward amount")
async def updatebountyamount(interaction: discord.Interaction, bounty_id: int, reward: float):
    if reward <= 0:
        await interaction.response.send_message("Reward must be greater than 0.", ephemeral=True)
        return

    existing = TOKEN_DB.get_bounty(bounty_id)
    if existing is None:
        await interaction.response.send_message("That bounty was not found.", ephemeral=True)
        return

    old_reward = existing["reward"]
    TOKEN_DB.update_bounty_reward(bounty_id, reward)
    updated = TOKEN_DB.get_bounty(bounty_id)
    embed = build_embed(
        f"🎯 Bounty Updated — #{bounty_id}",
        f"**Title:** {updated['title']}\n**Old Reward:** {fmt_tokens(old_reward)}\n**New Reward:** {fmt_tokens(reward)}",
        0x5865F2,
    )
    await interaction.response.send_message(embed=embed)
    await send_log_message(
        f"🎯 ADMIN: {interaction.user.mention} changed bounty **#{bounty_id}** from **{fmt_tokens(old_reward)}** to **{fmt_tokens(reward)}** tokens.",
        embed=embed,
    )


@bot.tree.command(name="postoverview", description="Admin: post the league token overview embed.")
@admin_only()
async def postoverview(interaction: discord.Interaction):
    embed = build_embed(
        "🎮 Meaty Tokens Overview",
        (
            "**How to Earn Tokens**\n"
            "• Regular stream win = 1\n"
            "• Regular stream loss = 0.5\n"
            "• GOTW win/loss = 2 / 1\n"
            "• Rival win/loss = 3 / 1.5\n"
            "• Playoff win/loss = 3 / 1.5\n"
            "• Super Bowl win/loss = 4 / 2\n"
            "• Division winner = 2\n"
            "• Award = 1.5 (max 3)\n"
            "• Highlight of the week = 0.5\n"
            "• Recruit bonus = 2\n\n"
            "**Core Rules**\n"
            "• Rewards do not stack\n"
            "• Highest eligible payout only\n"
            "• Fake streams / farming / collusion = commissioner action\n"
            "• Minimum 2 tokens earned to stay in league"
        ),
        0x5865F2,
    )
    await interaction.response.send_message("Posted below:")
    await interaction.channel.send(embed=embed)
    await send_log_message(
        f"📌 ADMIN: {interaction.user.mention} posted the token overview in {interaction.channel.mention}.",
        embed=embed,
    )


@bot.tree.command(name="create_week_channels", description="Admin: create one matchup channel per game for a week.")
@admin_only()
@app_commands.describe(
    week="Week number from the games table (preseason week 1 appears to be week 0)",
    category_name="Optional category name to create/use",
)
async def create_week_channels(
    interaction: discord.Interaction,
    week: int,
    category_name: Optional[str] = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        games = fetch_games_for_week(week)
    except Exception as exc:
        await interaction.followup.send(f"Failed to load games for week {week}: {exc}", ephemeral=True)
        return

    if not games:
        await interaction.followup.send(f"No games found for week {week}.", ephemeral=True)
        return

    guild = interaction.guild
    category_title = category_name or f"Week {week} Games"

    existing_category = discord.utils.get(guild.categories, name=category_title)
    if existing_category is None:
        existing_category = await guild.create_category(category_title)

    created_channels = []
    skipped_channels = []

    for game in games:
        game_id = game[0]
        game_week = game[1]
        stage_index = game[2]
        status = game[3]
        away_team_name = game[4]
        home_team_name = game[5]

        channel_name = f"wk{game_week}-{slugify_channel_name(away_team_name)}-vs-{slugify_channel_name(home_team_name)}"
        channel_name = channel_name[:100]

        existing_channel = discord.utils.get(guild.text_channels, name=channel_name)
        if existing_channel is not None:
            skipped_channels.append(f"{channel_name} (already exists)")
            continue

        away_member = find_member_for_team(guild, away_team_name)
        home_member = find_member_for_team(guild, home_team_name)

        channel = await guild.create_text_channel(
            name=channel_name,
            category=existing_category,
            topic=f"Game ID {game_id} | Week {game_week} | Stage {stage_index} | Status {status}",
        )

        mention_parts = []
        if away_member is not None:
            mention_parts.append(away_member.mention)
        else:
            mention_parts.append(f"**{away_team_name}** (no Discord match found)")

        if home_member is not None:
            mention_parts.append(home_member.mention)
        else:
            mention_parts.append(f"**{home_team_name}** (no Discord match found)")

        message_lines = [
            f"🏈 **Week {game_week} Matchup**",
            f"**Away:** {away_team_name}",
            f"**Home:** {home_team_name}",
            "",
            f"{mention_parts[0]} vs {mention_parts[1]}",
            "",
            "Use this channel to schedule your game.",
        ]

        await channel.send("\n".join(message_lines))
        created_channels.append(channel_name)

    summary_lines = [
        f"Created **{len(created_channels)}** channel(s) for week **{week}** in **{category_title}**."
    ]

    if skipped_channels:
        summary_lines.append("")
        summary_lines.append("Skipped:")
        summary_lines.extend(f"- {name}" for name in skipped_channels[:20])

    await interaction.followup.send("\n".join(summary_lines), ephemeral=True)

    await send_log_message(
        f"📅 SCHEDULE: {interaction.user.mention} created week {week} matchup channels. "
        f"Created: {len(created_channels)} | Skipped: {len(skipped_channels)}"
    )


if not BOT_TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN is missing. Set it as an environment variable before running the bot.")

bot.run(BOT_TOKEN)
