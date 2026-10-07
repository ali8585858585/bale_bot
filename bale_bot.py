import os
import re
import html
import time
import math
import logging
import psycopg
import requests
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger("hobab-bale-bot")

# ---------------------------------------------------------------------------
# تنظیمات اصلی
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("BALE_TOKEN", "1121828278:4xf2bRX0-WtnP0kbOGT30RKSjzjq0ZwRzIE")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook/{TOKEN}" if RENDER_EXTERNAL_HOSTNAME else ""

ADMIN_ID = 52937597  # شناسه عددی ادمین در بله
ADMIN_USERNAME = "Hobabadmin"

BALANCE_BOT_LINK = "https://t.me/reportvolume_bot"

CARD_NUMBER = "5022 2913 3683 0904"
CARD_HOLDER = "علی باقری فرد"

RENEWAL_USERNAME_PATTERN = re.compile(r"^provpn[0-9]+$")

# ---------------------------------------------------------------------------
# تعریف پلن‌ها
# ---------------------------------------------------------------------------
PLANS = {
    "single": {
        "title": "🌀 تک کاربره",
        "subcats": {
            "m1": {
                "title": "✨ یک ماهه",
                "items": [
                    {"id": "s_m1_20", "label": "یکماه تک کاربر ۲۰ گیگ", "toman": 260},
                    {"id": "s_m1_40", "label": "یکماه تک کاربر ۴۰ گیگ", "toman": 420, "recommended": True},
                    {"id": "s_m1_60", "label": "یکماه تک کاربر ۶۰ گیگ", "toman": 550},
                    {"id": "s_m1_100", "label": "یکماه تک کاربر ۱۰۰ گیگ", "toman": 690},
                ],
            },
            "m3": {
                "title": "✨ سه ماهه",
                "items": [
                    {"id": "s_m3_100", "label": "سه ماه تک کاربر ۱۰۰ گیگ", "toman": 1190, "recommended": True},
                    {"id": "s_m3_150", "label": "سه ماه تک کاربر ۱۵۰ گیگ", "toman": 1390},
                    {"id": "s_m3_180", "label": "سه ماه تک کاربر ۱۸۰ گیگ", "toman": 1590},
                ],
            },
        },
    },
    "double": {
        "title": "🌀 دو کاربره",
        "subcats": {
            "m1": {
                "title": "✨ یک ماهه",
                "items": [
                    {"id": "d_m1_40", "label": "یکماه دو کاربر ۴۰ گیگ", "toman": 590},
                    {"id": "d_m1_60", "label": "یکماه دو کاربر ۶۰ گیگ", "toman": 720},
                    {"id": "d_m1_80", "label": "یکماه دو کاربر ۸۰ گیگ", "toman": 800, "recommended": True},
                    {"id": "d_m1_100", "label": "یکماه دو کاربر ۱۰۰ گیگ", "toman": 890},
                ],
            },
            "m3": {
                "title": "✨ سه ماهه",
                "items": [
                    {"id": "d_m3_100", "label": "سه ماه دو کاربر ۱۰۰ گیگ", "toman": 1490},
                    {"id": "d_m3_200", "label": "سه ماه دو کاربر ۲۰۰ گیگ", "toman": 1990},
                    {"id": "d_m3_360", "label": "سه ماه دو کاربر ۳۶۰ گیگ", "toman": 2390, "recommended": True},
                ],
            },
        },
    },
}

BUY_BUTTON_TEXT = "🛒 خرید اشتراک"
RENEW_BUTTON_TEXT = "🔄 تمدید سرور"
PRICE_LIST_BUTTON_TEXT = "📋 لیست قیمت‌ها"
MY_SERVICES_BUTTON_TEXT = "📦 سرویس‌های من"
CHECK_BALANCE_BUTTON_TEXT = "📊 چک کردن مانده سرویس"
SUPPORT_BUTTON_TEXT = "🎧 پشتیبانی"
HOME_BUTTON_TEXT = "🏠 منوی اصلی"

# ---------------------------------------------------------------------------
# ابزارهای محاسباتی و زمان
# ---------------------------------------------------------------------------
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))
PERSIAN_TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

def now_dt() -> datetime:
    return datetime.now(TEHRAN_TZ).replace(tzinfo=None)

def _now() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M")

def to_persian_digits(text: str) -> str:
    return str(text).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

def format_toman(amount: int) -> str:
    return f"{to_persian_digits(f'{amount:,}')} تومن"

def format_rial(amount_toman: int) -> str:
    rial = amount_toman * 10_000
    return f"{to_persian_digits(f'{rial:,}')} ریال"

def parse_int(text: str) -> int:
    digits = re.sub(r"\D", "", (text or "").translate(PERSIAN_TO_EN))
    return int(digits) if digits else 0

def find_plan(plan_id: str):
    for cat_key, category in PLANS.items():
        for sub_key, sub in category["subcats"].items():
            for item in sub["items"]:
                if item["id"] == plan_id:
                    return cat_key, sub_key, item
    return None, None, None

def build_full_price_list_text() -> str:
    lines = [
        "💎 **لیست کلی تعرفه‌های اشتراک طرح پرو** 💎",
        "🔥 = پلن پیشنهادی ما",
        "────────────────────",
        "",
    ]
    for cat_key in ("single", "double"):
        cat = PLANS[cat_key]
        lines.append(f"📌 **{cat['title']}**")
        lines.append("")
        for sub_key in ("m1", "m3"):
            sub = cat["subcats"][sub_key]
            lines.append(f"  🔹 {sub['title']}:")
            for item in sub["items"]:
                mark = "  🔥 (پیشنهادی)" if item.get("recommended") else ""
                lines.append(f"     • {item['label']} ── 💰 **{format_toman(item['toman'])}**{mark}")
            lines.append("")
        lines.append("────────────────────")
        lines.append("")
    lines.append("📢 پشتیبانی: @Hobabadmin")
    return "\n".join(lines).strip()

# ---------------------------------------------------------------------------
# مدیریت دیتابیس Postgres (Neon)
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

def _db_execute(query: str, params: tuple = (), fetch: str = None):
    if not DATABASE_URL:
        raise RuntimeError("متغیر محیطی DATABASE_URL تنظیم نشده است.")
    last_exc = None
    for _attempt in range(2):
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
            logger.warning("DB connection problem, retrying: %s", exc)
            time.sleep(1)
    raise last_exc

def init_db():
    _db_execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            plan_label TEXT NOT NULL,
            price TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            duration_days INTEGER,
            amount_toman INTEGER,
            created_ts TIMESTAMP,
            confirmed_at TIMESTAMP,
            expires_at TIMESTAMP,
            renewal_username TEXT
        )
        """
    )
    _db_execute(
        """
        CREATE TABLE IF NOT EXISTS user_state (
            user_id BIGINT PRIMARY KEY,
            pending_plan_id TEXT,
            renewal_username TEXT,
            awaiting_username BOOLEAN DEFAULT FALSE,
            username_attempts INTEGER DEFAULT 0,
            updated_at TEXT
        )
        """
    )
    _db_execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            first_seen TEXT,
            blocked BOOLEAN NOT NULL DEFAULT FALSE
        )
        """
    )
    _db_execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    apply_saved_settings()

def apply_saved_settings():
    global CARD_NUMBER, CARD_HOLDER
    rows = _db_execute("SELECT key, value FROM settings", (), "all") or []
    for key, value in rows:
        if key == "card_number":
            CARD_NUMBER = value
        elif key == "card_holder":
            CARD_HOLDER = value
        elif key.startswith("price_"):
            _, _, item = find_plan(key[len("price_"):])
            if item:
                try:
                    item["toman"] = int(value)
                except ValueError:
                    pass

def register_user(user_id: int, full_name: str, username: str):
    try:
        _db_execute(
            "INSERT INTO users (user_id, full_name, username, first_seen, blocked) "
            "VALUES (%s, %s, %s, %s, FALSE) "
            "ON CONFLICT (user_id) DO UPDATE SET full_name = EXCLUDED.full_name, "
            "username = EXCLUDED.username, blocked = FALSE",
            (user_id, full_name, username, _now()),
        )
    except Exception:
        logger.exception("register_user failed for user %s", user_id)

# ---------------------------------------------------------------------------
# API بله
# ---------------------------------------------------------------------------
def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    headers = {"Content-Type": "application/json"}
    try:
        r = requests.post(f"{BASE_URL}/sendMessage", json=payload, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"sendMessage exception: {e}")
        return None

def edit_message_text(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    headers = {"Content-Type": "application/json"}
    try:
        r = requests.post(f"{BASE_URL}/editMessageText", json=payload, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"editMessageText exception: {e}")
        return None

def answer_callback_query(callback_query_id, text=None):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = True
    try:
        requests.post(f"{BASE_URL}/answerCallbackQuery", json=payload, timeout=5)
    except Exception as e:
        logger.error(f"answerCallbackQuery exception: {e}")

# ---------------------------------------------------------------------------
# کیبوردها
# ---------------------------------------------------------------------------
def persistent_keyboard():
    return {
        "keyboard": [
            [{"text": BUY_BUTTON_TEXT}, {"text": RENEW_BUTTON_TEXT}],
            [{"text": PRICE_LIST_BUTTON_TEXT}, {"text": MY_SERVICES_BUTTON_TEXT}],
            [{"text": CHECK_BALANCE_BUTTON_TEXT}, {"text": SUPPORT_BUTTON_TEXT}],
            [{"text": HOME_BUTTON_TEXT}],
        ],
        "resize_keyboard": True
    }

def main_menu_inline():
    return {
        "inline_keyboard": [
            [{"text": "🛒 خرید اشتراک", "callback_data": "plans"}],
            [{"text": "🔄 تمدید سرور", "callback_data": "renew"}],
            [{"text": "📋 لیست قیمت‌ها", "callback_data": "all_prices"}],
            [{"text": "📦 سرویس‌های من", "callback_data": "my_services"}],
            [{"text": "📊 چک کردن مانده سرویس", "callback_data": "check_balance"}],
            [{"text": "🎧 پشتیبانی", "callback_data": "support"}]
        ]
    }

def plans_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔥 پلن‌های پیشنهادی", "callback_data": "recommended"}],
            [{"text": "🌀 تک کاربره", "callback_data": "cat_single"}],
            [{"text": "🌀 دو کاربره", "callback_data": "cat_double"}],
            [{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "back"}]
        ]
    }

# ---------------------------------------------------------------------------
# پردازش جریان‌ها و پیام‌ها
# ---------------------------------------------------------------------------
def reset_user_state(user_id):
    _db_execute(
        "INSERT INTO user_state (user_id, awaiting_username, username_attempts, pending_plan_id, renewal_username, updated_at) "
        "VALUES (%s, FALSE, 0, NULL, NULL, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET awaiting_username = FALSE, username_attempts = 0, "
        "pending_plan_id = NULL, updated_at = EXCLUDED.updated_at",
        (user_id, _now())
    )

def handle_renewal_username(chat_id, text, user_info):
    row = _db_execute("SELECT awaiting_username, username_attempts FROM user_state WHERE user_id = %s", (chat_id,), "one")
    if not row or not row[0]:
        return False

    username_input = (text or "").strip()

    if RENEWAL_USERNAME_PATTERN.match(username_input):
        _db_execute(
            "UPDATE user_state SET awaiting_username = FALSE, username_attempts = 0, renewal_username = %s, updated_at = %s WHERE user_id = %s",
            (username_input, _now(), chat_id)
        )
        send_message(chat_id, f"✅ نام کاربری شما با موفقیت تایید شد! (`{username_input}`)")
        send_message(chat_id, "لطفاً نوع اشتراک مورد نظر خود جهت تمدید را انتخاب کنید:", plans_keyboard())
        return True

    attempts = (row[1] or 0) + 1
    _db_execute("UPDATE user_state SET username_attempts = %s WHERE user_id = %s", (attempts, chat_id))

    base_text = "❌ نام کاربری شما اشتباه است!\n\nلطفاً دوباره با فرمت صحیح ارسال کنید، مثلاً:\nprovpn27"
    if attempts >= 2:
        kb = {"inline_keyboard": [[{"text": "💬 ارتباط با پشتیبانی", "url": f"https://ble.ir/{ADMIN_USERNAME}"}]]}
        send_message(chat_id, base_text + "\n\nاگر در تایید نام کاربری مشکلی پیش آمده به پشتیبانی پیام دهید.", kb)
    else:
        send_message(chat_id, base_text)
    return True

def process_update(update):
    message = update.get("message") or update.get("edited_message")
    if message:
        chat_id = message.get("chat", {}).get("id")
        user_info = message.get("from", {})
        text = message.get("text", "").strip()

        if chat_id:
            register_user(chat_id, user_info.get("first_name", ""), user_info.get("username", ""))

        # دستورات ادمین
        if chat_id == ADMIN_ID and text.startswith("/"):
            if text == "/stats":
                total = _db_execute("SELECT COUNT(*), COALESCE(SUM(amount_toman), 0) FROM orders WHERE status = 'confirmed'", (), "one")
                users = _db_execute("SELECT COUNT(*) FROM users", (), "one")
                send_message(ADMIN_ID, f"📊 آمار فروش:\n\nکل سفارشات تایید شده: {to_persian_digits(total[0])}\nمجموع فروش: {format_toman(total[1])}\nتعداد کاربران: {to_persian_digits(users[0])}")
                return
            elif text == "/prices":
                lines = ["💰 لیست پلن‌ها:"]
                for cat in PLANS.values():
                    for sub in cat["subcats"].values():
                        for item in sub["items"]:
                            lines.append(f"`{item['id']}` — {item['label']} — {format_toman(item['toman'])}")
                send_message(ADMIN_ID, "\n".join(lines))
                return

        if text in ["/start", HOME_BUTTON_TEXT, "start"]:
            reset_user_state(chat_id)
            send_message(chat_id, "سلام! به ربات حباب خوش آمدید 😉\nجهت خرید یا تمدید سرور OpenConnect در خدمتیم.", persistent_keyboard())
            send_message(chat_id, "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:", main_menu_inline())
            return

        if text == BUY_BUTTON_TEXT:
            reset_user_state(chat_id)
            send_message(chat_id, "🛒 **بخش خرید اشتراک**\n\nلطفاً نوع اشتراک مورد نظر خود را انتخاب کنید:", plans_keyboard())
            return

        if text == RENEW_BUTTON_TEXT:
            reset_user_state(chat_id)
            _db_execute("INSERT INTO user_state (user_id, awaiting_username, updated_at) VALUES (%s, TRUE, %s) ON CONFLICT (user_id) DO UPDATE SET awaiting_username = TRUE", (chat_id, _now()))
            send_message(chat_id, "🔄 **تمدید سرور**\n\nلطفاً نام کاربری سرور خود را ارسال کنید (مثال: `provpn27`):", persistent_keyboard())
            return

        if text == PRICE_LIST_BUTTON_TEXT:
            reset_user_state(chat_id)
            send_message(chat_id, build_full_price_list_text())
            return

        if text == MY_SERVICES_BUTTON_TEXT:
            reset_user_state(chat_id)
            orders = _db_execute("SELECT plan_label, price, created_at FROM orders WHERE user_id = %s AND status = 'confirmed' ORDER BY id DESC", (chat_id,), "all") or []
            if not orders:
                send_message(chat_id, "📦 هنوز هیچ سرویس فعالی برای شما ثبت نشده است.")
            else:
                lines = ["📦 **سرویس‌های فعال شما:**\n"]
                for label, price, created_at in orders:
                    lines.append(f"✅ **{label}** — {price}\n🗓 تاریخ: {created_at}\n")
                send_message(chat_id, "\n".join(lines))
            return

        if text == CHECK_BALANCE_BUTTON_TEXT:
            reset_user_state(chat_id)
            kb = {"inline_keyboard": [[{"text": "📊 چک کردن مانده", "url": BALANCE_BOT_LINK}]]}
            send_message(chat_id, "📊 برای بررسی مانده سرویس، روی دکمه زیر کلیک کنید:", kb)
            return

        if text == SUPPORT_BUTTON_TEXT:
            reset_user_state(chat_id)
            kb = {"inline_keyboard": [[{"text": "💬 ارتباط با پشتیبانی", "url": f"https://ble.ir/{ADMIN_USERNAME}"}]]}
            send_message(chat_id, "🎧 برای دریافت پشتیبانی، روی دکمه زیر کلیک کنید:", kb)
            return

        if handle_renewal_username(chat_id, text, user_info):
            return

    cb = update.get("callback_query")
    if cb:
        cb_id = cb.get("id")
        cb_data = cb.get("data", "")
        msg = cb.get("message", {})
        msg_id = msg.get("message_id")
        chat_id = msg.get("chat", {}).get("id")
        user_info = cb.get("from", {})

        if cb_id:
            answer_callback_query(cb_id)
        if not chat_id:
            return

        if cb_data == "plans":
            edit_message_text(chat_id, msg_id, "🛒 **بخش خرید اشتراک**\n\nلطفاً نوع اشتراک مورد نظر را انتخاب کنید:", plans_keyboard())

        elif cb_data == "all_prices":
            edit_message_text(chat_id, msg_id, build_full_price_list_text())

        elif cb_data.startswith("cat_"):
            cat_key = cb_data.replace("cat_", "")
            if cat_key in PLANS:
                kb = {
                    "inline_keyboard": [
                        [{"text": "✨ یک ماهه", "callback_data": f"sub_{cat_key}_m1"}],
                        [{"text": "✨ سه ماهه", "callback_data": f"sub_{cat_key}_m3"}],
                        [{"text": "🔙 بازگشت", "callback_data": "plans"}]
                    ]
                }
                edit_message_text(chat_id, msg_id, f"✨ **{PLANS[cat_key]['title']}**\n\nمدت زمان را انتخاب کنید:", kb)

        elif cb_data.startswith("sub_"):
            _, cat_key, sub_key = cb_data.split("_", 2)
            sub = PLANS[cat_key]["subcats"][sub_key]
            rows = []
            for item in sub["items"]:
                prefix = "🔥 " if item.get("recommended") else ""
                rows.append([{"text": f"{prefix}{item['label']} — {format_toman(item['toman'])}", "callback_data": f"buy_{item['id']}"}])
            rows.append([{"text": "🔙 بازگشت", "callback_data": f"cat_{cat_key}"}])
            edit_message_text(chat_id, msg_id, f"⚡️ **{PLANS[cat_key]['title']} — {sub['title']}**\n\nپلن مورد نظر را انتخاب کنید:", {"inline_keyboard": rows})

        elif cb_data.startswith("buy_"):
            plan_id = cb_data.replace("buy_", "")
            cat_key, sub_key, plan = find_plan(plan_id)
            if plan:
                state_row = _db_execute("SELECT renewal_username FROM user_state WHERE user_id = %s", (chat_id,), "one")
                renewal_username = state_row[0] if state_row else None
                renewal_note = f"🔄 **نام کاربری جهت تمدید:** `{renewal_username}`\n\n" if renewal_username else ""

                text = (
                    f"{renewal_note}"
                    f"✅ **پلن انتخابی:** {plan['label']}\n"
                    f"💰 **مبلغ:** {format_toman(plan['toman'])}\n"
                    f"💱 **معادل ریالی:** {format_rial(plan['toman'])}\n\n"
                    f"────────────────────\n"
                    f"💳 **شماره کارت جهت واریز:**\n"
                    f"`{CARD_NUMBER}`\n"
                    f"👤 **به نام:** {CARD_HOLDER}\n"
                    f"────────────────────\n\n"
                    f"⚠️ **توجه:** پس از پرداخت، لطفاً **عکس رسید واریز** را همراه با اطلاعات زیر مستقیماً به پی‌وی پشتیبانی ارسال کنید:\n\n"
                    f"🆔 **آیدی (Chat ID) شما:** `{chat_id}`"
                )
                
                kb = {"inline_keyboard": [
                    [{"text": "💬 ارسال رسید به پی‌وی پشتیبانی", "url": f"https://ble.ir/{ADMIN_USERNAME}"}],
                    [{"text": "🔙 بازگشت", "callback_data": f"sub_{cat_key}_{sub_key}"}]
                ]}
                edit_message_text(chat_id, msg_id, text, kb)

                # ثبت سفارش اولیه و ارسال پیام به ادمین همراه با دکمه تایید
                order_id = _db_execute(
                    "INSERT INTO orders (user_id, plan_label, price, status, created_at, created_ts, amount_toman, duration_days, renewal_username) "
                    "VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s) RETURNING id",
                    (chat_id, plan['label'], format_toman(plan['toman']), _now(), now_dt(), plan['toman'], 30 if sub_key == 'm1' else 90, renewal_username),
                    "one"
                )[0]

                admin_msg = (
                    f"🔔 **درخواست سفارش جدید (#{order_id})**\n\n"
                    f"👤 **کاربر:** {user_info.get('first_name', '')} (@{user_info.get('username', 'ندارد')})\n"
                    f"🆔 **Chat ID:** `{chat_id}`\n"
                    f"{'🔄 نام کاربری تمدید: `' + str(renewal_username) + '`\n' if renewal_username else ''}"
                    f"📦 **پلن:** {plan['label']}\n"
                    f"💰 **مبلغ:** {format_toman(plan['toman'])}\n\n"
                    f"کاربر برای ارسال رسید به پی‌وی هدایت شد. پس از دریافت فیش و تایید، دکمه زیر را بزنید:"
                )
                admin_kb = {"inline_keyboard": [[{"text": "✅ تایید و فعال‌سازی سرویس", "callback_data": f"approve_{order_id}"}]]}
                send_message(ADMIN_ID, admin_msg, admin_kb)

        elif cb_data.startswith("approve_"):
            if chat_id != ADMIN_ID:
                return
            order_id = int(cb_data.split("_")[1])
            order = _db_execute("SELECT user_id, plan_label FROM orders WHERE id = %s AND status = 'pending'", (order_id,), "one")
            if order:
                _db_execute("UPDATE orders SET status = 'confirmed', confirmed_at = %s WHERE id = %s", (now_dt(), order_id))
                target_user, plan_label = order[0], order[1]
                edit_message_text(chat_id, msg_id, f"✅ **سفارش #{order_id} تایید و فعال گردید.**")
                send_message(target_user, f"✅ پرداخت شما تایید شد! سرویس «{plan_label}» با موفقیت فعال گردید.")
            else:
                answer_callback_query(cb_id, "این سفارش قبلاً تعیین تکلیف شده است.")

        elif cb_data == "back":
            reset_user_state(chat_id)
            edit_message_text(chat_id, msg_id, "🏠 منوی اصلی:", main_menu_inline())

app = Flask(__name__)
init_db()

@app.route("/", methods=["GET"])
def index():
    return "Bale Bot running with Neon DB."

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)
    if data:
        process_update(data)
    return "OK", 200

if WEBHOOK_URL:
    try:
        requests.get(f"{BASE_URL}/setWebhook?url={WEBHOOK_URL}", timeout=10)
    except Exception:
        pass

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
