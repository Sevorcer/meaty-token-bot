-- content_items: stores generated content pending review/approval
CREATE TABLE IF NOT EXISTS content_items (
    id              BIGSERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    content_type    TEXT NOT NULL,
    platform        TEXT NOT NULL DEFAULT 'discord',
    title           TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL DEFAULT '',
    caption         TEXT NOT NULL DEFAULT '',
    hashtags        TEXT NOT NULL DEFAULT '',
    hook            TEXT NOT NULL DEFAULT '',
    voiceover       TEXT NOT NULL DEFAULT '',
    on_screen_text  TEXT NOT NULL DEFAULT '',
    clip_instructions TEXT NOT NULL DEFAULT '',
    cta             TEXT NOT NULL DEFAULT '',
    source_summary  TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    source_type     TEXT NOT NULL DEFAULT '',
    source_id       TEXT NOT NULL DEFAULT '',
    created_by      BIGINT,
    approved_by     BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at     TIMESTAMPTZ,
    posted_at       TIMESTAMPTZ,
    review_message_id BIGINT,
    review_channel_id BIGINT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- content_templates: per-guild prompt templates
CREATE TABLE IF NOT EXISTS content_templates (
    id              BIGSERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    template_name   TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    platform        TEXT NOT NULL DEFAULT 'discord',
    prompt_template TEXT NOT NULL DEFAULT '',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (guild_id, template_name)
);

-- content_events: detected noteworthy league events
CREATE TABLE IF NOT EXISTS content_events (
    id              BIGSERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    event_type      TEXT NOT NULL,
    source_type     TEXT NOT NULL DEFAULT '',
    source_id       TEXT NOT NULL DEFAULT '',
    priority_score  INTEGER NOT NULL DEFAULT 0,
    processed       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- recruiting_posts: recruiting-focused content
CREATE TABLE IF NOT EXISTS recruiting_posts (
    id              BIGSERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    platform        TEXT NOT NULL DEFAULT 'discord',
    title           TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL DEFAULT '',
    short_caption   TEXT NOT NULL DEFAULT '',
    hashtags        TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    posted_at       TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Add content_review_channel_id and recruit_channel_id to guild_config if they don't exist
ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS content_review_channel_id BIGINT DEFAULT 0;
ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS recruit_channel_id BIGINT DEFAULT 0;
ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS auto_generate_content BOOLEAN DEFAULT FALSE;
ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS auto_post_approved_discord_content BOOLEAN DEFAULT FALSE;
ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS content_generation_interval_minutes INTEGER DEFAULT 60;
