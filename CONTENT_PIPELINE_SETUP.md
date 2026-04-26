# Content Pipeline v1 — Setup Guide

## Overview
This module adds automated content generation to your Madden CFM Discord bot using OpenAI GPT. It detects noteworthy league events and generates ESPN-style content for Discord, TikTok, Instagram Reels, YouTube Shorts, and Facebook groups. All content goes through a human review step before posting — no external platform is ever auto-posted.

---

## Required Environment Variables
```
DATABASE_URL=postgresql://...         # existing — shared Postgres DB
OPENAI_API_KEY=sk-...                 # optional global fallback key
OPENAI_MODEL=gpt-4o-mini              # optional, default gpt-4o-mini
GUILD_IDS=123456789,987654321         # comma-separated Discord guild IDs
AUTO_GENERATE_CONTENT=false           # set true to enable background auto-gen
AUTO_POST_APPROVED_DISCORD_CONTENT=false  # set true to auto-post on approval
CONTENT_GENERATION_INTERVAL_MINUTES=60   # how often background scan runs
```

---

## Per-Guild Configuration (via /setup commands)
The bot already supports per-guild OpenAI API key via `/setup` commands. The content pipeline reads from:
- `guild_config.openai_api_key` (per-guild, takes priority)
- `OPENAI_API_KEY` env var (global fallback)
- `guild_config.content_review_channel_id` — where review embeds are posted
- `guild_config.recruit_channel_id` — where recruiting posts are posted
- `guild_config.auto_generate_content` — enable/disable background pipeline
- `guild_config.auto_post_approved_discord_content` — auto-post approved Discord content
- `guild_config.content_generation_interval_minutes` — scan frequency

---

## Running the Migration
The migration runs automatically on bot startup via `ContentDB.ensure_tables()`. You can also run `content_pipeline/migration.sql` manually against your Postgres DB:

```bash
psql $DATABASE_URL -f content_pipeline/migration.sql
```

---

## Adding New `/setup` Commands for Content Pipeline
After installing the module, configure channels by running directly in your DB:
```sql
UPDATE guild_config SET content_review_channel_id = <channel_id> WHERE guild_id = <guild_id>;
UPDATE guild_config SET recruit_channel_id = <channel_id> WHERE guild_id = <guild_id>;
UPDATE guild_config SET auto_generate_content = true WHERE guild_id = <guild_id>;
UPDATE guild_config SET auto_post_approved_discord_content = true WHERE guild_id = <guild_id>;
```

---

## Content Review Workflow
1. Pipeline detects noteworthy events → generates content → saves as `pending`
2. Review embed posted to `content_review_channel` with 4 buttons: **Approve | Reject | Regenerate | Post Now**
3. Admin approves → status becomes `approved`
4. If `AUTO_POST_APPROVED_DISCORD_CONTENT=true`, approved Discord content is posted automatically
5. TikTok/Reels scripts remain in the review channel for copy-paste — never auto-posted to external platforms

---

## Adding the Cog to Your Bot
The content pipeline is wired up automatically in `meaty_token_bot.py` when the `content_pipeline` package is present. The bot file already contains:

```python
# Content Pipeline v1
try:
    from content_pipeline.cog import ContentPipelineCog
    from content_pipeline.db import ContentDB as _ContentDB
    from content_pipeline.generator import ContentGenerator as _ContentGenerator
    from content_pipeline.events import EventScanner as _EventScanner
    from content_pipeline.scheduler import ContentScheduler as _ContentScheduler
    _CONTENT_PIPELINE_AVAILABLE = True
except ImportError:
    _CONTENT_PIPELINE_AVAILABLE = False
    print("[ContentPipeline] Module not found — content pipeline disabled.")
```

And near `bot.run(TOKEN)`:
```python
if _CONTENT_PIPELINE_AVAILABLE:
    _content_db = _ContentDB(DATABASE_URL)
    _content_db.ensure_tables()
    _openai_key = os.getenv("OPENAI_API_KEY", "")
    _openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    _content_generator = _ContentGenerator(_openai_key, _openai_model) if _openai_key else None
    _event_scanner = _EventScanner(_content_db)
    _content_scheduler = _ContentScheduler(bot, _content_db, _content_generator, _event_scanner)
    asyncio.get_event_loop().run_until_complete(
        bot.add_cog(ContentPipelineCog(bot, _content_db, _content_generator, _event_scanner, _content_scheduler))
    )
    if os.getenv("AUTO_GENERATE_CONTENT", "false").lower() == "true":
        # Scheduler starts inside on_ready
        pass
    print("[ContentPipeline] v1 ready.")
```

---

## Available Slash Commands

| Command | Description |
|---------|-------------|
| `/content_generate` | Generate content for a specific type and platform |
| `/content_queue` | Show pending/approved/posted content queue |
| `/content_review` | Review a specific item with approval buttons |
| `/content_approve` | Approve item by ID |
| `/content_reject` | Reject item by ID with optional reason |
| `/content_regenerate` | Regenerate item using same context |
| `/content_post` | Post approved content to a channel |
| `/tiktok_generate` | Generate a full TikTok/Reels/Shorts script |
| `/recruit_post` | Generate a recruiting post |
| `/weekly_media_generate` | Generate full weekly media package |

All commands are **admin-only** (Commissioner/Admin role required).

---

## Content Types Reference

| Type | Description | Platform |
|------|-------------|----------|
| `gotw_hype` | Game of the Week hype | discord, tiktok |
| `postgame_recap` | Post-game summary | discord |
| `upset_alert` | Upset result alert | discord, tiktok |
| `blowout_win` | Dominant win post | discord, tiktok |
| `rivalry_week` | Rivalry matchup hype | discord, tiktok |
| `sportsbook_preview` | Betting preview | discord |
| `token_economy_promo` | Casino/token promo | discord |
| `player_spotlight` | Individual player feature | discord, tiktok |
| `mvp_race` | MVP standings post | discord |
| `playoff_race` | Playoff implications | discord |
| `open_team_recruiting` | Open team ad | discord, instagram |
| `waitlist_recruiting` | Waitlist growth ad | discord, instagram |
| `weekly_news` | League news article | discord |
| `tiktok_script` | Full short-form video script | tiktok, reels, shorts |
| `commissioner_announcement` | Announcement draft | discord |

---

## Event Detection

The EventScanner automatically detects these events from your Madden database:

| Event | Source Table | Priority | Threshold |
|-------|-------------|----------|-----------|
| `upset_alert` | `games` + `standings` | 90 | Winner had fewer wins than loser |
| `close_game` | `games` | 75 | Score diff ≤ 3 |
| `rivalry_week` | `bot_weekly_rivalries` | 85 | Active rivalry matchup |
| `sportsbook_upset` | `bot_sportsbook_bets` | 80 | Large odds payout |
| `blowout_win` | `games` | 70 | Score diff ≥ 28 |
| `high_defense_game` | `player_defense_stats` | 65 | 3+ sacks or 2+ INTs |
| `high_passing_game` | `player_passing_stats` | 65 | 350+ passing yards |
| `high_rushing_game` | `player_rushing_stats` | 60 | 150+ rushing yards |
| `high_receiving_game` | `player_receiving_stats` | 55 | 150+ receiving yards |
| `bounty_completed` | `bot_bounties` | 50 | Recently claimed bounty |

All event detection is **defensive** — missing tables or columns are silently skipped.

---

## Security Notes
- Content pipeline never auto-posts to TikTok, Instagram, Facebook, or any external platform
- Approved Discord content can only be auto-posted if `auto_post_approved_discord_content = true` in guild_config
- All slash commands require Admin or Commissioner role
- The `openai_api_key` is stored per-guild in the database and is never logged
