"""ContentScheduler — background loop for automated content pipeline runs."""
from __future__ import annotations

import asyncio
import os
from typing import Optional, TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from .db import ContentDB
    from .generator import ContentGenerator
    from .events import EventScanner

_INTERVAL_MINUTES = int(os.getenv("CONTENT_GENERATION_INTERVAL_MINUTES", "60"))


class ContentScheduler:
    """Background scheduler that runs the full content pipeline for each guild."""

    def __init__(
        self,
        bot: discord.Client,
        db: "ContentDB",
        generator: Optional["ContentGenerator"],
        scanner: "EventScanner",
    ):
        self.bot = bot
        self.db = db
        self.generator = generator
        self.scanner = scanner
        self._running = False

    async def start(self):
        """Start the background loop."""
        if self._running:
            return
        self._running = True
        print(f"[ContentPipeline] Scheduler started (interval: {_INTERVAL_MINUTES}m).")
        while self._running:
            await self._run_all_guilds()
            await asyncio.sleep(_INTERVAL_MINUTES * 60)

    def stop(self):
        self._running = False

    async def _run_all_guilds(self):
        raw = os.getenv("GUILD_IDS", "")
        guild_ids: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                guild_ids.append(int(part))
            except ValueError:
                print(f"[ContentPipeline] Invalid guild ID in GUILD_IDS: {part!r} — skipping.")
        for guild_id in guild_ids:
            try:
                cfg = await asyncio.to_thread(self.db.get_guild_config, guild_id)
                if not cfg.get("auto_generate_content"):
                    continue
                await self.run_pipeline(guild_id)
            except Exception as exc:
                print(f"[ContentPipeline] Pipeline error for guild {guild_id}: {exc}")

    async def run_pipeline(self, guild_id: int):
        """
        Full pipeline for one guild:
        1. Scan events via EventScanner
        2. Create content_events in DB
        3. For top N events, generate content via ContentGenerator
        4. Save as pending content_items
        5. Post review embeds to content_review_channel if configured
        """
        print(f"[ContentPipeline] Running pipeline for guild {guild_id}...")

        events = await self.scanner.scan(guild_id)
        if not events:
            print(f"[ContentPipeline] No events found for guild {guild_id}.")
            return

        print(f"[ContentPipeline] Found {len(events)} events for guild {guild_id}.")

        for event in events[:5]:
            try:
                event_id = await asyncio.to_thread(
                    self.db.create_content_event,
                    guild_id,
                    event["event_type"],
                    event["source_type"],
                    event["source_id"],
                    event["priority_score"],
                    event.get("metadata"),
                )

                if self.generator:
                    api_key = await asyncio.to_thread(
                        self.db.get_openai_key,
                        guild_id,
                        os.getenv("OPENAI_API_KEY", ""),
                    )
                    if api_key and api_key != self.generator.api_key:
                        from .generator import ContentGenerator
                        gen = ContentGenerator(api_key, self.generator.model)
                    else:
                        gen = self.generator

                    platform = "discord"
                    content = await gen.generate(
                        content_type=event["event_type"],
                        platform=platform,
                        context_data=event.get("metadata") or {},
                    )

                    item_id = await asyncio.to_thread(
                        self.db.create_content_item,
                        guild_id,
                        event["event_type"],
                        platform,
                        content.get("title", ""),
                        content.get("body", ""),
                        content.get("caption", ""),
                        content.get("hashtags", ""),
                        content.get("hook", ""),
                        content.get("voiceover", ""),
                        content.get("on_screen_text", ""),
                        content.get("clip_instructions", ""),
                        content.get("cta", ""),
                        content.get("source_summary", ""),
                        event["source_type"],
                        event["source_id"],
                        None,
                        event.get("metadata"),
                    )

                    await asyncio.to_thread(self.db.mark_event_processed, event_id)

                    # Fetch item and post review embed
                    item = await asyncio.to_thread(self.db.get_content_item, item_id)
                    if item:
                        await self._post_review_embed(guild_id, item)

                    print(f"[ContentPipeline] Created content item {item_id} for guild {guild_id} ({event['event_type']}).")
                else:
                    await asyncio.to_thread(self.db.mark_event_processed, event_id)
                    print(f"[ContentPipeline] No generator — event {event_id} saved but no content created.")

            except Exception as exc:
                print(f"[ContentPipeline] Error processing event {event.get('event_type')} for guild {guild_id}: {exc}")

    async def _post_review_embed(self, guild_id: int, item: dict):
        """Post a review embed to the content_review_channel_id channel."""
        channel_id = await asyncio.to_thread(self.db.get_review_channel_id, guild_id)
        if not channel_id:
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as exc:
                print(f"[ContentPipeline] Could not fetch review channel {channel_id}: {exc}")
                return

        from .views import ContentReviewView, _build_item_embed
        embed = _build_item_embed(item)
        view = ContentReviewView(
            item_id=int(item["id"]),
            db=self.db,
            bot=self.bot,
            generator=self.generator,
        )

        try:
            msg = await channel.send(embed=embed, view=view)
            await asyncio.to_thread(
                self.db.update_content_status,
                int(item["id"]),
                "pending",
                review_message_id=msg.id,
                review_channel_id=channel_id,
            )
        except Exception as exc:
            print(f"[ContentPipeline] Failed to post review embed for item {item['id']}: {exc}")
