"""ContentPipelineCog — Discord slash commands for the Content Pipeline."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Optional, TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from .db import ContentDB
    from .generator import ContentGenerator
    from .events import EventScanner
    from .scheduler import ContentScheduler

from .views import ContentReviewView, _build_item_embed


def _parse_role_names(raw: str | None) -> set[str]:
    names = [item.strip() for item in (raw or "").split(",") if item.strip()]
    return set(names) if names else {"Commissioner", "Admin", "COMMISH"}


def _is_admin(interaction: discord.Interaction, db: "ContentDB") -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    guild_id = int(interaction.guild_id or 0)
    try:
        cfg = db.get_guild_config(guild_id)
        admin_role_names = _parse_role_names(str(cfg.get("admin_role_names") or ""))
    except Exception:
        admin_role_names = {"Commissioner", "Admin", "COMMISH"}
    return any(role.name in admin_role_names for role in interaction.user.roles)


def _admin_check(db: "ContentDB"):
    async def predicate(interaction: discord.Interaction) -> bool:
        if _is_admin(interaction, db):
            return True
        raise app_commands.CheckFailure(
            "❌ You need the Commissioner or Admin role to use this command."
        )
    return app_commands.check(predicate)


CONTENT_TYPE_CHOICES = [
    app_commands.Choice(name="Game of the Week Hype", value="gotw_hype"),
    app_commands.Choice(name="Postgame Recap", value="postgame_recap"),
    app_commands.Choice(name="Upset Alert", value="upset_alert"),
    app_commands.Choice(name="Blowout Win", value="blowout_win"),
    app_commands.Choice(name="Rivalry Week", value="rivalry_week"),
    app_commands.Choice(name="Sportsbook Preview", value="sportsbook_preview"),
    app_commands.Choice(name="Token Economy Promo", value="token_economy_promo"),
    app_commands.Choice(name="Player Spotlight", value="player_spotlight"),
    app_commands.Choice(name="MVP Race", value="mvp_race"),
    app_commands.Choice(name="Playoff Race", value="playoff_race"),
    app_commands.Choice(name="Open Team Recruiting", value="open_team_recruiting"),
    app_commands.Choice(name="Waitlist Recruiting", value="waitlist_recruiting"),
    app_commands.Choice(name="Weekly News", value="weekly_news"),
    app_commands.Choice(name="TikTok Script", value="tiktok_script"),
    app_commands.Choice(name="Commissioner Announcement", value="commissioner_announcement"),
]

PLATFORM_CHOICES = [
    app_commands.Choice(name="Discord", value="discord"),
    app_commands.Choice(name="TikTok", value="tiktok"),
    app_commands.Choice(name="Instagram", value="instagram"),
    app_commands.Choice(name="YouTube Shorts", value="youtube_shorts"),
]

STATUS_CHOICES = [
    app_commands.Choice(name="Pending", value="pending"),
    app_commands.Choice(name="Approved", value="approved"),
    app_commands.Choice(name="Rejected", value="rejected"),
    app_commands.Choice(name="Posted", value="posted"),
]

TIKTOK_EVENT_CHOICES = [
    app_commands.Choice(name="Upset Alert", value="upset_alert"),
    app_commands.Choice(name="Blowout Win", value="blowout_win"),
    app_commands.Choice(name="Game of the Week Hype", value="gotw_hype"),
    app_commands.Choice(name="Player Spotlight", value="player_spotlight"),
    app_commands.Choice(name="Recruiting", value="open_team_recruiting"),
]

RECRUIT_POST_CHOICES = [
    app_commands.Choice(name="Open Team", value="open_team"),
    app_commands.Choice(name="Waitlist", value="waitlist"),
    app_commands.Choice(name="Token Economy", value="token_economy"),
    app_commands.Choice(name="Sportsbook", value="sportsbook"),
    app_commands.Choice(name="Weekly Media", value="weekly_media"),
    app_commands.Choice(name="General Ad", value="general_ad"),
]


class ContentPipelineCog(commands.Cog, name="ContentPipeline"):
    """Cog providing all Content Pipeline slash commands."""

    def __init__(
        self,
        bot: discord.Client,
        db: "ContentDB",
        generator: Optional["ContentGenerator"],
        scanner: "EventScanner",
        scheduler: "ContentScheduler",
    ):
        self.bot = bot
        self.db = db
        self.generator = generator
        self.scanner = scanner
        self.scheduler = scheduler

    def _guild_id(self, interaction: discord.Interaction) -> int:
        return int(interaction.guild_id or (interaction.guild.id if interaction.guild else 0) or 0)

    def _get_generator(self, guild_id: int) -> Optional["ContentGenerator"]:
        """Return a generator with the best available API key for this guild."""
        from .generator import ContentGenerator
        api_key = self.db.get_openai_key(guild_id, os.getenv("OPENAI_API_KEY", ""))
        if not api_key:
            return None
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        if self.generator and self.generator.api_key == api_key:
            return self.generator
        return ContentGenerator(api_key, model)

    # ------------------------------------------------------------------
    # /content_generate
    # ------------------------------------------------------------------

    @app_commands.command(
        name="content_generate",
        description="Admin: Generate content for a specific type and platform.",
    )
    @app_commands.describe(
        content_type="Type of content to generate",
        platform="Target platform",
    )
    @app_commands.choices(content_type=CONTENT_TYPE_CHOICES, platform=PLATFORM_CHOICES)
    async def content_generate(
        self,
        interaction: discord.Interaction,
        content_type: app_commands.Choice[str],
        platform: app_commands.Choice[str] = None,
    ):
        if not _is_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild_id = self._guild_id(interaction)
        plat = platform.value if platform else "discord"

        gen = await asyncio.to_thread(self._get_generator, guild_id)
        if not gen:
            await interaction.followup.send(
                "⚠️ No OpenAI key configured. Set `openai_api_key` in guild settings or set "
                "`OPENAI_API_KEY` environment variable.",
                ephemeral=True,
            )
            return

        # Gather some context data from scanner
        events = await self.scanner.scan(guild_id)
        context_data: dict = {}
        for ev in events:
            if ev["event_type"] == content_type.value:
                context_data = ev.get("metadata") or {}
                break
        if not context_data:
            context_data = {"content_type": content_type.value, "platform": plat, "guild_id": guild_id}

        try:
            content = await gen.generate(
                content_type=content_type.value,
                platform=plat,
                context_data=context_data,
            )
        except Exception as exc:
            await interaction.followup.send(f"❌ Generation failed: {exc}", ephemeral=True)
            return

        item_id = await asyncio.to_thread(
            self.db.create_content_item,
            guild_id,
            content_type.value,
            plat,
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
            "",
            "",
            int(interaction.user.id),
            context_data,
        )

        item = await asyncio.to_thread(self.db.get_content_item, item_id)
        if not item:
            await interaction.followup.send(f"✅ Content item #{item_id} created.", ephemeral=True)
            return

        embed = _build_item_embed(item)
        view = ContentReviewView(item_id, self.db, self.bot, gen)
        await self.scheduler._post_review_embed(guild_id, item)
        await interaction.followup.send(
            f"✅ Content item **#{item_id}** created and posted to review channel.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /content_queue
    # ------------------------------------------------------------------

    @app_commands.command(
        name="content_queue",
        description="Admin: Show content items queue by status.",
    )
    @app_commands.describe(status="Filter by status (default: pending)")
    @app_commands.choices(status=STATUS_CHOICES)
    async def content_queue(
        self,
        interaction: discord.Interaction,
        status: app_commands.Choice[str] = None,
    ):
        if not _is_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild_id = self._guild_id(interaction)
        status_val = status.value if status else "pending"

        items = await asyncio.to_thread(
            self.db.list_content_items, guild_id, status_val, 20
        )

        if not items:
            await interaction.followup.send(
                f"📭 No content items with status `{status_val}`.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"📋 Content Queue — {status_val.upper()}",
            color=0x5865F2,
            description=f"Showing up to 20 `{status_val}` items",
        )

        for item in items[:20]:
            title_str = str(item.get("title") or "Untitled")[:60]
            ct = str(item.get("content_type") or "")
            plat = str(item.get("platform") or "discord")
            embed.add_field(
                name=f"#{item['id']} — {ct}",
                value=f"**{title_str}**\nPlatform: `{plat}` | Status: `{item.get('status', '?')}`",
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /content_review
    # ------------------------------------------------------------------

    @app_commands.command(
        name="content_review",
        description="Admin: Review a specific content item with approval buttons.",
    )
    @app_commands.describe(item_id="Content item ID to review")
    async def content_review(self, interaction: discord.Interaction, item_id: int):
        if not _is_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild_id = self._guild_id(interaction)

        gen = await asyncio.to_thread(self._get_generator, guild_id)
        item = await asyncio.to_thread(self.db.get_content_item, item_id)

        if not item:
            await interaction.followup.send(f"❌ Content item #{item_id} not found.", ephemeral=True)
            return

        embed = _build_item_embed(item)

        # Show all text fields in detail
        for field_name, label in [
            ("on_screen_text", "📱 On-Screen Text"),
            ("clip_instructions", "🎬 Clip Instructions"),
            ("source_summary", "📄 Source Summary"),
        ]:
            val = str(item.get(field_name) or "")
            if val:
                embed.add_field(name=label, value=val[:512], inline=False)

        view = ContentReviewView(item_id, self.db, self.bot, gen)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ------------------------------------------------------------------
    # /content_approve
    # ------------------------------------------------------------------

    @app_commands.command(
        name="content_approve",
        description="Admin: Approve a content item by ID.",
    )
    @app_commands.describe(item_id="Content item ID to approve")
    async def content_approve(self, interaction: discord.Interaction, item_id: int):
        if not _is_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await asyncio.to_thread(
            self.db.update_content_status,
            item_id,
            "approved",
            approved_by=int(interaction.user.id),
        )
        await interaction.followup.send(f"✅ Content item **#{item_id}** approved.", ephemeral=True)

    # ------------------------------------------------------------------
    # /content_reject
    # ------------------------------------------------------------------

    @app_commands.command(
        name="content_reject",
        description="Admin: Reject a content item by ID.",
    )
    @app_commands.describe(item_id="Content item ID to reject", reason="Optional rejection reason")
    async def content_reject(
        self,
        interaction: discord.Interaction,
        item_id: int,
        reason: str = "",
    ):
        if not _is_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await asyncio.to_thread(self.db.update_content_status, item_id, "rejected")
        msg = f"❌ Content item **#{item_id}** rejected."
        if reason:
            msg += f"\n**Reason:** {reason}"
        await interaction.followup.send(msg, ephemeral=True)

    # ------------------------------------------------------------------
    # /content_regenerate
    # ------------------------------------------------------------------

    @app_commands.command(
        name="content_regenerate",
        description="Admin: Regenerate a content item using the same event context.",
    )
    @app_commands.describe(item_id="Content item ID to regenerate")
    async def content_regenerate(self, interaction: discord.Interaction, item_id: int):
        if not _is_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild_id = self._guild_id(interaction)

        gen = await asyncio.to_thread(self._get_generator, guild_id)
        if not gen:
            await interaction.followup.send(
                "⚠️ No OpenAI key configured for this guild.", ephemeral=True
            )
            return

        item = await asyncio.to_thread(self.db.get_content_item, item_id)
        if not item:
            await interaction.followup.send(f"❌ Content item #{item_id} not found.", ephemeral=True)
            return

        await asyncio.to_thread(self.db.update_content_status, item_id, "regenerating")

        meta = item.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

        try:
            new_content = await gen.generate(
                content_type=str(item.get("content_type") or ""),
                platform=str(item.get("platform") or "discord"),
                context_data=meta,
            )

            with self.db._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE content_items
                        SET title = %s, body = %s, caption = %s, hashtags = %s,
                            hook = %s, voiceover = %s, on_screen_text = %s,
                            clip_instructions = %s, cta = %s, source_summary = %s,
                            status = 'pending'
                        WHERE id = %s
                        """,
                        (
                            new_content.get("title", ""),
                            new_content.get("body", ""),
                            new_content.get("caption", ""),
                            new_content.get("hashtags", ""),
                            new_content.get("hook", ""),
                            new_content.get("voiceover", ""),
                            new_content.get("on_screen_text", ""),
                            new_content.get("clip_instructions", ""),
                            new_content.get("cta", ""),
                            new_content.get("source_summary", ""),
                            item_id,
                        ),
                    )
                conn.commit()

            await interaction.followup.send(
                f"🔄 Content item **#{item_id}** regenerated.", ephemeral=True
            )
        except Exception as exc:
            await asyncio.to_thread(self.db.update_content_status, item_id, "pending")
            await interaction.followup.send(f"❌ Regeneration failed: {exc}", ephemeral=True)

    # ------------------------------------------------------------------
    # /content_post
    # ------------------------------------------------------------------

    @app_commands.command(
        name="content_post",
        description="Admin: Post approved content to a specific channel.",
    )
    @app_commands.describe(
        item_id="Content item ID to post",
        channel="Channel to post to",
    )
    async def content_post(
        self,
        interaction: discord.Interaction,
        item_id: int,
        channel: discord.TextChannel,
    ):
        if not _is_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        item = await asyncio.to_thread(self.db.get_content_item, item_id)
        if not item:
            await interaction.followup.send(f"❌ Content item #{item_id} not found.", ephemeral=True)
            return

        status = str(item.get("status") or "pending")
        if status not in ("approved", "posted"):
            await asyncio.to_thread(
                self.db.update_content_status,
                item_id,
                "approved",
                approved_by=int(interaction.user.id),
            )

        embed = _build_item_embed(item)
        try:
            await channel.send(embed=embed)
        except Exception as exc:
            await interaction.followup.send(f"❌ Failed to post: {exc}", ephemeral=True)
            return

        await asyncio.to_thread(self.db.mark_content_posted, item_id)
        await interaction.followup.send(
            f"📤 Content item **#{item_id}** posted to {channel.mention}.", ephemeral=True
        )

    # ------------------------------------------------------------------
    # /tiktok_generate
    # ------------------------------------------------------------------

    @app_commands.command(
        name="tiktok_generate",
        description="Admin: Generate a TikTok/Reels/Shorts script.",
    )
    @app_commands.describe(
        event_type="Type of event to script",
        context="Free-text description of what happened",
    )
    @app_commands.choices(event_type=TIKTOK_EVENT_CHOICES)
    async def tiktok_generate(
        self,
        interaction: discord.Interaction,
        event_type: app_commands.Choice[str],
        context: str,
    ):
        if not _is_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild_id = self._guild_id(interaction)

        gen = await asyncio.to_thread(self._get_generator, guild_id)
        if not gen:
            await interaction.followup.send(
                "⚠️ No OpenAI key configured for this guild.", ephemeral=True
            )
            return

        context_data = {"event_type": event_type.value, "context": context, "platform": "tiktok"}

        try:
            content = await gen.generate(
                content_type="tiktok_script",
                platform="tiktok",
                context_data=context_data,
            )
        except Exception as exc:
            await interaction.followup.send(f"❌ Generation failed: {exc}", ephemeral=True)
            return

        item_id = await asyncio.to_thread(
            self.db.create_content_item,
            guild_id,
            "tiktok_script",
            "tiktok",
            content.get("title", "TikTok Script"),
            content.get("body", ""),
            content.get("caption", ""),
            content.get("hashtags", ""),
            content.get("hook", ""),
            content.get("voiceover", ""),
            content.get("on_screen_text", ""),
            content.get("clip_instructions", ""),
            content.get("cta", ""),
            content.get("source_summary", ""),
            "tiktok_generate",
            "",
            int(interaction.user.id),
            context_data,
        )

        embed = discord.Embed(
            title=f"🎬 TikTok Script — {content.get('title', 'Generated Script')}",
            color=0x010101,
        )

        hook = content.get("hook", "")
        if hook:
            embed.add_field(name="🎣 Hook (0–3s)", value=hook[:512], inline=False)

        body = content.get("body", "")
        if body:
            embed.add_field(name="📖 Body (Storyline)", value=body[:512], inline=False)

        voiceover = content.get("voiceover", "")
        if voiceover:
            embed.add_field(name="🎙️ Voiceover Script", value=voiceover[:512], inline=False)

        on_screen = content.get("on_screen_text", "")
        if on_screen:
            # Try to pretty-print list
            try:
                parsed_list = json.loads(on_screen)
                if isinstance(parsed_list, list):
                    on_screen = "\n".join(f"• {line}" for line in parsed_list)
            except Exception:
                pass
            embed.add_field(name="📱 On-Screen Text", value=on_screen[:512], inline=False)

        clips = content.get("clip_instructions", "")
        if clips:
            try:
                parsed_list = json.loads(clips)
                if isinstance(parsed_list, list):
                    clips = "\n".join(f"🎥 {clip}" for clip in parsed_list)
            except Exception:
                pass
            embed.add_field(name="🎬 Clip Instructions", value=clips[:512], inline=False)

        caption = content.get("caption", "")
        if caption:
            embed.add_field(name="📸 Caption", value=caption[:512], inline=False)

        hashtags = content.get("hashtags", "")
        if hashtags:
            try:
                parsed_list = json.loads(hashtags)
                if isinstance(parsed_list, list):
                    hashtags = " ".join(parsed_list)
            except Exception:
                pass
            embed.add_field(name="# Hashtags", value=hashtags[:512], inline=False)

        cta = content.get("cta", "")
        if cta:
            embed.add_field(name="📣 CTA", value=cta[:256], inline=False)

        embed.set_footer(text=f"Item ID: #{item_id} • Save this script for TikTok/Reels/Shorts")

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /recruit_post
    # ------------------------------------------------------------------

    @app_commands.command(
        name="recruit_post",
        description="Admin: Generate a recruiting post.",
    )
    @app_commands.describe(post_type="Type of recruiting post to generate")
    @app_commands.choices(post_type=RECRUIT_POST_CHOICES)
    async def recruit_post(
        self,
        interaction: discord.Interaction,
        post_type: app_commands.Choice[str],
    ):
        if not _is_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild_id = self._guild_id(interaction)

        gen = await asyncio.to_thread(self._get_generator, guild_id)
        if not gen:
            await interaction.followup.send(
                "⚠️ No OpenAI key configured for this guild.", ephemeral=True
            )
            return

        # Map post_type to content_type
        type_map = {
            "open_team": "open_team_recruiting",
            "waitlist": "waitlist_recruiting",
            "token_economy": "token_economy_promo",
            "sportsbook": "sportsbook_preview",
            "weekly_media": "weekly_news",
            "general_ad": "open_team_recruiting",
        }
        content_type = type_map.get(post_type.value, "open_team_recruiting")
        context_data = {
            "post_type": post_type.value,
            "platform": "discord",
            "guild_id": guild_id,
        }

        try:
            content = await gen.generate(
                content_type=content_type,
                platform="discord",
                context_data=context_data,
            )
        except Exception as exc:
            await interaction.followup.send(f"❌ Generation failed: {exc}", ephemeral=True)
            return

        hashtags = content.get("hashtags", "")
        try:
            parsed = json.loads(hashtags)
            if isinstance(parsed, list):
                hashtags = " ".join(parsed)
        except Exception:
            pass

        post_id = await asyncio.to_thread(
            self.db.create_recruiting_post,
            guild_id,
            "discord",
            content.get("title", "Recruiting Post"),
            content.get("body", ""),
            content.get("caption", ""),
            hashtags,
            context_data,
        )

        embed = discord.Embed(
            title=f"📢 Recruiting Post — {content.get('title', '')}",
            description=content.get("body", ""),
            color=0x27AE60,
        )
        if content.get("caption"):
            embed.add_field(name="Caption", value=content["caption"][:512], inline=False)
        if hashtags:
            embed.add_field(name="Hashtags", value=hashtags[:512], inline=False)
        if content.get("cta"):
            embed.add_field(name="CTA", value=content["cta"][:256], inline=False)
        embed.set_footer(text=f"Post ID: #{post_id} — Use /content_post to publish")

        view = _RecruitPostView(post_id=post_id, db=self.db, bot=self.bot)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ------------------------------------------------------------------
    # /weekly_media_generate
    # ------------------------------------------------------------------

    @app_commands.command(
        name="weekly_media_generate",
        description="Admin: Generate a full weekly media package.",
    )
    async def weekly_media_generate(self, interaction: discord.Interaction):
        if not _is_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild_id = self._guild_id(interaction)

        gen = await asyncio.to_thread(self._get_generator, guild_id)
        if not gen:
            await interaction.followup.send(
                "⚠️ No OpenAI key configured for this guild.", ephemeral=True
            )
            return

        types_to_generate = [
            ("gotw_hype", "discord"),
            ("weekly_news", "discord"),
            ("player_spotlight", "discord"),
            ("open_team_recruiting", "discord"),
        ]

        created_ids = []
        base_context = {
            "guild_id": guild_id,
            "note": "Weekly media package generation",
        }

        for content_type, platform in types_to_generate:
            try:
                content = await gen.generate(
                    content_type=content_type,
                    platform=platform,
                    context_data=base_context,
                )
                item_id = await asyncio.to_thread(
                    self.db.create_content_item,
                    guild_id,
                    content_type,
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
                    "weekly_media",
                    "",
                    int(interaction.user.id),
                    base_context,
                )
                created_ids.append((content_type, item_id))

                item = await asyncio.to_thread(self.db.get_content_item, item_id)
                if item:
                    await self.scheduler._post_review_embed(guild_id, item)

            except Exception as exc:
                print(f"[ContentPipeline] Weekly media error for {content_type}: {exc}")
                created_ids.append((content_type, None))

        embed = discord.Embed(
            title="📦 Weekly Media Package Generated",
            description="The following content items have been created and sent to review:",
            color=0x5865F2,
        )

        for ct, item_id in created_ids:
            status = f"**#{item_id}**" if item_id else "❌ Failed"
            embed.add_field(
                name=ct.replace("_", " ").title(),
                value=status,
                inline=True,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)


class _RecruitPostView(discord.ui.View):
    """Simple approve/post buttons for recruiting posts."""

    def __init__(self, post_id: int, db: "ContentDB", bot: discord.Client):
        super().__init__(timeout=300)
        self.post_id = post_id
        self.db = db
        self.bot = bot

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await asyncio.to_thread(
            self.db.update_recruiting_post_status, self.post_id, "approved"
        )
        button.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Recruiting post **#{self.post_id}** approved.", view=self
        )

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await asyncio.to_thread(
            self.db.update_recruiting_post_status, self.post_id, "rejected"
        )
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(
            content=f"❌ Recruiting post **#{self.post_id}** rejected.", view=self
        )
