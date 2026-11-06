"""Spice Nest Hub - 24x7 Telegram AI Assistant Bot
Runs 24x7 via lightweight Long Polling (Zero Cost, No Public URL or Webhook Needed).
Allows the user to query product prices, stock status, and daily audits directly from their mobile phone!
"""

import os
import sys
import time
import json
import sqlite3
import re
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional

# Ensure UTF-8 console output
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spicenest.db")
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_config.json")


def load_config() -> Dict[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not token:
                    token = data.get("bot_token", "").strip()
                if not gemini_key:
                    gemini_key = data.get("gemini_api_key", "").strip()
        except Exception:
            pass
    return {"token": token, "gemini_key": gemini_key}


def save_config(token: str, gemini_key: str = ""):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"bot_token": token.strip(), "gemini_api_key": gemini_key.strip()}, f, indent=2)


def send_telegram_message(token: str, chat_id: int, text: str, reply_markup: Optional[dict] = None) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[Telegram Send Error] {e}", flush=True)
        return False


def query_db(sql: str, params: tuple = ()) -> List[dict]:
    if not os.path.exists(DB_PATH):
        return []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def handle_search_query(text: str) -> str:
    cleaned = text.strip()
    low = cleaned.lower()

    # 1. Check for Daily Movement / Audit queries
    if any(k in low for k in ["out of stock", "stock khatam", "stock"]):
        oos = query_db("""
            SELECT * FROM flipkart_catalog WHERE in_stock = 0 
            UNION 
            SELECT product_id, name, NULL as price, NULL as mrp, NULL as rating, NULL as review_count, 0 as in_stock, image_url, product_url, detected_at as last_seen 
            FROM flipkart_changes WHERE change_type = 'OUT_OF_STOCK'
            LIMIT 10
        """)
        if not oos:
            return "✅ <b>Good News!</b> Flipkart par abhi koi bhi Spice Nest product Out of Stock nahi hai. Sabhi active hain!"
        msg = f"⚠️ <b>Flipkart Out of Stock Products ({len(oos)}):</b>\n\n"
        for i, item in enumerate(oos, 1):
            msg += f"{i}. <b>{item['name']}</b>\n"
            if item.get('product_id'):
                msg += f"   • PID: <code>{item['product_id']}</code>\n"
            if item.get('product_url'):
                msg += f"   • <a href='{item['product_url']}'>Flipkart Link</a>\n"
            msg += "\n"
        return msg

    if any(k in low for k in ["delist", "nikal gaya", "gayab", "missing", "list se"]):
        delisted = query_db("SELECT * FROM flipkart_changes WHERE change_type = 'DELISTED' ORDER BY detected_at DESC LIMIT 10")
        if not delisted:
            return "✅ <b>All Active!</b> Store me se koi bhi listing delist ya remove nahi hui hai."
        msg = f"🚨 <b>Delisted / Missing Listings ({len(delisted)}):</b>\n\n"
        for i, item in enumerate(delisted, 1):
            msg += f"{i}. <b>{item['name']}</b>\n"
            msg += f"   • Detail: {item.get('old_value', '')}\n"
            msg += f"   • Detected: {item.get('detected_at', '')}\n\n"
        return msg

    if any(k in low for k in ["price hike", "price badha", "daam badha", "rate badha", "daam badhe"]):
        hikes = query_db("SELECT * FROM flipkart_changes WHERE change_type = 'PRICE_HIKE' ORDER BY detected_at DESC LIMIT 10")
        if not hikes:
            return "ℹ️ Haal hi me kisi bhi product ka price increase nahi hua hai."
        msg = "🔺 <b>Recent Price Hikes (दाम बढ़े):</b>\n\n"
        for i, item in enumerate(hikes, 1):
            msg += f"{i}. <b>{item['name']}</b>\n"
            msg += f"   • Old: {item.get('old_value')} ➔ <b>New: {item.get('new_value')}</b> (+₹{item.get('diff_amount', 0):.1f})\n"
            msg += f"   • Time: {item.get('detected_at', '')}\n\n"
        return msg

    if any(k in low for k in ["price drop", "price kam", "daam kam", "rate kam", "daam ghata"]):
        drops = query_db("SELECT * FROM flipkart_changes WHERE change_type = 'PRICE_DROP' ORDER BY detected_at DESC LIMIT 10")
        if not drops:
            return "ℹ️ Haal hi me kisi bhi product ka price drop nahi hua hai."
        msg = "🔻 <b>Recent Price Drops (दाम घटे):</b>\n\n"
        for i, item in enumerate(drops, 1):
            msg += f"{i}. <b>{item['name']}</b>\n"
            msg += f"   • Old: {item.get('old_value')} ➔ <b>New: {item.get('new_value')}</b> (-₹{abs(item.get('diff_amount', 0)):.1f})\n"
            msg += f"   • Time: {item.get('detected_at', '')}\n\n"
        return msg

    # 2. Extract product search keywords
    # Remove filler words
    kw = re.sub(r'\b(flipkart|amazon|meesho|jiomart|price|rate|kitni|kitna|he|hai|batao|kya|in|me|par|ka|ki|ke|product)\b', '', low, flags=re.IGNORECASE).strip()
    words = [w for w in kw.split() if len(w) > 2]
    if not words:
        words = [kw] if kw else ["spice"]

    # Search in flipkart_catalog first
    conditions = " AND ".join(["name LIKE ?"] * len(words))
    params = tuple(f"%{w}%" for w in words)
    fk_items = query_db(f"SELECT * FROM flipkart_catalog WHERE {conditions} LIMIT 5", params)

    # If no exact multi-word match, search with OR
    if not fk_items and len(words) > 1:
        conditions_or = " OR ".join(["name LIKE ?"] * len(words))
        fk_items = query_db(f"SELECT * FROM flipkart_catalog WHERE {conditions_or} LIMIT 5", params)

    # Search in Main Price Hub SKUs as well
    sku_items = query_db(f"SELECT * FROM sku WHERE {conditions} LIMIT 3", params)

    if not fk_items and not sku_items:
        return f"🔍 <b>'{cleaned}'</b> ke liye koi product nahi mila.\n\nKripya thoda alag naam likhein (jaise: <i>Garlic, Chilli Oil, Gochujang, Jam</i>)."

    resp = f"🌶️ <b>Spice Nest Product Search Results:</b>\n"
    resp += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for it in (fk_items or []):
        stock_badge = "🟢 In Stock" if it.get("in_stock", 1) == 1 else "⚠️ Out of Stock"
        mrp_str = f" <s>₹{it['mrp']:.0f}</s>" if it.get("mrp") and it["mrp"] > it["price"] else ""
        resp += f"📦 <b>{it['name']}</b>\n"
        resp += f"• 🛒 <b>Flipkart:</b> ₹{it['price']:.0f}{mrp_str} ({stock_badge})\n"
        if it.get("rating"):
            resp += f"• ⭐ <b>Rating:</b> ★ {it['rating']} ({it.get('review_count', 50)}+ Reviews)\n"
        if it.get("product_url"):
            resp += f"• 🔗 <a href='{it['product_url']}'>Flipkart Product Link</a>\n"
        resp += "\n"

    # Also check if other portals (Amazon, Meesho, JioMart) have price in prices table
    if sku_items:
        for s in sku_items:
            s_id = s["id"]
            p_rows = query_db("""
                SELECT l.platform, p.price, p.in_stock, p.scraped_at 
                FROM prices p 
                JOIN links l ON p.link_id = l.id 
                WHERE l.sku_id = ? 
                ORDER BY p.scraped_at DESC LIMIT 6
            """, (s_id,))
            if p_rows:
                resp += f"📊 <b>Multi-Portal Price Hub ({s['name']}):</b>\n"
                for pr in p_rows:
                    plat_emoji = {"Amazon": "📦", "Flipkart": "🛒", "Meesho": "🛍️", "JioMart": "🏷️", "Blinkit": "⚡"}.get(pr["platform"], "🔹")
                    resp += f"• {plat_emoji} <b>{pr['platform']}:</b> ₹{pr['price']:.0f}\n"
                resp += "\n"

    resp += "━━━━━━━━━━━━━━━━━━━━━━\n"
    resp += "💡 <i>Daily JSON snapshot aur live database se synced.</i>"
    return resp


def run_bot(token: str):
    print("=" * 60)
    print(f"🚀 SPICE NEST TELEGRAM 24x7 BOT LAUNCHED")
    print(f"   Connecting to Telegram Bot API...")
    print("=" * 60)

    # 1. Verify token
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            bot_info = json.loads(r.read().decode("utf-8")).get("result", {})
            print(f"✅ Bot Connected Successfully!")
            print(f"   • Bot Name: {bot_info.get('first_name')}")
            print(f"   • Username: @{bot_info.get('username')}")
            print(f"   • Link: https://t.me/{bot_info.get('username')}")
    except Exception as e:
        print(f"❌ Failed to connect to bot with token: {e}")
        return False

    offset = 0
    print("\n🟢 Listening for user messages 24x7 (Press Ctrl+C to stop)...\n", flush=True)

    while True:
        try:
            updates_url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=20"
            req = urllib.request.Request(updates_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                updates = json.loads(r.read().decode("utf-8")).get("result", [])

            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message")
                if not msg or "text" not in msg:
                    continue

                chat_id = msg["chat"]["id"]
                user_text = msg["text"].strip()
                user_name = msg.get("from", {}).get("first_name", "Seller")

                print(f"[New Message from {user_name} ({chat_id})]: {user_text}", flush=True)

                if user_text in ["/start", "/help", "hi", "hello", "namaste"]:
                    welcome = (
                        f"👋 <b>Namaste {user_name}!</b>\n\n"
                        f"Main <b>Spice Nest AI Price Assistant</b> hoon.\n\n"
                        f"Aap mujhse apne mobile se 24×7 kisi bhi product ka rate, "
                        f"stock status aur daily movement pooch sakte hain!\n\n"
                        f"📌 <b>Aap yeh pooch sakte hain:</b>\n"
                        f"• <i>Garlic pickle flipkart price kitni hai?</i>\n"
                        f"• <i>2x chilli oil ka rate batao</i>\n"
                        f"• <i>Kaunsa product out of stock hua?</i>\n"
                        f"• <i>Kaunsi listing delist hui?</i>\n"
                        f"• <i>Price hikes dikhao</i>\n\n"
                        f"Kripya apna sawal likhein ya kisi bhi spice ka naam bhejein!"
                    )
                    send_telegram_message(token, chat_id, welcome)
                else:
                    reply = handle_search_query(user_text)
                    send_telegram_message(token, chat_id, reply)

        except KeyboardInterrupt:
            print("\nBot stopped by user.")
            break
        except Exception as err:
            time.sleep(2)

    return True


if __name__ == "__main__":
    cfg = load_config()
    token = cfg.get("token")
    if len(sys.argv) > 1:
        token = sys.argv[1].strip()

    if not token:
        print("Usage: python telegram_bot.py <BOT_TOKEN>")
        sys.exit(1)

    save_config(token)
    run_bot(token)

