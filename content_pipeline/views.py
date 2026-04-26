"""Discord UI views for content review in the Content Pipeline."""
from __future__ import annotations

import asyncio
import json
from typing import Optional, TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from .db import ContentDB
    from .generator import ContentGenerator


def _parse_role_names(raw: str | None) -> set[str]:
    names = [item.strip() for item in (raw or "").split(",") if item.strip()]
    return set(names) if names else {"Commissioner", "Admin", "COMMISH"}


def _is_content_admin(interaction: discord.Interaction, db: "ContentDB") -> bool:
    """Check if the interacting user has admin/commissioner role per guild_config."""
    if not isinstance(interaction.user, discord.Member):
        return False
    guild_id = int(interaction.guild_id or 0)
    try:
        cfg = db.get_guild_config(guild_id)
        admin_role_names = _parse_role_names(str(cfg.get("admin_role_names") or ""))
    except Exception:
        admin_role_names = {"Commissioner", "Admin", "COMMISH"}
    return any(role.name in admin_role_names for role in interaction.user.roles)


def _build_item_embed(item: dict) -> discord.Embed:
    """Build a Discord embed from a content_items row."""
    status_emoji = {
        "pending": "⏳",
        "approved": "✅",
        "rejected": "❌",
        "posted": "📤",
        "regenerating": "🔄",
    }.get(str(item.get("status", "pending")), "⏳")

    color = {
        "pending": 0xFFA500,
        "approved": 0x2ECC71,
        "rejected": 0xE74C3C,
        "posted": 0x3498DB,
        "regenerating": 0x9B59B6,
    }.get(str(item.get("status", "pending")), 0xFFA500)

    title = str(item.get("title") or f"Content #{item.get('id', '?')}")
    embed = discord.Embed(
        title=f"{status_emoji} {title}",
        color=color,
    )

    content_type = str(item.get("content_type") or "")
    platform = str(item.get("platform") or "discord")
    embed.add_field(
        name="Type / Platform",
        value=f"`{content_type}` on **{platform}**",
        inline=True,
    )
    embed.add_field(
        name="Status",
        value=f"{status_emoji} **{item.get('status', 'pending').upper()}**",
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    body = str(item.get("body") or "")
    if body:
        embed.add_field(name="📝 Body", value=body[:1024], inline=False)

    hook = str(item.get("hook") or "")
    if hook:
        embed.add_field(name="🎣 Hook", value=hook[:512], inline=False)

    caption = str(item.get("caption") or "")
    if caption:
        embed.add_field(name="📸 Caption", value=caption[:512], inline=False)

    hashtags = str(item.get("hashtags") or "")
    if hashtags:
        embed.add_field(name="# Hashtags", value=hashtags[:512], inline=False)

    cta = str(item.get("cta") or "")
    if cta:
        embed.add_field(name="📣 CTA", value=cta[:512], inline=False)

    voiceover = str(item.get("voiceover") or "")
    if voiceover:
        embed.add_field(name="🎙️ Voiceover", value=voiceover[:512], inline=False)

    embed.set_footer(text=f"Item ID: {item.get('id', '?')} • Guild: {item.get('guild_id', '?')}")
    return embed


class ContentReviewView(discord.ui.View):
    """
    Persistent review view with buttons: ✅ Approve | ❌ Reject | 🔄 Regenerate | 📤 Post Now
    Admin-only interactions.
    """

    def __init__(
        self,
        item_id: int,
        db: "ContentDB",
        bot: discord.Client,
        generator: Optional["ContentGenerator"] = None,
    ):
        super().__init__(timeout=None)
        self.item_id = item_id
        self.db = db
        self.bot = bot
        self.generator = generator
        # Set custom_ids for persistence across restarts
        self.approve_btn.custom_id = f"content_approve_{item_id}"
        self.reject_btn.custom_id = f"content_reject_{item_id}"
        self.regenerate_btn.custom_id = f"content_regenerate_{item_id}"
        self.post_btn.custom_id = f"content_post_{item_id}"

    def _disable_all(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="content_approve_0")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_content_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer()

        await asyncio.to_thread(
            self.db.update_content_status,
            self.item_id,
            "approved",
            approved_by=int(interaction.user.id),
        )

        item = await asyncio.to_thread(self.db.get_content_item, self.item_id)
        if item:
            embed = _build_item_embed(item)
            embed.add_field(
                name="✅ Approved",
                value=f"Approved by {interaction.user.mention}",
                inline=False,
            )
            self._disable_all()
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger, custom_id="content_reject_0")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_content_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer()

        await asyncio.to_thread(
            self.db.update_content_status,
            self.item_id,
            "rejected",
        )

        item = await asyncio.to_thread(self.db.get_content_item, self.item_id)
        if item:
            embed = _build_item_embed(item)
            embed.add_field(
                name="❌ Rejected",
                value=f"Rejected by {interaction.user.mention}",
                inline=False,
            )
            self._disable_all()
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="🔄 Regenerate", style=discord.ButtonStyle.secondary, custom_id="content_regenerate_0")
    async def regenerate_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_content_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        if not self.generator:
            await interaction.response.send_message(
                "⚠️ Regeneration requires an OpenAI key configured in guild settings.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        item = await asyncio.to_thread(self.db.get_content_item, self.item_id)
        if not item:
            await interaction.followup.send("❌ Content item not found.", ephemeral=True)
            return

        await asyncio.to_thread(
            self.db.update_content_status, self.item_id, "regenerating"
        )

        try:
            meta = item.get("metadata") or {}
            if isinstance(meta, str):
                meta = json.loads(meta) if meta else {}

            new_content = await self.generator.generate(
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
                            self.item_id,
                        ),
                    )
                conn.commit()

            updated_item = await asyncio.to_thread(self.db.get_content_item, self.item_id)
            if updated_item:
                embed = _build_item_embed(updated_item)
                embed.add_field(
                    name="🔄 Regenerated",
                    value=f"Regenerated by {interaction.user.mention}",
                    inline=False,
                )
                await interaction.edit_original_response(embed=embed, view=self)
        except Exception as exc:
            print(f"[ContentPipeline] Regeneration error for item {self.item_id}: {exc}")
            await asyncio.to_thread(
                self.db.update_content_status, self.item_id, "pending"
            )
            await interaction.followup.send(f"❌ Regeneration failed: {exc}", ephemeral=True)

    @discord.ui.button(label="📤 Post Now", style=discord.ButtonStyle.primary, custom_id="content_post_0")
    async def post_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_content_admin(interaction, self.db):
            await interaction.response.send_message(
                "❌ You need Admin or Commissioner role.", ephemeral=True
            )
            return

        await interaction.response.defer()

        item = await asyncio.to_thread(self.db.get_content_item, self.item_id)
        if not item:
            await interaction.followup.send("❌ Content item not found.", ephemeral=True)
            return

        guild_id = int(item.get("guild_id") or 0)

        # Find posting channel
        channel_id = await asyncio.to_thread(self.db.get_review_channel_id, guild_id)
        if not channel_id:
            channel_id = int(item.get("review_channel_id") or 0)

        channel = None
        if channel_id:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    channel = None

        if channel is None:
            channel = interaction.channel

        if channel is None:
            await interaction.followup.send("❌ Could not find a channel to post to.", ephemeral=True)
            return

        # Approve first if not already approved
        status = str(item.get("status") or "pending")
        if status not in ("approved", "posted"):
            await asyncio.to_thread(
                self.db.update_content_status,
                self.item_id,
                "approved",
                approved_by=int(interaction.user.id),
            )

        post_embed = _build_item_embed(item)
        try:
            await channel.send(embed=post_embed)
        except Exception as exc:
            await interaction.followup.send(f"❌ Failed to post: {exc}", ephemeral=True)
            return

        await asyncio.to_thread(self.db.mark_content_posted, self.item_id)

        updated_item = await asyncio.to_thread(self.db.get_content_item, self.item_id)
        if updated_item:
            review_embed = _build_item_embed(updated_item)
            review_embed.add_field(
                name="📤 Posted",
                value=f"Posted by {interaction.user.mention} to {channel.mention}",
                inline=False,
            )
            self._disable_all()
            await interaction.edit_original_response(embed=review_embed, view=self)
