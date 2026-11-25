import io
import re
import asyncio
import traceback
from typing import Dict, Any
import qrcode
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.network import ConnectionTcpIntermediate
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    FloodWaitError,
    PhoneNumberInvalidError
)
from src.config import API_ID, API_HASH
from src.database import save_user_session, get_user_session, delete_user_session
from src.userbot.manager import start_user_session, stop_user_session, is_user_active

# In-memory dictionary tracking user login states
_login_states: Dict[int, Dict[str, Any]] = {}

def generate_qr_image(url: str) -> io.BytesIO:
    """Generates an in-memory PNG image of the Telegram login QR code."""
    img = qrcode.make(url)
    bio = io.BytesIO()
    bio.name = "qr_login.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

def normalize_digits(text: str) -> str:
    """Converts Eastern Arabic and Persian numerals to standard ASCII digits."""
    arabic_digits = "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹"
    ascii_digits  = "01234567890123456789"
    trans = str.maketrans(arabic_digits, ascii_digits)
    return text.translate(trans)

def normalize_phone(raw: str) -> str:
    """Normalizes phone numbers, converts local formats (07xxxxxxxxx) to international (+9647xxxxxxxxx)."""
    text = normalize_digits(raw)
    digits = re.sub(r"[^\d+]", "", text)
    
    if digits.startswith("07") and len(digits) == 11:
        return "+964" + digits[1:]
    if digits.startswith("7") and len(digits) == 10:
        return "+964" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if not digits.startswith("+") and digits:
        return "+" + digits
    return digits

def normalize_code(raw: str) -> str:
    """Normalizes OTP code string, removing spaces, dashes, and converting Arabic numerals."""
    text = normalize_digits(raw)
    return re.sub(r"\D", "", text)

def mask_phone(phone: str) -> str:
    """Masks phone number for privacy display (e.g. +964***1234)."""
    if len(phone) > 7:
        return phone[:4] + "***" + phone[-4:]
    return phone

def register_bot_handlers(bot: TelegramClient):
    """Registers all commands and message handlers for the interactive Bot interface."""

    async def start_qr_login_flow(event: Any, user_id: int):
        """Starts the QR code login sequence."""
        wait_msg = await event.respond("⏳ جاري إنشاء كود الـ QR للربط المباشر من خوادم تيليجرام...")
        try:
            client = TelegramClient(
                StringSession(),
                API_ID,
                API_HASH,
                device_model="Desktop Guard",
                system_version="Windows 11",
                app_version="5.0.0",
                lang_code="ar",
                connection=ConnectionTcpIntermediate,
                connection_retries=10,
                timeout=15
            )
            await client.connect()

            qr = await client.qr_login()
            qr_file = generate_qr_image(qr.url)

            caption = (
                "📷 **امسح كود الـ QR التالي لربط حسابك وتفعيل الحماية فوراً:**\n\n"
                "1️⃣ افتح تطبيق تيليجرام في هاتفك.\n"
                "2️⃣ اذهب إلى: **الإعدادات (Settings) ➔ الأجهزة (Devices)**.\n"
                "3️⃣ اضغط على: **ربط جهاز (Link Desktop Device)**.\n"
                "4️⃣ وجّه كاميرا الهاتف نحو هذه الصورة.\n\n"
                "⏳ *الكود صالح لمدة دقيقة واحدة، بانتظار مسح الكود...*"
            )
            qr_msg = await event.respond(file=qr_file, message=caption)
            await wait_msg.delete()

            _login_states[user_id] = {
                "step": "WAITING_QR_SCAN",
                "client": client,
                "qr": qr,
                "qr_msg": qr_msg
            }

            asyncio.create_task(_wait_for_qr(user_id, client, qr, qr_msg))

        except Exception as e:
            traceback.print_exc()
            await wait_msg.edit(f"❌ تعذر إنشاء كود الـ QR:\n`{str(e)}`")

    async def _wait_for_qr(user_id: int, client: TelegramClient, qr: Any, qr_msg: Any):
        """Background task waiting for the user to scan the QR code on mobile."""
        try:
            user = await qr.wait(timeout=90)

            # Successfully scanned and authenticated!
            session_str = client.session.save()
            phone = getattr(user, "phone", "") or str(user.id)

            save_user_session(user_id, phone, session_str)
            await start_user_session(user_id, session_str)
            await client.disconnect()
            _login_states.pop(user_id, None)

            user_display = getattr(user, "first_name", "مستخدم") or "مستخدم"
            username = f"@{user.username}" if getattr(user, "username", None) else "بدون يوزر"

            await qr_msg.reply(
                "🎉 **تم مسح الكود وربط الحساب بنجاح تام!**\n\n"
                f"👤 **الحساب:** {user_display} ({username})\n"
                f"📱 **الهاتف:** `{phone}`\n"
                f"🆔 **معرف الحساب:** `{user.id}`\n\n"
                "🛡️ **حارس الميديا المؤقتة:** نشط الآن، أي صورة أو فيديو مؤقت (View-Once) يصلك في الخاص سيُحفظ فوراً في رسائلك المحفوظة.\n"
                "📥 **حفظ المحتوى المقيد:** مفعل عبر أمر `/save <رابط_الرسالة>` في رسائلك المحفوظة.\n\n"
                "🔒 تم تشفير جلسة حسابك وتأمينها محلياً بتقنية AES-256."
            )

        except SessionPasswordNeededError:
            _login_states[user_id] = {
                "step": "AWAITING_2FA",
                "client": client,
                "phone": getattr(user_id, "phone", str(user_id))
            }
            await qr_msg.reply(
                "🔐 **تم مسح الكود بنجاح، لكن الحساب محمي بالتحقق بخطوتين (2FA Password)!**\n\n"
                "يرجى كتابة كلمة مرور حسابك هنا لإتمام الربط:\n"
                "*(للإلغاء أرسل /cancel)*"
            )
        except asyncio.TimeoutError:
            _login_states.pop(user_id, None)
            try:
                await client.disconnect()
            except Exception:
                pass
            await qr_msg.reply("⌛ **انتهت صلاحية كود الـ QR.** إذا أردت كوداً جديداً أرسل: /qr")
        except Exception as e:
            traceback.print_exc()
            _login_states.pop(user_id, None)
            try:
                await client.disconnect()
            except Exception:
                pass

    @bot.on(events.NewMessage(pattern=r"^/start"))
    async def handle_start(event: events.NewMessage.Event):
        user_id = event.sender_id
        session_data = get_user_session(user_id)

        if session_data:
            is_active = is_user_active(user_id)
            status_text = "🟢 نشط ويعمل" if is_active else "🟡 مسجل ولكن غير متصل"
            buttons = [
                [Button.inline("📊 حالة الحساب (/status)", data="status")],
                [Button.inline("❓ طريقة الاستخدام (/help)", data="help")],
                [Button.inline("🚪 تسجيل الخروج (/logout)", data="logout")]
            ]
            await event.reply(
                "👋 **أهلاً بك مجدداً في بوت حارس الميديا والمحتوى المقيد!**\n\n"
                f"📱 **الحساب:** `{mask_phone(session_data['phone'])}`\n"
                f"🛡️ **حالة الحماية:** {status_text}\n\n"
                "• يتم حفظ أي وسائط مؤقتة (تدمير ذاتي) تلقائياً فور وصولها وإرسالها لرسائلك المحفوظة.\n"
                "• لحفظ أي رسالة مقيدة، أرسل الرابط في رسائلك المحفوظة مع الأمر `/save`.",
                buttons=buttons
            )
        else:
            buttons = [
                [Button.inline("📷 مسح كود الـ QR (الأسهل والأسرع)", data="login_qr")],
                [Button.inline("🔑 ربط مباشر بكود الجلسة (StringSession)", data="login_session")],
                [Button.inline("📱 تسجيل الدخول برقم الهاتف (OTP)", data="login")]
            ]
            await event.reply(
                "🛡️ **مرحباً بك في بوت حارس الميديا المؤقتة والمحتوى المقيد!**\n\n"
                "**وظائف البوت الرئيسية:**\n"
                "1️⃣ **التقاط الميديا المؤقتة (View-Once):**\n"
                "أي صورة أو فيديو ذات تدمير ذاتي تصلك في الخاص يتم حفظها وإرسالها فوراً لرسائلك المحفوظة (Saved Messages).\n\n"
                "2️⃣ **حفظ المحتوى المقيد (Restricted Content):**\n"
                "تجاوز حظر التحميل والتوجيه في القنوات المقيدة عبر تزويد البوت برابط الرسالة في رسائلك المحفوظة.\n\n"
                "🔒 **الأمان والخصوصية:**\n"
                "يتم تشفير جلستك محلياً باستخدام مفاتيح تشفير AES-256 لحماية خصوصيتك التامة.\n\n"
                "👇 اختر طريقة الربط المناسبة لك:",
                buttons=buttons
            )

    @bot.on(events.NewMessage(pattern=r"^/qr"))
    async def handle_qr_cmd(event: events.NewMessage.Event):
        user_id = event.sender_id
        if get_user_session(user_id):
            await event.reply("⚠️ حسابك مربوط بالفعل! إذا أردت تبديل الحساب استخدم /logout أولاً.")
            return
        await start_qr_login_flow(event, user_id)

    @bot.on(events.NewMessage(pattern=r"^/session"))
    async def handle_session_cmd(event: events.NewMessage.Event):
        user_id = event.sender_id
        _login_states[user_id] = {"step": "AWAITING_SESSION"}
        await event.reply(
            "🔑 **الربط المباشر بكود الجلسة (StringSession):**\n\n"
            "أرسل كود الجلسة الخاص بحسابك هنا وسيقوم البوت بربطه وتفعيل الحماية فوراً:\n\n"
            "*(للإلغاء أرسل /cancel)*"
        )

    @bot.on(events.NewMessage(pattern=r"^/login"))
    async def handle_login_cmd(event: events.NewMessage.Event):
        user_id = event.sender_id
        if get_user_session(user_id):
            await event.reply("⚠️ حسابك مسجل بالفعل! إذا أردت تبديل الحساب، استخدم /logout أولاً.")
            return

        _login_states[user_id] = {"step": "AWAITING_PHONE"}
        request_buttons = [
            [Button.request_phone("📱 إرسال رقم هاتفي بنقرة واحدة")],
            [Button.text("❌ إلغاء (/cancel)")]
        ]
        await event.reply(
            "📱 **تسجيل الدخول برقم الهاتف:**\n\n"
            "اضغط على زر **'إرسال رقم هاتفي'** أدناه، أو اكتب رقم هاتفك يدوياً (مثال: `07701234567` أو `+9647701234567`):\n\n"
            "*(ملاحظة: يمكنك استخدام كود الـ QR السريع عبر /qr)*",
            buttons=request_buttons
        )

    @bot.on(events.NewMessage(pattern=r"^/cancel"))
    async def handle_cancel(event: events.NewMessage.Event):
        user_id = event.sender_id
        state = _login_states.pop(user_id, None)
        if state and "client" in state:
            try:
                await state["client"].disconnect()
            except Exception:
                pass
        await event.reply("❌ تم إلغاء العملية.", buttons=Button.clear())

    @bot.on(events.NewMessage(pattern=r"^/status"))
    async def handle_status(event: events.NewMessage.Event):
        user_id = event.sender_id
        session_data = get_user_session(user_id)
        if not session_data:
            await event.reply("❌ لم تسجل دخولك بعد. أرسل /qr لربط الحساب بكود QR.")
            return

        is_active = is_user_active(user_id)
        status_emoji = "🟢" if is_active else "🔴"
        status_word = "نشط ويعمل" if is_active else "متوقف"

        await event.reply(
            "📊 **حالة الحساب والخدمة:**\n\n"
            f"👤 **المعرف:** `{user_id}`\n"
            f"📱 **الحساب:** `{mask_phone(session_data['phone'])}`\n"
            f"🛡️ **حارس الميديا المؤقتة:** {status_emoji} {status_word}\n"
            f"🔒 **تشفير الجلسة:** مفعل (AES-256)\n"
            f"📅 **تاريخ الربط:** `{session_data['created_at']}`\n\n"
            "لإلغاء الربط في أي وقت، استخدم /logout."
        )

    @bot.on(events.NewMessage(pattern=r"^/logout"))
    async def handle_logout(event: events.NewMessage.Event):
        user_id = event.sender_id
        await stop_user_session(user_id)
        deleted = delete_user_session(user_id)
        _login_states.pop(user_id, None)

        if deleted:
            await event.reply("🚪 **تم تسجيل الخروج بنجاح!**\nتم مسح مفاتيح جلستك المشفرة من قاعدة البيانات وإيقاف الحارس.", buttons=Button.clear())
        else:
            await event.reply("ℹ️ أنت غير مسجل في النظام حالياً.")

    @bot.on(events.NewMessage(pattern=r"^/help"))
    async def handle_help(event: events.NewMessage.Event):
        await event.reply(
            "📖 **دليل استخدام البوت:**\n\n"
            "1️⃣ **الميديا المؤقتة (View-Once):**\n"
            "• بمجرد أن يرسل لك أي شخص في الخاص صورة أو فيديو بمؤقت تدمير ذاتي، سيلتقطه البوت فوراً ويرسله إلى قائمة **'الرسائل المحفوظة' (Saved Messages)** لديك قبل حذفه.\n\n"
            "2️⃣ **المحتوى المقيد (Restricted Content):**\n"
            "• في أي قناة أو محادثة تمنع الحفظ والتوجيه وأنت عضو فيها:\n"
            "• انسخ رابط المنشور وأرسله في 'رسائلك المحفوظة' بهذا الشكل:\n"
            "`/save https://t.me/c/1234567890/42`\n"
            "• سيقوم النظام بتحميل الملف وإعادة إرساله لك حراً بدون قيود.\n\n"
            "⚙️ **الأوامر:**\n"
            "/qr - الربط السريع عبر مسح كود الـ QR (الأسهل والأسرع)\n"
            "/session - ربط الحساب عبر كود الجلسة (StringSession)\n"
            "/login - ربط الحساب برقم الهاتف والكود\n"
            "/status - فحص حالة الخدمة\n"
            "/logout - تسجيل الخروج وحذف الجلسة\n"
            "/cancel - إلغاء العملية الحالية"
        )

    # Callback Query Handler for Inline Buttons
    @bot.on(events.CallbackQuery)
    async def handle_callback(event: events.CallbackQuery.Event):
        data = event.data.decode("utf-8")
        user_id = event.sender_id

        if data == "login_qr":
            await event.delete()
            await start_qr_login_flow(event, user_id)
        elif data == "login_session":
            await event.delete()
            _login_states[user_id] = {"step": "AWAITING_SESSION"}
            await event.respond(
                "🔑 **الربط المباشر بكود الجلسة (StringSession):**\n\n"
                "أرسل كود الجلسة الخاص بحسابك هنا وسيقوم البوت بربطه وتفعيل الحماية فوراً:\n\n"
                "*(للإلغاء أرسل /cancel)*"
            )
        elif data == "login":
            await event.delete()
            _login_states[user_id] = {"step": "AWAITING_PHONE"}
            request_buttons = [
                [Button.request_phone("📱 إرسال رقم هاتفي بنقرة واحدة")],
                [Button.text("❌ إلغاء (/cancel)")]
            ]
            await event.respond(
                "📱 **إرسال رقم الهاتف**\n\n"
                "اضغط على زر **'إرسال رقم هاتفي'** أدناه، أو اكتب رقم هاتفك يدوياً:\n\n"
                "*(للإلغاء أرسل /cancel)*",
                buttons=request_buttons
            )
        elif data == "status":
            session_data = get_user_session(user_id)
            if session_data:
                is_active = is_user_active(user_id)
                await event.answer(f"الحالة: {'نشط ويعمل 🟢' if is_active else 'متوقف 🔴'}", alert=True)
            else:
                await event.answer("الحساب غير مسجل!", alert=True)
        elif data == "help":
            await event.answer()
            await handle_help(event)
        elif data == "logout":
            await handle_logout(event)

    # State machine message handler for user input
    @bot.on(events.NewMessage(func=lambda e: e.is_private))
    async def handle_login_conversation(event: events.NewMessage.Event):
        user_id = event.sender_id
        text = (event.text or "").strip()

        if text.startswith("/"):
            return
        if "إلغاء" in text:
            await handle_cancel(event)
            return

        state = _login_states.get(user_id)
        if not state:
            return

        step = state.get("step")

        # Step: Direct StringSession Input
        if step == "AWAITING_SESSION":
            session_str = text.strip()
            if len(session_str) < 50:
                await event.reply("❌ كود الجلسة غير صالح (قصير جداً). يرجى التأكد من نسخ كود الجلسة كاملاً:")
                return

            wait_msg = await event.reply("⏳ جاري التحقق من كود الجلسة وربط الحساب...")
            try:
                test_client = TelegramClient(
                    StringSession(session_str),
                    API_ID,
                    API_HASH,
                    connection=ConnectionTcpIntermediate,
                    connection_retries=10,
                    timeout=15
                )
                await test_client.connect()

                if not await test_client.is_user_authorized():
                    await wait_msg.edit("❌ كود الجلسة غير صالح أو منتهي الصلاحية. يرجى توليد كود جلسة جديد.")
                    await test_client.disconnect()
                    return

                me = await test_client.get_me()
                user_display = getattr(me, "first_name", "مستخدم") or "مستخدم"
                user_phone = getattr(me, "phone", "") or str(me.id)
                username = f"@{me.username}" if getattr(me, "username", None) else "بدون يوزر"

                save_user_session(user_id, user_phone, session_str)
                await start_user_session(user_id, session_str)
                await test_client.disconnect()
                _login_states.pop(user_id, None)

                await wait_msg.edit(
                    "🎉 **تم ربط الحساب وتفعيل الحماية بنجاح!**\n\n"
                    f"👤 **الحساب:** {user_display} ({username})\n"
                    f"📱 **الهاتف:** `{user_phone}`\n"
                    f"🆔 **معرف الحساب:** `{me.id}`\n\n"
                    "🛡️ **حارس الميديا المؤقتة:** نشط الآن لحسابك.\n"
                    "📥 **حفظ المحتوى المقيد:** مفعل عبر أمر `/save <الرابط>` في رسائلك المحفوظة.\n\n"
                    "🔒 تم تشفير جلسة حسابك وتأمينها محلياً بتقنية AES-256."
                )
            except Exception as e:
                traceback.print_exc()
                await wait_msg.edit(f"❌ فشل الاتصال بالجلسة:\n`{str(e)}`\n\nيرجى التأكد من صحة كود الجلسة والمحاولة مجدداً.")
            return

        # Step: Receiving 2FA Password
        elif step == "AWAITING_2FA":
            password = text
            client: TelegramClient = state.get("client")
            phone = state.get("phone", str(user_id))

            wait_msg = await event.reply("⏳ جاري التحقق من كلمة المرور...")
            try:
                await client.sign_in(password=password)

                session_str = client.session.save()
                save_user_session(user_id, phone, session_str)
                await start_user_session(user_id, session_str)
                await client.disconnect()
                _login_states.pop(user_id, None)

                await wait_msg.edit(
                    "🎉 **تم التحقق وتسجيل الدخول بنجاح!**\n\n"
                    "🛡️ **حارس الميديا المؤقتة:** يعمل الآن في الخلفية لحسابك.\n"
                    "📥 **حفظ المحتوى المقيد:** مفعل عبر أمر `/save <الرابط>` في رسائلك المحفوظة.\n\n"
                    "🔒 تم تشفير جلسة حسابك محلياً بتقنية AES-256."
                )
            except PasswordHashInvalidError:
                await wait_msg.edit("❌ كلمة المرور غير صحيحة. يرجى إعادة كتابة كلمة المرور:")
            except Exception as e:
                traceback.print_exc()
                await wait_msg.edit(f"❌ حدث خطأ:\n`{str(e)}`")

        # Step: Phone Number Input (Fallback)
        elif step == "AWAITING_PHONE":
            raw_phone = ""
            if event.message.contact:
                raw_phone = event.message.contact.phone_number
            elif text:
                raw_phone = text

            phone = normalize_phone(raw_phone)
            print(f"[*] Processing phone login request for user {user_id}: {phone}")

            if not phone.startswith("+") or len(phone) < 9:
                await event.reply(
                    "❌ رقم هاتف غير صالح.\n"
                    "يرجى استخدام الربط السريع بكود الـ QR عبر /qr."
                )
                return

            wait_msg = await event.reply("⏳ جاري التواصل مع خوادم تيليجرام لطلب كود التحقق...", buttons=Button.clear())
            try:
                client = TelegramClient(
                    StringSession(),
                    API_ID,
                    API_HASH,
                    device_model="Desktop Guard",
                    system_version="Windows 11",
                    app_version="5.0.0",
                    lang_code="ar",
                    connection=ConnectionTcpIntermediate,
                    connection_retries=10,
                    timeout=15
                )
                await client.connect()

                sent_code = await client.send_code_request(phone)
                state["client"] = client
                state["phone"] = phone
                state["phone_code_hash"] = sent_code.phone_code_hash
                state["step"] = "AWAITING_CODE"

                await wait_msg.edit(
                    f"📩 **تم إرسال كود التحقق بنجاح إلى:** `{phone}`\n\n"
                    "📍 **مكان الكود:** افتح تطبيق تيليجرام وستجد الكود في محادثة **Telegram** الرسمية.\n\n"
                    "✍️ **يرجى كتابة الكود هنا للمتابعة:**\n"
                    "*(يُفضل مسح كود الـ QR بدلاً من ذلك عبر /qr)*"
                )
            except Exception as e:
                traceback.print_exc()
                await wait_msg.edit(f"❌ تعذر إرسال كود التحقق:\n`{str(e)}`\n\n💡 **موصى به:** استخدم مسح كود الـ QR عبر الأمر /qr بدون انتظار أي كود!")
                _login_states.pop(user_id, None)

        # Step: Receiving OTP Code
        elif step == "AWAITING_CODE":
            code = normalize_code(text)
            client: TelegramClient = state.get("client")
            phone = state.get("phone")
            phone_code_hash = state.get("phone_code_hash")

            if not code or len(code) < 4:
                await event.reply("❌ كود غير صحيح. يرجى إدخال أرقام الكود فقط (مثال: `1 2 3 4 5`).")
                return

            wait_msg = await event.reply("⏳ جاري التحقق من الكود...")
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
                session_str = client.session.save()
                save_user_session(user_id, phone, session_str)
                await start_user_session(user_id, session_str)
                await client.disconnect()
                _login_states.pop(user_id, None)

                await wait_msg.edit(
                    "🎉 **تم تسجيل الدخول وتفعيل الحماية بنجاح!**\n\n"
                    "🛡️ **حارس الميديا المؤقتة:** يعمل الآن في الخلفية لحسابك.\n"
                    "📥 **حفظ المحتوى المقيد:** مفعل عبر أمر `/save <الرابط>` في رسائلك المحفوظة.\n\n"
                    "🔒 تم تشفير جلسة حسابك محلياً بتقنية AES-256."
                )
            except SessionPasswordNeededError:
                state["step"] = "AWAITING_2FA"
                await wait_msg.edit(
                    "🔐 **الحساب محمي بكلمة مرور (التحقق بخطوتين - 2FA)**\n\n"
                    "يرجى كتابة كلمة مرور حسابك للمتابعة:"
                )
            except Exception as e:
                traceback.print_exc()
                await wait_msg.edit(f"❌ حدث خطأ أثناء التحقق:\n`{str(e)}`")
