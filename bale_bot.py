import os
import re
import sys
import time
import math
import threading
from datetime import datetime, timedelta, timezone

import psycopg
import requests
from flask import Flask, request

# ---------------------------------------------------------------------------
# تنظیمات اصلی (توکن و اطلاعات بله حفظ شده)
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("BALE_TOKEN", "1121828278:4xf2bRX0-WtnP0kbOGT30RKSjzjq0ZwRzIE")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook/{TOKEN}" if RENDER_EXTERNAL_HOSTNAME else ""

DATABASE_URL = os.environ.get("DATABASE_URL")

ADMIN_USERNAME = "Hobabadmin"
ADMIN_CHAT_ID = 52937597  # شناسه چت ادمین در بله

BALANCE_BOT_LINK = "https://t.me/reportvolume_bot"

CARD_NUMBER = "5022-2913-3683-0904"
CARD_HOLDER = "علی باقری فرد"

# عضویت اجباری در کانال (اگر ربات در کانال ادمین نباشد، بررسی انجام نمی‌شود و کاربر قفل نمی‌شود)
CHANNEL_USERNAME = "HobabServices"
FORCE_JOIN = True  # عضویت اجباری همیشه فعال است

RENEWAL_USERNAME_PATTERN = re.compile(r"^provpn[0-9]+$")

BUY_BUTTON_TEXT = "🛒 خرید اشتراک"
RENEW_BUTTON_TEXT = "🔄 تمدید سرور"
PRICE_LIST_BUTTON_TEXT = "📋 لیست قیمت‌ها"
MY_SERVICES_BUTTON_TEXT = "📦 سرویس‌های من"
CHECK_BALANCE_BUTTON_TEXT = "📊 چک کردن مانده سرویس"
SUPPORT_BUTTON_TEXT = "🎧 پشتیبانی"
HOME_BUTTON_TEXT = "🏠 منوی اصلی"

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))
PERSIAN_TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
DURATION_DAYS = {"monthly": 30, "quarterly": 90}
REMINDER_DAYS_BEFORE = 3
PENDING_REMIND_MINUTES = 30
BACKGROUND_INTERVAL = 3600


def log(*args):
    print(*args, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# ابزارهای کمکی
# ---------------------------------------------------------------------------
_EN2FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(n) -> str:
    return f"{int(n):,}".translate(_EN2FA)


def fa_digits(text) -> str:
    return str(text).translate(_EN2FA)


def price_toman_text(price_thousand_toman: int) -> str:
    return f"{fa_num(price_thousand_toman)} تومن"


def price_rial_text(price_thousand_toman: int) -> str:
    return f"{fa_num(price_thousand_toman * 10_000)} ریال"


def now_dt() -> datetime:
    """زمان فعلی به وقت تهران (بدون tzinfo)."""
    return datetime.now(TEHRAN_TZ).replace(tzinfo=None)


def now_str() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M")


def parse_int(text) -> int:
    digits = re.sub(r"\D", "", (text or "").translate(PERSIAN_TO_EN))
    return int(digits) if digits else 0


def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


# ---------------------------------------------------------------------------
# پلن‌ها (قیمت‌ها و آیدی‌های نسخه‌ی بله؛ قیمت به هزار تومان)
# ---------------------------------------------------------------------------
PLANS = {
    "single": {
        "title": "🌀 تک کاربره",
        "subcategories": {
            "monthly": {
                "title": "✨ یک ماهه",
                "items": [
                    {"id": "sm1", "label": "یک ماه تک کاربر ۲۰ گیگ", "price": 240},
                    {"id": "sm2", "label": "یک ماه تک کاربر ۴۰ گیگ", "price": 420, "recommended": True},
                    {"id": "sm3", "label": "یک ماه تک کاربر ۶۰ گیگ", "price": 550},
                    {"id": "sm4", "label": "یک ماه تک کاربر ۱۰۰ گیگ", "price": 690},
                ],
            },
            "quarterly": {
                "title": "✨ سه ماهه",
                "items": [
                    {"id": "sq1", "label": "سه ماه تک کاربر ۱۰۰ گیگ", "price": 990, "recommended": True},
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
                    {"id": "dm3", "label": "یک ماه دو کاربر ۸۰ گیگ", "price": 750, "recommended": True},
                    {"id": "dm4", "label": "یک ماه دو کاربر ۱۰۰ گیگ", "price": 890},
                ],
            },
            "quarterly": {
                "title": "✨ سه ماهه",
                "items": [
                    {"id": "dq1", "label": "سه ماه دو کاربر ۱۰۰ گیگ", "price": 1190},
                    {"id": "dq2", "label": "سه ماه دو کاربر ۲۰۰ گیگ", "price": 1790},
                    {"id": "dq3", "label": "سه ماه دو کاربر ۳۶۰ گیگ", "price": 2090, "recommended": True},
                ],
            },
        },
    },
}


def find_plan(plan_id: str):
    for cat_key, cat in PLANS.items():
        for sub_key, sub in cat["subcategories"].items():
            for item in sub["items"]:
                if item["id"] == plan_id:
                    return item, cat_key, sub_key
    return None, None, None


def get_recommended_plans():
    result = []
    for cat in PLANS.values():
        for sub in cat["subcategories"].values():
            for item in sub["items"]:
                if item.get("recommended"):
                    result.append(item)
    return result


def plan_button_text(item) -> str:
    prefix = "🔥 (پیشنهادی) " if item.get("recommended") else ""
    return f"{prefix}{item['label']} — {price_toman_text(item['price'])}"


def get_full_price_list_text() -> str:
    lines = ["💎 لیست کلی تعرفه‌های اشتراک طرح پرو 💎", "🔥 = پلن پیشنهادی ما", "────────────────────", ""]
    for cat_key in ("single", "double"):
        cat = PLANS[cat_key]
        lines.append(f"📌 {cat['title']}")
        lines.append("")
        for sub_key in ("monthly", "quarterly"):
            sub = cat["subcategories"][sub_key]
            lines.append(f"🔹 {sub['title']}:")
            for item in sub["items"]:
                mark = "  🔥 (پیشنهادی)" if item.get("recommended") else ""
                lines.append(f"• {item['label']} ── 💰 {price_toman_text(item['price'])}{mark}")
            lines.append("")
        lines.append("────────────────────")
        lines.append("")
    lines.append(f"📢 کانال ما: @{CHANNEL_USERNAME}")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# دیتابیس (Postgres روی Neon)
# ---------------------------------------------------------------------------
def db(query: str, params: tuple = (), fetch: str = None):
    """اجرای یک کوئری؛ یک بار تلاش مجدد برای زمانی که دیتابیس Neon تازه از خواب بیدار می‌شود."""
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
            log("DB connection problem, retrying:", exc)
            time.sleep(1)
    raise last_exc


def init_db():
    db(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            plan_label TEXT NOT NULL,
            price TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            created_ts TIMESTAMP,
            amount_toman INTEGER,
            duration_days INTEGER,
            confirmed_at TIMESTAMP,
            expires_at TIMESTAMP,
            renewal_username TEXT,
            expiry_reminded BOOLEAN NOT NULL DEFAULT FALSE,
            admin_reminded BOOLEAN NOT NULL DEFAULT FALSE
        )
        """
    )
    db(
        """
        CREATE TABLE IF NOT EXISTS user_state (
            user_id BIGINT PRIMARY KEY,
            awaiting_username BOOLEAN NOT NULL DEFAULT FALSE,
            username_attempts INTEGER NOT NULL DEFAULT 0,
            pending_plan_id TEXT,
            renewal_username TEXT,
            updated_at TEXT
        )
        """
    )
    db(
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
    db(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    apply_saved_settings()


def apply_saved_settings():
    """قیمت‌ها، شماره کارت و نام صاحب کارت ذخیره‌شده در دیتابیس را اعمال می‌کند."""
    global CARD_NUMBER, CARD_HOLDER
    rows = db("SELECT key, value FROM settings", (), "all") or []
    for key, value in rows:
        if key == "card_number":
            CARD_NUMBER = value
        elif key == "card_holder":
            CARD_HOLDER = value
        elif key.startswith("price_"):
            item, _, _ = find_plan(key[len("price_"):])
            if item:
                try:
                    item["price"] = int(value)
                except ValueError:
                    pass


def set_setting(key: str, value: str):
    db(
        "INSERT INTO settings (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, value),
    )


# ---------- وضعیت موقت کاربر (در دیتابیس تا با ری‌استارت سرور از بین نرود) ----------
def get_state(user_id: int) -> dict:
    try:
        row = db(
            "SELECT awaiting_username, username_attempts, pending_plan_id, renewal_username "
            "FROM user_state WHERE user_id = %s",
            (user_id,), "one",
        )
    except Exception as exc:
        log("get_state failed:", exc)
        row = None
    if not row:
        return {"awaiting_username": False, "username_attempts": 0, "pending_plan_id": None, "renewal_username": None}
    return {
        "awaiting_username": row[0], "username_attempts": row[1],
        "pending_plan_id": row[2], "renewal_username": row[3],
    }


_STATE_FIELDS = ("awaiting_username", "username_attempts", "pending_plan_id", "renewal_username")


def set_state(user_id: int, **fields):
    fields = {k: v for k, v in fields.items() if k in _STATE_FIELDS}
    if not fields:
        return
    cols = list(fields.keys())
    try:
        db(
            f"INSERT INTO user_state (user_id, {', '.join(cols)}, updated_at) "
            f"VALUES (%s, {', '.join(['%s'] * len(cols))}, %s) "
            f"ON CONFLICT (user_id) DO UPDATE SET "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols) + ", updated_at = EXCLUDED.updated_at",
            (user_id, *fields.values(), now_str()),
        )
    except Exception as exc:
        log("set_state failed:", exc)


def reset_state(user_id: int):
    try:
        db("DELETE FROM user_state WHERE user_id = %s", (user_id,))
    except Exception as exc:
        log("reset_state failed:", exc)


# ---------- کاربران ----------
_seen_users = set()


def register_user(user: dict):
    uid = user.get("id")
    if not uid or uid in _seen_users:
        return
    full_name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or None
    try:
        db(
            "INSERT INTO users (user_id, full_name, username, first_seen, blocked) VALUES (%s, %s, %s, %s, FALSE) "
            "ON CONFLICT (user_id) DO UPDATE SET full_name = EXCLUDED.full_name, "
            "username = EXCLUDED.username, blocked = FALSE",
            (uid, full_name, user.get("username"), now_str()),
        )
        _seen_users.add(uid)
    except Exception as exc:
        log("register_user failed:", exc)


# ---------- سفارش‌ها ----------
def create_order(user_id, plan_label, price_text, amount_thousand, duration_days, renewal_username) -> int:
    row = db(
        "INSERT INTO orders (user_id, plan_label, price, status, created_at, created_ts, amount_toman, "
        "duration_days, renewal_username) VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s) RETURNING id",
        (user_id, plan_label, price_text, now_str(), now_dt(), amount_thousand, duration_days, renewal_username),
        "one",
    )
    return row[0]


def get_order(order_id: int):
    row = db(
        "SELECT id, user_id, plan_label, price, status, created_at, duration_days "
        "FROM orders WHERE id = %s", (order_id,), "one",
    )
    if not row:
        return None
    return dict(zip(("id", "user_id", "plan_label", "price", "status", "created_at", "duration_days"), row))


def finalize_order(order_id: int, status: str, duration_days=None) -> bool:
    """فقط اگر سفارش هنوز pending باشد وضعیتش را عوض می‌کند (جلوگیری از تایید/رد دوباره)."""
    now = now_dt()
    confirmed = status == "confirmed"
    expires = now + timedelta(days=duration_days or 30) if confirmed else None
    row = db(
        "UPDATE orders SET status = %s, confirmed_at = %s, expires_at = %s "
        "WHERE id = %s AND status = 'pending' RETURNING id",
        (status, now if confirmed else None, expires, order_id), "one",
    )
    return row is not None


def get_user_services(user_id: int):
    return db(
        "SELECT plan_label, price, created_at, expires_at FROM orders "
        "WHERE user_id = %s AND status = 'confirmed' ORDER BY id DESC",
        (user_id,), "all",
    ) or []


def build_my_services_text(user_id: int) -> str:
    services = get_user_services(user_id)
    if not services:
        return "📦 هنوز سرویس فعالی برای این حساب ثبت نشده است."
    lines = ["📦 **سرویس‌های شما:**\n"]
    for label, price, created_at, expires_at in services:
        end = f"\n⏳ پایان سرویس: {expires_at.strftime('%Y-%m-%d')}" if expires_at else ""
        lines.append(f"✅ **{label}** — {price}\n🗓 تاریخ خرید: {created_at}{end}\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API بله
# ---------------------------------------------------------------------------
def api(method: str, payload: dict, timeout: int = 10):
    try:
        r = requests.post(f"{BASE_URL}/{method}", json=payload, timeout=timeout)
        return r.json()
    except Exception as exc:
        log(f"{method} exception: {exc}")
        return None


def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return api("sendMessage", payload)


def edit_message_text(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return api("editMessageText", payload)


def answer_callback_query(callback_query_id, text=None):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = True
    api("answerCallbackQuery", payload, timeout=5)


def copy_message(chat_id, from_chat_id, message_id):
    return api("copyMessage", {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id})


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
        "resize_keyboard": True,
    }


def main_menu_inline():
    return {"inline_keyboard": [
        [{"text": "🛒 خرید اشتراک", "callback_data": "plans"}],
        [{"text": "🔄 تمدید سرور", "callback_data": "renew"}],
        [{"text": "📋 لیست قیمت‌ها", "callback_data": "all_prices"}],
        [{"text": "📦 سرویس‌های من", "callback_data": "my_services"}],
        [{"text": "📊 چک کردن مانده سرویس", "callback_data": "check_balance"}],
        [{"text": "🎧 پشتیبانی", "callback_data": "support"}],
    ]}


def plans_keyboard():
    return {"inline_keyboard": [
        [{"text": "🔥 پلن‌های پیشنهادی (پرفروش‌ترین‌ها)", "callback_data": "recommended"}],
        [{"text": PLANS["single"]["title"], "callback_data": "cat_single"}],
        [{"text": PLANS["double"]["title"], "callback_data": "cat_double"}],
        [{"text": "📋 لیست کلی قیمت‌ها", "callback_data": "all_prices"}],
        [{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "back"}],
    ]}


def price_list_keyboard():
    return {"inline_keyboard": [
        [{"text": "🛒 خرید اشتراک", "callback_data": "plans"}],
        [{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "back"}],
    ]}


def subcategory_keyboard(cat_key):
    rows = [[{"text": sub["title"], "callback_data": f"sub_{cat_key}_{sub_key}"}]
            for sub_key, sub in PLANS[cat_key]["subcategories"].items()]
    rows.append([{"text": "🔙 بازگشت", "callback_data": "plans"}])
    return {"inline_keyboard": rows}


def items_keyboard(cat_key, sub_key):
    rows = [[{"text": plan_button_text(item), "callback_data": f"buy_{item['id']}"}]
            for item in PLANS[cat_key]["subcategories"][sub_key]["items"]]
    rows.append([{"text": "🔙 بازگشت", "callback_data": f"cat_{cat_key}"}])
    return {"inline_keyboard": rows}


def support_url():
    return f"https://ble.ir/{ADMIN_USERNAME}"


def join_keyboard():
    return {"inline_keyboard": [
        [{"text": "📢 عضویت در کانال", "url": f"https://ble.ir/{CHANNEL_USERNAME}"}],
        [{"text": "✅ عضو شدم", "callback_data": "check_join"}],
    ]}


def order_action_keyboard(order_id: int):
    return {"inline_keyboard": [[
        {"text": "✅ تایید", "callback_data": f"confirm_{order_id}"},
        {"text": "❌ رد", "callback_data": f"reject_{order_id}"},
    ]]}


# ---------------------------------------------------------------------------
# عضویت اجباری
# ---------------------------------------------------------------------------
_member_cache = {}
_join_warned = False


def is_channel_member(user_id: int, use_cache: bool = True) -> bool:
    global _join_warned
    if use_cache and _member_cache.get(user_id, 0) > time.time():
        return True
    res = api("getChatMember", {"chat_id": f"@{CHANNEL_USERNAME}", "user_id": user_id})
    if not res or not res.get("ok"):
        # برای اجباری بودن واقعی عضویت، در صورت خطا اجازه عبور نمی‌دهیم.
        if not _join_warned:
            _join_warned = True
            send_message(
                ADMIN_CHAT_ID,
                f"⚠️ بررسی عضویت در @{CHANNEL_USERNAME} ممکن نیست.\n"
                "حتماً ربات را در کانال «ادمین» کنید تا بررسی عضویت انجام شود.",
            )
        return False
    status = (res.get("result") or {}).get("status")
    ok = status in ("member", "administrator", "creator")
    if ok:
        _member_cache[user_id] = time.time() + 600
    return ok


JOIN_TEXT = (
    "🔒 برای استفاده از ربات ابتدا باید در کانال ما عضو شوید:\n"
    f"📢 @{CHANNEL_USERNAME}\n\n"
    "بعد از عضویت روی «✅ عضو شدم» بزنید."
)


# ---------------------------------------------------------------------------
# جریان‌های کاربر
# ---------------------------------------------------------------------------
def show_main_menu(chat_id, greeting=True):
    if greeting:
        send_message(chat_id, "سلام! به ربات حباب خوش آمدید 😉\nجهت خرید یا تمدید سرور OpenConnect در خدمتیم.",
                     persistent_keyboard())
    send_message(chat_id, "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:", main_menu_inline())


def start_renewal_flow(chat_id, message_id=None):
    reset_state(chat_id)
    set_state(chat_id, awaiting_username=True, username_attempts=0)
    text = (
        "🔄 **تمدید سرور**\n\n"
        "لطفاً نام کاربری سرور OpenConnect خود را همینجا ارسال کنید.\n\n"
        "📌 فرمت صحیح: کلمه‌ی `provpn` به همراه یک عدد انگلیسی، مثلاً:\n"
        "`provpn27` ✅\n\n"
        "برای انصراف می‌توانید دستور /cancel را ارسال کنید."
    )
    if message_id:
        edit_message_text(chat_id, message_id, text,
                          {"inline_keyboard": [[{"text": "🔙 بازگشت", "callback_data": "back"}]]})
    else:
        send_message(chat_id, text, persistent_keyboard())


def handle_renewal_username(chat_id, text) -> bool:
    state = get_state(chat_id)
    if not state["awaiting_username"]:
        return False
    username = (text or "").strip()
    if RENEWAL_USERNAME_PATTERN.match(username):
        set_state(chat_id, awaiting_username=False, username_attempts=0, renewal_username=username)
        send_message(chat_id, f"✅ نام کاربری شما با موفقیت تایید شد! (`{username}`)")
        send_message(chat_id, "لطفاً نوع اشتراک مورد نظر خود جهت تمدید را انتخاب کنید:", plans_keyboard())
        return True

    attempts = state["username_attempts"] + 1
    set_state(chat_id, username_attempts=attempts)
    base_text = "❌ نام کاربری شما اشتباه است!\n\nلطفاً دوباره با فرمت صحیح ارسال کنید، مثلاً:\n`provpn27`"
    if attempts >= 2:
        kb = {"inline_keyboard": [[{"text": "💬 ارتباط با پشتیبانی", "url": support_url()}]]}
        send_message(chat_id,
                     base_text + "\n\nاگر در تایید نام کاربری مشکلی برایتان پیش آمده، لطفاً به پشتیبانی پیام دهید.", kb)
    else:
        send_message(chat_id, base_text)
    return True


def payment_text(plan, renewal_username) -> str:
    renewal_note = f"🔄 **نام کاربری جهت تمدید:** `{renewal_username}`\n\n" if renewal_username else ""
    rec_note = "🔥 **انتخاب عالی! این یکی از پلن‌های پیشنهادی ماست.**\n\n" if plan.get("recommended") else ""
    return (
        f"{renewal_note}{rec_note}"
        f"✅ **پلن انتخابی:** {plan['label']}\n"
        f"💰 **مبلغ:** {price_toman_text(plan['price'])}\n"
        f"💱 **معادل ریالی:** {price_rial_text(plan['price'])}\n\n"
        "────────────────────\n"
        "💳 **شماره کارت جهت واریز:**\n"
        f"`{CARD_NUMBER}`\n"
        f"👤 **به نام:** {CARD_HOLDER}\n"
        "────────────────────\n\n"
        "📸 مراحل کار:\n"
        "۱) مبلغ را به کارت بالا واریز کنید.\n"
        "۲) عکس رسید را **در پیوی ادمین** بفرستید (دکمه‌ی «ارسال رسید به ادمین»).\n"
        "۳) برگردید همین‌جا و روی «✅ رسید را فرستادم» بزنید تا سفارش شما برای تایید ثبت شود."
    )


def handle_buy(chat_id, msg_id, plan_id):
    plan, cat_key, sub_key = find_plan(plan_id)
    if not plan:
        edit_message_text(chat_id, msg_id, "❌ این پلن پیدا نشد، دوباره تلاش کن.")
        return
    set_state(chat_id, pending_plan_id=plan_id)
    renewal_username = get_state(chat_id)["renewal_username"]
    kb = {"inline_keyboard": [
        [{"text": "💬 ارسال رسید به ادمین (پیوی)", "url": support_url()}],
        [{"text": "✅ رسید را فرستادم", "callback_data": "paid"}],
        [{"text": "🔙 بازگشت", "callback_data": f"sub_{cat_key}_{sub_key}"}],
    ]}
    edit_message_text(chat_id, msg_id, payment_text(plan, renewal_username), kb)


def handle_paid(chat_id, msg_id, user: dict):
    """کاربر اعلام می‌کند رسید را در پیوی ادمین فرستاده؛ سفارش ثبت و برای ادمین ارسال می‌شود."""
    state = get_state(chat_id)
    plan, _, sub_key = find_plan(state["pending_plan_id"] or "")
    if not plan:
        edit_message_text(
            chat_id, msg_id,
            "⚠️ سفارش فعالی پیدا نشد (احتمالاً قبلاً ثبت شده). از منوی اصلی دوباره پلن را انتخاب کنید.",
            {"inline_keyboard": [[{"text": "🛒 خرید اشتراک", "callback_data": "plans"}]]},
        )
        return
    renewal_username = state["renewal_username"]
    price_text = price_toman_text(plan["price"])
    try:
        order_id = create_order(chat_id, plan["label"], price_text, plan["price"],
                                DURATION_DAYS.get(sub_key, 30), renewal_username)
    except Exception as exc:
        log("create_order failed:", exc)
        send_message(chat_id, "⚠️ ثبت سفارش با خطا مواجه شد. لطفاً به پشتیبانی پیام دهید.",
                     {"inline_keyboard": [[{"text": "💬 ارتباط با پشتیبانی", "url": support_url()}]]})
        return
    reset_state(chat_id)

    edit_message_text(
        chat_id, msg_id,
        f"✅ سفارش شما با شماره #{fa_digits(order_id)} ثبت شد.\n\n"
        "اگر هنوز رسید را برای ادمین نفرستاده‌اید، همین حالا بفرستید و شماره سفارش را هم بنویسید.\n"
        "به محض تایید، اینجا به شما اطلاع داده می‌شود 🙏",
        {"inline_keyboard": [[{"text": "💬 ارسال رسید به ادمین", "url": support_url()}],
                             [{"text": "🏠 منوی اصلی", "callback_data": "back"}]]},
    )

    full_name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "---"
    uname = f"@{user['username']}" if user.get("username") else "---"
    renewal_line = f"🔄 نام کاربری سرور جهت تمدید: `{renewal_username}`\n\n" if renewal_username else ""
    admin_text = (
        f"🔔 **سفارش جدید #{order_id}**\n\n"
        f"👤 کاربر: {full_name}\n"
        f"🆔 آیدی عددی: `{chat_id}`\n"
        f"یوزرنیم: {uname}\n\n"
        f"{renewal_line}"
        f"📦 پلن: **{plan['label']}**\n"
        f"💰 مبلغ: **{price_text}**\n"
        f"💱 معادل ریالی: **{price_rial_text(plan['price'])}**\n\n"
        "ℹ️ کاربر می‌گوید رسید را در پیوی شما فرستاده. بعد از چک کردن، تایید یا رد کنید:"
    )
    send_message(ADMIN_CHAT_ID, admin_text, order_action_keyboard(order_id))
    threading.Timer(PENDING_REMIND_MINUTES * 60 + 5, safe_run, args=(remind_admin_pending,)).start()


def handle_confirm_reject(cb_id, admin_chat, msg, cb_data):
    action, order_id_str = cb_data.split("_", 1)
    order = get_order(int(order_id_str))
    original = msg.get("text", "")
    msg_id = msg.get("message_id")
    if not order:
        edit_message_text(admin_chat, msg_id, original + "\n\n⚠️ این سفارش پیدا نشد.")
        return
    new_status = "confirmed" if action == "confirm" else "rejected"
    if not finalize_order(order["id"], new_status, order.get("duration_days")):
        status_fa = {"confirmed": "تایید", "rejected": "رد"}.get(order["status"], order["status"])
        edit_message_text(admin_chat, msg_id, original + f"\n\n⚠️ این سفارش قبلاً {status_fa} شده است.")
        return
    if action == "confirm":
        user_text = "🎉 پرداخت شما تایید شد! سرویس شما فعال گردید و در بخش «📦 سرویس‌های من» قابل مشاهده است."
        suffix = "\n\n✅ تایید شد"
    else:
        user_text = "❌ رسید ارسالی تایید نشد. لطفاً با پشتیبانی در تماس باشید یا رسید صحیح را مجدداً ارسال کنید."
        suffix = "\n\n❌ رد شد"
    res = send_message(order["user_id"], user_text)
    if not res or not res.get("ok"):
        suffix += "\n⚠️ پیام به کاربر ارسال نشد (احتمالاً ربات را بلاک کرده)."
    edit_message_text(admin_chat, msg_id, original + suffix)


# ---------------------------------------------------------------------------
# دستورهای ادمین
# ---------------------------------------------------------------------------
_broadcast_payload = {}


def admin_help_text() -> str:
    return (
        "🛠 دستورهای ادمین\n\n"
        "/pending — سفارش‌های بررسی‌نشده (با دکمه‌ی تایید/رد)\n"
        "/stats — آمار فروش امروز، این ماه و کل\n"
        "/user <آیدی عددی یا @یوزرنیم> — اطلاعات و سفارش‌های یک کاربر\n"
        "/broadcast <متن> — پیام همگانی (یا روی یک پیام ریپلای کنید و /broadcast بزنید)\n"
        "/prices — لیست پلن‌ها با آیدی و قیمت فعلی\n"
        "/setprice <آیدی پلن> <قیمت> — مثال: /setprice sm2 450\n"
        "/setcard <شماره کارت ۱۶ رقمی> — تغییر شماره کارت\n"
        "/setholder <نام> — تغییر نام صاحب کارت"
    )


def cmd_pending():
    rows = db(
        "SELECT id, user_id, plan_label, price, created_at, renewal_username FROM orders "
        "WHERE status = 'pending' ORDER BY id LIMIT 20", (), "all",
    )
    if not rows:
        send_message(ADMIN_CHAT_ID, "✅ هیچ سفارش بررسی‌نشده‌ای وجود ندارد.")
        return
    send_message(ADMIN_CHAT_ID, f"🧾 {fa_num(len(rows))} سفارش در انتظار بررسی (حداکثر ۲۰ مورد):")
    for oid, uid, label, price, created_at, renewal in rows:
        renewal_line = f"🔄 نام کاربری تمدید: `{renewal}`\n" if renewal else ""
        text = (
            f"🧾 **سفارش در انتظار بررسی #{oid}**\n\n"
            f"🆔 آیدی کاربر: `{uid}`\n{renewal_line}"
            f"📦 پلن: **{label}**\n💰 مبلغ: **{price}**\n🗓 ثبت: {created_at}"
        )
        send_message(ADMIN_CHAT_ID, text, order_action_keyboard(oid))
        time.sleep(0.05)


def cmd_stats():
    now = now_dt()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    _, _, jalali_day = gregorian_to_jalali(now.year, now.month, now.day)
    month_start = day_start - timedelta(days=jalali_day - 1)
    q = ("SELECT COUNT(*), COALESCE(SUM(amount_toman), 0) FROM orders "
         "WHERE status = 'confirmed' AND confirmed_at >= %s")
    today = db(q, (day_start,), "one")
    month = db(q, (month_start,), "one")
    total = db("SELECT COUNT(*), COALESCE(SUM(amount_toman), 0) FROM orders WHERE status = 'confirmed'", (), "one")
    pending = db("SELECT COUNT(*) FROM orders WHERE status = 'pending'", (), "one")
    users = db("SELECT COUNT(*), COUNT(*) FILTER (WHERE blocked) FROM users", (), "one")

    def fmt(row):
        return f"{fa_num(row[0])} سفارش — {price_toman_text(int(row[1]))}"

    send_message(
        ADMIN_CHAT_ID,
        "📊 آمار فروش\n\n"
        f"📅 امروز: {fmt(today)}\n"
        f"🗓 این ماه (از اول ماه شمسی): {fmt(month)}\n"
        f"💰 کل: {fmt(total)}\n\n"
        f"⏳ سفارش در انتظار بررسی: {fa_num(pending[0])}\n"
        f"👥 کاربران ربات: {fa_num(users[0])} ({fa_num(users[1])} نفر ربات را بلاک کرده‌اند)",
    )


def cmd_user(args):
    if not args:
        send_message(ADMIN_CHAT_ID, "استفاده: /user <آیدی عددی یا @یوزرنیم>")
        return
    arg = args[0].strip().lstrip("@").translate(PERSIAN_TO_EN)
    if arg.isdigit():
        uid = int(arg)
    else:
        row = db("SELECT user_id FROM users WHERE LOWER(username) = LOWER(%s) LIMIT 1", (arg,), "one")
        if not row:
            send_message(ADMIN_CHAT_ID, "کاربری با این یوزرنیم پیدا نشد (فقط کاربرانی که با ربات تعامل داشته‌اند ذخیره شده‌اند).")
            return
        uid = row[0]
    info = db("SELECT full_name, username, first_seen, blocked FROM users WHERE user_id = %s", (uid,), "one")
    orders = db(
        "SELECT id, plan_label, price, status, created_at, expires_at, renewal_username "
        "FROM orders WHERE user_id = %s ORDER BY id DESC LIMIT 15", (uid,), "all",
    ) or []
    summary = db(
        "SELECT COUNT(*) FILTER (WHERE status = 'confirmed'), "
        "COALESCE(SUM(amount_toman) FILTER (WHERE status = 'confirmed'), 0) FROM orders WHERE user_id = %s",
        (uid,), "one",
    )
    if not info and not orders:
        send_message(ADMIN_CHAT_ID, "اطلاعاتی برای این آیدی پیدا نشد.")
        return
    lines = []
    if info:
        full_name, username, first_seen, blocked = info
        lines += [f"👤 {full_name or '---'}", f"🆔 {uid}", f"یوزرنیم: @{username or '---'}",
                  f"🗓 اولین تعامل: {first_seen or '---'}"]
        if blocked:
            lines.append("🚫 این کاربر ربات را بلاک کرده است.")
    else:
        lines.append(f"🆔 {uid}")
    lines += ["", f"🧾 سفارش‌ها (تایید شده: {fa_num(summary[0])} — جمع: {price_toman_text(int(summary[1]))})"]
    icons = {"pending": "⏳", "confirmed": "✅", "rejected": "❌"}
    for oid, label, price, status, created_at, expires_at, renewal in orders:
        line = f"{icons.get(status, '•')} #{oid} — {label} — {price} — {created_at}"
        if status == "confirmed" and expires_at:
            line += f" (پایان: {expires_at.strftime('%Y-%m-%d')})"
        if renewal:
            line += f" 🔄 {renewal}"
        lines.append(line)
    if not orders:
        lines.append("سفارشی ثبت نشده است.")
    send_message(ADMIN_CHAT_ID, "\n".join(lines))


def cmd_prices():
    lines = ["💰 پلن‌ها (آیدی — عنوان — قیمت فعلی)\n"]
    for cat in PLANS.values():
        for sub in cat["subcategories"].values():
            for item in sub["items"]:
                lines.append(f"`{item['id']}` — {item['label']} — {price_toman_text(item['price'])}")
    lines.append("\nتغییر قیمت: /setprice <آیدی پلن> <قیمت>")
    lines.append(f"💳 کارت فعلی: `{CARD_NUMBER}` — {CARD_HOLDER}")
    send_message(ADMIN_CHAT_ID, "\n".join(lines))


def cmd_setprice(args):
    if len(args) != 2:
        send_message(ADMIN_CHAT_ID, "استفاده: /setprice <آیدی پلن> <قیمت>\nمثال: /setprice sm2 450\nآیدی‌ها: /prices")
        return
    item, _, _ = find_plan(args[0])
    amount = parse_int(args[1])
    if not item:
        send_message(ADMIN_CHAT_ID, "❌ آیدی پلن پیدا نشد. لیست آیدی‌ها: /prices")
        return
    if amount <= 0:
        send_message(ADMIN_CHAT_ID, "❌ قیمت باید یک عدد مثبت باشد.")
        return
    old = item["price"]
    item["price"] = amount
    set_setting(f"price_{args[0]}", str(amount))
    send_message(ADMIN_CHAT_ID,
                 f"✅ قیمت «{item['label']}» از {price_toman_text(old)} به {price_toman_text(amount)} تغییر کرد.")


def cmd_setcard(args):
    global CARD_NUMBER
    digits = re.sub(r"\D", "", " ".join(args).translate(PERSIAN_TO_EN))
    if len(digits) != 16:
        send_message(ADMIN_CHAT_ID, "استفاده: /setcard <شماره کارت ۱۶ رقمی>\nمثال: /setcard 6037 9911 2233 4455")
        return
    CARD_NUMBER = "-".join(digits[i:i + 4] for i in range(0, 16, 4))
    set_setting("card_number", CARD_NUMBER)
    send_message(ADMIN_CHAT_ID, f"✅ شماره کارت تغییر کرد:\n{CARD_NUMBER}")


def cmd_setholder(args):
    global CARD_HOLDER
    name = " ".join(args).strip()
    if not name:
        send_message(ADMIN_CHAT_ID, "استفاده: /setholder <نام صاحب کارت>")
        return
    CARD_HOLDER = name
    set_setting("card_holder", name)
    send_message(ADMIN_CHAT_ID, f"✅ نام صاحب کارت تغییر کرد: {name}")


def cmd_broadcast(message):
    text = message.get("text", "")
    reply = message.get("reply_to_message")
    parts = re.split(r"\s+", text, maxsplit=1)
    body = parts[1].strip() if len(parts) > 1 else ""
    if reply:
        payload = {"mode": "copy", "chat_id": message["chat"]["id"], "message_id": reply["message_id"]}
    elif body:
        payload = {"mode": "text", "text": body}
    else:
        send_message(ADMIN_CHAT_ID,
                     "استفاده:\n/broadcast <متن پیام>\n\nیا روی هر پیامی ریپلای کنید و فقط /broadcast بفرستید.")
        return
    row = db("SELECT COUNT(*) FROM users WHERE blocked = FALSE AND user_id <> %s", (ADMIN_CHAT_ID,), "one")
    _broadcast_payload["data"] = payload
    if payload["mode"] == "copy":
        copy_message(ADMIN_CHAT_ID, payload["chat_id"], payload["message_id"])
    else:
        send_message(ADMIN_CHAT_ID, payload["text"])
    kb = {"inline_keyboard": [[{"text": "✅ ارسال", "callback_data": "bc_send"},
                               {"text": "❌ لغو", "callback_data": "bc_cancel"}]]}
    send_message(ADMIN_CHAT_ID, f"📣 پیام بالا برای {fa_num(row[0] if row else 0)} کاربر ارسال می‌شود. تایید می‌کنید؟", kb)


def run_broadcast(payload):
    try:
        rows = db("SELECT user_id FROM users WHERE blocked = FALSE AND user_id <> %s", (ADMIN_CHAT_ID,), "all") or []
        sent = failed = 0
        blocked = []
        for (uid,) in rows:
            if payload["mode"] == "copy":
                res = copy_message(uid, payload["chat_id"], payload["message_id"])
            else:
                res = send_message(uid, payload["text"])
            if res and res.get("ok"):
                sent += 1
            elif res and res.get("error_code") in (403, 400):
                blocked.append(uid)
                _seen_users.discard(uid)
            else:
                failed += 1
            time.sleep(0.05)
        if blocked:
            db("UPDATE users SET blocked = TRUE WHERE user_id = ANY(%s)", (blocked,))
        send_message(
            ADMIN_CHAT_ID,
            "📣 گزارش پیام همگانی\n\n"
            f"✅ ارسال‌شده: {fa_num(sent)}\n🚫 بلاک‌کرده‌ها: {fa_num(len(blocked))}\n⚠️ ناموفق: {fa_num(failed)}",
        )
    except Exception as exc:
        log("run_broadcast failed:", exc)
        send_message(ADMIN_CHAT_ID, "⚠️ ارسال پیام همگانی با خطا مواجه شد؛ لاگ سرور را ببینید.")


def handle_admin_command(message, text) -> bool:
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]
    if cmd == "/admin":
        send_message(ADMIN_CHAT_ID, admin_help_text())
    elif cmd == "/pending":
        cmd_pending()
    elif cmd == "/stats":
        cmd_stats()
    elif cmd == "/user":
        cmd_user(args)
    elif cmd == "/broadcast":
        cmd_broadcast(message)
    elif cmd == "/prices":
        cmd_prices()
    elif cmd == "/setprice":
        cmd_setprice(args)
    elif cmd == "/setcard":
        cmd_setcard(args)
    elif cmd == "/setholder":
        cmd_setholder(args)
    else:
        return False
    return True


# ---------------------------------------------------------------------------
# یادآوری‌ها
# ---------------------------------------------------------------------------
def safe_run(fn):
    try:
        fn()
    except Exception as exc:
        log(f"{fn.__name__} failed:", exc)


def send_expiry_reminders():
    now = now_dt()
    rows = db(
        "SELECT o.id, o.user_id, o.plan_label, o.expires_at FROM orders o "
        "WHERE o.status = 'confirmed' AND o.expiry_reminded = FALSE "
        "AND o.expires_at IS NOT NULL AND o.expires_at > %s AND o.expires_at <= %s "
        "AND NOT EXISTS (SELECT 1 FROM orders n WHERE n.user_id = o.user_id "
        "AND n.status = 'confirmed' AND n.expires_at > o.expires_at)",
        (now, now + timedelta(days=REMINDER_DAYS_BEFORE)), "all",
    ) or []
    kb = {"inline_keyboard": [[{"text": "🔄 تمدید سرور", "callback_data": "renew"}]]}
    for oid, uid, label, expires_at in rows:
        days_left = max(1, math.ceil((expires_at - now).total_seconds() / 86400))
        text = (
            "⏰ یادآوری تمدید\n\n"
            f"سرویس «{label}» شما حدود {fa_digits(days_left)} روز دیگر به پایان می‌رسد.\n"
            "برای اینکه اتصال شما قطع نشود، همین حالا تمدید کنید 👇"
        )
        res = send_message(uid, text, kb)
        if res is not None:  # اگر شبکه قطع بود دوباره تلاش می‌شود؛ خطای 4xx یعنی کاربر بلاک کرده
            if not res.get("ok") and res.get("error_code") in (400, 403):
                db("UPDATE users SET blocked = TRUE WHERE user_id = %s", (uid,))
            db("UPDATE orders SET expiry_reminded = TRUE WHERE id = %s", (oid,))
        time.sleep(0.1)


def remind_admin_pending():
    cutoff = now_dt() - timedelta(minutes=PENDING_REMIND_MINUTES)
    rows = db(
        "SELECT id, plan_label, price, created_at FROM orders WHERE status = 'pending' "
        "AND admin_reminded = FALSE AND created_ts IS NOT NULL AND created_ts <= %s ORDER BY id",
        (cutoff,), "all",
    ) or []
    if not rows:
        return
    lines = [f"⏰ سفارش‌های بررسی‌نشده (بیش از {fa_digits(PENDING_REMIND_MINUTES)} دقیقه)\n"]
    for oid, label, price, created_at in rows:
        lines.append(f"• سفارش #{oid} — {label} — {price} — {created_at or ''}")
    lines.append("\nبرای دیدن و تایید/رد: /pending")
    send_message(ADMIN_CHAT_ID, "\n".join(lines))
    db("UPDATE orders SET admin_reminded = TRUE WHERE id = ANY(%s)", ([r[0] for r in rows],))


def background_loop():
    time.sleep(15)
    while True:
        safe_run(send_expiry_reminders)
        safe_run(remind_admin_pending)
        time.sleep(BACKGROUND_INTERVAL)


# ---------------------------------------------------------------------------
# پردازش آپدیت‌ها
# ---------------------------------------------------------------------------
def process_message(message):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    user = message.get("from") or {}
    text = (message.get("text") or "").strip()
    if chat_id is None:
        return
    is_private = chat.get("type", "private") == "private"
    if not is_private:
        return

    register_user({**user, "id": user.get("id", chat_id)})
    is_admin = chat_id == ADMIN_CHAT_ID

    if text == "/myid":
        send_message(chat_id, f"🆔 شناسه (Chat ID) شما در بله:\n`{chat_id}`")
        return

    if is_admin and text.startswith("/") and handle_admin_command(message, text):
        return

    if FORCE_JOIN and not is_admin and not is_channel_member(chat_id):
        send_message(chat_id, JOIN_TEXT, join_keyboard())
        return

    if text in ("/start", "start"):
        reset_state(chat_id)
        show_main_menu(chat_id)
    elif text == HOME_BUTTON_TEXT:
        reset_state(chat_id)
        send_message(chat_id, "🏠 منوی اصلی:", main_menu_inline())
    elif text == "/cancel":
        st = get_state(chat_id)
        had_flow = st["awaiting_username"] or st["pending_plan_id"] is not None
        reset_state(chat_id)
        send_message(chat_id,
                     "❌ فرآیند جاری لغو شد و از آن خارج شدید." if had_flow else "چیزی برای لغو کردن وجود نداشت.",
                     persistent_keyboard())
        send_message(chat_id, "🏠 منوی اصلی:", main_menu_inline())
    elif text == BUY_BUTTON_TEXT:
        reset_state(chat_id)
        send_message(chat_id, "🛒 **بخش خرید اشتراک**\n\nلطفاً نوع اشتراک مورد نظر خود را انتخاب کنید:", plans_keyboard())
    elif text == RENEW_BUTTON_TEXT:
        start_renewal_flow(chat_id)
    elif text == PRICE_LIST_BUTTON_TEXT:
        reset_state(chat_id)
        send_message(chat_id, get_full_price_list_text(), price_list_keyboard())
    elif text == MY_SERVICES_BUTTON_TEXT:
        reset_state(chat_id)
        send_message(chat_id, build_my_services_text(chat_id))
    elif text == CHECK_BALANCE_BUTTON_TEXT:
        reset_state(chat_id)
        kb = {"inline_keyboard": [[{"text": "📊 چک کردن مانده", "url": BALANCE_BOT_LINK}]]}
        send_message(chat_id, "📊 برای بررسی مانده سرویس خود، روی دکمه زیر کلیک کنید:", kb)
    elif text == SUPPORT_BUTTON_TEXT:
        reset_state(chat_id)
        kb = {"inline_keyboard": [[{"text": "💬 ارتباط با پشتیبانی", "url": support_url()}]]}
        send_message(chat_id, "🎧 برای دریافت پشتیبانی روی دکمه زیر کلیک کنید تا مستقیم چت باز شود:", kb)
    elif message.get("photo") or message.get("document"):
        # رسید باید در پیوی ادمین فرستاده شود، نه برای ربات
        kb = {"inline_keyboard": [[{"text": "💬 ارسال رسید به ادمین", "url": support_url()}]]}
        send_message(
            chat_id,
            "📸 رسید را برای ربات نفرستید؛ لطفاً آن را **مستقیم در پیوی ادمین** بفرستید.\n"
            "بعد از ارسال، به ربات برگردید و روی «✅ رسید را فرستادم» بزنید.",
            kb,
        )
    elif text and not text.startswith("/"):
        handle_renewal_username(chat_id, text)


def process_callback(cb):
    cb_id = cb.get("id")
    data = cb.get("data", "")
    msg = cb.get("message", {})
    msg_id = msg.get("message_id")
    chat_id = msg.get("chat", {}).get("id")
    user = cb.get("from", {})
    user_id = user.get("id", chat_id)
    if not chat_id:
        return

    is_admin = user_id == ADMIN_CHAT_ID

    # دکمه‌های ادمین
    if data.startswith(("confirm_", "reject_")):
        if not is_admin:
            answer_callback_query(cb_id)
            return
        answer_callback_query(cb_id)
        handle_confirm_reject(cb_id, chat_id, msg, data)
        return
    if data in ("bc_send", "bc_cancel"):
        if not is_admin:
            answer_callback_query(cb_id, "این دکمه فقط برای ادمین است.")
            return
        answer_callback_query(cb_id)
        payload = _broadcast_payload.pop("data", None)
        if data == "bc_cancel":
            edit_message_text(chat_id, msg_id, "❌ ارسال پیام همگانی لغو شد.")
        elif not payload:
            edit_message_text(chat_id, msg_id, "⚠️ پیامی برای ارسال پیدا نشد. دوباره /broadcast بزنید.")
        else:
            edit_message_text(chat_id, msg_id, "⏳ ارسال شروع شد؛ بعد از پایان گزارش می‌فرستم.")
            threading.Thread(target=run_broadcast, args=(payload,), daemon=True).start()
        return

    register_user({**user, "id": user_id})

    if data == "check_join":
        if is_channel_member(user_id, use_cache=False):
            answer_callback_query(cb_id)
            edit_message_text(chat_id, msg_id, "✅ عضویت شما تایید شد! به ربات حباب خوش آمدید 😉")
            show_main_menu(chat_id)
        else:
            answer_callback_query(cb_id, "❌ هنوز عضو کانال نشده‌اید.")
        return

    if FORCE_JOIN and not is_admin and not is_channel_member(user_id):
        answer_callback_query(cb_id, "ابتدا باید در کانال عضو شوید.")
        send_message(chat_id, JOIN_TEXT, join_keyboard())
        return

    answer_callback_query(cb_id)

    if data == "plans":
        edit_message_text(chat_id, msg_id, "🛒 **بخش خرید اشتراک**\n\nلطفاً نوع اشتراک مورد نظر خود را انتخاب کنید:",
                          plans_keyboard())
    elif data == "renew":
        start_renewal_flow(chat_id, message_id=msg_id)
    elif data == "recommended":
        rows = [[{"text": plan_button_text(i), "callback_data": f"buy_{i['id']}"}] for i in get_recommended_plans()]
        rows.append([{"text": "🔙 بازگشت", "callback_data": "plans"}])
        edit_message_text(
            chat_id, msg_id,
            "🔥 **پلن‌های پیشنهادی ما**\n\nیکی را انتخاب کنید تا مستقیم به مرحله‌ی پرداخت بروید 👇",
            {"inline_keyboard": rows},
        )
    elif data == "all_prices":
        edit_message_text(chat_id, msg_id, get_full_price_list_text(), price_list_keyboard())
    elif data.startswith("cat_"):
        cat_key = data[4:]
        if cat_key in PLANS:
            edit_message_text(chat_id, msg_id, f"✨ **{PLANS[cat_key]['title']}**\n\nمدت اشتراک را انتخاب کنید:",
                              subcategory_keyboard(cat_key))
    elif data.startswith("sub_"):
        parts = data.split("_")
        if len(parts) == 3 and parts[1] in PLANS and parts[2] in PLANS[parts[1]]["subcategories"]:
            cat = PLANS[parts[1]]
            sub = cat["subcategories"][parts[2]]
            edit_message_text(
                chat_id, msg_id,
                f"⚡️ **{cat['title']} — {sub['title']}**\n\nپلن مورد نظر خود را انتخاب کنید:\n🔥 = پلن پیشنهادی ما",
                items_keyboard(parts[1], parts[2]),
            )
    elif data.startswith("buy_"):
        handle_buy(chat_id, msg_id, data[4:])
    elif data == "paid":
        handle_paid(chat_id, msg_id, user)
    elif data == "my_services":
        edit_message_text(chat_id, msg_id, build_my_services_text(chat_id),
                          {"inline_keyboard": [[{"text": "🔙 بازگشت", "callback_data": "back"}]]})
    elif data == "support":
        kb = {"inline_keyboard": [[{"text": "💬 ارتباط با پشتیبانی", "url": support_url()}],
                                  [{"text": "🔙 بازگشت", "callback_data": "back"}]]}
        edit_message_text(chat_id, msg_id, "🎧 برای دریافت پشتیبانی روی دکمه زیر کلیک کنید تا مستقیم چت باز شود:", kb)
    elif data == "check_balance":
        kb = {"inline_keyboard": [[{"text": "📊 چک کردن مانده", "url": BALANCE_BOT_LINK}],
                                  [{"text": "🔙 بازگشت", "callback_data": "back"}]]}
        edit_message_text(chat_id, msg_id, "📊 برای بررسی مانده سرویس خود، روی دکمه زیر کلیک کنید:", kb)
    elif data == "back":
        reset_state(chat_id)
        edit_message_text(chat_id, msg_id, "🏠 منوی اصلی:", main_menu_inline())


def process_update(update):
    message = update.get("message") or update.get("edited_message")
    if message:
        process_message(message)
        return
    cb = update.get("callback_query")
    if cb:
        process_callback(cb)


# ---------------------------------------------------------------------------
# Flask / وب‌هوک
# ---------------------------------------------------------------------------
app = Flask(__name__)
init_db()


@app.route("/", methods=["GET", "HEAD"])
def index():
    return "Bot is running on Render."


@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)
    if data:
        try:
            process_update(data)
        except Exception as exc:
            log("process_update failed:", repr(exc))
    return "OK", 200


if WEBHOOK_URL:
    try:
        requests.get(f"{BASE_URL}/setWebhook?url={WEBHOOK_URL}", timeout=10)
    except Exception:
        pass

threading.Thread(target=background_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
