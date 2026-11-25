import os
import re
import asyncio
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

# Regex to parse Telegram message links
# Examples:
# https://t.me/c/1234567890/42 (private supergroup/channel)
# https://t.me/public_channel/42 (public channel)
TG_LINK_PATTERN = re.compile(r"https?://t\.me/(c/)?([a-zA-Z0-9_]+)/(\d+)")

def register_userbot_listeners(client: TelegramClient, user_id: int):
    """
    Registers event listeners on an active userbot client.
    1. Automatic interception of Disappearing / TTL media (View-Once).
    2. /save command in Saved Messages to download restricted content from any chat/channel.
    """

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def handle_incoming_private(event: events.NewMessage.Event):
        """
        Listens to all private incoming messages and catches disappearing/self-destructing media.
        """
        message = event.message
        if not message.media:
            return

        # Check for TTL (Time-To-Live / View Once) in media attributes
        ttl = getattr(message.media, "ttl_seconds", None)
        
        # Telethon may also set ttl_seconds on specific photo or document attributes
        if not ttl and isinstance(message.media, (MessageMediaPhoto, MessageMediaDocument)):
            ttl = getattr(message.media, "ttl_seconds", None)

        if ttl and ttl > 0:
            sender = await event.get_sender()
            sender_name = getattr(sender, "first_name", "") or "Unknown"
            if getattr(sender, "last_name", None):
                sender_name += f" {sender.last_name}"
            username = f"@{sender.username}" if getattr(sender, "username", None) else "No Username"
            sender_id = getattr(sender, "id", "Unknown")

            # Download media immediately before it expires
            temp_path = await client.download_media(message)
            if not temp_path:
                return

            caption = (
                "🚨 **[تم حفظ وسائط مؤقتة بنجاح - View-Once Captured]**\n\n"
                f"👤 **المرسل:** {sender_name} ({username})\n"
                f"🆔 **معرف المرسل:** `{sender_id}`\n"
                f"⏱ **مؤقت التدمير الذاتي:** {ttl} ثانية\n"
                f"📅 **الوقت:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
            )
            if message.text:
                caption += f"💬 **النص المرافق:** {message.text}\n"

            try:
                # Send the preserved file to Saved Messages ("me")
                await client.send_file(
                    entity="me",
                    file=temp_path,
                    caption=caption
                )
            except Exception as e:
                print(f"[!] Error forwarding TTL media to Saved Messages: {e}")
            finally:
                # Clean up local temporary file
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

    @client.on(events.NewMessage(chats="me", pattern=r"^/save(?:\s+(.+))?"))
    async def handle_save_restricted(event: events.NewMessage.Event):
        """
        Allows the user to send /save <message_link> in their own Saved Messages
        to extract and save any restricted/protected content.
        """
        args = event.pattern_match.group(1)
        if not args:
            await event.reply(
                "ℹ️ **طريقة حفظ المحتوى المقيد:**\n"
                "أرسل الأمر مع رابط الرسالة المطلوب حفظها:\n"
                "`/save https://t.me/c/1234567890/42`\n"
                "أو:\n"
                "`/save https://t.me/channel_name/42`"
            )
            return

        link = args.strip()
        match = TG_LINK_PATTERN.match(link)
        if not match:
            await event.reply("❌ رابط غير صالح. يرجى إرسال رابط رسالة صحيح من تيليجرام.")
            return

        is_private_channel, chat_identifier, msg_id_str = match.groups()
        msg_id = int(msg_id_str)

        status_msg = await event.reply("⏳ جاري جلب المحتوى المقيد وتجاوز القيود...")

        try:
            # Resolve chat entity
            if is_private_channel:
                # Private channel links format: /c/1234567890 -> -1001234567890
                target_chat_id = int(f"-100{chat_identifier}")
                chat = await client.get_input_entity(target_chat_id)
            else:
                chat = await client.get_input_entity(chat_identifier)

            # Retrieve target message
            target_msg = await client.get_messages(chat, ids=msg_id)
            if not target_msg:
                await status_msg.edit("❌ لم يتم العثور على الرسالة أو الحساب غير منضم للقناة.")
                return

            if not target_msg.media:
                # Text-only message
                text_content = target_msg.text or "(رسالة فارغة)"
                await event.reply(f"📄 **نص الرسالة المقيدة:**\n\n{text_content}")
                await status_msg.delete()
                return

            # Download media stream directly bypassing UI restrictions
            await status_msg.edit("⬇️ جاري تحميل الوسائط المقيدة من السيرفر...")
            downloaded_file = await client.download_media(target_msg)

            if not downloaded_file:
                await status_msg.edit("❌ فشل تحميل الوسائط المقيدة.")
                return

            await status_msg.edit("⬆️ جاري إعادة الإرسال إلى الرسائل المحفوظة بدون قيود...")
            caption = (
                "✅ **تم استخراج المحتوى المقيد بنجاح!**\n"
                f"🔗 **الرابط الأصلي:** {link}\n"
            )
            if target_msg.text:
                caption += f"💬 **الوصف:** {target_msg.text}\n"

            await client.send_file(
                entity="me",
                file=downloaded_file,
                caption=caption
            )
            await status_msg.delete()

            # Clean up local file
            if os.path.exists(downloaded_file):
                try:
                    os.remove(downloaded_file)
                except Exception:
                    pass

        except Exception as e:
            await status_msg.edit(f"❌ حدث خطأ أثناء الحفظ:\n`{str(e)}`")
