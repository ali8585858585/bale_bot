import re
import os
import sys
import time
import threading
import requests
import psycopg
from datetime import datetime, timedelta, timezone
from flask import Flask, request

# ---------------------------------------------------------------------------
# تنظیمات اصلی بله — توکن و اطلاعات مخصوص ربات بله حفظ شده‌اند
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("BALE_TOKEN", "1121828278:4xf2bRX0-WtnP0kbOGT30RKSjzjq0ZwRzIE")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook/{TOKEN}" if RENDER_EXTERNAL_HOSTNAME else ""

ADMIN_USERNAME = "Hobabadmin"
ADMIN_CHAT_ID = 52937597
BALANCE_BOT_LINK = "https://t.me/reportvolume_bot"
CHANNEL_USERNAME = "HobabServices"

CARD_NUMBER = "5022-2913-3683-0904"
CARD_HOLDER = "علی باقری فرد"

RENEWAL_USERNAME_PATTERN = re.compile(r"^provpn[0-9]+$")

BUY_BUTTON_TEXT = "🛒 خرید اشتراک"
RENEW_BUTTON_TEXT = "🔄 تمدید سرور"
MY_SERVICES_BUTTON_TEXT = "📦 سرویس‌های من"
CHECK_BALANCE_BUTTON_TEXT = "📊 چک کردن مانده سرویس"
SUPPORT_BUTTON_TEXT = "🎧 پشتیبانی"
HOME_BUTTON_TEXT = "🏠 منوی اصلی"
PRICE_LIST_BUTTON_TEXT = "💵 لیست قیمت‌ها"

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))
DURATION_DAYS = {"monthly": 30, "quarterly": 90}
REMINDER_DAYS_BEFORE = 3
PENDING_REMIND_MINUTES = 30
BACKGROUND_INTERVAL = 3600

DATABASE_URL = os.environ.get("DATABASE_URL")

# ---------------------------------------------------------------------------
# پلن‌ها — محتوای بله حفظ شده
# ---------------------------------------------------------------------------
PLANS = {
    "single": {
        "title": "🌀 تک کاربره",
        "subcategories": {
            "monthly": {
                "title": "✨ یک ماهه",
                "items": [
                    {"id": "sm1", "label": "یک ماه تک کاربر ۲۰ گیگ", "price": 240},
                    {"id": "sm2", "label": "یک ماه تک کاربر ۴۰ گیگ", "price": 420},
                    {"id": "sm3", "label": "یک ماه تک کاربر ۶۰ گیگ", "price": 550},
                    {"id": "sm4", "label": "یک ماه تک کاربر ۱۰۰ گیگ", "price": 690},
                ],
            },
            "quarterly": {
                "title": "✨ سه ماهه",
                "items": [
                    {"id": "sq1", "label": "سه ماه تک کاربر ۱۰۰ گیگ", "price": 990},
                    {"id": "sq2", "label": "سه ماه تک کاربر ۱۵۰ گیگ", "price": 1390},
                    {"id": "sq3", "label": "سه ماه تک کاربر ۱۸۰ گیگ", "price": 1590},
                ],
            },
        },
    },
    "double": {
        "title": "🌀 دو کاربره",
        "subcategories": {
            "monthly": {
                "title": "✨ یک ماهه",
                "items": [
                    {"id": "dm1", "label": "یک ماه دو کاربر ۴۰ گیگ", "price": 540},
                    {"id": "dm2", "label": "یک ماه دو کاربر ۶۰ گیگ", "price": 650},
                    {"id": "dm3", "label": "یک ماه دو کاربر ۸۰ گیگ", "price": 750},
                    {"id": "dm4", "label": "یک ماه دو کاربر ۱۰۰ گیگ", "price": 890},
                ],
            },
            "quarterly": {
                "title": "✨ سه ماهه",
                "items": [
                    {"id": "dq1", "label": "سه ماه دو کاربر ۱۰۰ گیگ", "price": 1190},
                    {"id": "dq2", "label": "سه ماه دو کاربر ۲۰۰ گیگ", "price": 1790},
                    {"id": "dq3", "label": "سه ماه دو کاربر ۳۶۰ گیگ", "price": 2090},
                ],
            },
        },
    },
}


def now_dt():
    return datetime.now(TEHRAN_TZ).replace(tzinfo=None)


def now_text():
    return now_dt().strftime("%Y-%m-%d %H:%M")


_EN2FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

def fa_num(n):
    return f"{int(n):,}".translate(_EN2FA)


def price_toman_text(price):
    return f"{fa_num(price)} تومن"


def price_rial_text(price):
    return f"{fa_num(int(price) * 10_000)} ریال"


def parse_int(text):
    return int(re.sub(r"\D", "", str(text or "").translate(_EN2FA)) or 0)


def find_plan(plan_id):
    for cat_key, cat in PLANS.items():
        for sub_key, sub in cat["subcategories"].items():
            for item in sub["items"]:
                if item["id"] == plan_id:
                    return item, cat_key, sub_key
    return None, None, None


def get_full_price_list_text():
    lines = ["💵 تعرفه های اشتراک های طرح پرو:", ""]
    for cat_key in ("single", "double"):
        cat = PLANS[cat_key]
        lines += [cat["title"], ""]
        for sub_key in ("monthly", "quarterly"):
            sub = cat["subcategories"][sub_key]
            lines.append(sub["title"] + ":")
            for item in sub["items"]:
                lines.append(f"{item['label']} {price_toman_text(item['price'])}")
            lines.append("")
    lines.append(f"@{CHANNEL_USERNAME}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# PostgreSQL / Neon
# ---------------------------------------------------------------------------
def db_execute(query, params=(), fetch=None):
    if not DATABASE_URL:
        raise RuntimeError("متغیر محیطی DATABASE_URL تنظیم نشده است.")
    last_exc = None
    for _ in range(2):
        try:
            with psycopg.connect(DATABASE_URL, connect_timeout=15) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    if fetch == "one":
                        return cur.fetchone()
                    if fetch == "all":
                        return cur.fetchall()
                    return None
        except psycopg.OperationalError as exc:
            last_exc = exc
            time.sleep(1)
    raise last_exc


def init_db():
    db_execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            full_name TEXT,
            username TEXT,
            plan_id TEXT,
            plan_label TEXT NOT NULL,
            price TEXT NOT NULL,
            amount_toman INTEGER NOT NULL DEFAULT 0,
            duration_days INTEGER NOT NULL DEFAULT 30,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            created_ts TIMESTAMP,
            confirmed_at TIMESTAMP,
            expires_at TIMESTAMP,
            renewal_username TEXT,
            admin_reminded BOOLEAN NOT NULL DEFAULT FALSE,
            expiry_reminded BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    db_execute("""
        CREATE TABLE IF NOT EXISTS user_state (
            user_id BIGINT PRIMARY KEY,
            pending_plan_id TEXT,
            renewal_username TEXT,
            updated_at TEXT
        )
    """)
    db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            first_seen TEXT,
            blocked BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    db_execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    # ارتقای دیتابیس‌های قدیمی
    db_execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS full_name TEXT,
        ADD COLUMN IF NOT EXISTS username TEXT,
        ADD COLUMN IF NOT EXISTS plan_id TEXT,
        ADD COLUMN IF NOT EXISTS amount_toman INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS duration_days INTEGER DEFAULT 30,
        ADD COLUMN IF NOT EXISTS created_ts TIMESTAMP,
        ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS renewal_username TEXT,
        ADD COLUMN IF NOT EXISTS admin_reminded BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS expiry_reminded BOOLEAN NOT NULL DEFAULT FALSE
    """)
    db_execute("""
        UPDATE orders SET amount_toman = COALESCE(amount_toman, 0), duration_days = COALESCE(duration_days, 30)
        WHERE amount_toman IS NULL OR duration_days IS NULL
    """)
    apply_saved_settings()


def apply_saved_settings():
    global CARD_NUMBER, CARD_HOLDER
    try:
        rows = db_execute("SELECT key, value FROM settings", fetch="all") or []
    except Exception:
        return
    for key, value in rows:
        if key == "card_number":
            CARD_NUMBER = value
        elif key == "card_holder":
            CARD_HOLDER = value
        elif key.startswith("price_"):
            item, _, _ = find_plan(key[6:])
            if item:
                try:
                    item["price"] = int(value)
                except ValueError:
                    pass


def set_setting(key, value):
    db_execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, value),
    )


def upsert_user(user_id, full_name=None, username=None):
    db_execute("""
        INSERT INTO users (user_id, full_name, username, first_seen)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET full_name=EXCLUDED.full_name, username=EXCLUDED.username
    """, (user_id, full_name, username, now_text()))


def save_state(user_id, pending_plan_id=None, renewal_username=None):
    db_execute("""
        INSERT INTO user_state (user_id, pending_plan_id, renewal_username, updated_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            pending_plan_id = COALESCE(EXCLUDED.pending_plan_id, user_state.pending_plan_id),
            renewal_username = COALESCE(EXCLUDED.renewal_username, user_state.renewal_username),
            updated_at = EXCLUDED.updated_at
    """, (user_id, pending_plan_id, renewal_username, now_text()))


def get_state(user_id):
    return db_execute("SELECT pending_plan_id, renewal_username FROM user_state WHERE user_id=%s", (user_id,), "one")


def clear_state(user_id):
    db_execute("DELETE FROM user_state WHERE user_id=%s", (user_id,))


def create_order(user_id, full_name, username, plan, plan_id, duration_days, renewal_username):
    row = db_execute("""
        INSERT INTO orders
        (user_id, full_name, username, plan_id, plan_label, price, amount_toman, duration_days,
         status, created_at, created_ts, renewal_username)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s)
        RETURNING id
    """, (user_id, full_name, username, plan_id, plan["label"], price_toman_text(plan["price"]),
          plan["price"], duration_days, now_text(), now_dt(), renewal_username), "one")
    return row[0]


def get_order(order_id):
    row = db_execute("""
        SELECT id,user_id,full_name,username,plan_id,plan_label,price,amount_toman,status,created_at,
               duration_days,confirmed_at,expires_at,renewal_username
        FROM orders WHERE id=%s
    """, (order_id,), "one")
    if not row:
        return None
    keys = ["id","user_id","full_name","username","plan_id","plan_label","price","amount_toman","status",
            "created_at","duration_days","confirmed_at","expires_at","renewal_username"]
    return dict(zip(keys, row))


def finalize_order(order_id, status):
    order = get_order(order_id)
    if not order or order["status"] != "pending":
        return False, order
    confirmed_at = now_dt() if status == "confirmed" else None
    expires_at = confirmed_at + timedelta(days=order["duration_days"]) if confirmed_at else None
    row = db_execute("""
        UPDATE orders SET status=%s, confirmed_at=%s, expires_at=%s
        WHERE id=%s AND status='pending' RETURNING id
    """, (status, confirmed_at, expires_at, order_id), "one")
    return row is not None, get_order(order_id)


def get_user_orders(user_id, status="confirmed"):
    return db_execute("""
        SELECT plan_label, price, created_at, expires_at, renewal_username
        FROM orders WHERE user_id=%s AND status=%s ORDER BY id DESC
    """, (user_id, status), "all") or []

# ---------------------------------------------------------------------------
# API بله
# ---------------------------------------------------------------------------
def api_post(method, payload):
    try:
        r = requests.post(f"{BASE_URL}/{method}", json=payload, timeout=15)
        return r.json()
    except Exception as exc:
        print(f"Bale API {method} exception: {exc}", file=sys.stderr)
        return None


def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return api_post("sendMessage", payload)


def edit_message_text(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return api_post("editMessageText", payload)


def answer_callback_query(callback_query_id, text=None):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = True
    return api_post("answerCallbackQuery", payload)

# ---------------------------------------------------------------------------
# کیبوردها
# ---------------------------------------------------------------------------
def persistent_keyboard():
    return {"keyboard": [
        [{"text": BUY_BUTTON_TEXT}, {"text": RENEW_BUTTON_TEXT}],
        [{"text": MY_SERVICES_BUTTON_TEXT}, {"text": CHECK_BALANCE_BUTTON_TEXT}],
        [{"text": PRICE_LIST_BUTTON_TEXT}, {"text": SUPPORT_BUTTON_TEXT}],
        [{"text": HOME_BUTTON_TEXT}],
    ], "resize_keyboard": True}


def main_menu_inline():
    return {"inline_keyboard": [
        [{"text": BUY_BUTTON_TEXT, "callback_data": "plans"}],
        [{"text": RENEW_BUTTON_TEXT, "callback_data": "renew"}],
        [{"text": MY_SERVICES_BUTTON_TEXT, "callback_data": "my_services"}],
        [{"text": CHECK_BALANCE_BUTTON_TEXT, "callback_data": "check_balance"}],
        [{"text": PRICE_LIST_BUTTON_TEXT, "callback_data": "all_prices"}],
        [{"text": SUPPORT_BUTTON_TEXT, "callback_data": "support"}],
    ]}


def category_keyboard():
    return {"inline_keyboard": [
        [{"text": PLANS["single"]["title"], "callback_data": "cat_single"}],
        [{"text": PLANS["double"]["title"], "callback_data": "cat_double"}],
        [{"text": "📋 لیست کلی قیمت‌ها", "callback_data": "all_prices"}],
        [{"text": "🔙 بازگشت", "callback_data": "back"}],
    ]}


def subcategory_keyboard(cat_key):
    rows = []
    for sub_key, sub in PLANS[cat_key]["subcategories"].items():
        rows.append([{"text": sub["title"], "callback_data": f"sub_{cat_key}_{sub_key}"}])
    rows.append([{"text": "🔙 بازگشت", "callback_data": "plans"}])
    return {"inline_keyboard": rows}


def items_keyboard(cat_key, sub_key):
    rows = []
    for item in PLANS[cat_key]["subcategories"][sub_key]["items"]:
        rows.append([{"text": f"{item['label']} — {price_toman_text(item['price'])}", "callback_data": f"buy_{item['id']}"}])
    rows.append([{"text": "🔙 بازگشت", "callback_data": f"cat_{cat_key}"}])
    return {"inline_keyboard": rows}


def build_my_services_text(user_id):
    rows = get_user_orders(user_id)
    if not rows:
        return "📦 هنوز هیچ سرویس فعالی برای شما ثبت نشده است."
    lines = ["📦 سرویس‌های شما:\n"]
    for label, price, created_at, expires_at, renewal in rows:
        exp = expires_at.strftime("%Y-%m-%d %H:%M") if expires_at else "نامشخص"
        line = f"🔹 اشتراک: {label}\n💰 مبلغ: {price}\n⏱ فعال‌سازی: {created_at}\n📅 پایان: {exp}"
        if renewal:
            line += f"\n🔄 تمدید: {renewal}"
        lines += [line, "---"]
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# پردازش فلوهای کاربر
# ---------------------------------------------------------------------------
USER_STATE = {}

def mem_state(user_id):
    return USER_STATE.setdefault(user_id, {"awaiting_username": False, "attempts": 0, "renewal_username": None})


def reset_mem_state(user_id):
    USER_STATE[user_id] = {"awaiting_username": False, "attempts": 0, "renewal_username": None}


def start_renewal(chat_id):
    st = mem_state(chat_id)
    st["awaiting_username"] = True
    st["attempts"] = 0
    send_message(chat_id,
        "🔄 تمدید سرور\n\nلطفاً نام کاربری سرور OpenConnect خود را همینجا ارسال کنید.\n\n"
        "📌 فرمت صحیح: کلمه‌ی provpn به همراه یک عدد انگلیسی، مثلاً:\nprovpn27 ✅",
        persistent_keyboard())


def handle_text_message(message):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    user = message.get("from", {}) or {}
    if not chat_id:
        return
    upsert_user(chat_id, user.get("first_name") or user.get("last_name") or "کاربر", user.get("username"))

    if text in ("/start", HOME_BUTTON_TEXT, "start"):
        reset_mem_state(chat_id)
        send_message(chat_id, "سلام، جهت خرید یا تمدید سرور در خدمتم😉", persistent_keyboard())
        send_message(chat_id, "یکی از گزینه‌های زیر رو انتخاب کن:", main_menu_inline())
        return
    if text == "/myid":
        send_message(chat_id, f"🆔 شناسه (Chat ID) شما در بله:\n{chat_id}")
        return
    if text == "/cancel":
        reset_mem_state(chat_id)
        clear_state(chat_id)
        send_message(chat_id, "❌ فرآیند جاری لغو شد.", persistent_keyboard())
        send_message(chat_id, "🏠 منوی اصلی:", main_menu_inline())
        return
    if text == BUY_BUTTON_TEXT:
        reset_mem_state(chat_id)
        send_message(chat_id, "💵 تعرفه اشتراک‌های طرح پرو:\n\nنوع اشتراک رو انتخاب کن:", category_keyboard())
        return
    if text == RENEW_BUTTON_TEXT:
        start_renewal(chat_id)
        return
    if text == MY_SERVICES_BUTTON_TEXT:
        reset_mem_state(chat_id)
        send_message(chat_id, build_my_services_text(chat_id))
        return
    if text == CHECK_BALANCE_BUTTON_TEXT:
        reset_mem_state(chat_id)
        send_message(chat_id, "📊 برای چک کردن مانده‌ی سرویس روی دکمه‌ی زیر بزن:",
                     {"inline_keyboard": [[{"text": "📊 چک کردن مانده", "url": BALANCE_BOT_LINK}]]})
        return
    if text == PRICE_LIST_BUTTON_TEXT:
        reset_mem_state(chat_id)
        send_message(chat_id, get_full_price_list_text())
        return
    if text == SUPPORT_BUTTON_TEXT:
        reset_mem_state(chat_id)
        send_message(chat_id, "🎧 برای پشتیبانی روی دکمه‌ی زیر بزن:",
                     {"inline_keyboard": [[{"text": "💬 ارتباط با پشتیبانی", "url": f"https://ble.ir/{ADMIN_USERNAME}"}]]})
        return

    # اگر کاربر اشتباهاً فیش را برای خود ربات فرستاد
    if message.get("photo") or message.get("document"):
        send_message(chat_id,
            f"⚠️ فیش واریز را برای خود ربات نفرستید.\n\n"
            f"لطفاً فیش را مستقیماً در PV ادمین ارسال کنید:\nhttps://ble.ir/{ADMIN_USERNAME}\n\n"
            f"شماره سفارش را هم داخل پیام بنویسید.")
        return

    st = mem_state(chat_id)
    if st.get("awaiting_username"):
        username = text
        if RENEWAL_USERNAME_PATTERN.match(username):
            st["awaiting_username"] = False
            st["attempts"] = 0
            st["renewal_username"] = username
            save_state(chat_id, renewal_username=username)
            send_message(chat_id, f"✅ نام کاربری شما با موفقیت تایید شد! ({username})")
            send_message(chat_id, "لطفاً نوع اشتراک مورد نظر خود جهت تمدید را انتخاب کنید:", category_keyboard())
        else:
            st["attempts"] += 1
            base = "❌ نام کاربری شما اشتباه است!\n\nلطفاً دوباره با فرمت صحیح ارسال کنید، مثلاً:\nprovpn27"
            if st["attempts"] >= 2:
                send_message(chat_id, base + f"\n\nپشتیبانی: https://ble.ir/{ADMIN_USERNAME}")
            else:
                send_message(chat_id, base)

# ---------------------------------------------------------------------------
# Callbackها
# ---------------------------------------------------------------------------
def handle_callback(cb):
    cb_id = cb.get("id")
    data = cb.get("data", "")
    msg = cb.get("message", {}) or {}
    chat_id = (msg.get("chat") or {}).get("id")
    msg_id = msg.get("message_id")
    user = cb.get("from", {}) or {}
    if cb_id:
        answer_callback_query(cb_id)
    if not chat_id:
        return

    try:
        upsert_user(chat_id, user.get("first_name") or "کاربر", user.get("username"))
    except Exception:
        pass

    if data == "plans":
        edit_message_text(chat_id, msg_id, "💵 تعرفه اشتراک‌های طرح پرو:\n\nنوع اشتراک رو انتخاب کن:", category_keyboard())
    elif data == "renew":
        start_renewal(chat_id)
    elif data == "all_prices":
        edit_message_text(chat_id, msg_id, get_full_price_list_text(), {"inline_keyboard": [[{"text": "🛒 ثبت سفارش", "callback_data": "plans"}], [{"text": "🔙 بازگشت", "callback_data": "back"}]]})
    elif data.startswith("cat_"):
        cat_key = data[4:]
        if cat_key in PLANS:
            edit_message_text(chat_id, msg_id, f"{PLANS[cat_key]['title']}\n\nمدت اشتراک رو انتخاب کن:", subcategory_keyboard(cat_key))
    elif data.startswith("sub_"):
        parts = data.split("_")
        if len(parts) == 3 and parts[1] in PLANS and parts[2] in PLANS[parts[1]]["subcategories"]:
            cat_key, sub_key = parts[1], parts[2]
            edit_message_text(chat_id, msg_id,
                              f"{PLANS[cat_key]['title']}\n{PLANS[cat_key]['subcategories'][sub_key]['title']}\n\nپلن مورد نظرت رو انتخاب کن:",
                              items_keyboard(cat_key, sub_key))
    elif data.startswith("buy_"):
        plan_id = data[4:]
        plan, cat_key, sub_key = find_plan(plan_id)
        if not plan:
            edit_message_text(chat_id, msg_id, "❌ این پلن پیدا نشد.")
            return
        st = mem_state(chat_id)
        db_state = get_state(chat_id)
        renewal_username = st.get("renewal_username") or (db_state[1] if db_state else None)
        duration = DURATION_DAYS.get(sub_key, 30)
        try:
            order_id = create_order(chat_id,
                                    user.get("first_name") or "کاربر",
                                    user.get("username"), plan, plan_id, duration, renewal_username)
            save_state(chat_id, pending_plan_id=plan_id, renewal_username=renewal_username)
        except Exception as exc:
            print(f"create order failed: {exc}", file=sys.stderr)
            send_message(chat_id, "⚠️ ثبت سفارش موقتاً با مشکل مواجه شد. چند لحظه بعد دوباره تلاش کنید.")
            return

        renewal_note = f"🔄 نام کاربری جهت تمدید: {renewal_username}\n\n" if renewal_username else ""
        text = (
            f"{renewal_note}"
            f"✅ پلن انتخابی: {plan['label']}\n"
            f"💰 مبلغ: {price_toman_text(plan['price'])}\n"
            f"💱 معادل این میشه: {price_rial_text(plan['price'])}\n\n"
            f"💳 شماره کارت:\n{CARD_NUMBER}\n"
            f"👤 به نام: {CARD_HOLDER}\n\n"
            f"🧾 شماره سفارش شما: #{order_id}\n\n"
            f"📸 بعد از واریز، فیش را مستقیماً داخل PV ادمین ارسال کنید و حتماً شماره سفارش #{order_id} را هم بنویسید.\n\n"
            f"💬 ادمین: https://ble.ir/{ADMIN_USERNAME}"
        )
        edit_message_text(chat_id, msg_id, text, {"inline_keyboard": [[{"text": "💬 ارسال فیش به ادمین", "url": f"https://ble.ir/{ADMIN_USERNAME}"}], [{"text": "🔙 بازگشت", "callback_data": f"sub_{cat_key}_{sub_key}"}]]})
    elif data == "my_services":
        edit_message_text(chat_id, msg_id, build_my_services_text(chat_id), {"inline_keyboard": [[{"text": "🔙 بازگشت", "callback_data": "back"}]]})
    elif data == "support":
        edit_message_text(chat_id, msg_id, "🎧 برای پشتیبانی روی دکمه‌ی زیر بزن:", {"inline_keyboard": [[{"text": "💬 ارتباط با پشتیبانی", "url": f"https://ble.ir/{ADMIN_USERNAME}"}], [{"text": "🔙 بازگشت", "callback_data": "back"}]]})
    elif data == "check_balance":
        edit_message_text(chat_id, msg_id, "📊 برای چک کردن مانده‌ی سرویس روی دکمه‌ی زیر بزن:", {"inline_keyboard": [[{"text": "📊 چک کردن مانده", "url": BALANCE_BOT_LINK}], [{"text": "🔙 بازگشت", "callback_data": "back"}]]})
    elif data == "back":
        reset_mem_state(chat_id)
        clear_state(chat_id)
        edit_message_text(chat_id, msg_id, "🏠 منوی اصلی:", main_menu_inline())
    elif data.startswith("approve_") or data.startswith("reject_"):
        if chat_id != ADMIN_CHAT_ID:
            answer_callback_query(cb_id, "دسترسی ندارید.")
            return
        action, order_id_text = data.split("_", 1)
        try:
            order_id = int(order_id_text)
        except ValueError:
            return
        changed, order = finalize_order(order_id, "confirmed" if action == "approve" else "rejected")
        if not changed:
            send_message(ADMIN_CHAT_ID, f"⚠️ سفارش #{order_id} پیدا نشد یا قبلاً بررسی شده است.")
            return
        if action == "approve":
            send_message(order["user_id"], f"🎉 پرداخت شما تایید شد!\n\nاشتراک «{order['plan_label']}» با موفقیت فعال شد.\n📅 مدت: {order['duration_days']} روز\n📦 از بخش «سرویس‌های من» قابل مشاهده است.")
            edit_message_text(chat_id, msg_id, f"✅ سفارش #{order_id} تایید و سرویس فعال شد.\n👤 کاربر: {order['user_id']}\n📦 {order['plan_label']}")
        else:
            send_message(order["user_id"], "❌ پرداخت شما تایید نشد. لطفاً با پشتیبانی تماس بگیرید و در صورت نیاز فیش صحیح را مجدداً برای ادمین ارسال کنید.")
            edit_message_text(chat_id, msg_id, f"❌ سفارش #{order_id} رد شد.")

# ---------------------------------------------------------------------------
# دستورات ادمین
# ---------------------------------------------------------------------------
def admin_only(chat_id):
    return chat_id == ADMIN_CHAT_ID


def pending_text(order):
    renewal = f"\n🔄 تمدید: {order['renewal_username']}" if order.get("renewal_username") else ""
    return (
        f"🧾 سفارش #{order['id']}\n"
        f"👤 {order.get('full_name') or '---'} (@{order.get('username') or 'بدون_یوزرنیم'})\n"
        f"🆔 Chat ID: {order['user_id']}\n"
        f"📦 {order['plan_label']}\n"
        f"💰 {order['price']}\n"
        f"🕐 {order['created_at']}"
        f"{renewal}\n\n"
        f"📌 فیش این سفارش را باید در PV ادمین بررسی کنید."
    )


def handle_admin_command(message, text):
    chat_id = (message.get("chat") or {}).get("id")
    if not admin_only(chat_id):
        return False
    parts = text.split()
    cmd = parts[0].lower() if parts else ""
    if cmd == "/admin":
        send_message(chat_id, "🛠 دستورات مدیریت:\n/pending\n/stats\n/user <chat_id>\n/prices\n/setprice <plan_id> <price>\n/setcard <شماره>\n/setholder <نام>\n/broadcast <متن>")
    elif cmd == "/pending":
        rows = db_execute("SELECT id FROM orders WHERE status='pending' ORDER BY id LIMIT 30", fetch="all") or []
        if not rows:
            send_message(chat_id, "✅ سفارش در انتظار بررسی وجود ندارد.")
            return True
        for (oid,) in rows:
            order = get_order(oid)
            send_message(chat_id, pending_text(order), {"inline_keyboard": [[{"text": "✅ تایید", "callback_data": f"approve_{oid}"}, {"text": "❌ رد", "callback_data": f"reject_{oid}"}]]})
    elif cmd == "/stats":
        total = db_execute("SELECT COUNT(*), COALESCE(SUM(amount_toman),0) FROM orders WHERE status='confirmed'", fetch="one")
        pending = db_execute("SELECT COUNT(*) FROM orders WHERE status='pending'", fetch="one")[0]
        users = db_execute("SELECT COUNT(*) FROM users", fetch="one")[0]
        send_message(chat_id, f"📊 آمار\n\n💰 فروش تاییدشده: {fa_num(total[1])} تومن\n🧾 تعداد فروش: {fa_num(total[0])}\n⏳ در انتظار: {fa_num(pending)}\n👥 کاربران: {fa_num(users)}")
    elif cmd == "/user" and len(parts) >= 2:
        uid = parse_int(parts[1])
        info = db_execute("SELECT full_name,username,first_seen FROM users WHERE user_id=%s", (uid,), "one")
        orders = db_execute("SELECT id,plan_label,price,status,created_at,expires_at FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT 20", (uid,), "all") or []
        if not info:
            send_message(chat_id, "کاربر پیدا نشد.")
            return True
        lines = [f"👤 {info[0]} (@{info[1] or '-'})", f"🆔 {uid}", f"اولین ورود: {info[2]}", ""]
        for row in orders:
            exp = row[5].strftime("%Y-%m-%d %H:%M") if row[5] else "-"
            lines.append(f"#{row[0]} | {row[1]} | {row[2]} | {row[3]} | پایان: {exp}")
        send_message(chat_id, "\n".join(lines))
    elif cmd == "/prices":
        send_message(chat_id, get_full_price_list_text())
    elif cmd == "/setprice" and len(parts) >= 3:
        plan, _, _ = find_plan(parts[1])
        if not plan:
            send_message(chat_id, "❌ plan_id نامعتبر است.")
        else:
            value = parse_int(parts[2])
            plan["price"] = value
            set_setting(f"price_{parts[1]}", str(value))
            send_message(chat_id, f"✅ قیمت {parts[1]} روی {price_toman_text(value)} تنظیم شد.")
    elif cmd == "/setcard" and len(parts) >= 2:
        value = " ".join(parts[1:])
        set_setting("card_number", value)
        globals()["CARD_NUMBER"] = value
        send_message(chat_id, "✅ شماره کارت ذخیره شد.")
    elif cmd == "/setholder" and len(parts) >= 2:
        value = " ".join(parts[1:])
        set_setting("card_holder", value)
        globals()["CARD_HOLDER"] = value
        send_message(chat_id, "✅ نام صاحب کارت ذخیره شد.")
    elif cmd == "/broadcast":
        payload = text[len("/broadcast"):].strip()
        if not payload:
            send_message(chat_id, "استفاده: /broadcast متن پیام")
        else:
            rows = db_execute("SELECT user_id FROM users WHERE blocked=FALSE", fetch="all") or []
            ok = 0
            for (uid,) in rows:
                result = send_message(uid, payload)
                if result and result.get("ok") is not False:
                    ok += 1
                time.sleep(0.05)
            send_message(chat_id, f"📣 پیام همگانی ارسال شد.\nموفق: {fa_num(ok)}\nکل: {fa_num(len(rows))}")
    else:
        return False
    return True

# ---------------------------------------------------------------------------
# یادآوری‌های پس‌زمینه
# ---------------------------------------------------------------------------
def send_expiry_reminders():
    now = now_dt()
    target = now + timedelta(days=REMINDER_DAYS_BEFORE)
    rows = db_execute("""
        SELECT id,user_id,plan_label,expires_at FROM orders
        WHERE status='confirmed' AND expiry_reminded=FALSE AND expires_at IS NOT NULL
          AND expires_at <= %s AND expires_at > %s
    """, (target, now), "all") or []
    for oid, uid, label, expires in rows:
        send_message(uid, f"⏰ یادآوری: سرویس «{label}» حدود {REMINDER_DAYS_BEFORE} روز دیگر منقضی می‌شود.\nبرای تمدید از گزینه «{RENEW_BUTTON_TEXT}» استفاده کنید.")
        db_execute("UPDATE orders SET expiry_reminded=TRUE WHERE id=%s", (oid,))


def remind_admin_pending():
    cutoff = now_dt() - timedelta(minutes=PENDING_REMIND_MINUTES)
    rows = db_execute("""
        SELECT id,plan_label,price,user_id FROM orders
        WHERE status='pending' AND admin_reminded=FALSE AND created_ts <= %s
        ORDER BY id LIMIT 20
    """, (cutoff,), "all") or []
    if rows:
        lines = ["⏳ چند سفارش هنوز بررسی نشده‌اند:"]
        for oid, label, price, uid in rows:
            lines.append(f"#{oid} — {label} — {price} — کاربر {uid}")
            db_execute("UPDATE orders SET admin_reminded=TRUE WHERE id=%s", (oid,))
        lines.append("\nفیش‌ها در PV ادمین هستند؛ برای بررسی جزئیات /pending را بزنید.")
        send_message(ADMIN_CHAT_ID, "\n".join(lines))


def background_loop():
    time.sleep(15)
    while True:
        try:
            send_expiry_reminders()
            remind_admin_pending()
        except Exception as exc:
            print(f"background error: {exc}", file=sys.stderr)
        time.sleep(BACKGROUND_INTERVAL)

# ---------------------------------------------------------------------------
# Flask / Webhook / Health
# ---------------------------------------------------------------------------
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return "Bale bot is running on Render.", 200

@app.route("/health", methods=["GET"])
def health():
    try:
        db_execute("SELECT 1", fetch="one")
        return {"ok": True, "database": "connected"}, 200
    except Exception as exc:
        return {"ok": False, "database": str(exc)}, 503

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    try:
        if data.get("message"):
            message = data["message"]
            text = (message.get("text") or "").strip()
            if text.startswith("/") and handle_admin_command(message, text):
                return "OK", 200
            handle_text_message(message)
        elif data.get("callback_query"):
            handle_callback(data["callback_query"])
    except Exception as exc:
        print(f"update processing error: {exc}", file=sys.stderr)
    return "OK", 200


def configure_webhook():
    if not WEBHOOK_URL:
        return
    try:
        result = requests.get(f"{BASE_URL}/setWebhook", params={"url": WEBHOOK_URL}, timeout=15)
        print("setWebhook:", result.text)
    except Exception as exc:
        print(f"setWebhook error: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# شروع برنامه
# ---------------------------------------------------------------------------
try:
    init_db()
except Exception as exc:
    print(f"Database initialization failed: {exc}", file=sys.stderr)

threading.Thread(target=background_loop, daemon=True).start()
threading.Thread(target=configure_webhook, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
