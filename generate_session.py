import os
import sys
import asyncio
import qrcode
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.network import ConnectionTcpIntermediate
from telethon.errors import SessionPasswordNeededError
from src.config import API_ID, API_HASH

async def main():
    print("=" * 65)
    print("📷 مولد جلسة تيليجرام عبر كود الـ QR (بدون رسائل SMS أو أكواد)")
    print("=" * 65)
    print("[*] جاري الاتصال بخوادم تيليجرام وتوليد كود الـ QR...")

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
        retry_delay=2,
        timeout=15
    )
    await client.connect()

    qr = await client.qr_login()

    # Save QR code image
    img = qrcode.make(qr.url)
    img_path = "qr_login.png"
    img.save(img_path)
    print(f"\n[+] تم حفظ صورة الـ QR في: {os.path.abspath(img_path)}")

    # Open image automatically on Windows
    try:
        os.startfile(img_path)
        print("[+] تم فتح صورة الـ QR تلقائياً على شاشتك!")
    except Exception:
        pass

    print("\n" + "-" * 65)
    print("📲 خطوات الربط من هاتفك:")
    print("1. افتح تطبيق تيليجرام في الموبايل.")
    print("2. اذهب إلى: الإعدادات (Settings) ➔ الأجهزة (Devices).")
    print("3. اضغط على: 'ربط جهاز' (Link Desktop Device).")
    print("4. وجّه كاميرا الهاتف نحو صورة الـ QR التي فُتحت أمامك.")
    print("-" * 65)
    print("⏳ جاري انتظار المسح من هاتفك (المهلة 90 ثانية)...")

    try:
        user = await qr.wait(timeout=90)
    except SessionPasswordNeededError:
        print("\n🔐 الحساب محمي بكلمة مرور التحقق بخطوتين (2FA).")
        password = input("اكتب كلمة مرور حسابك هنا: ")
        user = await client.sign_in(password=password)

    session_string = client.session.save()
    me = await client.get_me()

    print("\n" + "=" * 65)
    print(f"🎉 تم تسجيل الدخول بنجاح بحساب: {me.first_name} (@{me.username})")
    print("=" * 65)
    print("\n👇 هذا هو كود الجلسة (StringSession) الخاص بك (انسخه كاملاً):\n")
    print(session_string)
    print("\n" + "=" * 65)
    print("قم بنسخ هذا الكود وإرساله لبوتك في تيليجرام عبر الأمر /session!")
    print("=" * 65)

    await client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n❌ حدث خطأ: {e}")
