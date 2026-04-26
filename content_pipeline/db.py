"""ContentDB — synchronous psycopg3 database layer for the Content Pipeline."""
from __future__ import annotations

import json
import os
from typing import Optional

import psycopg
from psycopg.rows import dict_row


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
                      AND created_at >= NOW() - INTERVAL '%s hours'
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
