"""Default prompt templates for all 15 content types in the Content Pipeline."""
from __future__ import annotations

DEFAULT_TEMPLATES: dict[str, dict] = {
    "gotw_hype": {
        "platform": "discord",
        "prompt_template": (
            "You are an ESPN-style hype writer for a competitive Madden CFM franchise league.\n"
            "Generate a Game of the Week hype post for Discord.\n\n"
            "Game details:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Short, punchy headline (max 10 words)\n"
            "- Body: 3–5 sentences. Build suspense. Talk stakes, rivalries, season implications.\n"
            "- Caption: One-liner teaser for social sharing\n"
            "- Hashtags: Relevant league/gaming hashtags\n"
            "- CTA: Tell people to watch, lock in, show up\n\n"
            "Tone examples: 'One game. One rivalry. One team trying to save their season.' "
            "'This is not just another Madden league. This is a full franchise universe.'\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "postgame_recap": {
        "platform": "discord",
        "prompt_template": (
            "You are an ESPN-style game recap writer for a competitive Madden CFM franchise league.\n"
            "Write a postgame recap for Discord.\n\n"
            "Game data:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Score-based headline (e.g. 'Cowboys 38, Eagles 17 — Statement Win')\n"
            "- Body: 4–6 sentences. Cover final score, key plays, turning point, player standouts.\n"
            "- Caption: Short shareable line\n"
            "- Hashtags: Relevant tags\n"
            "- CTA: Invite reactions or next-game hype\n\n"
            "Tone: Dramatic but factual. ESPN SportsCenter energy.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "upset_alert": {
        "platform": "discord",
        "prompt_template": (
            "You are a sports broadcaster covering a shocking upset in a Madden CFM franchise league.\n"
            "Write an upset alert post.\n\n"
            "Upset details:\n{context}\n\n"
            "Requirements:\n"
            "- Title: UPSET ALERT headline — dramatic\n"
            "- Body: 3–4 sentences. Who got upset, who the underdog was, why it matters.\n"
            "- Caption: Reaction bait one-liner\n"
            "- Hook: 0–3 second attention grabber\n"
            "- Hashtags: Upset/reaction tags\n"
            "- CTA: Get the community reacting\n\n"
            "Tone examples: 'The sportsbook had them as underdogs. The scoreboard told a different story.' "
            "'Everybody thought this game was over. Then the fourth quarter happened.'\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "blowout_win": {
        "platform": "discord",
        "prompt_template": (
            "You are a sports content writer for a Madden CFM franchise league.\n"
            "Write a blowout/statement win post.\n\n"
            "Game data:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Dominant performance headline\n"
            "- Body: 3–5 sentences. Emphasize dominance, margin, what it means for the standings.\n"
            "- Caption: Power move one-liner\n"
            "- Hashtags: Relevant tags\n"
            "- CTA: Challenge the rest of the league\n\n"
            "Tone: Confident, powerful, no mercy. The winning team just sent a message.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "rivalry_week": {
        "platform": "discord",
        "prompt_template": (
            "You are a hype writer for a Madden CFM franchise league's rivalry matchup.\n"
            "Write a rivalry week hype post.\n\n"
            "Rivalry details:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Rivalry framing (e.g. 'The Grudge Match', 'Bad Blood Week')\n"
            "- Body: 4–5 sentences. History, hatred, what's at stake, who wants it more.\n"
            "- Caption: War declaration one-liner\n"
            "- Hashtags: Rivalry/hype tags\n"
            "- CTA: Tell people to tune in and pick sides\n\n"
            "Tone: This is personal. Not just a game.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "sportsbook_preview": {
        "platform": "discord",
        "prompt_template": (
            "You are a sportsbook analyst for a Madden CFM franchise league.\n"
            "Write a betting preview post for Discord.\n\n"
            "Game/event data:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Betting preview headline\n"
            "- Body: 4–6 sentences. Odds analysis, key matchups, pick recommendation.\n"
            "- Caption: Betting hook one-liner\n"
            "- Hashtags: Betting/gaming tags\n"
            "- CTA: Lock in bets with the token system\n\n"
            "Tone: Sharp, analytical, but with some personality. Think DraftKings meets ESPN.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "token_economy_promo": {
        "platform": "discord",
        "prompt_template": (
            "You are a marketing writer for a Madden CFM franchise league with a token economy and casino.\n"
            "Write a promo post for the token/casino system.\n\n"
            "Promo context:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Casino/token promo headline\n"
            "- Body: 3–4 sentences. Hype the economy, prizes, ways to earn, fun factor.\n"
            "- Caption: Action-oriented one-liner\n"
            "- Hashtags: Gaming/casino tags\n"
            "- CTA: Tell people to play, earn, and get rich in the league economy\n\n"
            "Tone: Fun, energetic, FOMO-inducing. Like a casino ad but for Madden.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "player_spotlight": {
        "platform": "discord",
        "prompt_template": (
            "You are a sports feature writer for a Madden CFM franchise league.\n"
            "Write a player spotlight post.\n\n"
            "Player data:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Player name + achievement headline\n"
            "- Body: 4–6 sentences. Stats, what they did, why it matters, the narrative.\n"
            "- Caption: Star player one-liner\n"
            "- Hashtags: Player/game tags\n"
            "- CTA: Crown them, debate it, react to it\n\n"
            "Tone: This player just went off. Treat it like SportsCenter's Top 10.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "mvp_race": {
        "platform": "discord",
        "prompt_template": (
            "You are a sports analyst covering the MVP race in a Madden CFM franchise league.\n"
            "Write an MVP race standings post.\n\n"
            "Standings/stats data:\n{context}\n\n"
            "Requirements:\n"
            "- Title: MVP race headline\n"
            "- Body: 4–6 sentences. Current leader, challengers, key stats, narrative.\n"
            "- Caption: MVP debate one-liner\n"
            "- Hashtags: MVP/stats tags\n"
            "- CTA: Get the community debating who deserves it\n\n"
            "Tone: Statistical authority with debate energy. Like ESPN First Take meets PFR.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "playoff_race": {
        "platform": "discord",
        "prompt_template": (
            "You are a playoff race analyst for a Madden CFM franchise league.\n"
            "Write a playoff race update post.\n\n"
            "Standings/schedule data:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Playoff race update headline\n"
            "- Body: 4–6 sentences. Who's in, who's out, who's on the bubble, key remaining games.\n"
            "- Caption: Stakes one-liner\n"
            "- Hashtags: Playoff/standings tags\n"
            "- CTA: Get people locked in to the stretch run\n\n"
            "Tone: Every game matters. Season survival energy.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "open_team_recruiting": {
        "platform": "discord",
        "prompt_template": (
            "You are a recruiting coordinator for a competitive Madden CFM franchise league.\n"
            "Write an open team recruiting post to attract new members.\n\n"
            "League/team details:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Recruiting headline (e.g. 'OPEN TEAM AVAILABLE — [Team Name]')\n"
            "- Body: 4–6 sentences. Team info, league features, why join, what makes this league elite.\n"
            "- Caption: Short Instagram/Discord caption\n"
            "- Hashtags: Madden recruiting tags (always include #MaddenCFM #MaddenFranchise #CFMLeague #MaddenRecruiting)\n"
            "- CTA: Tell them how to apply/join\n\n"
            "Tone: Exclusive and competitive. This is a league worth joining. Make them feel like they're "
            "getting an opportunity, not just filling a slot.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "waitlist_recruiting": {
        "platform": "discord",
        "prompt_template": (
            "You are a recruiting coordinator for a competitive Madden CFM franchise league.\n"
            "Write a waitlist recruiting post to build the prospect pipeline.\n\n"
            "League details:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Waitlist/interest headline\n"
            "- Body: 3–5 sentences. Full league is elite, but waitlist lets them get first dibs next opening.\n"
            "- Caption: Exclusivity-driven one-liner\n"
            "- Hashtags: Madden recruiting tags (always include #MaddenCFM #MaddenFranchise #CFMLeague)\n"
            "- CTA: Join the waitlist now\n\n"
            "Tone: FOMO-driven. You want to be in this league when a spot opens.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "weekly_news": {
        "platform": "discord",
        "prompt_template": (
            "You are a sports journalist covering a Madden CFM franchise league.\n"
            "Write a weekly league news article.\n\n"
            "Week data:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Weekly headline (e.g. 'Week 8 Recap: Chaos, Upsets, and Playoff Implications')\n"
            "- Body: 6–10 sentences. Top games, notable performances, standings updates, drama.\n"
            "- Caption: Week summary teaser\n"
            "- Hashtags: League news tags\n"
            "- CTA: Read more, react, tune in next week\n\n"
            "Tone: Professional but engaging. Like an NFL.com weekly wrap-up with personality.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
    "tiktok_script": {
        "platform": "tiktok",
        "prompt_template": (
            "You are a viral TikTok/Reels/Shorts scriptwriter for a Madden CFM franchise league.\n"
            "Create a full short-form video script (10–60 seconds).\n\n"
            "Story/event context:\n{context}\n\n"
            "IMPORTANT: Return ONLY a valid JSON object with these exact fields:\n"
            "- title: Video title (short, searchable)\n"
            "- hook: 0–3 second opening line to stop the scroll (attention-grabbing, dramatic)\n"
            "- body: 10–20 second storyline narration\n"
            "- voiceover: Full voiceover script (read aloud, 30–60 seconds total with hook+body+cta)\n"
            "- on_screen_text: Array of 3–5 caption/text overlay lines that appear during the video\n"
            "- clip_instructions: Array of 3–5 specific clip suggestions (what to record/show)\n"
            "- caption: Social media caption for the post (engaging, emoji-friendly)\n"
            "- hashtags: Array of hashtags — ALWAYS include #Madden #MaddenCFM #MaddenFranchise #GamingLeague\n"
            "- cta: Call to action (subscribe, follow, join the league, etc.)\n\n"
            "Hook examples: 'Everybody thought this game was over. Then the fourth quarter happened.' "
            "'The sportsbook had them as underdogs. The scoreboard told a different story.' "
            "'This is not just another Madden league. This is a full franchise universe.'\n\n"
            "Tone: Viral, punchy, ESPN-energy. Make non-Madden players want to join.\n\n"
            "Return ONLY the JSON object. No markdown, no explanation."
        ),
    },
    "commissioner_announcement": {
        "platform": "discord",
        "prompt_template": (
            "You are drafting an official announcement for a Madden CFM franchise league commissioner.\n"
            "Write a formal but engaging commissioner announcement.\n\n"
            "Announcement context:\n{context}\n\n"
            "Requirements:\n"
            "- Title: Official announcement headline\n"
            "- Body: 3–8 sentences depending on complexity. Professional tone, clear information.\n"
            "- Caption: Summary one-liner\n"
            "- Hashtags: League tags\n"
            "- CTA: What members need to do (acknowledge, comply, react, prepare)\n\n"
            "Tone: Official and authoritative, but not boring. The commissioner runs this. "
            "This is not just another Madden league. This is a full franchise universe.\n\n"
            "Return a JSON object with keys: title, body, caption, hashtags, cta, source_summary, "
            "hook, voiceover, on_screen_text, clip_instructions."
        ),
    },
}
