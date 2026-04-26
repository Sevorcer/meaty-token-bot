"""EventScanner — detects noteworthy Madden CFM league events for content generation."""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from .db import ContentDB

# Only allow column names that consist of alphanumeric characters and underscores
_VALID_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _safe_col(name: Optional[str]) -> Optional[str]:
    """Return `name` only if it is a safe SQL identifier, else None."""
    if name and _VALID_IDENT.match(name):
        return name
    return None


def _safe_cols(*names: Optional[str]) -> list[str]:
    """Return only the non-None, safe column names from the given list."""
    return [c for c in names if _safe_col(c)]


class EventScanner:
    """Scans Madden league data tables and returns noteworthy content events."""

    def __init__(self, db: ContentDB):
        self.db = db

    async def scan(self, guild_id: int) -> list[dict]:
        """
        Scan league data and return list of content event dicts.
        Each dict: {event_type, source_type, source_id, priority_score, metadata}

        Defensively handles missing tables and columns.
        Returns up to 5 events sorted by priority_score descending.
        """
        events: list[dict] = []

        scanners = [
            self._scan_games,
            self._scan_player_passing,
            self._scan_player_rushing,
            self._scan_player_receiving,
            self._scan_player_defense,
            self._scan_rivalries,
            self._scan_sportsbook,
            self._scan_bounties,
        ]

        for scanner in scanners:
            try:
                found = await asyncio.to_thread(scanner, guild_id)
                events.extend(found)
            except Exception as exc:
                print(f"[ContentPipeline] Scanner {scanner.__name__} error for guild {guild_id}: {exc}")

        # Deduplicate by (event_type, source_id) — keep highest priority
        seen: dict[tuple, dict] = {}
        for ev in events:
            key = (ev["event_type"], ev["source_id"])
            if key not in seen or ev["priority_score"] > seen[key]["priority_score"]:
                seen[key] = ev

        unique_events = sorted(seen.values(), key=lambda e: e["priority_score"], reverse=True)
        return unique_events[:5]

    # ------------------------------------------------------------------
    # Game-level scanners
    # ------------------------------------------------------------------

    def _scan_games(self, guild_id: int) -> list[dict]:
        events: list[dict] = []

        # Check table exists
        cols = self.db.get_table_columns("games")
        if not cols:
            return events

        home_score_col = _safe_col(self.db.pick_column("games", ["home_score", "home_final_score"]))
        away_score_col = _safe_col(self.db.pick_column("games", ["away_score", "away_final_score"]))
        week_col = _safe_col(self.db.pick_column("games", ["week", "schedule_week"]))
        played_col = _safe_col(self.db.pick_column("games", ["is_played", "played", "game_played"]))
        home_team_col = _safe_col(self.db.pick_column("games", ["home_team_name", "home_team"]))
        away_team_col = _safe_col(self.db.pick_column("games", ["away_team_name", "away_team"]))

        if not all([home_score_col, away_score_col, played_col]):
            return events

        try:
            with self.db._conn() as conn:
                with conn.cursor() as cur:
                    select_cols = ", ".join(
                        _safe_cols(
                            "id", home_score_col, away_score_col,
                            week_col, played_col, home_team_col, away_team_col,
                        )
                    )
                    cur.execute(
                        f"SELECT {select_cols} FROM games WHERE {played_col} = TRUE ORDER BY id DESC LIMIT 20"
                    )
                    games = cur.fetchall()
        except Exception as exc:
            print(f"[ContentPipeline] games scan error: {exc}")
            return events

        # Load standings for upset detection
        standings_wins: dict[str, int] = {}
        try:
            standings_cols = self.db.get_table_columns("standings")
            if standings_cols:
                team_col = _safe_col(self.db.pick_column("standings", ["team_name", "team"]))
                wins_col = _safe_col(self.db.pick_column("standings", ["total_wins", "wins", "win_count"]))
                if team_col and wins_col:
                    with self.db._conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(f"SELECT {team_col}, {wins_col} FROM standings")
                            for row in cur.fetchall():
                                t = str(row.get(team_col) or "")
                                w = int(row.get(wins_col) or 0)
                                if t:
                                    standings_wins[t] = w
        except Exception:
            pass

        for game in games:
            game_id = str(game.get("id", ""))
            home_score = int(game.get(home_score_col) or 0)
            away_score = int(game.get(away_score_col) or 0)
            home_team = str(game.get(home_team_col) or "") if home_team_col else ""
            away_team = str(game.get(away_team_col) or "") if away_team_col else ""
            week = int(game.get(week_col) or 0) if week_col else 0

            if home_score == 0 and away_score == 0:
                continue

            diff = abs(home_score - away_score)
            winner = home_team if home_score > away_score else away_team
            loser = away_team if home_score > away_score else home_team

            metadata = {
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_score,
                "away_score": away_score,
                "week": week,
                "winner": winner,
                "loser": loser,
                "margin": diff,
            }

            # Blowout win
            if diff >= 28:
                source_id = f"blowout_{game_id}"
                if not self.db.has_recent_event(guild_id, "blowout_win", source_id, hours=24):
                    events.append({
                        "event_type": "blowout_win",
                        "source_type": "games",
                        "source_id": source_id,
                        "priority_score": 70,
                        "metadata": {**metadata, "event_detail": f"{winner} blew out {loser} by {diff}"},
                    })

            # Close game
            elif diff <= 3:
                source_id = f"close_{game_id}"
                if not self.db.has_recent_event(guild_id, "close_game", source_id, hours=24):
                    events.append({
                        "event_type": "close_game",
                        "source_type": "games",
                        "source_id": source_id,
                        "priority_score": 75,
                        "metadata": {**metadata, "event_detail": f"{winner} edged {loser} by {diff}"},
                    })

            # Upset alert (winner had fewer wins than loser)
            if standings_wins:
                winner_wins = standings_wins.get(winner, 0)
                loser_wins = standings_wins.get(loser, 0)
                if winner_wins < loser_wins:
                    source_id = f"upset_{game_id}"
                    if not self.db.has_recent_event(guild_id, "upset_alert", source_id, hours=24):
                        events.append({
                            "event_type": "upset_alert",
                            "source_type": "games",
                            "source_id": source_id,
                            "priority_score": 90,
                            "metadata": {
                                **metadata,
                                "event_detail": (
                                    f"{winner} ({winner_wins}W) upset "
                                    f"{loser} ({loser_wins}W)"
                                ),
                            },
                        })

        return events

    def _scan_player_passing(self, guild_id: int) -> list[dict]:
        events: list[dict] = []
        cols = self.db.get_table_columns("player_passing_stats")
        if not cols:
            return events

        yds_col = _safe_col(self.db.pick_column("player_passing_stats", ["pass_yds", "pass_yards", "passing_yards"]))
        player_col = _safe_col(self.db.pick_column("player_passing_stats", ["player_name", "full_name", "name"]))
        game_col = _safe_col(self.db.pick_column("player_passing_stats", ["game_id", "schedule_id"]))

        if not yds_col:
            return events

        try:
            with self.db._conn() as conn:
                with conn.cursor() as cur:
                    select_cols = ", ".join(_safe_cols("id", yds_col, player_col, game_col))
                    cur.execute(
                        f"SELECT {select_cols} FROM player_passing_stats WHERE {yds_col} >= 350 ORDER BY {yds_col} DESC LIMIT 5"
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            print(f"[ContentPipeline] player_passing_stats scan error: {exc}")
            return events

        for row in rows:
            row_id = str(row.get("id", ""))
            player = str(row.get(player_col) or "Player") if player_col else "Player"
            yds = int(row.get(yds_col) or 0)
            source_id = f"passing_{row_id}"
            if not self.db.has_recent_event(guild_id, "high_passing_game", source_id, hours=24):
                events.append({
                    "event_type": "high_passing_game",
                    "source_type": "player_passing_stats",
                    "source_id": source_id,
                    "priority_score": 65,
                    "metadata": {"player": player, "yards": yds, "stat": "passing"},
                })
        return events

    def _scan_player_rushing(self, guild_id: int) -> list[dict]:
        events: list[dict] = []
        cols = self.db.get_table_columns("player_rushing_stats")
        if not cols:
            return events

        yds_col = _safe_col(self.db.pick_column("player_rushing_stats", ["rush_yds", "rush_yards", "rushing_yards"]))
        player_col = _safe_col(self.db.pick_column("player_rushing_stats", ["player_name", "full_name", "name"]))

        if not yds_col:
            return events

        try:
            with self.db._conn() as conn:
                with conn.cursor() as cur:
                    select_cols = ", ".join(_safe_cols("id", yds_col, player_col))
                    cur.execute(
                        f"SELECT {select_cols} FROM player_rushing_stats WHERE {yds_col} >= 150 ORDER BY {yds_col} DESC LIMIT 5"
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            print(f"[ContentPipeline] player_rushing_stats scan error: {exc}")
            return events

        for row in rows:
            row_id = str(row.get("id", ""))
            player = str(row.get(player_col) or "Player") if player_col else "Player"
            yds = int(row.get(yds_col) or 0)
            source_id = f"rushing_{row_id}"
            if not self.db.has_recent_event(guild_id, "high_rushing_game", source_id, hours=24):
                events.append({
                    "event_type": "high_rushing_game",
                    "source_type": "player_rushing_stats",
                    "source_id": source_id,
                    "priority_score": 60,
                    "metadata": {"player": player, "yards": yds, "stat": "rushing"},
                })
        return events

    def _scan_player_receiving(self, guild_id: int) -> list[dict]:
        events: list[dict] = []
        cols = self.db.get_table_columns("player_receiving_stats")
        if not cols:
            return events

        yds_col = _safe_col(self.db.pick_column("player_receiving_stats", ["rec_yds", "rec_yards", "receiving_yards"]))
        player_col = _safe_col(self.db.pick_column("player_receiving_stats", ["player_name", "full_name", "name"]))

        if not yds_col:
            return events

        try:
            with self.db._conn() as conn:
                with conn.cursor() as cur:
                    select_cols = ", ".join(_safe_cols("id", yds_col, player_col))
                    cur.execute(
                        f"SELECT {select_cols} FROM player_receiving_stats WHERE {yds_col} >= 150 ORDER BY {yds_col} DESC LIMIT 5"
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            print(f"[ContentPipeline] player_receiving_stats scan error: {exc}")
            return events

        for row in rows:
            row_id = str(row.get("id", ""))
            player = str(row.get(player_col) or "Player") if player_col else "Player"
            yds = int(row.get(yds_col) or 0)
            source_id = f"receiving_{row_id}"
            if not self.db.has_recent_event(guild_id, "high_receiving_game", source_id, hours=24):
                events.append({
                    "event_type": "high_receiving_game",
                    "source_type": "player_receiving_stats",
                    "source_id": source_id,
                    "priority_score": 55,
                    "metadata": {"player": player, "yards": yds, "stat": "receiving"},
                })
        return events

    def _scan_player_defense(self, guild_id: int) -> list[dict]:
        events: list[dict] = []
        cols = self.db.get_table_columns("player_defense_stats")
        if not cols:
            return events

        sacks_col = _safe_col(self.db.pick_column("player_defense_stats", ["sacks", "def_sacks"]))
        ints_col = _safe_col(self.db.pick_column("player_defense_stats", ["ints", "interceptions", "def_ints"]))
        player_col = _safe_col(self.db.pick_column("player_defense_stats", ["player_name", "full_name", "name"]))

        if not sacks_col and not ints_col:
            return events

        try:
            with self.db._conn() as conn:
                with conn.cursor() as cur:
                    conditions = []
                    if sacks_col:
                        conditions.append(f"{sacks_col} >= 3")
                    if ints_col:
                        conditions.append(f"{ints_col} >= 2")
                    where_clause = " OR ".join(conditions)
                    select_cols = ", ".join(_safe_cols("id", sacks_col, ints_col, player_col))
                    cur.execute(
                        f"SELECT {select_cols} FROM player_defense_stats WHERE {where_clause} ORDER BY id DESC LIMIT 5"
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            print(f"[ContentPipeline] player_defense_stats scan error: {exc}")
            return events

        for row in rows:
            row_id = str(row.get("id", ""))
            player = str(row.get(player_col) or "Player") if player_col else "Player"
            sacks = int(row.get(sacks_col) or 0) if sacks_col else 0
            ints = int(row.get(ints_col) or 0) if ints_col else 0
            source_id = f"defense_{row_id}"
            if not self.db.has_recent_event(guild_id, "high_defense_game", source_id, hours=24):
                events.append({
                    "event_type": "high_defense_game",
                    "source_type": "player_defense_stats",
                    "source_id": source_id,
                    "priority_score": 65,
                    "metadata": {"player": player, "sacks": sacks, "interceptions": ints},
                })
        return events

    def _scan_rivalries(self, guild_id: int) -> list[dict]:
        events: list[dict] = []
        cols = self.db.get_table_columns("bot_weekly_rivalries")
        if not cols:
            return events

        try:
            with self.db._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM bot_weekly_rivalries ORDER BY id DESC LIMIT 5"
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            print(f"[ContentPipeline] bot_weekly_rivalries scan error: {exc}")
            return events

        for row in rows:
            source_id = f"rivalry_{row.get('id', '')}"
            if not self.db.has_recent_event(guild_id, "rivalry_week", source_id, hours=24):
                events.append({
                    "event_type": "rivalry_week",
                    "source_type": "bot_weekly_rivalries",
                    "source_id": source_id,
                    "priority_score": 85,
                    "metadata": dict(row),
                })
        return events

    def _scan_sportsbook(self, guild_id: int) -> list[dict]:
        events: list[dict] = []
        cols = self.db.get_table_columns("bot_sportsbook_bets")
        if not cols:
            return events

        odds_col = _safe_col(self.db.pick_column("bot_sportsbook_bets", ["odds", "payout_multiplier", "multiplier"]))
        status_col = _safe_col(self.db.pick_column("bot_sportsbook_bets", ["status", "bet_status"]))
        if not status_col:
            return events

        try:
            with self.db._conn() as conn:
                with conn.cursor() as cur:
                    select_cols = ", ".join(_safe_cols("id", odds_col, status_col))
                    if odds_col:
                        cur.execute(
                            f"SELECT {select_cols} FROM bot_sportsbook_bets "
                            f"WHERE {status_col} = 'won' AND {odds_col} >= 3 "
                            f"ORDER BY id DESC LIMIT 5"
                        )
                    else:
                        cur.execute(
                            f"SELECT {select_cols} FROM bot_sportsbook_bets "
                            f"WHERE {status_col} = 'won' "
                            f"ORDER BY id DESC LIMIT 5"
                        )
                    rows = cur.fetchall()
        except Exception as exc:
            print(f"[ContentPipeline] bot_sportsbook_bets scan error: {exc}")
            return events

        for row in rows:
            source_id = f"sportsbook_{row.get('id', '')}"
            if not self.db.has_recent_event(guild_id, "sportsbook_upset", source_id, hours=24):
                events.append({
                    "event_type": "sportsbook_upset",
                    "source_type": "bot_sportsbook_bets",
                    "source_id": source_id,
                    "priority_score": 80,
                    "metadata": dict(row),
                })
        return events

    def _scan_bounties(self, guild_id: int) -> list[dict]:
        events: list[dict] = []
        cols = self.db.get_table_columns("bot_bounties")
        if not cols:
            return events

        claimed_col = _safe_col(self.db.pick_column("bot_bounties", ["claimed_at", "completed_at", "claimed"]))
        if not claimed_col:
            return events

        try:
            with self.db._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM bot_bounties WHERE {claimed_col} IS NOT NULL ORDER BY id DESC LIMIT 5"
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            print(f"[ContentPipeline] bot_bounties scan error: {exc}")
            return events

        for row in rows:
            source_id = f"bounty_{row.get('id', '')}"
            if not self.db.has_recent_event(guild_id, "bounty_completed", source_id, hours=24):
                events.append({
                    "event_type": "bounty_completed",
                    "source_type": "bot_bounties",
                    "source_id": source_id,
                    "priority_score": 50,
                    "metadata": {k: str(v) for k, v in dict(row).items() if v is not None},
                })
        return events
