"""ContentGenerator — OpenAI-backed content generation for the Content Pipeline."""
from __future__ import annotations

import json
import logging
import sys
from typing import Optional

from .templates import DEFAULT_TEMPLATES

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an ESPN-style sports content creator for a Madden CFM franchise league Discord. "
    "Generate punchy, dramatic, recruit-focused content. "
    "Always return valid JSON when asked."
)

_DEFAULT_FIELDS = {
    "title": "",
    "body": "",
    "caption": "",
    "hashtags": "",
    "hook": "",
    "voiceover": "",
    "on_screen_text": "",
    "clip_instructions": "",
    "cta": "",
    "source_summary": "",
}


def _serialize_list_fields(data: dict) -> dict:
    """Ensure list fields are serialized to JSON strings for DB storage."""
    list_fields = {"on_screen_text", "clip_instructions", "hashtags"}
    result = dict(data)
    for field in list_fields:
        val = result.get(field, "")
        if isinstance(val, list):
            result[field] = json.dumps(val)
        elif not isinstance(val, str):
            result[field] = str(val)
    return result


def _build_fallback(
    content_type: str,
    platform: str,
    context_data: dict,
) -> dict:
    """Return a minimal fallback dict when OpenAI is unavailable."""
    body_parts = []
    for k, v in context_data.items():
        if v:
            body_parts.append(f"{k}: {v}")
    body = "\n".join(body_parts) if body_parts else "League event detected."
    return {
        "title": f"{content_type.replace('_', ' ').title()} — {platform.title()}",
        "platform": platform,
        "content_type": content_type,
        "body": body,
        "caption": "",
        "hashtags": "#Madden #MaddenCFM #MaddenFranchise",
        "hook": "",
        "voiceover": "",
        "on_screen_text": "[]",
        "clip_instructions": "[]",
        "cta": "Check the league Discord for more details.",
        "source_summary": body[:200],
    }


class ContentGenerator:
    """Generates content using OpenAI GPT with template-based fallback."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import openai  # noqa: PLC0415 — lazy import
            self._client = openai.AsyncOpenAI(api_key=self.api_key)
        except ImportError:
            print("[ContentPipeline] openai package not installed — AI generation disabled.", file=sys.stderr)
            self._client = None
        return self._client

    async def generate(
        self,
        content_type: str,
        platform: str,
        context_data: dict,
        custom_prompt: Optional[str] = None,
    ) -> dict:
        """
        Generate content. Returns structured dict with fields:
        title, platform, content_type, hook, body, voiceover,
        on_screen_text, clip_instructions, caption, hashtags, cta, source_summary.

        Falls back to template-based content if OpenAI is unavailable or fails.
        """
        if not self.api_key:
            print("[ContentPipeline] No OpenAI API key — using fallback content.", file=sys.stderr)
            return _build_fallback(content_type, platform, context_data)

        client = self._get_client()
        if client is None:
            return _build_fallback(content_type, platform, context_data)

        # Build the user prompt
        if custom_prompt:
            user_prompt = custom_prompt
        else:
            template_entry = DEFAULT_TEMPLATES.get(content_type)
            if template_entry:
                prompt_template = template_entry["prompt_template"]
            else:
                prompt_template = (
                    "Generate {content_type} content for a Madden CFM league.\n"
                    "Context:\n{context}\n\n"
                    "Return a JSON object with keys: title, body, caption, hashtags, cta, "
                    "source_summary, hook, voiceover, on_screen_text, clip_instructions."
                )
            context_str = "\n".join(f"{k}: {v}" for k, v in context_data.items() if v)
            user_prompt = prompt_template.replace("{context}", context_str).replace(
                "{content_type}", content_type
            )

        try:
            response = await client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=1500,
                temperature=0.85,
            )
            raw_content = response.choices[0].message.content or "{}"
        except Exception as exc:
            print(f"[ContentPipeline] OpenAI API error: {exc}", file=sys.stderr)
            return _build_fallback(content_type, platform, context_data)

        # Parse JSON response safely
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            # Try to extract a JSON object from the response
            try:
                start = raw_content.index("{")
                end = raw_content.rindex("}") + 1
                parsed = json.loads(raw_content[start:end])
            except (ValueError, json.JSONDecodeError):
                print(
                    f"[ContentPipeline] Failed to parse OpenAI JSON response for {content_type}",
                    file=sys.stderr,
                )
                return _build_fallback(content_type, platform, context_data)

        # Merge with defaults so all keys are present
        result = dict(_DEFAULT_FIELDS)
        result.update({k: v for k, v in parsed.items() if k in _DEFAULT_FIELDS or k in ("title",)})

        # Ensure TikTok list fields are proper lists before serializing
        if platform in {"tiktok", "instagram", "youtube_shorts", "reels", "shorts"}:
            for field in ("on_screen_text", "clip_instructions"):
                val = result.get(field, "")
                if isinstance(val, str) and val.strip().startswith("["):
                    try:
                        result[field] = json.loads(val)
                    except json.JSONDecodeError:
                        result[field] = [val] if val else []
                elif not isinstance(val, list):
                    result[field] = [str(val)] if val else []

        # Serialize list fields to JSON strings for DB storage
        result = _serialize_list_fields(result)

        result["platform"] = platform
        result["content_type"] = content_type

        return result
