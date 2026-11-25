import asyncio
from typing import Dict
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.network import ConnectionTcpIntermediate
from src.config import API_ID, API_HASH
from src.database import get_all_active_users, delete_user_session
from src.userbot.listeners import register_userbot_listeners

# Active clients mapped by user_id
_active_clients: Dict[int, TelegramClient] = {}

async def start_user_session(user_id: int, session_str: str) -> bool:
    """
    Initializes and starts a Telethon MTProto client for a user session,
    registers listeners, and keeps it active in background.
    """
    if user_id in _active_clients:
        return True

    try:
        session = StringSession(session_str)
        client = TelegramClient(
            session,
            API_ID,
            API_HASH,
            connection=ConnectionTcpIntermediate,
            connection_retries=10,
            retry_delay=2,
            timeout=15
        )
        await client.connect()

        if not await client.is_user_authorized():
            print(f"[!] Session for user {user_id} is expired or invalid. Removing from DB.")
            delete_user_session(user_id)
            await client.disconnect()
            return False

        # Register event handlers for disappearing media & restricted content
        register_userbot_listeners(client, user_id)

        _active_clients[user_id] = client
        print(f"[+] User session started successfully for user_id: {user_id}")
        return True

    except Exception as e:
        print(f"[!] Failed to start user session for {user_id}: {e}")
        return False

async def stop_user_session(user_id: int) -> bool:
    """Disconnects and removes an active user session."""
    client = _active_clients.pop(user_id, None)
    if client:
        try:
            await client.disconnect()
            print(f"[-] User session stopped for user_id: {user_id}")
            return True
        except Exception as e:
            print(f"[!] Error stopping user session for {user_id}: {e}")
    return False

def is_user_active(user_id: int) -> bool:
    """Checks if the user's MTProto session is currently running."""
    return user_id in _active_clients

async def start_all_saved_sessions() -> int:
    """Boots up all active user sessions from the encrypted database."""
    users = get_all_active_users()
    count = 0
    for user in users:
        success = await start_user_session(user["user_id"], user["session_str"])
        if success:
            count += 1
    print(f"[*] Bootstrapped {count}/{len(users)} active user sessions.")
    return count

async def stop_all_sessions() -> None:
    """Gracefully disconnects all active user clients."""
    user_ids = list(_active_clients.keys())
    for uid in user_ids:
        await stop_user_session(uid)
