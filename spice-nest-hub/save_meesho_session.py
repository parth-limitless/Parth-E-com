"""
Meesho Session & Authenticated Cookie Saver
===========================================
Allows you to open a real visible browser window, log in to your Meesho account
(or complete any verification/captcha), and automatically saves the authentic session
cookies to 'storage/meesho_session.json' for the bot to use daily.
"""

import asyncio
import os
import sys
from pathlib import Path

# UTF-8 console output
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from playwright.async_api import async_playwright

async def main():
    print("=" * 65)
    print("🌸 SPICE NEST HUB - MEESHO SESSION & LOGIN SAVER")
    print("=" * 65)

    base_dir = Path(__file__).resolve().parent
    storage_dir = base_dir / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    session_file = storage_dir / "meesho_session.json"

    print("\n⏳ Chromium browser khul raha hai...")
    async with async_playwright() as p:
        # Launch visible browser (headed mode)
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context_kwargs = {
            "viewport": None,
            "locale": "en-IN",
            "timezone_id": "Asia/Kolkata",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

        # Restore previous session if it exists so user doesn't have to re-enter OTP every time
        if session_file.exists():
            try:
                context_kwargs["storage_state"] = str(session_file)
                print(f"🔄 Previous session detect hui: {session_file}")
            except Exception:
                pass

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        target_url = "https://www.meesho.com"
        print(f"🌐 Navigating to {target_url}...")
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"⚠️ Page load notice: {e}")

        print("\n" + "#" * 65)
        print("📌 INSTRUCTIONS:")
        print("1. Chrome window aapke samne khuli hai.")
        print("2. Meesho par Login karein (OTP enter karein) agar aap login save karna chahte hain.")
        print("3. Agar login pehle se hai ya bas verification complete karni hai, toh wo karein.")
        print("4. Sab kuch hone ke baad, vapas IS CONSOLE WINDOW me aakar [ENTER] dabayein.")
        print("#" * 65 + "\n")

        # Wait for user to press ENTER
        await asyncio.to_thread(input, "👉 Login / Verification hone ke baad yahan [ENTER] dabayein... ")

        print("\n⏳ Session cookies aur storage tokens save ho rahe hain...")
        await context.storage_state(path=str(session_file))

        print(f"✅ BINGO! Aapka Meesho session kamyabi se save ho gaya hai:")
        print(f"📁 Path: {session_file}")
        print("Ab bot daily isi authenticated session ka use karke scan karega!")
        print("=" * 65)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

