import os
import asyncio
import signal
import sys
from aiohttp import web
from telethon import TelegramClient
from telethon.network import ConnectionTcpIntermediate
from src.config import API_ID, API_HASH, BOT_TOKEN, validate_config
from src.database import init_db
from src.bot.handlers import register_bot_handlers
from src.userbot.manager import start_all_saved_sessions, stop_all_sessions

async def start_health_server(port: int):
    """Starts a lightweight HTTP server for cloud platforms (Render, Koyeb, Hugging Face)."""
    async def health_handler(request):
        return web.json_response({
            "status": "online",
            "service": "Telegram Session Guard",
            "message": "Running 24/7"
        })

    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[+] Cloud HTTP Health Server listening on 0.0.0.0:{port}")
    return runner

async def main():
    print("=" * 60)
    print("🛡️  Telegram Session Guard - Starting Application")
    print("=" * 60)

    # 1. Validate environment
    if not validate_config():
        sys.exit(1)

    # 2. Initialize Database
    init_db()
    print("[+] Database initialized.")

    # 3. Start Cloud Health HTTP server if PORT environment variable is set
    port_env = os.getenv("PORT")
    web_runner = None
    if port_env and port_env.isdigit():
        web_runner = await start_health_server(int(port_env))

    # 4. Create Telegram Bot Client with ConnectionTcpIntermediate
    bot = TelegramClient(
        "bot_service",
        API_ID,
        API_HASH,
        connection=ConnectionTcpIntermediate,
        connection_retries=10,
        retry_delay=2,
        timeout=15
    )
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    print(f"[+] Bot running as @{me.username} ({me.first_name})")

    # 5. Register Bot Handlers
    register_bot_handlers(bot)
    print("[+] Bot handlers registered.")

    # 6. Boot active Userbot sessions from DB
    await start_all_saved_sessions()

    # 7. Setup Graceful Shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        print("\n[!] Shutdown signal received. Cleaning up active sessions...")
        stop_event.set()

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

    print("[*] Telegram Session Guard is fully operational.")
    print("    Press Ctrl+C to stop.")

    try:
        bot_task = asyncio.create_task(bot.run_until_disconnected())
        wait_task = asyncio.create_task(stop_event.wait())
        
        done, pending = await asyncio.wait(
            [bot_task, wait_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        print("[*] Disconnecting active user sessions...")
        await stop_all_sessions()
        await bot.disconnect()
        if web_runner:
            await web_runner.cleanup()
        print("[+] Application stopped cleanly.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Program terminated.")
