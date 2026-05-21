"""Madden Companion App export HTTP server.

Provides run_web_server() to run the aiohttp ingest server alongside
the Discord bot using asyncio.gather().

The route handlers and app factory live in meaty_token_bot.py so that
they can share helpers (get_pg_conn, safe_int, etc.) without duplication.
This module is a thin wrapper that exposes run_web_server() for the
asyncio.gather() call in meaty_token_bot.main().
"""
import asyncio

# How long (seconds) to sleep between keep-alive ticks.
_KEEP_ALIVE_INTERVAL = 3600


async def run_web_server() -> None:
    """Start the Madden Companion App export HTTP server and keep it running.

    Uses a late import of meaty_token_bot to avoid circular-import issues:
    meaty_token_bot imports this module at module level, but by the time
    run_web_server() is invoked meaty_token_bot is fully initialised and
    already present in sys.modules.
    """
    import meaty_token_bot as _bot
    await _bot.ensure_export_server_started()
    # Keep the coroutine alive so asyncio.gather() does not exit.
    while True:
        await asyncio.sleep(_KEEP_ALIVE_INTERVAL)
