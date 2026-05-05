# meaty-token-bot

A Discord bot for managing Madden fantasy football leagues — tokens, trades, schedules, standings, and more.

---

## Slash Commands

### Channel Management

| Command | Description |
|---------|-------------|
| `/create_week_channels week:<int> [phase] [category_name] [auto_news]` | **Admin** — Create one matchup channel per game for a given week and phase. |
| `/delete_channels week:<int> phase:<str>` | **Admin** — Delete all matchup channels for a given week and phase. Requires **Manage Channels** permission. Shows an ephemeral confirmation before deleting. |

#### `/delete_channels` usage

```
/delete_channels week:5 phase:Regular Season
```

- `week` (required, integer) — The human-readable week number (1-based) whose channels should be deleted.
- `phase` (required) — One of: `Preseason`, `Regular Season`, `Wild Card`, `Divisional`, `Conference Championship`, `Super Bowl`.

The command finds all text channels whose names match the pattern used by `/create_week_channels` (e.g. `wk5-…`, `gotw-wk5-…`), displays an ephemeral preview with a **Confirm Delete** / **Cancel** button pair, and only deletes after confirmation. All deletions are logged to stdout and to the configured log channel.

---

### Token Economy

| Command | Description |
|---------|-------------|
| `/balance` | Check your token balance. |
| `/leaderboard` | Show everyone who currently has tokens. |
| `/history` | Show your most recent token activity. |
| `/addtokens user amount reason` | **Admin** — Add tokens to a user. |
| `/removetokens user amount reason` | **Admin** — Remove tokens from a user. |

### Shop / Casino

| Command | Description |
|---------|-------------|
| `/shop` | Show the token shop. |
| `/wheel` | Spin the Prize Wheel (costs tokens). |
| `/boomorbust` | Risk tokens on a Boom or Bust roll. |
| `/mysterycrate` | Open a Mystery Crate. |
| `/roulette` | Bet tokens on roulette. |
| `/blackjack` | Play a hand of blackjack. |
| `/buy_attribute` | Buy 1 attribute point. |
| `/buy_namechange` | Buy a player name change. |
| `/buy_rookiereveal` | Buy a rookie dev reveal. |
| `/buy_devopportunity` | Buy a dev opportunity. |

### League / Schedule

| Command | Description |
|---------|-------------|
| `/standings` | Show current league standings. |
| `/schedule` | Show live schedule data. |
| `/statleaders` | Show live stat leaders. |
| `/seasonleaders` | Show current season stat leaders. |
| `/player name` | Look up a player card. |
| `/roster team` | Show live roster data. |
| `/team name` | Show a team summary. |
| `/openteams` | Browse all open franchise teams. |
| `/assignteam` | **Admin** — Assign or unassign a franchise team. |
| `/gamerecap` | Generate a recap for one completed game. |
| `/weeklyrivalries` | Show rivalry games for a selected week and phase. |
| `/powerrankings` | Show current league power rankings. |
| `/storylines` | Show current league storylines. |

### Trades

| Command | Description |
|---------|-------------|
| `/submittrade` | Submit a trade for committee review. |
| `/forcetrade` | **Admin** — Force-approve or force-deny a trade. |

### Sportsbook

| Command | Description |
|---------|-------------|
| `/sportsbook` | Show current sportsbook lines. |
| `/bet` | Place a sportsbook bet. |
| `/activebets` | Show all open sportsbook bets. |
| `/settlebets` | **Admin** — Settle open bets for completed games. |

### Bounties

| Command | Description |
|---------|-------------|
| `/bounties` | List all active bounties. |
| `/claimbounty id` | Claim an active bounty. |
| `/createbounty` | **Admin** — Create a new bounty. |
| `/updatebountyamount` | **Admin** — Update a bounty reward. |

### Content Pipeline

See [CONTENT_PIPELINE_SETUP.md](CONTENT_PIPELINE_SETUP.md) for full details.

| Command | Description |
|---------|-------------|
| `/content_generate` | **Admin** — Generate content for a specific type and platform. |
| `/content_queue` | **Admin** — Show content items queue by status. |
| `/content_review` | **Admin** — Review a specific item with approval buttons. |
| `/tiktok_generate` | **Admin** — Generate a TikTok/Reels/Shorts script. |
| `/recruit_post` | **Admin** — Generate a recruiting post. |
| `/weekly_media_generate` | **Admin** — Generate full weekly media package. |

---

## Setup

Set the following environment variables before running:

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | ✅ | Discord bot token |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `GUILD_IDS` | | Comma-separated guild IDs for guild-scoped command sync |
| `LOG_CHANNEL_ID` | | Channel ID for bot log messages |
| `OPENAI_API_KEY` | | OpenAI key for AI-assisted content generation |

See the source for the full list of optional environment variables.
