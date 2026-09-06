import re
import sqlite3
import os
import sys
import requests
from datetime import datetime
from flask import Flask, request, jsonify

# ---------------------------------------------------------------------------
# تنظیمات اصلی
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("BALE_TOKEN", "1121828278:4xf2bRX0-WtnP0kbOGT30RKSjzjq0ZwRzIE")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook/{TOKEN}" if RENDER_EXTERNAL_HOSTNAME else ""

ADMIN_USERNAME = "Hobabadmin"
ADMIN_CHAT_ID = 52937597  # شناسه چت شما در بله جهت دریافت درخواست‌های تایید

# لینک تلگرامی ربات چک مانده حجم
BALANCE_BOT_LINK = "https://t.me/reportvolume_bot"

CARD_NUMBER = "5022-2913-3683-0904"
CARD_HOLDER = "علی باقری فرد"

# الگوی نام کاربری معتبر سرور جهت تمدید: provpn + عدد انگلیسی (مثال: provpn27)
RENEWAL_USERNAME_PATTERN = re.compile(r"^provpn[0-9]+$")

# متن دکمه‌های کیبورد ثابت
BUY_BUTTON_TEXT = "🛒 خرید اشتراک"
RENEW_BUTTON_TEXT = "🔄 تمدید سرور"
MY_SERVICES_BUTTON_TEXT = "📦 سرویس‌های من"
CHECK_BALANCE_BUTTON_TEXT = "📊 چک کردن مانده سرویس"
SUPPORT_BUTTON_TEXT = "🎧 پشتیبانی"
HOME_BUTTON_TEXT = "🏠 منوی اصلی"

# ---------------------------------------------------------------------------
# وضعیت موقت هر کاربر (چون این ربات به‌صورت وب‌هوک و بدون حافظه‌ی مکالمه‌ست،
# وضعیت در‌انتظارِ نام‌کاربری تمدید را در یک دیکشنری در حافظه نگه می‌داریم)
# ---------------------------------------------------------------------------
USER_STATE = {}


def get_state(chat_id):
    return USER_STATE.setdefault(
        chat_id, {"awaiting_username": False, "username_attempts": 0, "renewal_username": None}
    )


def reset_state(chat_id):
    USER_STATE[chat_id] = {"awaiting_username": False, "username_attempts": 0, "renewal_username": None}


_EN2FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(n: int) -> str:
    return f"{n:,}".translate(_EN2FA)


def price_toman_text(price_thousand_toman: int) -> str:
    return f"{fa_num(price_thousand_toman)} تومن"


def price_rial_text(price_thousand_toman: int) -> str:
    rial = price_thousand_toman * 10_000
    return f"{fa_num(rial)} ریال"


# ---------------------------------------------------------------------------
# تعریف پلن‌ها
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


def find_plan(plan_id: str):
    for cat_key, cat in PLANS.items():
        for sub_key, sub in cat["subcategories"].items():
            for item in sub["items"]:
                if item["id"] == plan_id:
                    return item, cat_key, sub_key
    return None, None, None


def get_full_price_list_text():
    return (
        "💵 تعرفه های اشتراک های طرح پرو:\n\n"
        "🌀 تک کاربره:\n\n"
        "✨ یک ماهه:\n"
        "یکماه تک کاربر ۲۰ گیگ ۲۴۰ تومن\n"
        "یکماه تک کاربر ۴۰ گیگ ۴۲۰ تومن\n"
        "یکماه تک کاربر ۶۰ گیگ ۵۵۰ تومن\n"
        "یکماه تک کاربر ۱۰۰ گیگ ۶۹۰ تومن\n\n"
        "✨ سه ماهه:\n"
        "سه ماه تک کاربر ۱۰۰ گیگ ۹۹۰ تومن\n"
        "سه ماه تک کاربر ۱۵۰ گیگ ۱۳۹۰ تومن\n"
        "سه ماه تک کاربر ۱۸۰ گیگ ۱۵۹۰ تومن\n\n"
        "🌀 دو کاربره:\n\n"
        "✨ یک ماهه:\n"
        "یکماه دو کاربر ۴۰ گیگ ۵۴۰ تومن\n"
        "یکماه دو کاربر ۶۰ گیگ ۶۵۰ تومن\n"
        "یکماه دو کاربر ۸۰ گیگ ۷۵۰ تومن\n"
        "یکماه دو کاربر ۱۰۰ گیگ ۸۹۰ تومن\n\n"
        "✨ سه ماهه:\n"
        "سه ماه دو کاربر ۱۰۰ گیگ ۱۱۹۰ تومن\n"
        "سه ماه دو کاربر ۲۰۰ گیگ ۱۷۹۰ تومن\n"
        "سه ماه دو کاربر ۳۶۰ گیگ ۲۰۹۰ تومن\n\n"
        "@HobabServices"
    )


# ---------------------------------------------------------------------------
# دیتابیس
# ---------------------------------------------------------------------------
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "services.db")


def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_label TEXT NOT NULL,
            activated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def add_user_service(user_id: int, plan_label: str):
    now_str = datetime.now().strftime("%Y-%m-%d — %H:%M")
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT INTO user_services (user_id, plan_label, activated_at) VALUES (?, ?, ?)",
        (user_id, plan_label, now_str)
    )
    conn.commit()
    conn.close()


def get_user_services(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        "SELECT plan_label, activated_at FROM user_services WHERE user_id = ? ORDER BY id DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return rows


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
        print(f"sendMessage exception: {e}", file=sys.stderr)
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
        print(f"editMessageText exception: {e}", file=sys.stderr)
        return None


def answer_callback_query(callback_query_id, text=None):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = True
    try:
        requests.post(f"{BASE_URL}/answerCallbackQuery", json=payload, timeout=5)
    except Exception as e:
        print(f"answerCallbackQuery exception: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# کیبوردها
# ---------------------------------------------------------------------------
def persistent_keyboard():
    # تمام آیتم‌های منوی اصلی در کنار «منوی اصلی» به صورت کیبورد ثابت نمایش داده می‌شوند
    return {
        "keyboard": [
            [{"text": BUY_BUTTON_TEXT}, {"text": RENEW_BUTTON_TEXT}],
            [{"text": MY_SERVICES_BUTTON_TEXT}, {"text": CHECK_BALANCE_BUTTON_TEXT}],
            [{"text": SUPPORT_BUTTON_TEXT}, {"text": HOME_BUTTON_TEXT}],
        ],
        "resize_keyboard": True
    }


def main_menu_inline():
    return {
        "inline_keyboard": [
            [{"text": "🛒 خرید اشتراک", "callback_data": "plans"}],
            [{"text": "🔄 تمدید سرور", "callback_data": "renew"}],
            [{"text": "📦 سرویس‌های من", "callback_data": "my_services"}],
            [{"text": "📊 چک کردن مانده سرویس", "callback_data": "check_balance"}],
            [{"text": "🎧 پشتیبانی", "callback_data": "support"}]
        ]
    }


def category_keyboard():
    return {
        "inline_keyboard": [
            [{"text": PLANS["single"]["title"], "callback_data": "cat_single"}],
            [{"text": PLANS["double"]["title"], "callback_data": "cat_double"}],
            [{"text": "📋 لیست کلی قیمت‌ها", "callback_data": "all_prices"}],
            [{"text": "🔙 بازگشت", "callback_data": "back"}]
        ]
    }


def subcategory_keyboard(cat_key):
    cat = PLANS[cat_key]
    rows = []
    for sub_key, sub in cat["subcategories"].items():
        rows.append([{"text": sub["title"], "callback_data": f"sub_{cat_key}_{sub_key}"}])
    rows.append([{"text": "🔙 بازگشت", "callback_data": "plans"}])
    return {"inline_keyboard": rows}


def items_keyboard(cat_key, sub_key):
    sub = PLANS[cat_key]["subcategories"][sub_key]
    rows = []
    for item in sub["items"]:
        text = f"{item['label']} — {price_toman_text(item['price'])}"
        rows.append([{"text": text, "callback_data": f"buy_{item['id']}"}])
    rows.append([{"text": "🔙 بازگشت", "callback_data": f"cat_{cat_key}"}])
    return {"inline_keyboard": rows}


def build_my_services_text(chat_id):
    services = get_user_services(chat_id)
    if not services:
        return "📦 هنوز هیچ سرویس فعالی برای شما ثبت نشده است."
    text_lines = ["📦 **سرویس‌های شما:**\n"]
    for label, activated_at in services:
        text_lines.append(f"🔹 **اشتراک:** {label}\n⏱ **زمان فعال‌سازی:** {activated_at}\n---")
    return "\n".join(text_lines)


def start_renewal_flow(chat_id, message_id=None):
    state = get_state(chat_id)
    state["awaiting_username"] = True
    state["username_attempts"] = 0

    text = (
        "🔄 تمدید سرور\n\n"
        "لطفاً نام کاربری سرور OpenConnect خود را همینجا ارسال کنید.\n\n"
        "📌 فرمت صحیح: کلمه‌ی provpn به همراه یک عدد انگلیسی، مثلاً:\n"
        "provpn27 ✅"
    )

    if message_id:
        kb = {"inline_keyboard": [[{"text": "🔙 بازگشت", "callback_data": "back"}]]}
        edit_message_text(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, persistent_keyboard())


def handle_renewal_username(chat_id, text):
    """اگر ربات منتظر دریافت نام کاربری تمدید سرور از این کاربر باشد، پیام متنی را بررسی می‌کند.
    خروجی True یعنی پیام مربوط به این جریان بوده و پردازش شد."""
    state = get_state(chat_id)
    if not state.get("awaiting_username"):
        return False

    username = (text or "").strip()

    if RENEWAL_USERNAME_PATTERN.match(username):
        state["awaiting_username"] = False
        state["username_attempts"] = 0
        state["renewal_username"] = username
        send_message(chat_id, f"✅ نام کاربری شما با موفقیت تایید شد! ({username})")
        send_message(chat_id, "لطفاً نوع اشتراک مورد نظر خود جهت تمدید را انتخاب کنید:", category_keyboard())
        return True

    attempts = state.get("username_attempts", 0) + 1
    state["username_attempts"] = attempts

    base_text = (
        "❌ نام کاربری شما اشتباه است!\n\n"
        "لطفاً دوباره با فرمت صحیح ارسال کنید، مثلاً:\n"
        "provpn27"
    )

    if attempts >= 2:
        kb = {"inline_keyboard": [[{"text": "💬 ارتباط با پشتیبانی", "url": f"https://ble.ir/{ADMIN_USERNAME}"}]]}
        send_message(
            chat_id,
            base_text + "\n\nاگر در تایید نام کاربری مشکلی برایتان پیش آمده، لطفاً به پشتیبانی پیام دهید.",
            kb,
        )
    else:
        send_message(chat_id, base_text)
    return True


# ---------------------------------------------------------------------------
# پردازش پیام‌ها
# ---------------------------------------------------------------------------
def process_update(update):
    message = update.get("message") or update.get("edited_message")
    if message:
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()

        if text in ["/start", HOME_BUTTON_TEXT, "start"]:
            reset_state(chat_id)
            send_message(chat_id, "سلام، جهت خرید یا تمدید سرور در خدمتم😉", persistent_keyboard())
            send_message(chat_id, "یکی از گزینه‌های زیر رو انتخاب کن:", main_menu_inline())
            return

        if text == "/myid":
            send_message(chat_id, f"🆔 شناسه (Chat ID) شما در بله:\n`{chat_id}`")
            return

        if text == "/cancel":
            state = get_state(chat_id)
            had_active_flow = state.get("awaiting_username") is True
            reset_state(chat_id)
            reply = "❌ فرآیند جاری لغو شد و از آن خارج شدید." if had_active_flow else "چیزی برای لغو کردن وجود نداشت."
            send_message(chat_id, reply, persistent_keyboard())
            send_message(chat_id, "🏠 منوی اصلی:", main_menu_inline())
            return

        if text == BUY_BUTTON_TEXT:
            reset_state(chat_id)
            send_message(chat_id, "💵 تعرفه اشتراک‌های طرح پرو:\n\nنوع اشتراک رو انتخاب کن:", category_keyboard())
            return

        if text == RENEW_BUTTON_TEXT:
            start_renewal_flow(chat_id)
            return

        if text == MY_SERVICES_BUTTON_TEXT:
            reset_state(chat_id)
            send_message(chat_id, build_my_services_text(chat_id))
            return

        if text == CHECK_BALANCE_BUTTON_TEXT:
            reset_state(chat_id)
            kb = {"inline_keyboard": [[{"text": "📊 چک کردن مانده", "url": BALANCE_BOT_LINK}]]}
            send_message(chat_id, "📊 برای چک کردن مانده‌ی سرویست روی دکمه‌ی زیر بزن:", kb)
            return

        if text == SUPPORT_BUTTON_TEXT:
            reset_state(chat_id)
            kb = {"inline_keyboard": [[{"text": "💬 ارتباط با پشتیبانی", "url": f"https://ble.ir/{ADMIN_USERNAME}"}]]}
            send_message(chat_id, "🎧 برای پشتیبانی، روی دکمه‌ی زیر بزن تا مستقیم چت باز بشه:", kb)
            return

        # هندلر عمومی متن: بررسی نام کاربری تمدید سرور (کمترین اولویت)
        if chat_id is not None:
            handle_renewal_username(chat_id, text)
        return

    cb = update.get("callback_query")
    if cb:
        cb_id = cb.get("id")
        cb_data = cb.get("data", "")
        msg = cb.get("message", {})
        msg_id = msg.get("message_id")
        chat_id = msg.get("chat", {}).get("id")
        user_info = cb.get("from", {})
        first_name = user_info.get("first_name", "کاربر")
        username = user_info.get("username", "")

        if cb_id:
            answer_callback_query(cb_id)

        if not chat_id:
            return

        if cb_data == "plans":
            edit_message_text(chat_id, msg_id, "💵 تعرفه اشتراک‌های طرح پرو:\n\nنوع اشتراک رو انتخاب کن:", category_keyboard())

        elif cb_data == "renew":
            start_renewal_flow(chat_id, message_id=msg_id)

        elif cb_data == "all_prices":
            kb = {"inline_keyboard": [
                [{"text": "🛒 ثبت سفارش", "callback_data": "plans"}],
                [{"text": "🔙 بازگشت", "callback_data": "plans"}]
            ]}
            edit_message_text(chat_id, msg_id, get_full_price_list_text(), kb)

        elif cb_data.startswith("cat_"):
            cat_key = cb_data.replace("cat_", "")
            if cat_key in PLANS:
                cat = PLANS[cat_key]
                edit_message_text(chat_id, msg_id, f"{cat['title']}\n\nمدت اشتراک رو انتخاب کن:", subcategory_keyboard(cat_key))

        elif cb_data.startswith("sub_"):
            parts = cb_data.split("_")
            if len(parts) == 3:
                cat_key, sub_key = parts[1], parts[2]
                if cat_key in PLANS and sub_key in PLANS[cat_key]["subcategories"]:
                    cat = PLANS[cat_key]
                    sub = cat["subcategories"][sub_key]
                    text = f"{cat['title']}\n{sub['title']}\n\nپلن مورد نظرت رو انتخاب کن:"
                    edit_message_text(chat_id, msg_id, text, items_keyboard(cat_key, sub_key))

        elif cb_data.startswith("buy_"):
            plan_id = cb_data.replace("buy_", "")
            plan, cat_key, sub_key = find_plan(plan_id)
            if plan:
                state = get_state(chat_id)
                renewal_username = state.get("renewal_username")
                renewal_note = f"🔄 نام کاربری جهت تمدید: {renewal_username}\n\n" if renewal_username else ""

                text = (
                    f"{renewal_note}"
                    f"✅ پلن انتخابی: {plan['label']}\n"
                    f"💰 مبلغ: {price_toman_text(plan['price'])}\n"
                    f"💱 معادل این میشه: {price_rial_text(plan['price'])}\n\n"
                    f"لطفاً مبلغ رو به شماره کارت زیر واریز کن:\n\n"
                    f"💳 `{CARD_NUMBER}`\n"
                    f"👤 به نام: {CARD_HOLDER}\n\n"
                    f"⚠️ **توجه:** پس از پرداخت، رسید واریز را همراه با آیدی زیر برای پشتیبانی بفرستید:\n\n"
                    f"🆔 **آیدی (Chat ID) شما:** `{chat_id}`"
                )
                back_kb = {"inline_keyboard": [
                    [{"text": "💬 ارسال رسید به مدیریت", "url": f"https://ble.ir/{ADMIN_USERNAME}"}],
                    [{"text": "🔙 بازگشت", "callback_data": f"sub_{cat_key}_{sub_key}"}]
                ]}
                edit_message_text(chat_id, msg_id, text, back_kb)

                # ارسال درخواست تایید برای شما (ادمین) همراه با دکمه تایید
                admin_renewal_line = f"🔄 **نام کاربری جهت تمدید:** `{renewal_username}`\n" if renewal_username else ""
                admin_msg = (
                    f"🔔 **درخواست سفارش جدید**\n\n"
                    f"👤 **کاربر:** {first_name} (@{username if username else 'بدون_نام_کاربری'})\n"
                    f"🆔 **Chat ID:** `{chat_id}`\n"
                    f"{admin_renewal_line}"
                    f"📦 **پلن انتخابی:** {plan['label']}\n"
                    f"💰 **مبلغ:** {price_toman_text(plan['price'])}\n\n"
                    f"پس از بررسی و واریز وجه، روی دکمه زیر کلیک کنید تا سرویس برای این کاربر فعال شود:"
                )
                admin_kb = {"inline_keyboard": [
                    [{"text": "✅ تایید و فعال‌سازی سرویس", "callback_data": f"approve_{chat_id}_{plan['id']}"}]
                ]}
                send_message(ADMIN_CHAT_ID, admin_msg, admin_kb)

                state["renewal_username"] = None

        # پردازش کلیک روی دکمه تایید توسط ادمین
        elif cb_data.startswith("approve_"):
            parts = cb_data.split("_")
            if len(parts) == 3:
                target_user_id = int(parts[1])
                plan_id = parts[2]
                plan, _, _ = find_plan(plan_id)
                if plan:
                    add_user_service(target_user_id, plan['label'])
                    
                    # ویرایش پیام ادمین و تایید نهایی
                    edit_message_text(
                        chat_id, msg_id,
                        f"✅ **سرویس فعال شد!**\n\n"
                        f"👤 **کاربر:** `{target_user_id}`\n"
                        f"📦 **پلن:** {plan['label']}\n"
                        f"⏱ **زمان فعال‌سازی:** {datetime.now().strftime('%Y-%m-%d — %H:%M')}"
                    )
                    
                    # اطلاع‌رسانی خودکار به کاربر
                    send_message(
                        target_user_id,
                        f"🎉 **پرداخت شما تایید شد!**\n\n"
                        f"اشتراک «{plan['label']}» با موفقیت برای شما فعال شد.\n"
                        f"می‌توانید اطلاعات آن را در بخش «سرویس‌های من» مشاهده کنید."
                    )
                    answer_callback_query(cb_id, "سرویس با موفقیت فعال شد.")

        elif cb_data == "my_services":
            text = build_my_services_text(chat_id)
            kb = {"inline_keyboard": [[{"text": "🔙 بازگشت", "callback_data": "back"}]]}
            edit_message_text(chat_id, msg_id, text, kb)

        elif cb_data == "support":
            kb = {"inline_keyboard": [
                [{"text": "💬 ارتباط با پشتیبانی", "url": f"https://ble.ir/{ADMIN_USERNAME}"}],
                [{"text": "🔙 بازگشت", "callback_data": "back"}]
            ]}
            edit_message_text(chat_id, msg_id, "🎧 برای پشتیبانی، روی دکمه‌ی زیر بزن تا مستقیم چت باز بشه:", kb)

        elif cb_data == "check_balance":
            kb = {"inline_keyboard": [
                [{"text": "📊 چک کردن مانده", "url": BALANCE_BOT_LINK}],
                [{"text": "🔙 بازگشت", "callback_data": "back"}]
            ]}
            edit_message_text(chat_id, msg_id, "📊 برای چک کردن مانده‌ی سرویست روی دکمه‌ی زیر بزن:", kb)

        elif cb_data == "back":
            reset_state(chat_id)
            edit_message_text(chat_id, msg_id, "🏠 منوی اصلی:", main_menu_inline())


app = Flask(__name__)
init_db()


@app.route("/", methods=["GET"])
def index():
    return "Bot is running on Render."


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
