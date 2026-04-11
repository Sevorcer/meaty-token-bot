import os
import random
import re
import sqlite3
import asyncio
import json
from dataclasses import dataclass
from typing import Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

import discord
import psycopg
from psycopg.rows import dict_row
from discord import app_commands
from discord.ext import commands

# =========================================================
# Meaty Token Bot
# =========================================================

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
GUILD_IDS_RAW = os.getenv("GUILD_IDS") or os.getenv("GUILD_ID", "")
GUILD_IDS = [int(x.strip()) for x in GUILD_IDS_RAW.split(",") if x.strip()]
TOKEN_DB_PATH = os.getenv("MEATY_TOKEN_DB", "meaty_tokens.db")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
LEADERS_CHANNEL_ID = int(os.getenv("LEADERS_CHANNEL_ID", "0"))
NEWS_CHANNEL_ID = int(os.getenv("NEWS_CHANNEL_ID", "0"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
AUTO_POST_MATCHUP_PREVIEWS = os.getenv("AUTO_POST_MATCHUP_PREVIEWS", "true").lower() in {"1", "true", "yes", "on"}
AUTO_POST_WEEKLY_NEWS = os.getenv("AUTO_POST_WEEKLY_NEWS", "true").lower() in {"1", "true", "yes", "on"}
DATABASE_URL = os.getenv("DATABASE_URL", "")

ADMIN_ROLE_NAMES = {"Commissioner", "Admin", "COMMISH"}

STAGE_LABELS = {
    1: "Preseason",
    2: "Regular Season",
    3: "Wild Card",
    4: "Divisional",
    5: "Conference Championship",
    6: "Super Bowl",
    7: "Offseason",
}
STAGE_PARSE_MAP = {
    "auto": None,
    "preseason": 1,
    "regular": 2,
    "regular season": 2,
    "wild card": 3,
    "wildcard": 3,
    "divisional": 4,
    "conference": 5,
    "conference championship": 5,
    "super bowl": 6,
    "superbowl": 6,
    "offseason": 7,
}
COMPLETE_GAME_STATUS_VALUES = {2, 4, 5, 6, 7, 8}

DEV_TRAIT_LABELS = {
    0: "Normal",
    1: "Star",
    2: "Superstar",
    3: "X-Factor",
}

DEV_TRAIT_EMOJIS = {
    0: "⚪",
    1: "⭐",
    2: "🌟",
    3: "🔥",
}

DEV_TRAIT_COLORS = {
    0: 0x95A5A6,
    1: 0xF1C40F,
    2: 0x9B59B6,
    3: 0xE74C3C,
}

ROSTER_PAGE_SIZE = 15
POSITION_SORT_ORDER = {
    "QB": 1,
    "HB": 2,
    "FB": 3,
    "WR": 4,
    "TE": 5,
    "LT": 6,
    "LG": 7,
    "C": 8,
    "RG": 9,
    "RT": 10,
    "LEDGE": 11,
    "REDGE": 12,
    "LE": 13,
    "RE": 14,
    "DT": 15,
    "LOLB": 16,
    "MLB": 17,
    "ROLB": 18,
    "SAM": 19,
    "MIKE": 20,
    "WILL": 21,
    "CB": 22,
    "FS": 23,
    "SS": 24,
    "K": 25,
    "P": 26,
    "LS": 27,
}

PRIZE_WHEEL_COST = 2
BOOM_OR_BUST_COST = 5
MYSTERY_CRATE_COST = 8
ATTRIBUTE_COST = 3
NAME_CHANGE_COST = 5
ROOKIE_REVEAL_COST = 10
DEV_OPPORTUNITY_COST = 53

ROULETTE_MIN_BET = 1
ROULETTE_MAX_BET = 15

BLACKJACK_MIN_BET = 1
BLACKJACK_MAX_BET = 25
BLACKJACK_BLACKJACK_MULTIPLIER = 2.5
BLACKJACK_WIN_MULTIPLIER = 2.0

CASINO_DELETE_DELAY = 60
BLACKJACK_FINISHED_DELETE_DELAY = 180

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


def schedule_message_delete(message: discord.Message, delay: int):
    async def _delete_later():
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except Exception:
            pass
    asyncio.create_task(_delete_later())


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
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


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


def stage_display_name(stage_index: int) -> str:
    return STAGE_LABELS.get(stage_index, f"Stage {stage_index}")


def stage_channel_prefix(stage_index: int) -> str:
    return {
        1: "pre-wk",
        2: "wk",
        3: "wc",
        4: "div",
        5: "conf",
        6: "sb",
    }.get(stage_index, f"s{stage_index}-w")


def stage_week_label(stage_index: int, display_week: int) -> str:
    if stage_index == 2:
        return f"Week {display_week}"
    if stage_index == 1:
        return f"Preseason Week {display_week}"
    if stage_index == 3:
        return f"Wild Card Week {display_week}"
    if stage_index == 4:
        return f"Divisional Week {display_week}"
    if stage_index == 5:
        return f"Conference Championship Week {display_week}"
    if stage_index == 6:
        return "Super Bowl"
    return f"{stage_display_name(stage_index)} Week {display_week}"


def parse_phase_to_stage_index(phase: Optional[str]) -> Optional[int]:
    if phase is None:
        return None
    return STAGE_PARSE_MAP.get(phase.strip().lower())


def looks_like_completed_game(row) -> bool:
    away_score = int(row.get("away_score") or 0)
    home_score = int(row.get("home_score") or 0)
    if away_score > 0 or home_score > 0:
        return True
    status = row.get("status")
    try:
        status_int = int(status)
    except (TypeError, ValueError):
        return False
    return status_int in COMPLETE_GAME_STATUS_VALUES


def detect_current_stage_and_week() -> tuple[Optional[int], Optional[int]]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT g.stage_index, g.week, g.status, g.away_score, g.home_score
                FROM games g
                WHERE g.season_index = (SELECT MAX(season_index) FROM games)
                ORDER BY g.stage_index ASC, g.week ASC, g.game_id ASC
                """
            )
            rows = cur.fetchall()

    if not rows:
        return None, None

    progress = {}
    for row in rows:
        key = (int(row["stage_index"]), int(row["week"]))
        bucket = progress.setdefault(key, {"total": 0, "completed": 0})
        bucket["total"] += 1
        if looks_like_completed_game(row):
            bucket["completed"] += 1

    for (stage_index, raw_week), counts in sorted(progress.items(), key=lambda item: (item[0][0], item[0][1])):
        if counts["completed"] < counts["total"]:
            return stage_index, raw_week + 1

    last_stage, last_week = sorted(progress.keys(), key=lambda item: (item[0], item[1]))[-1]
    return last_stage, last_week + 1


def resolve_command_stage(phase: Optional[str]) -> int:
    chosen = parse_phase_to_stage_index(phase)
    if chosen is not None:
        return chosen
    detected_stage, detected_week = detect_current_stage_and_week()
    if detected_stage is None:
        raise RuntimeError("Unable to detect the current phase from imported games.")
    print(f"Auto-detected stage {stage_display_name(detected_stage)} at display week {detected_week}")
    return detected_stage


def fetch_games_for_stage_week(stage_index: int, display_week: int):
    raw_week = max(display_week - 1, 0)
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    g.game_id,
                    g.week,
                    (g.week + 1) AS display_week,
                    g.stage_index,
                    g.status,
                    g.season_index,
                    g.away_score,
                    g.home_score,
                    away.team_name AS away_team_name,
                    home.team_name AS home_team_name,
                    g.away_team_id,
                    g.home_team_id,
                    COALESCE(away_standings.wins, 0) AS away_wins,
                    COALESCE(away_standings.losses, 0) AS away_losses,
                    COALESCE(away_standings.ties, 0) AS away_ties,
                    COALESCE(away_standings.win_pct, 0) AS away_win_pct,
                    COALESCE(away.team_ovr, 0) AS away_ovr,
                    COALESCE(home_standings.wins, 0) AS home_wins,
                    COALESCE(home_standings.losses, 0) AS home_losses,
                    COALESCE(home_standings.ties, 0) AS home_ties,
                    COALESCE(home_standings.win_pct, 0) AS home_win_pct,
                    COALESCE(home.team_ovr, 0) AS home_ovr
                FROM games g
                JOIN teams away ON away.team_id = g.away_team_id
                JOIN teams home ON home.team_id = g.home_team_id
                LEFT JOIN standings away_standings ON away_standings.team_id = g.away_team_id
                LEFT JOIN standings home_standings ON home_standings.team_id = g.home_team_id
                WHERE g.season_index = (SELECT MAX(season_index) FROM games)
                  AND g.stage_index = %s
                  AND g.week = %s
                ORDER BY g.game_id ASC
                """,
                (stage_index, raw_week),
            )
            return cur.fetchall()


def fetch_games_for_week(week: int, stage_index: Optional[int] = None):
    resolved_stage = stage_index if stage_index is not None else resolve_command_stage(None)
    return fetch_games_for_stage_week(resolved_stage, week)


def compute_matchup_score(game_row) -> float:
    away_wins = game_row["away_wins"] or 0
    away_win_pct = float(game_row["away_win_pct"] or 0)
    away_ovr = game_row["away_ovr"] or 0

    home_wins = game_row["home_wins"] or 0
    home_win_pct = float(game_row["home_win_pct"] or 0)
    home_ovr = game_row["home_ovr"] or 0

    both_good_bonus = 0
    if away_win_pct >= 0.500 and home_win_pct >= 0.500:
        both_good_bonus += 5
    if away_wins >= 5 and home_wins >= 5:
        both_good_bonus += 3

    return (
        away_wins
        + home_wins
        + (away_win_pct * 10)
        + (home_win_pct * 10)
        + (away_ovr / 10)
        + (home_ovr / 10)
        + both_good_bonus
    )


def fetch_top_passing_leaders(limit: int = 5):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pps.roster_id,
                    COALESCE(MAX(players.full_name), MAX(pps.full_name)) AS player_name,
                    COALESCE(MAX(teams.team_name), 'Unknown Team') AS team_name,
                    SUM(COALESCE(pps.pass_yds, 0)) AS total_pass_yds
                FROM player_passing_stats pps
                LEFT JOIN players ON players.roster_id = pps.roster_id
                LEFT JOIN teams ON teams.team_id = COALESCE(players.team_id, pps.team_id)
                GROUP BY pps.roster_id
                ORDER BY total_pass_yds DESC, player_name ASC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()


def fetch_top_rushing_leaders(limit: int = 5):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    prs.roster_id,
                    COALESCE(MAX(players.full_name), MAX(prs.full_name)) AS player_name,
                    COALESCE(MAX(teams.team_name), 'Unknown Team') AS team_name,
                    SUM(COALESCE(prs.rush_yds, 0)) AS total_rush_yds
                FROM player_rushing_stats prs
                LEFT JOIN players ON players.roster_id = prs.roster_id
                LEFT JOIN teams ON teams.team_id = COALESCE(players.team_id, prs.team_id)
                GROUP BY prs.roster_id
                ORDER BY total_rush_yds DESC, player_name ASC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()


def fetch_top_sack_leaders(limit: int = 5):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pds.roster_id,
                    COALESCE(MAX(players.full_name), MAX(pds.full_name)) AS player_name,
                    COALESCE(MAX(teams.team_name), 'Unknown Team') AS team_name,
                    SUM(COALESCE(pds.def_sacks, 0)) AS total_sacks
                FROM player_defense_stats pds
                LEFT JOIN players ON players.roster_id = pds.roster_id
                LEFT JOIN teams ON teams.team_id = COALESCE(players.team_id, pds.team_id)
                GROUP BY pds.roster_id
                ORDER BY total_sacks DESC, player_name ASC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()


def fetch_top_interception_leaders(limit: int = 5):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pds.roster_id,
                    COALESCE(MAX(players.full_name), MAX(pds.full_name)) AS player_name,
                    COALESCE(MAX(teams.team_name), 'Unknown Team') AS team_name,
                    SUM(COALESCE(pds.def_ints, 0)) AS total_ints
                FROM player_defense_stats pds
                LEFT JOIN players ON players.roster_id = pds.roster_id
                LEFT JOIN teams ON teams.team_id = COALESCE(players.team_id, pds.team_id)
                GROUP BY pds.roster_id
                ORDER BY total_ints DESC, player_name ASC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()


def format_leader_lines(rows, stat_key: str, stat_label: str):
    if not rows:
        return [f"No data found for {stat_label.lower()}."]
    lines = []
    for idx, row in enumerate(rows, start=1):
        player_name = row.get("player_name", "Unknown")
        team_name = row.get("team_name", "Unknown Team")
        stat_value = row.get(stat_key, 0)
        lines.append(f"{idx}. {player_name} ({team_name}) — {stat_value}")
    return lines


# -----------------------------
# Blackjack
# -----------------------------
BLACKJACK_GAMES: dict[int, "BlackjackGame"] = {}


def blackjack_make_deck() -> list[str]:
    ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    suits = ["♠", "♥", "♦", "♣"]
    deck = [f"{rank}{suit}" for rank in ranks for suit in suits]
    deck *= 4
    random.shuffle(deck)
    return deck


def blackjack_card_rank(card: str) -> str:
    return card[:-1]


def blackjack_hand_value(cards: list[str]) -> tuple[int, bool]:
    total = 0
    aces = 0

    for card in cards:
        rank = blackjack_card_rank(card)
        if rank in {"J", "Q", "K"}:
            total += 10
        elif rank == "A":
            total += 11
            aces += 1
        else:
            total += int(rank)

    while total > 21 and aces > 0:
        total -= 10
        aces -= 1

    soft = False
    running = 0
    ace_count = 0
    for card in cards:
        rank = blackjack_card_rank(card)
        if rank == "A":
            ace_count += 1
            running += 1
        elif rank in {"J", "Q", "K"}:
            running += 10
        else:
            running += int(rank)
    if ace_count > 0 and running + 10 <= 21:
        soft = True

    return total, soft


def blackjack_format_hand(cards: list[str], hide_first: bool = False) -> str:
    if hide_first and cards:
        return "🎴 ??  " + "  ".join(cards[1:])
    return "  ".join(cards)


class BlackjackGame:
    def __init__(self, user: discord.abc.User, bet: float):
        self.user_id = user.id
        self.username = str(user)
        self.bet = bet
        self.deck = blackjack_make_deck()
        self.player_cards = [self.deck.pop(), self.deck.pop()]
        self.dealer_cards = [self.deck.pop(), self.deck.pop()]
        self.is_finished = False
        self.message_id: Optional[int] = None
        self.channel_id: Optional[int] = None

    @property
    def player_total(self) -> int:
        return blackjack_hand_value(self.player_cards)[0]

    @property
    def dealer_total(self) -> int:
        return blackjack_hand_value(self.dealer_cards)[0]

    def player_has_blackjack(self) -> bool:
        return len(self.player_cards) == 2 and self.player_total == 21

    def dealer_has_blackjack(self) -> bool:
        return len(self.dealer_cards) == 2 and self.dealer_total == 21

    def player_bust(self) -> bool:
        return self.player_total > 21

    def dealer_bust(self) -> bool:
        return self.dealer_total > 21

    def dealer_should_hit(self) -> bool:
        total, _soft = blackjack_hand_value(self.dealer_cards)
        return total < 17

    def hit_player(self):
        if not self.is_finished:
            self.player_cards.append(self.deck.pop())

    def play_dealer(self):
        while self.dealer_should_hit():
            self.dealer_cards.append(self.deck.pop())

    def outcome(self) -> str:
        if self.player_bust():
            return "lose"
        if self.dealer_bust():
            return "win"
        if self.player_total > self.dealer_total:
            return "win"
        if self.player_total < self.dealer_total:
            return "lose"
        return "push"

    def payout_amount(self) -> float:
        if self.player_has_blackjack() and not self.dealer_has_blackjack():
            return self.bet * BLACKJACK_BLACKJACK_MULTIPLIER
        result = self.outcome()
        if result == "win":
            return self.bet * BLACKJACK_WIN_MULTIPLIER
        if result == "push":
            return self.bet
        return 0.0

    def active_embed(self, user_mention: str) -> discord.Embed:
        embed = discord.Embed(
            title="🃏 Blackjack",
            description=f"{user_mention} is playing blackjack for **{fmt_tokens(self.bet)}** tokens.",
            color=0x5865F2,
        )
        embed.add_field(
            name=f"Your Hand — {self.player_total}",
            value=blackjack_format_hand(self.player_cards),
            inline=False,
        )
        embed.add_field(
            name="Dealer Hand",
            value=blackjack_format_hand(self.dealer_cards, hide_first=True),
            inline=False,
        )
        embed.set_footer(text="Use the buttons below to Hit or Stand.")
        return embed

    def finished_embed(self, user_mention: str, title: str, result_text: str, color: int) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=f"{user_mention} bet **{fmt_tokens(self.bet)}** tokens.\n\n{result_text}",
            color=color,
        )
        embed.add_field(
            name=f"Your Hand — {self.player_total}",
            value=blackjack_format_hand(self.player_cards),
            inline=False,
        )
        embed.add_field(
            name=f"Dealer Hand — {self.dealer_total}",
            value=blackjack_format_hand(self.dealer_cards),
            inline=False,
        )
        return embed


class BlackjackView(discord.ui.View):
    def __init__(self, game: BlackjackGame, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message("This is not your blackjack hand.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.game.is_finished:
            return

        self.game.is_finished = True
        BLACKJACK_GAMES.pop(self.game.user_id, None)

        for item in self.children:
            item.disabled = True

        channel = bot.get_channel(self.game.channel_id) if self.game.channel_id else None
        if channel and self.game.message_id:
            try:
                message = await channel.fetch_message(self.game.message_id)
                embed = self.game.finished_embed(
                    f"<@{self.game.user_id}>",
                    "🃏 Blackjack — Timed Out",
                    "Your blackjack hand expired. Your bet was forfeited.",
                    0xED4245,
                )
                await message.edit(embed=embed, view=self)
                schedule_message_delete(message, BLACKJACK_FINISHED_DELETE_DELAY)
            except Exception:
                pass

    async def finish_game(self, interaction: discord.Interaction, final_title: str, final_text: str, color: int):
        self.game.is_finished = True
        BLACKJACK_GAMES.pop(self.game.user_id, None)

        for item in self.children:
            item.disabled = True

        embed = self.game.finished_embed(interaction.user.mention, final_title, final_text, color)
        await interaction.response.edit_message(embed=embed, view=self)

        try:
            message = await interaction.original_response()
            schedule_message_delete(message, BLACKJACK_FINISHED_DELETE_DELAY)
        except Exception:
            pass

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.is_finished:
            await interaction.response.send_message("This hand is already finished.", ephemeral=True)
            return

        self.game.hit_player()

        if self.game.player_bust():
            TOKEN_DB.update_casino_result(interaction.user, False)
            await send_log_message(
                f"🃏 BLACKJACK: {interaction.user.mention} busted with **{self.game.player_total}** after betting **{fmt_tokens(self.game.bet)}**."
            )
            await self.finish_game(
                interaction,
                "🃏 Blackjack — Bust",
                "You busted. The dealer wins.",
                0xED4245,
            )
            return

        embed = self.game.active_embed(interaction.user.mention)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.success)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.is_finished:
            await interaction.response.send_message("This hand is already finished.", ephemeral=True)
            return

        if self.game.player_has_blackjack() or self.game.dealer_has_blackjack():
            self.game.is_finished = True
            BLACKJACK_GAMES.pop(self.game.user_id, None)

            for item in self.children:
                item.disabled = True

            if self.game.player_has_blackjack() and self.game.dealer_has_blackjack():
                payout = self.game.bet
                TOKEN_DB.add_tokens(
                    interaction.user,
                    payout,
                    f"Blackjack push refund ({fmt_tokens(self.game.bet)} bet)",
                    "casino",
                )
                title = "🃏 Blackjack — Push"
                text = f"Both you and the dealer have blackjack. Your **{fmt_tokens(self.game.bet)}** token bet was returned."
                color = 0xFEE75C
            elif self.game.player_has_blackjack():
                payout = self.game.payout_amount()
                TOKEN_DB.add_tokens(
                    interaction.user,
                    payout,
                    f"Blackjack natural payout ({fmt_tokens(self.game.bet)} bet)",
                    "casino",
                )
                TOKEN_DB.update_casino_result(interaction.user, True)
                title = "🃏 Blackjack — Blackjack!"
                text = f"Natural blackjack! You were paid **{fmt_tokens(payout)}** tokens."
                color = 0x57F287
            else:
                TOKEN_DB.update_casino_result(interaction.user, False)
                title = "🃏 Blackjack — Dealer Blackjack"
                text = "Dealer has blackjack. You lose."
                color = 0xED4245

            embed = self.game.finished_embed(interaction.user.mention, title, text, color)
            await interaction.response.edit_message(embed=embed, view=self)

            try:
                message = await interaction.original_response()
                schedule_message_delete(message, BLACKJACK_FINISHED_DELETE_DELAY)
            except Exception:
                pass
            return

        self.game.play_dealer()
        result = self.game.outcome()
        payout = self.game.payout_amount()

        if result == "win":
            TOKEN_DB.add_tokens(
                interaction.user,
                payout,
                f"Blackjack win payout ({fmt_tokens(self.game.bet)} bet)",
                "casino",
            )
            TOKEN_DB.update_casino_result(interaction.user, True)
            await send_log_message(
                f"🃏 BLACKJACK: {interaction.user.mention} won blackjack and was paid **{fmt_tokens(payout)}** on a **{fmt_tokens(self.game.bet)}** bet."
            )
            await self.finish_game(
                interaction,
                "🃏 Blackjack — Win",
                f"You beat the dealer and were paid **{fmt_tokens(payout)}** tokens.",
                0x57F287,
            )
        elif result == "push":
            TOKEN_DB.add_tokens(
                interaction.user,
                payout,
                f"Blackjack push refund ({fmt_tokens(self.game.bet)} bet)",
                "casino",
            )
            await send_log_message(
                f"🃏 BLACKJACK: {interaction.user.mention} pushed in blackjack and got back **{fmt_tokens(payout)}**."
            )
            await self.finish_game(
                interaction,
                "🃏 Blackjack — Push",
                f"Push. Your **{fmt_tokens(self.game.bet)}** token bet was returned.",
                0xFEE75C,
            )
        else:
            TOKEN_DB.update_casino_result(interaction.user, False)
            await send_log_message(
                f"🃏 BLACKJACK: {interaction.user.mention} lost blackjack after betting **{fmt_tokens(self.game.bet)}**."
            )
            await self.finish_game(
                interaction,
                "🃏 Blackjack — Lose",
                "Dealer wins.",
                0xED4245,
            )


# -----------------------------
# Misc dataclasses
# -----------------------------
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
    print(f"LEADERS_CHANNEL_ID: {LEADERS_CHANNEL_ID}")
    print(f"NEWS_CHANNEL_ID: {NEWS_CHANNEL_ID}")
    print(f"OPENAI_API_KEY set: {'yes' if OPENAI_API_KEY else 'no'}")
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
        team_name = row["team_name"]
        wins = row["wins"]
        losses = row["losses"]
        ties = row["ties"]
        win_pct = row["win_pct"] or 0
        seed = row["seed"] or 0
        team_ovr = row["team_ovr"] or 0
        pts_for = row["pts_for"] or 0
        pts_against = row["pts_against"] or 0
        turnover_diff = row["turnover_diff"] or 0

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


@bot.tree.command(name="player", description="Look up a player card with dev trait and ratings.")
@app_commands.describe(name="Player name to search")
async def player(interaction: discord.Interaction, name: str):
    results = fetch_player_search_results(name, limit=10)
    if not results:
        await interaction.response.send_message(f"No player found matching **{name}**.", ephemeral=True)
        return

    first = results[0]
    exact_match = safe_text(first.get("full_name")).lower() == name.strip().lower()
    if exact_match or len(results) == 1:
        await interaction.response.send_message(embed=build_player_embed(first))
        return

    embed = build_embed(
        f"🔎 Player Search: {name}",
        "\n".join(
            f"**{idx}.** {safe_text(row.get('full_name'))} — {safe_text(row.get('team_name'), 'Free Agent')} | "
            f"{safe_text(row.get('position'))} | {safe_int(row.get('overall_rating'))} OVR | "
            f"{dev_trait_to_label(row.get('dev_trait'), row.get('resolved_dev_trait_label') or row.get('dev_trait_label'))}"
            for idx, row in enumerate(results[:10], start=1)
        ),
        0x5865F2,
    )
    embed.set_footer(text="Search with a more exact name to pull one player card.")
    await interaction.response.send_message(embed=embed, ephemeral=True)




class RosterPaginationView(discord.ui.View):
    def __init__(self, title_team: dict, roster_rows: list[dict], requester_id: int, page: int = 1, timeout: int = 180):
        super().__init__(timeout=timeout)
        self.title_team = title_team
        self.roster_rows = roster_rows
        self.requester_id = requester_id
        self.page = max(1, page)
        self.max_page = max(1, (len(self.roster_rows) + ROSTER_PAGE_SIZE - 1) // ROSTER_PAGE_SIZE)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_page.disabled = self.page <= 1
        self.next_page.disabled = self.page >= self.max_page

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the user who opened this roster can use these buttons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.page > 1:
            self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=build_roster_embed(self.title_team, self.roster_rows, self.page), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.page < self.max_page:
            self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=build_roster_embed(self.title_team, self.roster_rows, self.page), view=self)


@bot.tree.command(name="roster", description="Show a team roster with 12 players per page.")
@app_commands.describe(team_name="Team name or mascot", page="Roster page number")
async def roster(interaction: discord.Interaction, team_name: str, page: Optional[int] = 1):
    team_row = resolve_team_row(team_name)
    if not team_row:
        await interaction.response.send_message(f"Could not find a team matching **{team_name}**.", ephemeral=True)
        return

    roster_rows = fetch_team_roster_rows(safe_int(team_row.get("team_id")))
    if not roster_rows:
        await interaction.response.send_message(f"No roster rows found for **{safe_text(team_row.get('team_name'))}**.", ephemeral=True)
        return

    standing_row = fetch_team_standing(safe_int(team_row.get("team_id"))) or {}
    merged_team = {**team_row, **standing_row}
    embed = build_roster_embed(merged_team, roster_rows, page or 1)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="team", description="Show a team summary and its first roster page.")
@app_commands.describe(team_name="Team name or mascot")
async def team(interaction: discord.Interaction, team_name: str):
    team_row = resolve_team_row(team_name)
    if not team_row:
        await interaction.response.send_message(f"Could not find a team matching **{team_name}**.", ephemeral=True)
        return

    roster_rows = fetch_team_roster_rows(safe_int(team_row.get("team_id")))
    standing_row = fetch_team_standing(safe_int(team_row.get("team_id"))) or {}
    merged_team = {**team_row, **standing_row}
    embed = build_roster_embed(merged_team, roster_rows, 1)
    await interaction.response.send_message(embed=embed)


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
            f"**{ATTRIBUTE_COST}** — 1 attribute point\n"
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
    used_voucher = TOKEN_DB.consume_voucher(interaction.user, "wheel_spin", 1)
    if not used_voucher:
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
        result = PrizeResult("+2 Tokens", "Nice. The wheel gives you a small payout.", payout=2, won=True)
    elif roll <= 72:
        result = PrizeResult("+4 Tokens", "Solid hit. Great spin.", payout=4, won=True)
    elif roll <= 84:
        result = PrizeResult(
            "Free Name Change",
            "You won a cosmetic voucher. Commissioner can honor this manually.",
            won=True,
            bonus_note="Free Name Change Voucher",
        )
    elif roll <= 88:
        result = PrizeResult(
            "Position Group +1 Upgrade",
            "You won a position group +1 upgrade. Commissioner can honor this manually.",
            won=True,
            bonus_note="Position Group +1 Upgrade",
        )
    else:
        result = PrizeResult("Jackpot", "Huge spin. The wheel pays out +8 tokens.", payout=8, won=True)

    if result.payout > 0:
        TOKEN_DB.add_tokens(interaction.user, result.payout, f"Prize Wheel reward: {result.title}", "casino")
    TOKEN_DB.update_casino_result(interaction.user, result.won)

    if result.bonus_note:
        voucher_type = voucher_type_from_note(result.bonus_note)
        if voucher_type:
            TOKEN_DB.add_voucher(interaction.user, voucher_type, 1)

    extra = f"\n\n**Voucher Added:** {result.bonus_note}" if result.bonus_note else ""
    cost_line = "Used **1 Prize Wheel voucher**" if used_voucher else f"**Cost:** {PRIZE_WHEEL_COST} tokens"
    embed = build_embed(
        f"🎡 Prize Wheel — {result.title}",
        f"{cost_line}\n{result.description}{extra}",
        0xFEE75C if result.won else 0xED4245,
    )
    await interaction.response.send_message(embed=embed)

    try:
        msg = await interaction.original_response()
        schedule_message_delete(msg, CASINO_DELETE_DELAY)
    except Exception:
        pass

    await send_log_message(
        f"🎡 WHEEL: {interaction.user.mention} spun the Prize Wheel for **{PRIZE_WHEEL_COST}** tokens and got **{result.title}**.",
        embed=embed,
    )


@bot.tree.command(name="boomorbust", description="Risk tokens on a Boom or Bust roll.")
@app_commands.describe(player_name="Player attached to the gamble")
async def boomorbust(interaction: discord.Interaction, player_name: str):
    used_voucher = TOKEN_DB.consume_voucher(interaction.user, "boom_or_bust", 1)
    if not used_voucher:
        ok = TOKEN_DB.spend_tokens(interaction.user, BOOM_OR_BUST_COST, f"Boom or Bust on {player_name}", "casino")
        if not ok:
            await interaction.response.send_message(
                f"You need **{BOOM_OR_BUST_COST}** tokens to use Boom or Bust.",
                ephemeral=True,
            )
            return

    hit = random.randint(1, 100) <= 35
    TOKEN_DB.update_casino_result(interaction.user, hit)

    if hit:
        payout = BOOM_OR_BUST_COST * 2
        TOKEN_DB.add_tokens(interaction.user, payout, f"Boom or Bust payout for {player_name}", "casino")
        desc = (
            f"**BOOM.** {player_name} hit the upside roll.\n\n"
            f"You were paid **{fmt_tokens(payout)}** tokens."
        )
        color = 0x57F287
        title = "💥 Boom or Bust — BOOM"
    else:
        desc = f"**BUST.** {player_name} gets nothing. The house keeps your tokens."
        color = 0xED4245
        title = "💀 Boom or Bust — BUST"

    cost_line = "Used **1 Boom or Bust voucher**" if used_voucher else f"**Cost:** {BOOM_OR_BUST_COST} tokens"
    embed = build_embed(title, f"{cost_line}\n{desc}", color)
    await interaction.response.send_message(embed=embed)

    try:
        msg = await interaction.original_response()
        schedule_message_delete(msg, CASINO_DELETE_DELAY)
    except Exception:
        pass

    await send_log_message(
        f"💥 BOOM OR BUST: {interaction.user.mention} used Boom or Bust on **{player_name}** for **{BOOM_OR_BUST_COST}** tokens.",
        embed=embed,
    )


@bot.tree.command(name="mysterycrate", description="Open a Mystery Crate.")
async def mysterycrate(interaction: discord.Interaction):
    used_voucher = TOKEN_DB.consume_voucher(interaction.user, "mystery_crate", 1)
    if not used_voucher:
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
        title = "+8 Tokens"
        desc = "Nice crate hit."
        payout = 8
    elif roll <= 57:
        title = "+12 Tokens"
        desc = "Big crate hit."
        payout = 12
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
        desc = "Massive crate. You win +16 tokens."
        payout = 16

    if payout > 0:
        TOKEN_DB.add_tokens(interaction.user, payout, f"Mystery Crate reward: {title}", "casino")
    TOKEN_DB.update_casino_result(interaction.user, won)

    if bonus_note:
        voucher_type = voucher_type_from_note(bonus_note)
        if voucher_type:
            TOKEN_DB.add_voucher(interaction.user, voucher_type, 1)

    extra = f"\n\n**Voucher Added:** {bonus_note}" if bonus_note else ""
    cost_line = "Used **1 Mystery Crate voucher**" if used_voucher else f"**Cost:** {MYSTERY_CRATE_COST} tokens"
    embed = build_embed(
        f"📦 Mystery Crate — {title}",
        f"{cost_line}\n{desc}{extra}",
        0x5865F2 if won else 0xED4245,
    )
    await interaction.response.send_message(embed=embed)

    try:
        msg = await interaction.original_response()
        schedule_message_delete(msg, CASINO_DELETE_DELAY)
    except Exception:
        pass

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

    try:
        msg = await interaction.original_response()
        schedule_message_delete(msg, CASINO_DELETE_DELAY)
    except Exception:
        pass

    await send_log_message(
        f"🎲 ROULETTE: {interaction.user.mention} bet **{fmt_tokens(amount)}** on **{bet_type.value}={normalized}**. Result: **{number} ({color})**.",
        embed=embed,
    )


@bot.tree.command(name="blackjack", description="Play a hand of blackjack.")
@app_commands.describe(amount="How many tokens to bet")
async def blackjack(interaction: discord.Interaction, amount: float):
    if amount < BLACKJACK_MIN_BET or amount > BLACKJACK_MAX_BET:
        await interaction.response.send_message(
            f"Blackjack bets must be between **{BLACKJACK_MIN_BET}** and **{BLACKJACK_MAX_BET}** tokens.",
            ephemeral=True,
        )
        return

    if interaction.user.id in BLACKJACK_GAMES:
        await interaction.response.send_message(
            "You already have an active blackjack hand.",
            ephemeral=True,
        )
        return

    ok = TOKEN_DB.spend_tokens(
        interaction.user,
        amount,
        f"Blackjack bet: {fmt_tokens(amount)}",
        "casino",
    )
    if not ok:
        await interaction.response.send_message(
            "You do not have enough tokens for that blackjack bet.",
            ephemeral=True,
        )
        return

    game = BlackjackGame(interaction.user, amount)
    BLACKJACK_GAMES[interaction.user.id] = game

    view = BlackjackView(game)
    embed = game.active_embed(interaction.user.mention)
    await interaction.response.send_message(embed=embed, view=view)

    try:
        sent = await interaction.original_response()
        game.message_id = sent.id
        game.channel_id = sent.channel.id
    except Exception:
        pass


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




@bot.tree.command(name="vouchers", description="Show your available automatic vouchers.")
@app_commands.describe(user="Optional: check another user's vouchers")
async def vouchers(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    rows = TOKEN_DB.list_vouchers(target)
    if not rows:
        await interaction.response.send_message(f"No vouchers found for {target.display_name}.", ephemeral=(target == interaction.user))
        return
    lines = [f"**{voucher_label(row['voucher_type'])}:** {int(row['quantity'])}" for row in rows]
    await interaction.response.send_message(
        embed=build_embed(f"🎟️ {target.display_name}'s Vouchers", "\n".join(lines), 0x9B59B6),
        ephemeral=(target == interaction.user),
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




def record_to_dict(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return row


def wins_losses_ties_text(row) -> str:
    return f"{row.get('wins', 0)}-{row.get('losses', 0)}-{row.get('ties', 0)}"


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def safe_text(value, default: str = "Unknown") -> str:
    text = (value or "").strip() if isinstance(value, str) else str(value or "").strip()
    return text or default


def dev_trait_to_label(raw_value, existing_label: Optional[str] = None) -> str:
    if existing_label:
        return existing_label
    try:
        raw = int(raw_value or 0)
    except Exception:
        return "Unknown"
    return DEV_TRAIT_LABELS.get(raw, f"Trait {raw}")


def format_height_inches(height_inches: Optional[int]) -> str:
    try:
        total = int(height_inches or 0)
    except Exception:
        return "Unknown"
    if total <= 0:
        return "Unknown"
    feet = total // 12
    inches = total % 12
    return f"{feet}'{inches}\""


def format_currency_compact(value) -> str:
    try:
        amount = int(value or 0)
    except Exception:
        return "0"
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if abs(amount) >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount}"


def fetch_all_team_rows() -> list[dict]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    team_id,
                    team_name,
                    conference_name,
                    division_name,
                    team_ovr
                FROM teams
                ORDER BY team_name ASC
                """
            )
            return [record_to_dict(row) for row in cur.fetchall()]


def resolve_team_row(team_name: str):
    normalized_query = normalize_team_name(team_name)
    if not normalized_query:
        return None

    teams = fetch_all_team_rows()
    best_exact = None
    best_contains = None
    best_suffix = None

    for team in teams:
        team_display = safe_text(team.get("team_name"), "")
        team_norm = normalize_team_name(team_display)
        mascot = normalize_team_name(team_display.split()[-1]) if team_display else ""

        if team_norm == normalized_query:
            best_exact = team
            break
        if mascot == normalized_query and best_suffix is None:
            best_suffix = team
        if normalized_query in team_norm or team_norm in normalized_query:
            if best_contains is None:
                best_contains = team

    return best_exact or best_suffix or best_contains


def fetch_player_search_results(name: str, limit: int = 10) -> list[dict]:
    wildcard = f"%{name.strip()}%"
    exact_name = name.strip().lower()
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.*,
                    t.team_name,
                    t.conference_name,
                    t.division_name,
                    COALESCE(
                        p.dev_trait_label,
                        CASE COALESCE(p.dev_trait, 0)
                            WHEN 0 THEN 'Normal'
                            WHEN 1 THEN 'Star'
                            WHEN 2 THEN 'Superstar'
                            WHEN 3 THEN 'X-Factor'
                            ELSE 'Unknown'
                        END
                    ) AS resolved_dev_trait_label
                FROM players p
                LEFT JOIN teams t ON t.team_id = p.team_id
                WHERE p.full_name ILIKE %s
                ORDER BY
                    CASE
                        WHEN LOWER(p.full_name) = %s THEN 0
                        WHEN LOWER(p.last_name) = %s THEN 1
                        WHEN LOWER(p.first_name) = %s THEN 2
                        ELSE 3
                    END,
                    COALESCE(NULLIF(p.overall_rating, 0), p.player_best_ovr, 0) DESC,
                    p.full_name ASC
                LIMIT %s
                """,
                (wildcard, exact_name, exact_name, exact_name, limit),
            )
            return [record_to_dict(row) for row in cur.fetchall()]


def fetch_team_roster_rows(team_id: int) -> list[dict]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.*,
                    t.team_name,
                    COALESCE(
                        p.dev_trait_label,
                        CASE COALESCE(p.dev_trait, 0)
                            WHEN 0 THEN 'Normal'
                            WHEN 1 THEN 'Star'
                            WHEN 2 THEN 'Superstar'
                            WHEN 3 THEN 'X-Factor'
                            ELSE 'Unknown'
                        END
                    ) AS resolved_dev_trait_label
                FROM players p
                LEFT JOIN teams t ON t.team_id = p.team_id
                WHERE p.team_id = %s
                ORDER BY
                    COALESCE(NULLIF(p.overall_rating, 0), p.player_best_ovr, 0) DESC,
                    p.full_name ASC
                """,
                (team_id,),
            )
            return [record_to_dict(row) for row in cur.fetchall()]


def build_player_embed(row: dict) -> discord.Embed:
    team_name = safe_text(row.get("team_name"), "Free Agent")
    dev_label = dev_trait_to_label(row.get("dev_trait"), row.get("resolved_dev_trait_label") or row.get("dev_trait_label"))
    position = safe_text(row.get("position"))
    jersey = safe_int(row.get("jersey_num"))
    title_name = safe_text(row.get("full_name"))
    title = f"🏈 {title_name}"
    if jersey:
        title += f" #{jersey}"

    embed = build_embed(
        title,
        f"**{position}** • **{team_name}** • **{safe_int(row.get('overall_rating'))} OVR** • **{dev_label}**",
        0x5865F2,
    )
    embed.add_field(
        name="Profile",
        value=(
            f"Age: {safe_int(row.get('age'))}\n"
            f"Years Pro: {safe_int(row.get('years_pro'))}\n"
            f"Height / Weight: {format_height_inches(row.get('height'))} / {safe_int(row.get('weight'))} lbs\n"
            f"College: {safe_text(row.get('college'))}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Key Ratings",
        value=(
            f"Speed: {safe_int(row.get('speed_rating'))}\n"
            f"Awareness: {safe_int(row.get('awareness_rating'))}\n"
            f"Catch: {safe_int(row.get('catch_rating'))}\n"
            f"Break Tackle: {safe_int(row.get('break_tackle_rating'))}\n"
            f"Throw Power: {safe_int(row.get('throw_power_rating'))}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Contract",
        value=(
            f"Years Left: {safe_int(row.get('contract_years_left'))}\n"
            f"Salary: {format_currency_compact(row.get('contract_salary'))}\n"
            f"Best OVR: {safe_int(row.get('player_best_ovr'))}\n"
            f"Rookie Year: {safe_int(row.get('rookie_year'))}"
        ),
        inline=False,
    )
    abilities = safe_text(row.get("signature_abilities"), "")
    if abilities:
        embed.add_field(name="Abilities", value=abilities, inline=False)
    return embed


def build_roster_embed(team_row: dict, roster_rows: list[dict], page: int) -> discord.Embed:
    total_players = len(roster_rows)
    total_pages = max(1, (total_players + ROSTER_PAGE_SIZE - 1) // ROSTER_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * ROSTER_PAGE_SIZE
    end = start + ROSTER_PAGE_SIZE
    chunk = roster_rows[start:end]

    if not chunk:
        description = "No players found for this roster."
    else:
        lines = []
        for idx, row in enumerate(chunk, start=start + 1):
            dev_label = dev_trait_to_label(row.get("dev_trait"), row.get("resolved_dev_trait_label") or row.get("dev_trait_label"))
            lines.append(
                f"**{idx}.** {safe_text(row.get('full_name'))} — {safe_text(row.get('position'))} | "
                f"{safe_int(row.get('overall_rating'))} OVR | {dev_label}"
            )
        description = "\n".join(lines)

    record_bits = []
    if team_row.get("wins") is not None:
        record_bits.append(wins_losses_ties_text(team_row))
    if team_row.get("team_ovr") is not None:
        record_bits.append(f"{safe_int(team_row.get('team_ovr'))} OVR")
    subtitle = " • ".join(record_bits) if record_bits else "Team roster"

    embed = build_embed(
        f"📋 {safe_text(team_row.get('team_name'))} Roster",
        description,
        0x57F287,
    )
    embed.add_field(
        name="Team Snapshot",
        value=(
            f"{subtitle}\n"
            f"{safe_text(team_row.get('conference_name'))} / {safe_text(team_row.get('division_name'))}\n"
            f"Players: {total_players}"
        ),
        inline=False,
    )
    embed.set_footer(text=f"Page {page}/{total_pages} • 12 players per page")
    return embed


def fetch_team_standing(team_id: int):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.team_id,
                    t.team_name,
                    t.conference_name,
                    t.division_name,
                    t.team_ovr,
                    COALESCE(s.wins, 0) AS wins,
                    COALESCE(s.losses, 0) AS losses,
                    COALESCE(s.ties, 0) AS ties,
                    COALESCE(s.win_pct, 0) AS win_pct,
                    COALESCE(s.seed, 0) AS seed,
                    COALESCE(s.pts_for, 0) AS pts_for,
                    COALESCE(s.pts_against, 0) AS pts_against,
                    COALESCE(s.turnover_diff, 0) AS turnover_diff
                FROM teams t
                LEFT JOIN standings s ON s.team_id = t.team_id
                WHERE t.team_id = %s
                LIMIT 1
                """,
                (team_id,),
            )
            row = cur.fetchone()
            return record_to_dict(row)


def fetch_team_stat_leaders(team_id: int) -> dict:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            passing = None
            rushing = None
            sacks = None
            interceptions = None

            cur.execute(
                """
                SELECT
                    pps.roster_id,
                    COALESCE(MAX(players.full_name), MAX(pps.full_name)) AS player_name,
                    SUM(COALESCE(pps.pass_yds, 0)) AS total_pass_yds,
                    SUM(COALESCE(pps.pass_tds, 0)) AS total_pass_tds
                FROM player_passing_stats pps
                LEFT JOIN players ON players.roster_id = pps.roster_id
                WHERE COALESCE(players.team_id, pps.team_id) = %s
                GROUP BY pps.roster_id
                ORDER BY total_pass_yds DESC, total_pass_tds DESC, player_name ASC
                LIMIT 1
                """,
                (team_id,),
            )
            passing = record_to_dict(cur.fetchone())

            cur.execute(
                """
                SELECT
                    prs.roster_id,
                    COALESCE(MAX(players.full_name), MAX(prs.full_name)) AS player_name,
                    SUM(COALESCE(prs.rush_yds, 0)) AS total_rush_yds,
                    SUM(COALESCE(prs.rush_tds, 0)) AS total_rush_tds
                FROM player_rushing_stats prs
                LEFT JOIN players ON players.roster_id = prs.roster_id
                WHERE COALESCE(players.team_id, prs.team_id) = %s
                GROUP BY prs.roster_id
                ORDER BY total_rush_yds DESC, total_rush_tds DESC, player_name ASC
                LIMIT 1
                """,
                (team_id,),
            )
            rushing = record_to_dict(cur.fetchone())

            cur.execute(
                """
                SELECT
                    pds.roster_id,
                    COALESCE(MAX(players.full_name), MAX(pds.full_name)) AS player_name,
                    SUM(COALESCE(pds.def_sacks, 0)) AS total_sacks,
                    SUM(COALESCE(pds.def_ints, 0)) AS total_ints
                FROM player_defense_stats pds
                LEFT JOIN players ON players.roster_id = pds.roster_id
                WHERE COALESCE(players.team_id, pds.team_id) = %s
                GROUP BY pds.roster_id
                ORDER BY total_sacks DESC, total_ints DESC, player_name ASC
                LIMIT 1
                """,
                (team_id,),
            )
            sacks = record_to_dict(cur.fetchone())

            cur.execute(
                """
                SELECT
                    pds.roster_id,
                    COALESCE(MAX(players.full_name), MAX(pds.full_name)) AS player_name,
                    SUM(COALESCE(pds.def_ints, 0)) AS total_ints,
                    SUM(COALESCE(pds.def_sacks, 0)) AS total_sacks
                FROM player_defense_stats pds
                LEFT JOIN players ON players.roster_id = pds.roster_id
                WHERE COALESCE(players.team_id, pds.team_id) = %s
                GROUP BY pds.roster_id
                ORDER BY total_ints DESC, total_sacks DESC, player_name ASC
                LIMIT 1
                """,
                (team_id,),
            )
            interceptions = record_to_dict(cur.fetchone())

    return {
        "passing": passing,
        "rushing": rushing,
        "sacks": sacks,
        "interceptions": interceptions,
    }


def build_team_storyline(team_row: dict, leaders: dict) -> str:
    team_name = team_row.get("team_name", "Unknown Team")
    record = wins_losses_ties_text(team_row)
    seed = safe_int(team_row.get("seed"))
    pf = safe_int(team_row.get("pts_for"))
    pa = safe_int(team_row.get("pts_against"))
    ovr = safe_int(team_row.get("team_ovr"))
    turnover_diff = safe_int(team_row.get("turnover_diff"))

    fragments = [f"{team_name} is {record} with a {ovr} OVR, {pf} points scored, {pa} allowed, and a turnover diff of {turnover_diff:+d}."]
    if seed:
        fragments.append(f"They currently sit on the {seed} seed.")
    passing = leaders.get("passing")
    if passing and passing.get("player_name") and safe_int(passing.get("total_pass_yds")) > 0:
        fragments.append(
            f"Top passer: {passing['player_name']} with {safe_int(passing.get('total_pass_yds'))} yards and {safe_int(passing.get('total_pass_tds'))} TDs."
        )
    rushing = leaders.get("rushing")
    if rushing and rushing.get("player_name") and safe_int(rushing.get("total_rush_yds")) > 0:
        fragments.append(
            f"Top rusher: {rushing['player_name']} with {safe_int(rushing.get('total_rush_yds'))} yards and {safe_int(rushing.get('total_rush_tds'))} TDs."
        )
    defender = leaders.get("interceptions") or leaders.get("sacks")
    if defender and defender.get("player_name"):
        sack_count = safe_int(defender.get("total_sacks"))
        int_count = safe_int(defender.get("total_ints"))
        if sack_count or int_count:
            fragments.append(
                f"Defensive tone-setter: {defender['player_name']} with {sack_count} sacks and {int_count} picks."
            )
    return " ".join(fragments)


def deterministic_choice(options: list[str], seed_value: str) -> str:
    if not options:
        return ""
    rng = random.Random(seed_value)
    return options[rng.randrange(len(options))]


def build_matchup_angle(away_team: dict, home_team: dict, away_leaders: dict, home_leaders: dict, is_gotw: bool, matchup_score: float) -> str:
    away_wins = safe_int(away_team.get("wins"))
    home_wins = safe_int(home_team.get("wins"))
    away_pf = safe_int(away_team.get("pts_for"))
    home_pf = safe_int(home_team.get("pts_for"))
    away_pa = safe_int(away_team.get("pts_against"))
    home_pa = safe_int(home_team.get("pts_against"))
    away_to = safe_int(away_team.get("turnover_diff"))
    home_to = safe_int(home_team.get("turnover_diff"))

    if is_gotw or matchup_score >= 28:
        return "marquee showdown"
    if abs(away_wins - home_wins) >= 4:
        return "prove-it test"
    if abs(away_pf - home_pf) >= 35 and abs(away_pa - home_pa) >= 20:
        return "style clash"
    if max(away_to, home_to) - min(away_to, home_to) >= 4:
        return "turnover battle"
    away_pass = away_leaders.get("passing")
    home_pass = home_leaders.get("passing")
    away_sacks = away_leaders.get("defense")
    home_sacks = home_leaders.get("defense")
    if away_pass and home_sacks:
        return "quarterback-vs-pass-rush"
    if home_pass and away_sacks:
        return "quarterback-vs-pass-rush"
    return "playoff pressure"


def build_matchup_headline(facts: dict) -> str:
    away = facts["away_team"]
    home = facts["home_team"]
    angle = facts["angle"]
    if angle == "marquee showdown":
        return f"{away['team_name']} and {home['team_name']} headline Week {facts['week']}"
    if angle == "prove-it test":
        return f"Can the {away['team_name']} crack the {home['team_name']} in Week {facts['week']}?"
    if angle == "style clash":
        return f"A style clash is on deck: {away['team_name']} vs {home['team_name']}"
    if angle == "turnover battle":
        return f"Takeaways could decide {away['team_name']} vs {home['team_name']}"
    if angle == "quarterback-vs-pass-rush":
        return f"Pressure point matchup arrives for {away['team_name']} and {home['team_name']}"
    return f"Week {facts['week']} spotlight: {away['team_name']} at {home['team_name']}"


def build_matchup_players_to_watch(facts: dict) -> list[str]:
    away = facts["away_team"]
    home = facts["home_team"]
    picks = []
    for team_key, team_name in (("away_leaders", away["team_name"]), ("home_leaders", home["team_name"])):
        leaders = facts[team_key]
        primary = leaders.get("passing") or leaders.get("rushing") or leaders.get("defense")
        if primary and primary.get("player_name"):
            stat_text = ""
            if "total_pass_yds" in primary:
                stat_text = f"{safe_int(primary.get('total_pass_yds'))} pass yds"
            elif "total_rush_yds" in primary:
                stat_text = f"{safe_int(primary.get('total_rush_yds'))} rush yds"
            elif "total_sacks" in primary:
                stat_text = f"{safe_int(primary.get('total_sacks'))} sacks"
            elif "total_ints" in primary:
                stat_text = f"{safe_int(primary.get('total_ints'))} INTs"
            picks.append(f"{primary['player_name']} ({team_name}{', ' + stat_text if stat_text else ''})")
    return picks[:2]


def build_matchup_stakes_line(facts: dict) -> str:
    away = facts["away_team"]
    home = facts["home_team"]
    both_winning = float(away.get("win_pct") or 0) >= 0.5 and float(home.get("win_pct") or 0) >= 0.5
    if facts["is_gotw"]:
        return "Game of the Week billing puts extra league-wide spotlight on every drive in this one."
    if both_winning:
        return "This game carries real seeding weight with both sides trying to stay near the top of the race."
    if abs(safe_int(away.get("wins")) - safe_int(home.get("wins"))) >= 4:
        return "This feels like a pressure game for the underdog and a statement opportunity for the favorite."
    return "Momentum, standings position, and league perception all shift a little depending on who walks out with this one."


def build_matchup_facts(game_row, is_gotw: bool) -> dict:
    away_team = fetch_team_standing(game_row["away_team_id"]) or {
        "team_name": game_row["away_team_name"],
        "wins": game_row.get("away_wins", 0),
        "losses": game_row.get("away_losses", 0),
        "ties": game_row.get("away_ties", 0),
        "win_pct": game_row.get("away_win_pct", 0),
        "team_ovr": game_row.get("away_ovr", 0),
    }
    home_team = fetch_team_standing(game_row["home_team_id"]) or {
        "team_name": game_row["home_team_name"],
        "wins": game_row.get("home_wins", 0),
        "losses": game_row.get("home_losses", 0),
        "ties": game_row.get("home_ties", 0),
        "win_pct": game_row.get("home_win_pct", 0),
        "team_ovr": game_row.get("home_ovr", 0),
    }

    away_leaders = fetch_team_stat_leaders(game_row["away_team_id"])
    home_leaders = fetch_team_stat_leaders(game_row["home_team_id"])
    matchup_score = round(compute_matchup_score(game_row), 2)
    angle = build_matchup_angle(away_team, home_team, away_leaders, home_leaders, bool(is_gotw), matchup_score)

    return {
        "week": safe_int(game_row.get("week")),
        "game_id": safe_int(game_row.get("game_id")),
        "stage_index": safe_int(game_row.get("stage_index")),
        "status": safe_int(game_row.get("status")),
        "is_gotw": bool(is_gotw),
        "matchup_score": matchup_score,
        "angle": angle,
        "away_team": away_team,
        "home_team": home_team,
        "away_storyline": build_team_storyline(away_team, away_leaders),
        "home_storyline": build_team_storyline(home_team, home_leaders),
        "away_leaders": away_leaders,
        "home_leaders": home_leaders,
        "headline": "",
        "players_to_watch": [],
        "stakes_line": "",
    }


def template_matchup_preview_text(facts: dict) -> str:
    away = facts["away_team"]
    home = facts["home_team"]
    angle = facts["angle"]
    seed = f"wk{facts['week']}-game{facts['game_id']}-{angle}"

    opening_options = {
        "marquee showdown": [
            f"Week {facts['week']} gets one of its cleanest headline games with the {away['team_name']} ({wins_losses_ties_text(away)}) lining up against the {home['team_name']} ({wins_losses_ties_text(home)}).",
            f"All eyes in Week {facts['week']} should drift toward the {away['team_name']} and {home['team_name']}, two teams bringing real juice into this matchup.",
        ],
        "prove-it test": [
            f"The {away['team_name']} walk into Week {facts['week']} needing a statement against the {home['team_name']}, who have done more to control the season so far.",
            f"This Week {facts['week']} matchup feels like a measuring-stick game as the {away['team_name']} try to hang with the {home['team_name']}.",
        ],
        "style clash": [
            f"This one sets up like a real style clash, with the {away['team_name']} and {home['team_name']} bringing very different strengths into Week {facts['week']}.",
            f"Week {facts['week']} offers a contrast fight between the {away['team_name']} and {home['team_name']}, and that usually makes for chaos.",
        ],
        "turnover battle": [
            f"Week {facts['week']} might come down to ball security as the {away['team_name']} and {home['team_name']} meet in a matchup that screams turnover swing.",
            f"This one has takeaways written all over it, with the {away['team_name']} and {home['team_name']} both able to flip momentum fast.",
        ],
        "quarterback-vs-pass-rush": [
            f"The headline angle here is simple: can the quarterback stay clean when the {away['team_name']} and {home['team_name']} start trading shots in Week {facts['week']}?",
            f"Week {facts['week']} brings a pressure game where pass protection and quarterback poise could decide the entire script.",
        ],
        "playoff pressure": [
            f"The {away['team_name']} and {home['team_name']} are stepping into one of those Week {facts['week']} games that feels heavier than a normal regular-season slot.",
            f"There is real pressure under this Week {facts['week']} spotlight as the {away['team_name']} and {home['team_name']} fight for traction.",
        ],
    }
    opener = deterministic_choice(opening_options.get(angle, opening_options['playoff pressure']), seed)

    detail_line = deterministic_choice([
        f"{away['team_name']} have put up {safe_int(away.get('pts_for'))} points so far, while {home['team_name']} have allowed {safe_int(home.get('pts_against'))}, making finishing drives one of the biggest swing factors.",
        f"On the other side, {home['team_name']} have scored {safe_int(home.get('pts_for'))} points and carry a {safe_int(home.get('turnover_diff')):+d} turnover margin, so the {away['team_name']} cannot afford free possessions.",
        f"The overall ratings are close enough to keep this honest, but the cleaner team situationally should have the edge once the game tightens up.",
        f"This matchup score came in at {facts['matchup_score']}, which tracks with how much noise both teams have made in the standings so far.",
    ], seed + '-detail')

    story_options = [
        facts.get("away_storyline", ""),
        facts.get("home_storyline", ""),
        f"The stars are obvious, but hidden depth players could end up deciding field position and late-game tempo.",
    ]
    story_line = deterministic_choice([s for s in story_options if s], seed + '-story')

    players = build_matchup_players_to_watch(facts)
    player_line = ""
    if len(players) >= 2:
        player_line = f"Players to watch start with {players[0]} and {players[1]}, two names who can tilt this matchup fast."
    elif players:
        player_line = f"One name worth circling is {players[0]}, because a star performance could bend the entire game script."
    else:
        player_line = "Whoever lands the first explosive play or turnover will probably control how this game feels the rest of the way."

    stakes_line = build_matchup_stakes_line(facts)
    lines = [opener, detail_line, story_line, player_line, stakes_line]
    return " ".join(line.strip() for line in lines if line.strip())


def build_league_news_facts(week: int, games, gotw_game_ids: set[int]) -> dict:
    standings = [record_to_dict(row) for row in fetch_standings_rows()]
    passing = [record_to_dict(row) for row in fetch_top_passing_leaders(3)]
    rushing = [record_to_dict(row) for row in fetch_top_rushing_leaders(3)]
    sacks = [record_to_dict(row) for row in fetch_top_sack_leaders(3)]
    interceptions = [record_to_dict(row) for row in fetch_top_interception_leaders(3)]

    ranked_games = []
    for game in games:
        ranked_games.append({
            "game_id": safe_int(game["game_id"]),
            "away_team_name": game["away_team_name"],
            "home_team_name": game["home_team_name"],
            "matchup_score": round(compute_matchup_score(game), 2),
            "is_gotw": safe_int(game["game_id"]) in gotw_game_ids,
            "away_wins": safe_int(game.get("away_wins")),
            "away_losses": safe_int(game.get("away_losses")),
            "home_wins": safe_int(game.get("home_wins")),
            "home_losses": safe_int(game.get("home_losses")),
        })
    ranked_games.sort(key=lambda row: row["matchup_score"], reverse=True)

    lead_team = standings[0] if standings else None
    chase_team = standings[1] if len(standings) > 1 else None
    angle = "power race"
    if lead_team and chase_team and abs(safe_int(lead_team.get("wins")) - safe_int(chase_team.get("wins"))) <= 1:
        angle = "tight race"
    elif ranked_games and ranked_games[0].get("is_gotw"):
        angle = "headline week"
    elif passing or rushing or sacks or interceptions:
        angle = "awards watch"

    return {
        "week": week,
        "angle": angle,
        "top_teams": standings[:5],
        "passing_leaders": passing,
        "rushing_leaders": rushing,
        "sack_leaders": sacks,
        "interception_leaders": interceptions,
        "top_games": ranked_games[:5],
        "game_count": len(games),
    }


def build_weekly_news_headline(facts: dict) -> str:
    week = facts["week"]
    angle = facts.get("angle", "power race")
    top_game = facts["top_games"][0] if facts["top_games"] else None
    lead_team = facts["top_teams"][0] if facts["top_teams"] else None
    if angle == "tight race" and lead_team:
        return f"Week {week} opens with the standings race tightening around {lead_team['team_name']}"
    if angle == "headline week" and top_game:
        return f"Week {week} centers on {top_game['away_team_name']} vs {top_game['home_team_name']}"
    if angle == "awards watch":
        return f"Week {week} arrives with MVP and stat races heating up"
    return f"Week {week} league pulse report"


def build_weekly_news_spotlights(facts: dict) -> list[str]:
    items = []
    if facts["passing_leaders"]:
        p = facts["passing_leaders"][0]
        items.append(f"Passing race: {p['player_name']} ({p['team_name']}) with {safe_int(p.get('total_pass_yds'))} yds")
    if facts["rushing_leaders"]:
        r = facts["rushing_leaders"][0]
        items.append(f"Ground game: {r['player_name']} ({r['team_name']}) with {safe_int(r.get('total_rush_yds'))} yds")
    if facts["sack_leaders"]:
        s = facts["sack_leaders"][0]
        items.append(f"Pass rush: {s['player_name']} ({s['team_name']}) with {safe_int(s.get('total_sacks'))} sacks")
    if facts["interception_leaders"]:
        i = facts["interception_leaders"][0]
        items.append(f"Ball hawk: {i['player_name']} ({i['team_name']}) with {safe_int(i.get('total_ints'))} INTs")
    if facts["top_games"]:
        g = facts["top_games"][0]
        label = "Game of the Week" if g.get("is_gotw") else "Main event"
        items.append(f"{label}: {g['away_team_name']} vs {g['home_team_name']}")
    return items[:4]


def template_weekly_news_text(facts: dict) -> str:
    week = facts["week"]
    top_teams = facts["top_teams"]
    top_games = facts["top_games"]
    seed = f"week-news-{week}-{facts.get('angle','power race')}"

    if top_teams:
        lead_team = top_teams[0]
        second_team = top_teams[1] if len(top_teams) > 1 else None
        opening_options = [
            f"Week {week} opens with {lead_team['team_name']} still setting the pace at {wins_losses_ties_text(lead_team)}.",
            f"The pressure keeps building in Week {week}, and {lead_team['team_name']} remain the team everybody is chasing.",
        ]
        standings_line = deterministic_choice(opening_options, seed)
        if second_team:
            standings_line += f" Right behind them, {second_team['team_name']} sit at {wins_losses_ties_text(second_team)} and keep the race honest."
    else:
        standings_line = f"Week {week} is on deck and the league is starting to sort contenders from noise."

    if top_games:
        top_game = top_games[0]
        marquee_options = [
            f"The headline game on the board is {top_game['away_team_name']} vs {top_game['home_team_name']}, a matchup that should pull a lot of league attention.",
            f"Circle {top_game['away_team_name']} against {top_game['home_team_name']} as the matchup most likely to move the room this week.",
        ]
        marquee_line = deterministic_choice(marquee_options, seed + '-marquee')
        if top_game.get("is_gotw"):
            marquee_line += " It also landed Game of the Week billing."
    else:
        marquee_line = "There are multiple games this week with enough juice to shake up the table."

    spotlight_items = build_weekly_news_spotlights(facts)
    if spotlight_items:
        stat_line = "Around the league, " + "; ".join(spotlight_items[:3]) + "."
    else:
        stat_line = "Stat races and playoff positioning are both starting to matter more every week."

    close_line = deterministic_choice([
        "This feels like one of those weeks where the standings could look a lot cleaner for some teams and a lot uglier for others.",
        "Momentum is real at this point in the season, and this slate should tell the league who is building something serious.",
    ], seed + '-close')
    return " ".join([standings_line, marquee_line, stat_line, close_line])


def call_openai_text(prompt: str, max_output_tokens: int = 220) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    payload = {
        "model": OPENAI_MODEL,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
    }

    req = urllib_request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {details[:500]}")
    except Exception as exc:
        raise RuntimeError(f"OpenAI request failed: {exc}")

    if isinstance(data, dict):
        text_value = data.get("output_text")
        if isinstance(text_value, str) and text_value.strip():
            return text_value.strip()

        output = data.get("output", [])
        collected = []
        for item in output:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    text_piece = content.get("text", "")
                    if text_piece:
                        collected.append(text_piece)
        joined = "\n".join(part.strip() for part in collected if part.strip()).strip()
        if joined:
            return joined

    raise RuntimeError("OpenAI returned no text output.")


def build_matchup_prompt(facts: dict) -> str:
    return (
        "You are writing a short Madden franchise pregame report for Discord.\n"
        "Rules:\n"
        "- Write exactly 4 or 5 sentences.\n"
        "- Use only the facts provided.\n"
        "- Do not invent players, injuries, streaks, awards, or statistics.\n"
        "- Choose one central angle and lean into it: marquee showdown, prove-it test, style clash, turnover battle, quarterback-vs-pass-rush, or playoff pressure.\n"
        "- Do not always open with both teams' records.\n"
        "- Make it sound like a polished TV pregame hit, not generic filler.\n"
        "- Vary sentence structure and avoid phrases like 'this one has all the makings' or 'both teams will look to'.\n"
        "- End with a sentence about what is at stake.\n\n"
        f"Facts JSON:\n{json.dumps(facts, indent=2)}"
    )


def build_weekly_news_prompt(facts: dict) -> str:
    return (
        "You are writing a main weekly league news article for a Madden franchise Discord.\n"
        "Rules:\n"
        "- Write 5 to 7 sentences.\n"
        "- Use only the facts provided.\n"
        "- Focus on the biggest season storylines, standings pressure, headline games, and major stat-race movement.\n"
        "- Do not invent records, streaks, awards, quotes, or outcomes.\n"
        "- Make it read like a real sports desk update, not a generic recap.\n"
        "- Use a distinct lead sentence and keep the body varied and specific.\n"
        "- End by explaining why this week matters for the season.\n\n"
        f"Facts JSON:\n{json.dumps(facts, indent=2)}"
    )


async def generate_matchup_preview_text(game_row, is_gotw: bool) -> tuple[str, bool]:
    facts = build_matchup_facts(game_row, is_gotw)
    fallback = template_matchup_preview_text(facts)
    if not OPENAI_API_KEY:
        return fallback, False

    try:
        ai_text = await asyncio.to_thread(call_openai_text, build_matchup_prompt(facts), 180)
        cleaned = re.sub(r"\s+", " ", ai_text).strip()
        return cleaned or fallback, True
    except Exception as exc:
        print(f"AI matchup preview failed for game {game_row.get('game_id')}: {exc}")
        return fallback, False


async def generate_weekly_news_text(week: int, games, gotw_game_ids: set[int]) -> tuple[str, bool]:
    facts = build_league_news_facts(week, games, gotw_game_ids)
    fallback = template_weekly_news_text(facts)
    if not OPENAI_API_KEY:
        return fallback, False

    try:
        ai_text = await asyncio.to_thread(call_openai_text, build_weekly_news_prompt(facts), 260)
        cleaned = re.sub(r"\s+", " ", ai_text).strip()
        return cleaned or fallback, True
    except Exception as exc:
        print(f"AI weekly news failed for week {week}: {exc}")
        return fallback, False


async def resolve_news_channel(guild: discord.Guild, fallback_channel: Optional[discord.TextChannel] = None):
    target_channel = None
    if NEWS_CHANNEL_ID:
        target_channel = guild.get_channel(NEWS_CHANNEL_ID)
        if target_channel is None:
            try:
                fetched = await bot.fetch_channel(NEWS_CHANNEL_ID)
                if isinstance(fetched, discord.TextChannel):
                    target_channel = fetched
            except Exception:
                target_channel = None

    if target_channel is None and isinstance(fallback_channel, discord.TextChannel):
        target_channel = fallback_channel

    return target_channel


async def post_weekly_news_article(
    guild: discord.Guild,
    week: int,
    games,
    gotw_game_ids: set[int],
    fallback_channel: Optional[discord.TextChannel] = None,
    stage_index: Optional[int] = None,
):
    target_channel = await resolve_news_channel(guild, fallback_channel)
    if target_channel is None:
        return None, False

    facts = build_league_news_facts(week, games, gotw_game_ids)
    article_text, used_ai = await generate_weekly_news_text(week, games, gotw_game_ids)
    spotlight_items = build_weekly_news_spotlights(facts)

    title_prefix = f"{stage_week_label(stage_index, week)} — " if stage_index is not None else ""
    embed = discord.Embed(
        title=f"📰 {title_prefix}{build_weekly_news_headline(facts)}",
        description=article_text,
        color=0x1ABC9C,
    )
    if spotlight_items:
        embed.add_field(name="League Spotlight", value="\n".join(f"• {item}" for item in spotlight_items), inline=False)
    embed.set_footer(text="AI-assisted report" if used_ai else "Template report")

    await target_channel.send(embed=embed)
    return target_channel, used_ai


@bot.tree.command(name="create_week_channels", description="Admin: create one matchup channel per game for a human week number.")
@admin_only()
@app_commands.describe(
    week="Human week number (Week 1, Week 2, etc.)",
    phase="Optional phase override. Leave empty to auto-detect the current phase.",
    category_name="Optional category name to create/use",
    auto_news="Optional override for posting the weekly news article",
)
@app_commands.choices(phase=[
    app_commands.Choice(name="Auto Detect", value="auto"),
    app_commands.Choice(name="Preseason", value="preseason"),
    app_commands.Choice(name="Regular Season", value="regular"),
    app_commands.Choice(name="Wild Card", value="wild card"),
    app_commands.Choice(name="Divisional", value="divisional"),
    app_commands.Choice(name="Conference Championship", value="conference championship"),
    app_commands.Choice(name="Super Bowl", value="super bowl"),
])
async def create_week_channels(
    interaction: discord.Interaction,
    week: int,
    phase: Optional[str] = None,
    category_name: Optional[str] = None,
    auto_news: Optional[bool] = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    if week < 1:
        await interaction.followup.send("Enter the real human week number, starting at 1.", ephemeral=True)
        return

    try:
        stage_index = resolve_command_stage(phase)
        games = fetch_games_for_stage_week(stage_index, week)
    except Exception as exc:
        await interaction.followup.send(f"Failed to load games for {stage_display_name(stage_index) if 'stage_index' in locals() else 'the selected phase'} week {week}: {exc}", ephemeral=True)
        return

    if not games:
        await interaction.followup.send(f"No games found for {stage_week_label(stage_index, week)}.", ephemeral=True)
        return

    guild = interaction.guild
    week_label = stage_week_label(stage_index, week)
    category_title = category_name or f"{week_label} Games"

    existing_category = discord.utils.get(guild.categories, name=category_title)
    if existing_category is None:
        existing_category = await guild.create_category(category_title)

    scored_games = [(game, compute_matchup_score(game)) for game in games]
    scored_games.sort(key=lambda item: item[1], reverse=True)
    gotw_game_ids = {game["game_id"] for game, _score in scored_games[:2]}

    created_channels = []
    skipped_channels = []
    gotw_created = []

    for game in games:
        game_id = game["game_id"]
        game_week = int(game.get("display_week", week))
        game_stage_index = int(game["stage_index"])
        status = game["status"]
        away_team_name = game["away_team_name"]
        home_team_name = game["home_team_name"]

        is_gotw = game_id in gotw_game_ids

        base_name = f"{stage_channel_prefix(game_stage_index)}{game_week}-{slugify_channel_name(away_team_name)}-vs-{slugify_channel_name(home_team_name)}"
        channel_name = f"gotw-{base_name}" if is_gotw else base_name
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
            topic=(
                f"Game ID {game_id} | Display Week {game_week} | Raw Week {game['week']} | "
                f"Stage {stage_display_name(game_stage_index)} ({game_stage_index}) | Status {status}"
            ),
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

        message_lines = []
        if is_gotw:
            message_lines.extend(["🔥 **GAME OF THE WEEK** 🔥", ""])
            gotw_created.append(channel_name)

        message_lines.extend([
            f"🏈 **{stage_week_label(game_stage_index, game_week)} Matchup**",
            f"**Away:** {away_team_name}",
            f"**Home:** {home_team_name}",
            "",
            f"{mention_parts[0]} vs {mention_parts[1]}",
            "",
            "Use this channel to schedule your game.",
        ])

        await channel.send("\n".join(message_lines))

        if AUTO_POST_MATCHUP_PREVIEWS:
            try:
                preview_text, used_ai = await generate_matchup_preview_text(game, is_gotw)
                facts = build_matchup_facts(game, is_gotw)
                embed = discord.Embed(
                    title=f"📰 {facts['headline']}",
                    description=preview_text,
                    color=0x3498DB if not is_gotw else 0xF39C12,
                )
                if facts["players_to_watch"]:
                    embed.add_field(name="Players to Watch", value="\n".join(f"• {item}" for item in facts["players_to_watch"]), inline=False)
                embed.add_field(name="Why It Matters", value=facts["stakes_line"], inline=False)
                embed.set_footer(text="AI-assisted preview" if used_ai else "Template preview")
                await channel.send(embed=embed)
            except Exception as exc:
                await channel.send(f"Pregame preview failed to generate: {exc}")

        created_channels.append(channel_name)

    should_post_news = AUTO_POST_WEEKLY_NEWS if auto_news is None else auto_news
    if should_post_news:
        try:
            await post_weekly_news_article(
                guild,
                week,
                games,
                gotw_game_ids,
                stage_index=stage_index,
            )
        except Exception as exc:
            print(f"Weekly news auto-post failed for {week_label}: {exc}")

    summary_lines = [f"Created {len(created_channels)} channel(s) in **{category_title}** for **{week_label}**."]
    if created_channels:
        summary_lines.append("Created:\n" + "\n".join(f"• {name}" for name in created_channels[:20]))
    if skipped_channels:
        summary_lines.append("Skipped:\n" + "\n".join(f"• {name}" for name in skipped_channels[:20]))
    if gotw_created:
        summary_lines.append("GOTW:\n" + "\n".join(f"• {name}" for name in gotw_created))

    await interaction.followup.send("\n\n".join(summary_lines), ephemeral=True)


@bot.tree.command(name="post_weekly_news", description="Admin: post the main weekly league news article.")
@admin_only()
@app_commands.describe(
    week="Human week number (Week 1, Week 2, etc.)",
    phase="Optional phase override. Leave empty to auto-detect the current phase.",
    channel="Optional channel to post in. Defaults to NEWS_CHANNEL_ID or current channel.",
)
@app_commands.choices(phase=[
    app_commands.Choice(name="Auto Detect", value="auto"),
    app_commands.Choice(name="Preseason", value="preseason"),
    app_commands.Choice(name="Regular Season", value="regular"),
    app_commands.Choice(name="Wild Card", value="wild card"),
    app_commands.Choice(name="Divisional", value="divisional"),
    app_commands.Choice(name="Conference Championship", value="conference championship"),
    app_commands.Choice(name="Super Bowl", value="super bowl"),
])
async def post_weekly_news(
    interaction: discord.Interaction,
    week: int,
    phase: Optional[str] = None,
    channel: Optional[discord.TextChannel] = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    if week < 1:
        await interaction.followup.send("Enter the real human week number, starting at 1.", ephemeral=True)
        return

    try:
        stage_index = resolve_command_stage(phase)
        games = fetch_games_for_stage_week(stage_index, week)
    except Exception as exc:
        await interaction.followup.send(f"Failed to load games for {stage_display_name(stage_index) if 'stage_index' in locals() else 'the selected phase'} week {week}: {exc}", ephemeral=True)
        return

    if not games:
        await interaction.followup.send(f"No games found for {stage_week_label(stage_index, week)}.", ephemeral=True)
        return

    scored_games = [(game, compute_matchup_score(game)) for game in games]
    scored_games.sort(key=lambda item: item[1], reverse=True)
    gotw_game_ids = {game["game_id"] for game, _score in scored_games[:2]}

    try:
        posted_channel, used_ai = await post_weekly_news_article(
            interaction.guild,
            week,
            games,
            gotw_game_ids,
            fallback_channel=channel or (interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None),
            stage_index=stage_index,
        )
    except Exception as exc:
        await interaction.followup.send(f"Failed to post weekly news: {exc}", ephemeral=True)
        return

    if posted_channel is None:
        await interaction.followup.send(
            "No valid news channel found. Set NEWS_CHANNEL_ID or provide a channel.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"Posted {stage_week_label(stage_index, week)} news in {posted_channel.mention} ({'AI' if used_ai else 'template'} mode).",
        ephemeral=True,
    )
    await send_log_message(
        f"📰 NEWS: {interaction.user.mention} posted {stage_week_label(stage_index, week)} league news in {posted_channel.mention} "
        f"using {'AI' if used_ai else 'template'} mode."
    )


@bot.tree.command(name="preview_matchup_article", description="Admin: post one matchup preview article in the current channel.")
@admin_only()
@app_commands.describe(
    week="Human week number",
    phase="Optional phase override. Leave empty to auto-detect the current phase.",
    away_team="Away team name",
    home_team="Home team name",
)
@app_commands.choices(phase=[
    app_commands.Choice(name="Auto Detect", value="auto"),
    app_commands.Choice(name="Preseason", value="preseason"),
    app_commands.Choice(name="Regular Season", value="regular"),
    app_commands.Choice(name="Wild Card", value="wild card"),
    app_commands.Choice(name="Divisional", value="divisional"),
    app_commands.Choice(name="Conference Championship", value="conference championship"),
    app_commands.Choice(name="Super Bowl", value="super bowl"),
])
async def preview_matchup_article(
    interaction: discord.Interaction,
    week: int,
    phase: Optional[str] = None,
    away_team: str = "",
    home_team: str = "",
):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    if week < 1:
        await interaction.followup.send("Enter the real human week number, starting at 1.", ephemeral=True)
        return

    try:
        stage_index = resolve_command_stage(phase)
        games = fetch_games_for_stage_week(stage_index, week)
    except Exception as exc:
        await interaction.followup.send(f"Failed to load games for {stage_display_name(stage_index) if 'stage_index' in locals() else 'the selected phase'} week {week}: {exc}", ephemeral=True)
        return

    normalized_away = normalize_team_name(away_team)
    normalized_home = normalize_team_name(home_team)

    selected_game = None
    for game in games:
        if normalize_team_name(game["away_team_name"]) == normalized_away and normalize_team_name(game["home_team_name"]) == normalized_home:
            selected_game = game
            break

    if selected_game is None:
        await interaction.followup.send("That matchup was not found for the requested phase/week.", ephemeral=True)
        return

    scored_games = [(game, compute_matchup_score(game)) for game in games]
    scored_games.sort(key=lambda item: item[1], reverse=True)
    gotw_game_ids = {game["game_id"] for game, _score in scored_games[:2]}
    is_gotw = selected_game["game_id"] in gotw_game_ids

    facts = build_matchup_facts(selected_game, is_gotw)
    preview_text, used_ai = await generate_matchup_preview_text(selected_game, is_gotw)
    embed = discord.Embed(
        title=f"📰 {facts['headline']}",
        description=preview_text,
        color=0x3498DB if not is_gotw else 0xF39C12,
    )
    if facts["players_to_watch"]:
        embed.add_field(name="Players to Watch", value="\n".join(f"• {item}" for item in facts["players_to_watch"]), inline=False)
    embed.add_field(name="Why It Matters", value=facts["stakes_line"], inline=False)
    embed.set_footer(text="AI-assisted preview" if used_ai else "Template preview")

    await interaction.followup.send("Posted below.", ephemeral=True)
    if interaction.channel:
        await interaction.channel.send(embed=embed)


@bot.tree.command(name="regenerate_weekly_news", description="Admin: regenerate and repost the weekly league news article.")
@admin_only()
@app_commands.describe(
    week="Human week number",
    phase="Optional phase override. Leave empty to auto-detect the current phase.",
    channel="Optional channel to post in. Defaults to NEWS_CHANNEL_ID or current channel.",
)
@app_commands.choices(phase=[
    app_commands.Choice(name="Auto Detect", value="auto"),
    app_commands.Choice(name="Preseason", value="preseason"),
    app_commands.Choice(name="Regular Season", value="regular"),
    app_commands.Choice(name="Wild Card", value="wild card"),
    app_commands.Choice(name="Divisional", value="divisional"),
    app_commands.Choice(name="Conference Championship", value="conference championship"),
    app_commands.Choice(name="Super Bowl", value="super bowl"),
])
async def regenerate_weekly_news(
    interaction: discord.Interaction,
    week: int,
    phase: Optional[str] = None,
    channel: Optional[discord.TextChannel] = None,
):
    await post_weekly_news.callback(interaction, week, phase, channel)  # type: ignore[attr-defined]


@bot.tree.command(name="regenerate_matchup_article", description="Admin: regenerate and repost one matchup preview article in the current channel.")
@admin_only()
@app_commands.describe(
    week="Human week number",
    phase="Optional phase override. Leave empty to auto-detect the current phase.",
    away_team="Away team name",
    home_team="Home team name",
)
@app_commands.choices(phase=[
    app_commands.Choice(name="Auto Detect", value="auto"),
    app_commands.Choice(name="Preseason", value="preseason"),
    app_commands.Choice(name="Regular Season", value="regular"),
    app_commands.Choice(name="Wild Card", value="wild card"),
    app_commands.Choice(name="Divisional", value="divisional"),
    app_commands.Choice(name="Conference Championship", value="conference championship"),
    app_commands.Choice(name="Super Bowl", value="super bowl"),
])
async def regenerate_matchup_article(
    interaction: discord.Interaction,
    week: int,
    phase: Optional[str] = None,
    away_team: str = "",
    home_team: str = "",
):
    await preview_matchup_article.callback(interaction, week, phase, away_team, home_team)  # type: ignore[attr-defined]


@bot.tree.command(name="post_season_leaders", description="Admin: post current season stat leaders.")
@admin_only()
@app_commands.describe(channel="Optional channel to post in. Defaults to LEADERS_CHANNEL_ID or current channel.")
async def post_season_leaders(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel] = None,
):
    await interaction.response.defer(ephemeral=True)

    try:
        passing_rows = fetch_top_passing_leaders()
        rushing_rows = fetch_top_rushing_leaders()
        sack_rows = fetch_top_sack_leaders()
        interception_rows = fetch_top_interception_leaders()
    except Exception as exc:
        await interaction.followup.send(f"Failed to load season leaders: {exc}", ephemeral=True)
        return

    target_channel = channel
    if target_channel is None and LEADERS_CHANNEL_ID:
        target_channel = interaction.guild.get_channel(LEADERS_CHANNEL_ID) if interaction.guild else None
        if target_channel is None:
            try:
                fetched = await bot.fetch_channel(LEADERS_CHANNEL_ID)
                if isinstance(fetched, discord.TextChannel):
                    target_channel = fetched
            except Exception:
                target_channel = None

    if target_channel is None:
        if isinstance(interaction.channel, discord.TextChannel):
            target_channel = interaction.channel
        else:
            await interaction.followup.send(
                "No target channel found. Provide a channel or set LEADERS_CHANNEL_ID.",
                ephemeral=True,
            )
            return

    sections = [
        ("🏈 Passing Yards", format_leader_lines(passing_rows, "total_pass_yds", "Passing Yards")),
        ("🏃 Rushing Yards", format_leader_lines(rushing_rows, "total_rush_yds", "Rushing Yards")),
        ("💥 Sacks", format_leader_lines(sack_rows, "total_sacks", "Sacks")),
        ("🖐️ Interceptions", format_leader_lines(interception_rows, "total_ints", "Interceptions")),
    ]

    embed = discord.Embed(
        title="📊 Season Stat Leaders",
        description="Top 5 current season leaders",
        color=0x5865F2,
    )

    for title, lines in sections:
        embed.add_field(name=title, value="\n".join(lines), inline=False)

    await target_channel.send(embed=embed)

    await interaction.followup.send(
        f"Posted season leaders in {target_channel.mention}.",
        ephemeral=True,
    )

    await send_log_message(
        f"📊 LEADERS: {interaction.user.mention} posted season leaders in {target_channel.mention}."
    )



# =========================================================
# Low-repetition article system overrides
# =========================================================
import hashlib
from collections import defaultdict

MATCHUP_ANGLE_POOL = [
    "statement game", "upset alert", "playoff leverage", "division pressure", "contender check",
    "pretender check", "star quarterback spotlight", "ground war", "defensive rock fight", "tempo clash",
    "pass game stress test", "red-zone pressure", "turnover tax", "trench war", "home-field squeeze",
    "road-test spotlight", "prove-it night", "heavyweight collision", "sleeping giant watch", "seeding collision",
    "chaos candidate", "fraud watch", "spotlight burden", "clock-control fight", "big-play hunt",
    "third-down stress", "finishing-drive battle", "defensive answer game", "offensive rebound spot", "bounce-back frame",
    "discipline test", "talent-gap question", "identity game", "edge-rusher spotlight", "playmaker showcase",
    "quarterback composure test", "must-answer matchup", "style contrast", "momentum swing game", "tone-setter",
    "measuring-stick game", "pressure cooker", "statement defense", "late-season energy", "spoiler angle",
]

MATCHUP_STRUCTURE_POOL = [
    "stakes-led bulletin", "player-spotlight open", "stat-punch opener", "tension-and-pressure build",
    "contrast of strengths", "why-it-matters first", "power-ranking style", "broadcast tease format",
    "warning-shot lead", "featured matchup desk hit", "fast-hitting four-pack", "narrative-first frame",
    "seed-race frame", "coaching-chess-match frame", "x-factor first", "what-breaks-first frame",
    "topline-and-subplot", "question-driven lead", "drama-heavy setup", "clean analytic setup",
    "defense-first setup", "offense-first setup", "sleeper-game frame", "headline-with-turn frame",
    "contender-meter frame", "separate-the-teams frame", "control-the-script frame", "pressure-point frame",
    "pace-of-game frame", "possession-battle frame", "finishing-kick frame", "one-edge-decides frame",
    "spotlight-vs-substance frame", "margin-for-error frame", "explosiveness frame", "physicality frame",
    "risk-reward frame", "keep-up-or-get-buried frame", "tilt-the-race frame", "who-blinks-first frame",
    "featured-sidestory frame", "trust-factor frame", "ceiling-vs-floor frame", "strength-on-strength frame",
    "identity-check frame",
]

NEWS_ANGLE_POOL = [
    "power vacuum", "top-tier separation", "conference squeeze", "awards-race heat", "headline week",
    "playoff map shift", "division chaos", "middle-class traffic", "surprise-rise", "fraud exposure",
    "statement-week setup", "defense grabs headlines", "offense driving the season", "seeding pressure",
    "must-keep-pace week", "mvp conversation reset", "tightening race", "contender sorting", "upset radar",
    "big-game gravity", "late-season urgency", "ranking shuffle", "tier-break week", "control-of-the-room",
    "chaos watch", "favorite-under-fire", "identity week", "passing-race spotlight", "ground-game spotlight",
    "defensive playmaker surge", "scoreboard pressure", "top-dog scrutiny", "shadow contenders", "one-week swing",
    "league pecking order", "trap-door week", "credibility week", "heavyweight traffic", "season temperature rise",
    "narrative reset", "margin-for-error evaporates", "who-runs-the-league", "power check", "pressure migration",
    "attention shift",
]

NEWS_STRUCTURE_POOL = [
    "headline thesis plus three pivots", "top-down sportsdesk open", "five-storyline stack", "league pulse frame",
    "power-race then stat-race", "headline game anchor", "contenders-and-chasers frame", "awards-desk frame",
    "pressure-map frame", "what-changed-this-week frame", "market-watch frame", "temperature-check frame",
    "if-the-season-ended-today frame", "who-has-the-leverage frame", "biggest-movers frame", "spotlight-carousel frame",
    "conversation-shifter frame", "from-the-top-down frame", "who-owns-the-week frame", "narrative-reset frame",
    "danger-list frame", "statement-board frame", "headline-and-undercard frame", "tier-report frame",
    "table-setter frame", "lead-story plus side quests", "power-lens frame", "awards-lens frame",
    "schedule-pressure frame", "separation-sunday frame", "one-room-one-story frame", "this-week-in-control frame",
    "what-everyone-is-watching frame", "high-ground frame", "traffic-jam frame", "center-of-gravity frame",
    "who-can-breathe frame", "topline-plus-ripple-effects frame", "watch-list frame", "credibility-board frame",
    "power-balance frame", "chaos-index frame", "spotlight-desk frame", "biggest-questions frame", "season-axis frame",
]

AVOID_PHRASES = [
    "both teams come in", "all eyes will be on", "this one has all the makings", "it will be interesting to see",
    "with momentum on the line", "this game could say a lot", "will look to", "could go a long way",
    "only time will tell", "set the tone", "battle-tested", "lights get brighter", "must-see matchup",
    "the pressure is on", "one thing is clear", "on paper", "plenty at stake", "circle this one",
]

_WEEKLY_ARTICLE_MEMORY = {
    "matchup_angles": defaultdict(lambda: defaultdict(int)),
    "matchup_structures": defaultdict(lambda: defaultdict(int)),
    "news_angles": defaultdict(lambda: defaultdict(int)),
    "news_structures": defaultdict(lambda: defaultdict(int)),
}


def _stable_hash(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest(), 16)


def _pick_low_repeat(pool, counter_map, seed: str):
    counts = counter_map
    min_count = min(counts.get(item, 0) for item in pool)
    candidates = [item for item in pool if counts.get(item, 0) == min_count]
    idx = _stable_hash(seed) % len(candidates)
    choice = candidates[idx]
    counts[choice] += 1
    return choice


def _top_story(row, label):
    if not row:
        return ""
    if "total_pass_yds" in row:
        return f"{label} passing pace runs through {row['player_name']} with {safe_int(row.get('total_pass_yds'))} yards"
    if "total_rush_yds" in row:
        return f"{label} ground production leans on {row['player_name']} with {safe_int(row.get('total_rush_yds'))} yards"
    if "total_sacks" in row:
        return f"{label} pressure starts with {row['player_name']} and {safe_int(row.get('total_sacks'))} sacks"
    if "total_ints" in row:
        return f"{label} ball production features {row['player_name']} with {safe_int(row.get('total_ints'))} picks"
    return ""


def _team_trait(team: dict) -> str:
    pf = safe_int(team.get("pts_for"))
    pa = safe_int(team.get("pts_against"))
    to = safe_int(team.get("turnover_diff"))
    win_pct = float(team.get("win_pct") or 0)
    ovr = safe_int(team.get("team_ovr"))
    lines = []
    if pf >= 150:
        lines.append("puts points on the board fast")
    if pa and pa <= 110:
        lines.append("has kept scoring windows tight")
    if to >= 5:
        lines.append("has lived off extra possessions")
    if to <= -5:
        lines.append("has been flirting with giveaway trouble")
    if win_pct >= 0.75:
        lines.append("has been operating like a front-line contender")
    if ovr >= 88:
        lines.append("has top-end roster talent")
    if not lines:
        lines.append("has been searching for cleaner weekly control")
    return deterministic_choice(lines, f"trait-{team.get('team_name','team')}-{pf}-{pa}-{to}-{ovr}")


def _structured_matchup_components(facts: dict):
    away = facts["away_team"]
    home = facts["home_team"]
    week = facts["week"]
    a_name = away["team_name"]
    h_name = home["team_name"]
    away_record = wins_losses_ties_text(away)
    home_record = wins_losses_ties_text(home)
    a_trait = _team_trait(away)
    h_trait = _team_trait(home)
    away_star = _top_story(facts["away_leaders"].get("passing") or facts["away_leaders"].get("rushing") or facts["away_leaders"].get("defense"), a_name)
    home_star = _top_story(facts["home_leaders"].get("passing") or facts["home_leaders"].get("rushing") or facts["home_leaders"].get("defense"), h_name)
    stakes = build_matchup_stakes_line(facts)
    top_story = deterministic_choice([x for x in [away_star, home_star, facts.get("away_storyline"), facts.get("home_storyline")] if x], f"top-story-{week}-{facts['game_id']}")
    score_gap = abs(safe_int(away.get("pts_for")) - safe_int(home.get("pts_for")))
    turnover_gap = abs(safe_int(away.get("turnover_diff")) - safe_int(home.get("turnover_diff")))
    return {
        "hook_a": f"Week {week} throws {a_name} ({away_record}) into a high-attention spot against {h_name} ({home_record}).",
        "hook_b": f"There is nothing quiet about {a_name} at {h_name} in Week {week}, especially with both sides carrying different kinds of pressure.",
        "hook_c": f"{a_name} and {h_name} land on the Week {week} board as a game that can move league opinion in a hurry.",
        "trait_a": f"{a_name} {a_trait}.",
        "trait_b": f"{h_name} {h_trait}.",
        "star": (top_story + ".") if top_story else f"The player layer is worth watching because one explosive performance could swing the whole script.",
        "metric": deterministic_choice([
            f"The scoring profiles are separated by just {score_gap} points, which makes execution late in drives feel huge.",
            f"Turnover margin could be the hinge here, with a difference of {turnover_gap} between the two teams on the year.",
            f"Roster strength is close enough that this game should be more about control than raw talent.",
            f"The matchup score landed at {facts['matchup_score']}, and that tracks with how much heat this game carries into kickoff.",
        ], f"metric-{week}-{facts['game_id']}-{facts['structure']}") ,
        "stakes": stakes,
        "close_a": f"That makes this less about surviving four quarters and more about which side can actually dictate the terms.",
        "close_b": f"Whoever controls the cleaner version of this game probably walks out with a result that carries into next week’s conversation.",
        "close_c": f"The winner gets more than a box-score bump here; the league reads these games as signals.",
    }


def build_matchup_angle(away_team, home_team, away_leaders, home_leaders, is_gotw: bool, matchup_score: float) -> str:
    week_seed = f"wk{safe_int(away_team.get('wins'))}-{safe_int(home_team.get('wins'))}-{is_gotw}-{matchup_score}-{away_team.get('team_name')}-{home_team.get('team_name')}"
    week_key = week_seed
    pool = MATCHUP_ANGLE_POOL[:]
    if is_gotw:
        pool = ["heavyweight collision", "headline week", "statement game", "seeding collision", "spotlight burden"] + pool
    return _pick_low_repeat(pool, _WEEKLY_ARTICLE_MEMORY["matchup_angles"][week_key], week_seed)


def build_matchup_facts(game_row, is_gotw: bool) -> dict:
    away_team = fetch_team_standing(game_row["away_team_id"]) or {
        "team_name": game_row["away_team_name"],
        "wins": game_row.get("away_wins", 0),
        "losses": game_row.get("away_losses", 0),
        "ties": game_row.get("away_ties", 0),
        "win_pct": game_row.get("away_win_pct", 0),
        "team_ovr": game_row.get("away_ovr", 0),
    }
    home_team = fetch_team_standing(game_row["home_team_id"]) or {
        "team_name": game_row["home_team_name"],
        "wins": game_row.get("home_wins", 0),
        "losses": game_row.get("home_losses", 0),
        "ties": game_row.get("home_ties", 0),
        "win_pct": game_row.get("home_win_pct", 0),
        "team_ovr": game_row.get("home_ovr", 0),
    }
    away_leaders = fetch_team_stat_leaders(game_row["away_team_id"])
    home_leaders = fetch_team_stat_leaders(game_row["home_team_id"])
    matchup_score = round(compute_matchup_score(game_row), 2)
    week = safe_int(game_row.get("display_week", safe_int(game_row.get("week")) + 1))
    base_seed = f"wk{week}-game{safe_int(game_row.get('game_id'))}-{away_team['team_name']}-{home_team['team_name']}"
    angle = _pick_low_repeat(MATCHUP_ANGLE_POOL, _WEEKLY_ARTICLE_MEMORY["matchup_angles"][week], base_seed + "-angle")
    structure = _pick_low_repeat(MATCHUP_STRUCTURE_POOL, _WEEKLY_ARTICLE_MEMORY["matchup_structures"][week], base_seed + "-structure")
    facts = {
        "week": week,
        "game_id": safe_int(game_row.get("game_id")),
        "stage_index": safe_int(game_row.get("stage_index")),
        "status": safe_int(game_row.get("status")),
        "is_gotw": bool(is_gotw),
        "matchup_score": matchup_score,
        "angle": angle,
        "structure": structure,
        "away_team": away_team,
        "home_team": home_team,
        "away_storyline": build_team_storyline(away_team, away_leaders),
        "home_storyline": build_team_storyline(home_team, home_leaders),
        "away_leaders": away_leaders,
        "home_leaders": home_leaders,
        "players_to_watch": [],
        "stakes_line": "",
    }
    facts["headline"] = build_matchup_headline(facts)
    facts["players_to_watch"] = build_matchup_players_to_watch(facts)
    facts["stakes_line"] = build_matchup_stakes_line(facts)
    return facts


def build_matchup_headline(facts: dict) -> str:
    away = facts["away_team"]["team_name"]
    home = facts["home_team"]["team_name"]
    week = facts["week"]
    angle = facts.get("angle", "statement game")
    options = {
        "statement game": [f"Week {week} puts {away} and {home} in a statement spot", f"{away} and {home} get a chance to move the room in Week {week}"],
        "upset alert": [f"Week {week} carries upset energy with {away} at {home}", f"Can {away} flip the expected script against {home}?"],
        "playoff leverage": [f"{away} at {home} carries real playoff leverage", f"Week {week} tightens around {away} vs {home}"],
        "heavyweight collision": [f"Heavyweight collision: {away} at {home}", f"Week {week} headline fight lands on {away} vs {home}"],
        "seeding collision": [f"{away} and {home} collide with seeding pressure attached", f"Seeding heat follows {away} into {home} this week"],
    }
    return deterministic_choice(options.get(angle, [f"Week {week} spotlight: {away} at {home}", f"{away} and {home} land in the Week {week} spotlight"]), f"headline-{week}-{facts['game_id']}-{angle}")


def template_matchup_preview_text(facts: dict) -> str:
    comp = _structured_matchup_components(facts)
    structure = facts.get("structure", "stakes-led bulletin")
    blocks = {
        "stakes-led bulletin": [comp["hook_a"], comp["stakes"], comp["star"], comp["metric"], comp["close_b"]],
        "player-spotlight open": [comp["star"], comp["hook_c"], comp["trait_a"], comp["trait_b"], comp["stakes"]],
        "stat-punch opener": [comp["metric"], comp["hook_a"], comp["trait_a"], comp["star"], comp["stakes"]],
        "tension-and-pressure build": [comp["hook_b"], comp["trait_a"], comp["trait_b"], comp["metric"], comp["close_a"]],
        "contrast of strengths": [comp["trait_a"], comp["trait_b"], comp["hook_c"], comp["star"], comp["stakes"]],
        "why-it-matters first": [comp["stakes"], comp["hook_a"], comp["metric"], comp["star"], comp["close_c"]],
        "power-ranking style": [comp["hook_c"], comp["trait_a"], comp["trait_b"], comp["stakes"], comp["close_b"]],
        "broadcast tease format": [comp["hook_a"], comp["star"], comp["metric"], comp["trait_b"], comp["close_a"]],
        "warning-shot lead": [comp["hook_b"], comp["metric"], comp["star"], comp["trait_a"], comp["stakes"]],
        "featured matchup desk hit": [comp["hook_c"], comp["trait_b"], comp["metric"], comp["star"], comp["close_c"]],
        "fast-hitting four-pack": [comp["hook_a"], comp["trait_a"], comp["trait_b"], comp["stakes"]],
        "narrative-first frame": [comp["hook_b"], comp["star"], comp["metric"], comp["close_b"]],
        "seed-race frame": [comp["stakes"], comp["metric"], comp["hook_c"], comp["star"], comp["close_c"]],
        "coaching-chess-match frame": [comp["hook_a"], comp["trait_a"], comp["metric"], comp["close_a"]],
        "x-factor first": [comp["star"], comp["metric"], comp["hook_b"], comp["stakes"]],
        "what-breaks-first frame": [comp["metric"], comp["trait_a"], comp["trait_b"], comp["close_b"]],
        "topline-and-subplot": [comp["hook_c"], comp["metric"], comp["star"], comp["close_c"]],
        "question-driven lead": [f"The Week {facts['week']} question is whether {facts['away_team']['team_name']} can drag this game into their preferred script against {facts['home_team']['team_name']}.", comp["trait_a"], comp["star"], comp["stakes"]],
        "drama-heavy setup": [comp["hook_b"], comp["stakes"], comp["metric"], comp["close_a"]],
        "clean analytic setup": [comp["metric"], comp["trait_a"], comp["trait_b"], comp["stakes"]],
        "defense-first setup": [comp["trait_b"], comp["metric"], comp["hook_a"], comp["close_b"]],
        "offense-first setup": [comp["trait_a"], comp["star"], comp["hook_c"], comp["stakes"]],
        "sleeper-game frame": [comp["hook_c"], comp["metric"], comp["close_c"]],
        "headline-with-turn frame": [comp["hook_a"], comp["metric"], comp["stakes"], comp["close_a"]],
        "contender-meter frame": [comp["hook_b"], comp["trait_a"], comp["trait_b"], comp["close_c"]],
        "separate-the-teams frame": [comp["metric"], comp["star"], comp["close_b"]],
        "control-the-script frame": [comp["hook_c"], comp["trait_a"], comp["stakes"], comp["close_a"]],
        "pressure-point frame": [comp["stakes"], comp["star"], comp["metric"], comp["close_b"]],
        "pace-of-game frame": [comp["trait_a"], comp["metric"], comp["hook_a"], comp["close_c"]],
        "possession-battle frame": [comp["metric"], comp["stakes"], comp["star"], comp["close_b"]],
        "finishing-kick frame": [comp["hook_b"], comp["metric"], comp["close_a"]],
        "one-edge-decides frame": [comp["star"], comp["metric"], comp["close_c"]],
        "spotlight-vs-substance frame": [comp["hook_c"], comp["stakes"], comp["trait_b"], comp["close_b"]],
        "margin-for-error frame": [comp["hook_a"], comp["metric"], comp["close_a"]],
        "explosiveness frame": [comp["trait_a"], comp["star"], comp["close_b"]],
        "physicality frame": [comp["trait_b"], comp["hook_b"], comp["metric"], comp["close_c"]],
        "risk-reward frame": [comp["metric"], comp["hook_c"], comp["stakes"], comp["close_a"]],
        "keep-up-or-get-buried frame": [comp["hook_b"], comp["trait_a"], comp["close_c"]],
        "tilt-the-race frame": [comp["stakes"], comp["hook_a"], comp["close_b"]],
        "who-blinks-first frame": [comp["hook_c"], comp["metric"], comp["close_a"]],
        "featured-sidestory frame": [comp["star"], comp["hook_a"], comp["close_c"]],
        "trust-factor frame": [comp["hook_b"], comp["trait_b"], comp["close_b"]],
        "ceiling-vs-floor frame": [comp["metric"], comp["trait_a"], comp["close_c"]],
        "strength-on-strength frame": [comp["trait_a"], comp["trait_b"], comp["star"], comp["stakes"]],
        "identity-check frame": [comp["hook_a"], comp["trait_a"], comp["trait_b"], comp["close_a"]],
    }
    selected = blocks.get(structure, blocks["stakes-led bulletin"])
    cleaned = []
    used = set()
    for line in selected:
        line = line.strip()
        low = line.lower()
        if line and low not in used:
            cleaned.append(line)
            used.add(low)
    return " ".join(cleaned[:5])


def build_matchup_prompt(facts: dict) -> str:
    return (
        "You are writing one matchup preview for a Madden franchise Discord.\n"
        "Hard rules:\n"
        "- Write exactly 4 or 5 sentences.\n"
        "- Use only the provided facts.\n"
        "- Do not invent players, streaks, quotes, injuries, awards, or results.\n"
        f"- The assigned narrative angle is: {facts['angle']}.\n"
        f"- The assigned article structure is: {facts['structure']}.\n"
        "- Make this preview feel sharply distinct from other previews in the same week.\n"
        "- Do not reuse generic sports filler or symmetrical phrasing.\n"
        f"- Avoid these phrases entirely: {', '.join(AVOID_PHRASES)}.\n"
        "- Use a different opening style than a plain records recap unless the facts force it.\n"
        "- End with a strong sentence about leverage, pressure, or why the game matters.\n\n"
        f"Facts JSON:\n{json.dumps(facts, indent=2)}"
    )


def build_league_news_facts(week: int, games, gotw_game_ids: set[int]) -> dict:
    standings = fetch_standings_rows()[:8]
    passing = fetch_top_passing_leaders(6)
    rushing = fetch_top_rushing_leaders(6)
    sacks = fetch_top_sack_leaders(6)
    interceptions = fetch_top_interception_leaders(6)
    ranked_games = []
    for game in games:
        ranked_games.append({
            "game_id": safe_int(game["game_id"]),
            "away_team_name": game["away_team_name"],
            "home_team_name": game["home_team_name"],
            "matchup_score": round(compute_matchup_score(game), 2),
            "is_gotw": safe_int(game["game_id"]) in gotw_game_ids,
            "away_wins": safe_int(game.get("away_wins")),
            "away_losses": safe_int(game.get("away_losses")),
            "home_wins": safe_int(game.get("home_wins")),
            "home_losses": safe_int(game.get("home_losses")),
        })
    ranked_games.sort(key=lambda row: row["matchup_score"], reverse=True)
    seed = f"news-week-{week}-{len(games)}-{len(gotw_game_ids)}"
    angle = _pick_low_repeat(NEWS_ANGLE_POOL, _WEEKLY_ARTICLE_MEMORY["news_angles"][week], seed + "-angle")
    structure = _pick_low_repeat(NEWS_STRUCTURE_POOL, _WEEKLY_ARTICLE_MEMORY["news_structures"][week], seed + "-structure")
    return {
        "week": week,
        "angle": angle,
        "structure": structure,
        "top_teams": standings[:6],
        "passing_leaders": passing,
        "rushing_leaders": rushing,
        "sack_leaders": sacks,
        "interception_leaders": interceptions,
        "top_games": ranked_games[:6],
        "game_count": len(games),
    }


def build_weekly_news_headline(facts: dict) -> str:
    week = facts["week"]
    angle = facts.get("angle", "power vacuum")
    g = facts["top_games"][0] if facts["top_games"] else None
    t = facts["top_teams"][0] if facts["top_teams"] else None
    headlines = [
        f"Week {week} pressure report: {angle.title()}",
        f"Week {week} watchboard: {angle.title()}",
        f"League pulse for Week {week}: {angle.title()}",
    ]
    if g:
        headlines.extend([
            f"Week {week} turns toward {g['away_team_name']} vs {g['home_team_name']}",
            f"{g['away_team_name']} vs {g['home_team_name']} sits at the center of Week {week}",
        ])
    if t:
        headlines.extend([
            f"Week {week} opens with {t['team_name']} still shaping the table",
            f"{t['team_name']} remain part of the Week {week} headline gravity",
        ])
    return deterministic_choice(headlines, f"news-headline-{week}-{angle}")


def _news_components(facts: dict):
    week = facts["week"]
    teams = facts["top_teams"]
    games = facts["top_games"]
    lead = teams[0] if teams else None
    second = teams[1] if len(teams) > 1 else None
    top_game = games[0] if games else None
    p = facts["passing_leaders"][0] if facts["passing_leaders"] else None
    r = facts["rushing_leaders"][0] if facts["rushing_leaders"] else None
    s = facts["sack_leaders"][0] if facts["sack_leaders"] else None
    i = facts["interception_leaders"][0] if facts["interception_leaders"] else None
    return {
        "lead": f"Week {week} lands with the league starting to show its real pressure points.",
        "topline": f"{lead['team_name']} sit first at {wins_losses_ties_text(lead)}." if lead else f"Week {week} arrives with the standings picture still under construction.",
        "chase": f"{second['team_name']} are close enough at {wins_losses_ties_text(second)} to keep the race uncomfortable." if second else "The chase pack still has room to crash the picture.",
        "game": f"The main game on the board is {top_game['away_team_name']} vs {top_game['home_team_name']}, and that matchup carries the loudest weekly gravity." if top_game else "There is no shortage of games this week that can shove the standings around.",
        "pass": f"The passing race still has {p['player_name']} ({p['team_name']}) leading with {safe_int(p.get('total_pass_yds'))} yards." if p else "The passing race remains one of the easiest ways to track the league's power centers.",
        "rush": f"On the ground, {r['player_name']} ({r['team_name']}) continue to push the pace with {safe_int(r.get('total_rush_yds'))} rushing yards." if r else "The ground game race still matters because a few teams are winning by controlling tempo.",
        "defense": deterministic_choice([
            f"Defensively, {s['player_name']} ({s['team_name']}) keep affecting pockets with {safe_int(s.get('total_sacks'))} sacks." if s else "Defensive disruption is shaping more games than usual right now.",
            f"Ball production is also part of the story thanks to {i['player_name']} ({i['team_name']}) and {safe_int(i.get('total_ints'))} interceptions." if i else "Coverage discipline continues to swing who survives tight games.",
        ], f"news-defense-{week}"),
        "close": f"That is why Week {week} feels less like background schedule filler and more like a week that can redraw how the league reads itself.",
    }


def template_weekly_news_text(facts: dict) -> str:
    comp = _news_components(facts)
    structure = facts.get("structure", "headline thesis plus three pivots")
    blocks = {
        "headline thesis plus three pivots": [comp["lead"], comp["topline"], comp["game"], comp["pass"], comp["close"]],
        "top-down sportsdesk open": [comp["topline"], comp["chase"], comp["game"], comp["defense"], comp["close"]],
        "five-storyline stack": [comp["lead"], comp["topline"], comp["pass"], comp["rush"], comp["game"], comp["close"]],
        "league pulse frame": [comp["lead"], comp["chase"], comp["defense"], comp["game"], comp["close"]],
        "power-race then stat-race": [comp["topline"], comp["chase"], comp["pass"], comp["rush"], comp["close"]],
        "headline game anchor": [comp["game"], comp["topline"], comp["pass"], comp["close"]],
        "contenders-and-chasers frame": [comp["topline"], comp["chase"], comp["game"], comp["close"]],
        "awards-desk frame": [comp["pass"], comp["rush"], comp["defense"], comp["game"], comp["close"]],
        "pressure-map frame": [comp["lead"], comp["game"], comp["topline"], comp["close"]],
        "what-changed-this-week frame": [comp["topline"], comp["game"], comp["defense"], comp["close"]],
        "market-watch frame": [comp["lead"], comp["chase"], comp["game"], comp["close"]],
        "temperature-check frame": [comp["lead"], comp["topline"], comp["rush"], comp["close"]],
        "if-the-season-ended-today frame": [comp["topline"], comp["chase"], comp["game"], comp["close"]],
        "who-has-the-leverage frame": [comp["topline"], comp["game"], comp["pass"], comp["close"]],
        "biggest-movers frame": [comp["lead"], comp["chase"], comp["rush"], comp["close"]],
        "spotlight-carousel frame": [comp["game"], comp["pass"], comp["defense"], comp["close"]],
        "conversation-shifter frame": [comp["lead"], comp["game"], comp["close"]],
        "from-the-top-down frame": [comp["topline"], comp["chase"], comp["defense"], comp["close"]],
        "who-owns-the-week frame": [comp["game"], comp["topline"], comp["close"]],
        "narrative-reset frame": [comp["lead"], comp["pass"], comp["game"], comp["close"]],
        "danger-list frame": [comp["chase"], comp["game"], comp["defense"], comp["close"]],
        "statement-board frame": [comp["lead"], comp["topline"], comp["game"], comp["pass"], comp["close"]],
        "headline-and-undercard frame": [comp["game"], comp["rush"], comp["defense"], comp["close"]],
        "tier-report frame": [comp["topline"], comp["chase"], comp["close"]],
        "table-setter frame": [comp["lead"], comp["game"], comp["close"]],
        "lead-story plus side quests": [comp["game"], comp["pass"], comp["rush"], comp["close"]],
        "power-lens frame": [comp["topline"], comp["game"], comp["defense"], comp["close"]],
        "awards-lens frame": [comp["pass"], comp["rush"], comp["close"]],
        "schedule-pressure frame": [comp["lead"], comp["game"], comp["chase"], comp["close"]],
        "separation-sunday frame": [comp["topline"], comp["close"]],
        "one-room-one-story frame": [comp["game"], comp["topline"], comp["pass"], comp["close"]],
        "this-week-in-control frame": [comp["topline"], comp["defense"], comp["close"]],
        "what-everyone-is-watching frame": [comp["game"], comp["pass"], comp["close"]],
        "high-ground frame": [comp["topline"], comp["chase"], comp["close"]],
        "traffic-jam frame": [comp["lead"], comp["chase"], comp["game"], comp["close"]],
        "center-of-gravity frame": [comp["game"], comp["topline"], comp["close"]],
        "who-can-breathe frame": [comp["lead"], comp["topline"], comp["close"]],
        "topline-plus-ripple-effects frame": [comp["topline"], comp["game"], comp["defense"], comp["close"]],
        "watch-list frame": [comp["pass"], comp["rush"], comp["game"], comp["close"]],
        "credibility-board frame": [comp["lead"], comp["game"], comp["close"]],
        "power-balance frame": [comp["topline"], comp["chase"], comp["close"]],
        "chaos-index frame": [comp["lead"], comp["game"], comp["close"]],
        "spotlight-desk frame": [comp["game"], comp["defense"], comp["close"]],
        "biggest-questions frame": [comp["lead"], comp["game"], comp["pass"], comp["close"]],
        "season-axis frame": [comp["topline"], comp["game"], comp["rush"], comp["close"]],
    }
    selected = blocks.get(structure, blocks["headline thesis plus three pivots"])
    cleaned = []
    seen = set()
    for line in selected:
        line = line.strip()
        low = line.lower()
        if line and low not in seen:
            cleaned.append(line)
            seen.add(low)
    return " ".join(cleaned[:7])


def build_weekly_news_prompt(facts: dict) -> str:
    return (
        "You are writing the main weekly ESPN-style league desk article for a Madden franchise Discord.\n"
        "Hard rules:\n"
        "- Write 6 or 7 sentences.\n"
        "- Use only the provided facts.\n"
        f"- The assigned narrative angle is: {facts['angle']}.\n"
        f"- The assigned article structure is: {facts['structure']}.\n"
        "- Make this article feel unlike the matchup previews and unlike other weekly desk pieces.\n"
        "- No invented results, quotes, streaks, awards, or injuries.\n"
        f"- Avoid these phrases entirely: {', '.join(AVOID_PHRASES)}.\n"
        "- Build a stronger headline-style lead than a generic standings recap.\n"
        "- End with why the week can reshape league perception.\n\n"
        f"Facts JSON:\n{json.dumps(facts, indent=2)}"
    )


def build_weekly_news_spotlights(facts: dict) -> list[str]:
    items = []
    if facts["top_games"]:
        g = facts["top_games"][0]
        items.append(f"Centerpiece game: {g['away_team_name']} vs {g['home_team_name']}")
    if facts["passing_leaders"]:
        p = facts["passing_leaders"][0]
        items.append(f"Passing pace: {p['player_name']} ({p['team_name']}) — {safe_int(p.get('total_pass_yds'))} yds")
    if facts["rushing_leaders"]:
        r = facts["rushing_leaders"][0]
        items.append(f"Rushing pace: {r['player_name']} ({r['team_name']}) — {safe_int(r.get('total_rush_yds'))} yds")
    if facts["sack_leaders"]:
        s = facts["sack_leaders"][0]
        items.append(f"Pressure leader: {s['player_name']} ({s['team_name']}) — {safe_int(s.get('total_sacks'))} sacks")
    if facts["interception_leaders"]:
        i = facts["interception_leaders"][0]
        items.append(f"Takeaway leader: {i['player_name']} ({i['team_name']}) — {safe_int(i.get('total_ints'))} INTs")
    return items[:4]


def _clean_generated_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    for phrase in AVOID_PHRASES:
        cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


async def generate_matchup_preview_text(game_row, is_gotw: bool) -> tuple[str, bool]:
    facts = build_matchup_facts(game_row, is_gotw)
    fallback = template_matchup_preview_text(facts)
    if not OPENAI_API_KEY:
        return fallback, False
    try:
        print(f"Generating matchup preview with OpenAI | week={facts['week']} game={facts['game_id']} angle={facts['angle']} structure={facts['structure']}")
        ai_text = await asyncio.to_thread(call_openai_text, build_matchup_prompt(facts), 220)
        cleaned = _clean_generated_text(ai_text)
        return cleaned or fallback, True
    except Exception as exc:
        print(f"OpenAI matchup preview failed, using template fallback | week={facts['week']} game={facts['game_id']} error={exc}")
        return fallback, False


async def generate_weekly_news_text(week: int, games, gotw_game_ids: set[int]) -> tuple[str, bool]:
    facts = build_league_news_facts(week, games, gotw_game_ids)
    fallback = template_weekly_news_text(facts)
    if not OPENAI_API_KEY:
        return fallback, False
    try:
        print(f"Generating weekly news with OpenAI | week={week} angle={facts['angle']} structure={facts['structure']}")
        ai_text = await asyncio.to_thread(call_openai_text, build_weekly_news_prompt(facts), 320)
        cleaned = _clean_generated_text(ai_text)
        return cleaned or fallback, True
    except Exception as exc:
        print(f"OpenAI weekly news failed, using template fallback | week={week} error={exc}")
        return fallback, False

if not BOT_TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN is missing. Set it as an environment variable before running the bot.")

bot.run(BOT_TOKEN)

def fetch_weekly_rivalry_games_for_current_week():
    stage_index, display_week = detect_current_stage_and_week()
    if stage_index is None or display_week is None:
        return []
    games = fetch_games_for_stage_week(stage_index, display_week)
    if stage_index != 1:
        return []
    rivalry_games = []
    for game in games:
        away_team = resolve_team_row(str(game.get("away_team_name") or ""))
        home_team = resolve_team_row(str(game.get("home_team_name") or ""))
        if not away_team or not home_team:
            continue
        away_div = safe_text(away_team.get("division_name")).lower()
        home_div = safe_text(home_team.get("division_name")).lower()
        away_conf = safe_text(away_team.get("conference_name")).lower()
        home_conf = safe_text(home_team.get("conference_name")).lower()
        if away_div and away_div == home_div and away_conf == home_conf:
            rivalry_games.append(game)
    return rivalry_games


def build_weekly_rivalries_embed() -> discord.Embed:
    games = fetch_weekly_rivalry_games_for_current_week()
    stage_index, display_week = detect_current_stage_and_week()
    title = f"🔥 Weekly Rivalries — {stage_week_label(stage_index or 1, display_week or 1)}"
    if not games:
        return build_embed(title, "No rivalry games detected for the current week.", 0xE67E22)
    lines = []
    for game in games:
        away_mult = implied_multiplier_for_game_side(game, game["away_team_id"])
        home_mult = implied_multiplier_for_game_side(game, game["home_team_id"])
        lines.append(
            f"**{safe_text(game.get('away_team_name'))}** at **{safe_text(game.get('home_team_name'))}** "
            f"— sportsbook: {away_mult}x / {home_mult}x"
        )
    return build_embed(title, "\n".join(lines), 0xE67E22)


@bot.tree.command(name="weeklyrivalries", description="Show this week's rivalry games.")
async def weeklyrivalries(interaction: discord.Interaction):
    try:
        embed = build_weekly_rivalries_embed()
    except Exception as exc:
        await interaction.response.send_message(f"Failed to load weekly rivalries: {exc}", ephemeral=True)
        return
    await interaction.response.send_message(embed=embed)





def fetch_open_sportsbook_bets(limit: int = 50):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    b.*,
                    g.away_team_id,
                    g.home_team_id,
                    away.team_name AS away_team_name,
                    home.team_name AS home_team_name
                FROM bot_sportsbook_bets b
                LEFT JOIN games g
                    ON g.game_id = b.game_id
                   AND g.season_index = b.season_index
                   AND g.stage_index = b.stage_index
                   AND g.week = b.week
                LEFT JOIN teams away ON away.team_id = g.away_team_id
                LEFT JOIN teams home ON home.team_id = g.home_team_id
                WHERE b.status = 'open'
                  AND b.season_index = (SELECT COALESCE(MAX(season_index), 0) FROM games)
                ORDER BY b.created_at DESC, b.id DESC
                LIMIT %s
                """,
                (int(limit),),
            )
            return cur.fetchall()


@bot.tree.command(name="activebets", description="Show all currently open sportsbook bets.")
async def activebets(interaction: discord.Interaction):
    try:
        rows = fetch_open_sportsbook_bets(limit=50)
    except Exception as exc:
        await interaction.response.send_message(f"Failed to load active bets: {exc}", ephemeral=True)
        return

    if not rows:
        await interaction.response.send_message("There are no active sportsbook bets right now.")
        return

    lines = []
    for row in rows[:25]:
        matchup = "Unknown matchup"
        away_name = row.get("away_team_name")
        home_name = row.get("home_team_name")
        if away_name and home_name:
            matchup = f"{away_name} at {home_name}"

        week_value = int(row.get("week") or 0) + 1
        stage_value = int(row.get("stage_index") or 0)
        stage_label = STAGE_LABELS.get(stage_value, f"Stage {stage_value}")
        if stage_value == 1:
            slate_label = f"Week {week_value}"
        elif stage_value == 0:
            slate_label = f"Preseason Week {week_value}"
        else:
            slate_label = f"{stage_label} Week {week_value}"

        lines.append(
            f"**<@{row['user_id']}>** — {fmt_tokens(float(row['amount']))} on **{row['team_name']}** at **{float(row['multiplier']):.2f}x**\n"
            f"{matchup} | {slate_label}"
        )

    embed = build_embed("🎟️ Active Sportsbook Bets", "\n\n".join(lines), 0x5865F2)
    if len(rows) > 25:
        embed.set_footer(text=f"Showing 25 of {len(rows)} open bets.")
    await interaction.response.send_message(embed=embed)
