"""ContentDB — synchronous psycopg3 database layer for the Content Pipeline."""
from __future__ import annotations

import json
import os
import re
from typing import Optional

import psycopg
from psycopg.rows import dict_row

# Only allow column names that consist of alphanumeric characters and underscores
_VALID_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _safe_ident(name: Optional[str]) -> Optional[str]:
    """Return name only if it is a safe SQL identifier, else None."""
    if name and _VALID_IDENT.match(name):
        return name
    return None


class ContentDB:
    """Synchronous psycopg3 database class for content pipeline tables."""

    def __init__(self, database_url: str):
        if not database_url:
            raise RuntimeError("DATABASE_URL is not set.")
        self.database_url = database_url

    def _conn(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def ensure_tables(self):
        """Run the full migration SQL to create/update all required tables."""
        migration_path = os.path.join(os.path.dirname(__file__), "migration.sql")
        with open(migration_path, "r", encoding="utf-8") as fh:
            migration_sql = fh.read()

        # Split on semicolons to execute each statement individually
        statements = [s.strip() for s in migration_sql.split(";") if s.strip()]
        with self._conn() as conn:
            with conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)
            conn.commit()
        print("[ContentPipeline] Database tables ensured.")

    # ------------------------------------------------------------------
    # Content Items
    # ------------------------------------------------------------------

    def create_content_item(
        self,
        guild_id: int,
        content_type: str,
        platform: str,
        title: str,
        body: str,
        caption: str,
        hashtags: str,
        hook: str,
        voiceover: str,
        on_screen_text: str,
        clip_instructions: str,
        cta: str,
        source_summary: str,
        source_type: str = "",
        source_id: str = "",
        created_by: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> int:
        meta = json.dumps(metadata or {})
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO content_items (
                        guild_id, content_type, platform, title, body,
                        caption, hashtags, hook, voiceover, on_screen_text,
                        clip_instructions, cta, source_summary,
                        source_type, source_id, created_by, metadata
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s
                    ) RETURNING id
                    """,
                    (
                        int(guild_id), content_type, platform, title, body,
                        caption, hashtags, hook, voiceover, on_screen_text,
                        clip_instructions, cta, source_summary,
                        source_type, source_id, created_by, meta,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return int(row["id"])

    def get_content_item(self, item_id: int) -> Optional[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM content_items WHERE id = %s",
                    (int(item_id),),
                )
                return cur.fetchone()

    def list_content_items(
        self,
        guild_id: int,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                if status:
                    cur.execute(
                        """
                        SELECT * FROM content_items
                        WHERE guild_id = %s AND status = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (int(guild_id), status, int(limit)),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM content_items
                        WHERE guild_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (int(guild_id), int(limit)),
                    )
                return cur.fetchall()

    def update_content_status(
        self,
        item_id: int,
        status: str,
        approved_by: Optional[int] = None,
        review_message_id: Optional[int] = None,
        review_channel_id: Optional[int] = None,
    ):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE content_items
                    SET status = %s,
                        approved_by = COALESCE(%s, approved_by),
                        approved_at = CASE WHEN %s = 'approved' THEN NOW() ELSE approved_at END,
                        review_message_id = COALESCE(%s, review_message_id),
                        review_channel_id = COALESCE(%s, review_channel_id)
                    WHERE id = %s
                    """,
                    (
                        status,
                        approved_by,
                        status,
                        review_message_id,
                        review_channel_id,
                        int(item_id),
                    ),
                )
            conn.commit()

    def mark_content_posted(self, item_id: int):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE content_items SET status = 'posted', posted_at = NOW() WHERE id = %s",
                    (int(item_id),),
                )
            conn.commit()

    def delete_content_item(self, item_id: int):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM content_items WHERE id = %s", (int(item_id),))
            conn.commit()

    # ------------------------------------------------------------------
    # Content Events
    # ------------------------------------------------------------------

    def create_content_event(
        self,
        guild_id: int,
        event_type: str,
        source_type: str,
        source_id: str,
        priority_score: int,
        metadata: Optional[dict] = None,
    ) -> int:
        meta = json.dumps(metadata or {})
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO content_events (
                        guild_id, event_type, source_type, source_id,
                        priority_score, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (int(guild_id), event_type, source_type, source_id, int(priority_score), meta),
                )
                row = cur.fetchone()
            conn.commit()
        return int(row["id"])

    def list_unprocessed_events(self, guild_id: int, limit: int = 10) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM content_events
                    WHERE guild_id = %s AND processed = FALSE
                    ORDER BY priority_score DESC, created_at DESC
                    LIMIT %s
                    """,
                    (int(guild_id), int(limit)),
                )
                return cur.fetchall()

    def mark_event_processed(self, event_id: int):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE content_events SET processed = TRUE WHERE id = %s",
                    (int(event_id),),
                )
            conn.commit()

    def has_recent_event(
        self,
        guild_id: int,
        event_type: str,
        source_id: str,
        hours: int = 24,
    ) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM content_events
                    WHERE guild_id = %s
                      AND event_type = %s
                      AND source_id = %s
                      AND created_at >= NOW() - INTERVAL '1 hour' * %s
                    LIMIT 1
                    """,
                    (int(guild_id), event_type, source_id, int(hours)),
                )
                return cur.fetchone() is not None

    # ------------------------------------------------------------------
    # Recruiting Posts
    # ------------------------------------------------------------------

    def create_recruiting_post(
        self,
        guild_id: int,
        platform: str,
        title: str,
        body: str,
        short_caption: str,
        hashtags: str,
        metadata: Optional[dict] = None,
    ) -> int:
        meta = json.dumps(metadata or {})
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO recruiting_posts (
                        guild_id, platform, title, body,
                        short_caption, hashtags, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (int(guild_id), platform, title, body, short_caption, hashtags, meta),
                )
                row = cur.fetchone()
            conn.commit()
        return int(row["id"])

    def list_recruiting_posts(
        self,
        guild_id: int,
        status: Optional[str] = None,
    ) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                if status:
                    cur.execute(
                        """
                        SELECT * FROM recruiting_posts
                        WHERE guild_id = %s AND status = %s
                        ORDER BY created_at DESC
                        """,
                        (int(guild_id), status),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM recruiting_posts WHERE guild_id = %s ORDER BY created_at DESC",
                        (int(guild_id),),
                    )
                return cur.fetchall()

    def update_recruiting_post_status(self, post_id: int, status: str):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE recruiting_posts
                    SET status = %s,
                        posted_at = CASE WHEN %s = 'posted' THEN NOW() ELSE posted_at END
                    WHERE id = %s
                    """,
                    (status, status, int(post_id)),
                )
            conn.commit()

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def get_template(self, guild_id: int, template_name: str) -> Optional[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM content_templates
                    WHERE guild_id = %s AND template_name = %s
                    """,
                    (int(guild_id), template_name),
                )
                return cur.fetchone()

    def list_templates(self, guild_id: int) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM content_templates WHERE guild_id = %s ORDER BY template_name",
                    (int(guild_id),),
                )
                return cur.fetchall()

    def upsert_template(
        self,
        guild_id: int,
        template_name: str,
        content_type: str,
        platform: str,
        prompt_template: str,
        enabled: bool = True,
    ):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO content_templates (
                        guild_id, template_name, content_type, platform,
                        prompt_template, enabled
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (guild_id, template_name) DO UPDATE
                    SET content_type = EXCLUDED.content_type,
                        platform = EXCLUDED.platform,
                        prompt_template = EXCLUDED.prompt_template,
                        enabled = EXCLUDED.enabled,
                        updated_at = NOW()
                    """,
                    (int(guild_id), template_name, content_type, platform, prompt_template, enabled),
                )
            conn.commit()

    # ------------------------------------------------------------------
    # Schema inspection (defensive SQL)
    # ------------------------------------------------------------------

    def get_table_columns(self, table_name: str) -> set[str]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    """,
                    (table_name,),
                )
                return {str(row["column_name"]) for row in cur.fetchall()}

    def pick_column(self, table_name: str, candidates: list[str]) -> Optional[str]:
        cols = self.get_table_columns(table_name)
        for candidate in candidates:
            if candidate in cols:
                return candidate
        return None

    # ------------------------------------------------------------------
    # Guild config helpers
    # ------------------------------------------------------------------

    def get_guild_config(self, guild_id: int) -> dict:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM guild_config WHERE guild_id = %s", (int(guild_id),))
                row = cur.fetchone()
        return dict(row) if row else {}

    def get_openai_key(self, guild_id: int, env_fallback: str = "") -> str:
        cfg = self.get_guild_config(guild_id)
        return str(cfg.get("openai_api_key") or env_fallback or "")

    def get_review_channel_id(self, guild_id: int) -> int:
        cfg = self.get_guild_config(guild_id)
        try:
            return int(cfg.get("content_review_channel_id") or 0)
        except (TypeError, ValueError):
            return 0

    def get_recruit_channel_id(self, guild_id: int) -> int:
        cfg = self.get_guild_config(guild_id)
        try:
            return int(cfg.get("recruit_channel_id") or 0)
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # Season-leader queries (defensive — handles missing tables/columns)
    # ------------------------------------------------------------------

    def get_current_season_index(self) -> Optional[int]:
        """
        Detect the current season_index by taking MAX(season_index) from available tables.
        Checks games first, then standings, then passing/rushing stat tables.
        Returns None if no season_index column is found in any table.
        """
        # All table names are literals here; _safe_ident used as an extra safety guard.
        for table in ("games", "standings", "player_passing_stats", "player_rushing_stats"):
            safe_table = _safe_ident(table)
            if not safe_table:
                continue
            cols = self.get_table_columns(safe_table)
            if "season_index" not in cols:
                continue
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"SELECT MAX(season_index) AS si FROM {safe_table}")  # noqa: S608
                        row = cur.fetchone()
                        if row and row.get("si") is not None:
                            return int(row["si"])
            except Exception as exc:
                print(f"[ContentPipeline] get_current_season_index from {safe_table}: {exc}")
        return None

    def _get_season_leaders(
        self,
        table: str,
        yards_candidates: list[str],
        td_candidates: list[str],
        extra_candidates: list[str],
        extra_label: str,
        season_index: Optional[int],
        limit: int = 5,
    ) -> list[dict]:
        """
        Generic helper: aggregate season-to-date leaders from *table*.
        Returns a list of dicts with player, team, yards, td (optional), extra (optional).
        Skips gracefully if the table or key columns are absent.

        All identifiers (table name, column names) are validated through _safe_ident
        before being interpolated into the query.  Only the season_index parameter
        is passed as a proper query parameter (%s) to prevent SQL injection.
        """
        safe_table = _safe_ident(table)
        if not safe_table:
            print(f"[ContentPipeline] _get_season_leaders: unsafe table name '{table}' — skipping.")
            return []

        cols = self.get_table_columns(safe_table)
        if not cols:
            return []

        yds_col = _safe_ident(self.pick_column(safe_table, yards_candidates))
        player_col = _safe_ident(
            self.pick_column(safe_table, ["player_name", "full_name", "name", "player_full_name"])
        )
        team_col = _safe_ident(
            self.pick_column(safe_table, ["team_name", "team", "club_name", "team_abbr"])
        )
        td_col = _safe_ident(self.pick_column(safe_table, td_candidates)) if td_candidates else None
        extra_col = _safe_ident(self.pick_column(safe_table, extra_candidates)) if extra_candidates else None
        season_col = _safe_ident("season_index") if "season_index" in cols else None
        player_id_col = _safe_ident(
            self.pick_column(safe_table, ["roster_id", "player_id", "playerId", "rosterId"])
        )

        if not yds_col or not player_col:
            print(f"[ContentPipeline] {safe_table}: required columns (yards/player) not found — skipping season leaders.")
            return []

        # Build GROUP BY — include player_id for uniqueness when available
        group_cols = [player_col]
        if player_id_col:
            group_cols.insert(0, player_id_col)

        # All identifiers here have been validated by _safe_ident above.
        select_parts = [f"MAX({player_col}) AS player"]
        if team_col:
            select_parts.append(f"MAX({team_col}) AS team")
        select_parts.append(f"SUM({yds_col}) AS total_yards")
        if td_col:
            select_parts.append(f"SUM({td_col}) AS total_tds")
        if extra_col:
            # extra_label is a fixed string supplied by internal callers only.
            safe_extra_label = _safe_ident(extra_label) or "total_extra"
            select_parts.append(f"SUM({extra_col}) AS {safe_extra_label}")

        select_clause = ", ".join(select_parts)
        group_clause = ", ".join(group_cols)

        # Use a parameterized placeholder for season_index to follow SQL best practices.
        if season_col and season_index is not None:
            where_clause = f"WHERE {season_col} = %s"
            params: tuple = (int(season_index), int(limit))
        else:
            where_clause = ""
            params = (int(limit),)

        query = (
            f"SELECT {select_clause} FROM {safe_table} "
            f"{where_clause} "
            f"GROUP BY {group_clause} "
            f"ORDER BY total_yards DESC NULLS LAST "
            f"LIMIT %s"
        )

        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            print(f"[ContentPipeline] {safe_table} season leaders query error: {exc}")
            return []

    def get_season_passing_leaders(self, season_index: Optional[int], limit: int = 5) -> list[dict]:
        """Season-to-date passing yards leaders."""
        return self._get_season_leaders(
            table="player_passing_stats",
            yards_candidates=["pass_yds", "pass_yards", "passing_yards", "passYds"],
            td_candidates=["pass_td", "pass_tds", "passing_tds", "pass_touchdowns", "passTDs"],
            extra_candidates=["ints", "interceptions", "pass_ints", "passInts"],
            extra_label="total_ints",
            season_index=season_index,
            limit=limit,
        )

    def get_season_rushing_leaders(self, season_index: Optional[int], limit: int = 5) -> list[dict]:
        """Season-to-date rushing yards leaders."""
        return self._get_season_leaders(
            table="player_rushing_stats",
            yards_candidates=["rush_yds", "rush_yards", "rushing_yards", "rushYds"],
            td_candidates=["rush_td", "rush_tds", "rushing_tds", "rush_touchdowns", "rushTDs"],
            extra_candidates=["rush_att", "rush_attempts", "carries", "rushAtt"],
            extra_label="total_carries",
            season_index=season_index,
            limit=limit,
        )

    def get_season_receiving_leaders(self, season_index: Optional[int], limit: int = 5) -> list[dict]:
        """Season-to-date receiving yards leaders."""
        return self._get_season_leaders(
            table="player_receiving_stats",
            yards_candidates=["rec_yds", "rec_yards", "receiving_yards", "recYds"],
            td_candidates=["rec_td", "rec_tds", "receiving_tds", "rec_touchdowns", "recTDs"],
            extra_candidates=["receptions", "catches", "recs", "rec"],
            extra_label="total_receptions",
            season_index=season_index,
            limit=limit,
        )

    def get_season_defense_leaders_sacks(self, season_index: Optional[int], limit: int = 5) -> list[dict]:
        """Season-to-date sacks leaders."""
        return self._get_season_leaders(
            table="player_defense_stats",
            yards_candidates=["sacks", "def_sacks", "sacksForLoss"],
            td_candidates=[],
            extra_candidates=["tackles", "total_tackles", "def_tackles"],
            extra_label="total_tackles",
            season_index=season_index,
            limit=limit,
        )

    def get_season_defense_leaders_ints(self, season_index: Optional[int], limit: int = 5) -> list[dict]:
        """Season-to-date interceptions leaders."""
        return self._get_season_leaders(
            table="player_defense_stats",
            yards_candidates=["ints", "interceptions", "def_ints", "defInts"],
            td_candidates=["int_td", "int_tds", "def_int_tds"],
            extra_candidates=["sacks", "def_sacks"],
            extra_label="total_sacks",
            season_index=season_index,
            limit=limit,
        )
