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
BALANCE_BOT_LINK = "https://ble.ir/reportvolume_bot"

CARD_NUMBER = "5022-2913-3683-0904"
CARD_HOLDER = "علی باقری فرد"

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


def answer_callback_query(callback_query_id):
    try:
        requests.post(f"{BASE_URL}/answerCallbackQuery", json={"callback_query_id": callback_query_id}, timeout=5)
    except Exception as e:
        print(f"answerCallbackQuery exception: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# کیبوردها
# ---------------------------------------------------------------------------
def persistent_keyboard():
    return {
        "keyboard": [[{"text": "🏠 منوی اصلی"}]],
        "resize_keyboard": True
    }


def main_menu_inline():
    return {
        "inline_keyboard": [
            [{"text": "🛒 خرید اشتراک", "callback_data": "plans"}],
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


# ---------------------------------------------------------------------------
# پردازش پیام‌ها
# ---------------------------------------------------------------------------
def process_update(update):
    message = update.get("message") or update.get("edited_message")
    if message:
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()

        if text in ["/start", "🏠 منوی اصلی", "start"]:
            send_message(chat_id, "سلام، جهت خرید یا تمدید سرور در خدمتم😉", persistent_keyboard())
            send_message(chat_id, "یکی از گزینه‌های زیر رو انتخاب کن:", main_menu_inline())
            return

        # دستور مستقیم برای دریافت شناسه Chat ID
        if text == "/myid":
            send_message(chat_id, f"🆔 شناسه (Chat ID) شما در بله:\n`{chat_id}`")
            return

        # دستور ادمین برای فعال‌سازی سرویس: /add USER_ID PLAN_NAME
        if text.startswith("/add"):
            parts = text.split(" ", 2)
            if len(parts) == 3:
                target_user_id = parts[1]
                plan_name = parts[2]
                try:
                    add_user_service(int(target_user_id), plan_name)
                    send_message(chat_id, f"✅ سرویس «{plan_name}» برای کاربر {target_user_id} ثبت شد.")
                    send_message(int(target_user_id), f"🎉 سرویس «{plan_name}» برای شما فعال شد! می‌توانید آن را در بخش «سرویس‌های من» ببینید.")
                except Exception as e:
                    send_message(chat_id, f"❌ خطا در ثبت: {e}")
            else:
                send_message(chat_id, "⚠️ فرمت صحیح:\n`/add USER_ID PLAN_NAME`")
            return

    cb = update.get("callback_query")
    if cb:
        cb_id = cb.get("id")
        cb_data = cb.get("data", "")
        msg = cb.get("message", {})
        msg_id = msg.get("message_id")
        chat_id = msg.get("chat", {}).get("id")

        if cb_id:
            answer_callback_query(cb_id)

        if not chat_id:
            return

        if cb_data == "plans":
            edit_message_text(chat_id, msg_id, "💵 تعرفه اشتراک‌های طرح پرو:\n\nنوع اشتراک رو انتخاب کن:", category_keyboard())

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
                text = (
                    f"✅ پلن انتخابی: {plan['label']}\n"
                    f"💰 مبلغ: {price_toman_text(plan['price'])}\n"
                    f"💱 معادل این میشه: {price_rial_text(plan['price'])}\n\n"
                    f"لطفاً مبلغ رو به شماره کارت زیر واریز کن:\n\n"
                    f"💳 `{CARD_NUMBER}`\n"
                    f"👤 به نام: {CARD_HOLDER}\n\n"
                    f"⚠️ **توجه:** پس از پرداخت، رسید واریز را همراه با آیدی زیر برای پشتیبانی بفرستید تا سرویس فعال شود:\n\n"
                    f"🆔 **آیدی (Chat ID) شما:** `{chat_id}`"
                )
                back_kb = {"inline_keyboard": [
                    [{"text": "💬 ارسال رسید به مدیریت", "url": f"https://ble.ir/{ADMIN_USERNAME}"}],
                    [{"text": "🔙 بازگشت", "callback_data": f"sub_{cat_key}_{sub_key}"}]
                ]}
                edit_message_text(chat_id, msg_id, text, back_kb)

        elif cb_data == "my_services":
            services = get_user_services(chat_id)
            if not services:
                text = "📦 هنوز هیچ سرویس فعالی برای شما ثبت نشده است."
            else:
                text_lines = ["📦 **سرویس‌های شما:**\n"]
                for label, activated_at in services:
                    text_lines.append(f"🔹 **اشتراک:** {label}\n⏱ **زمان فعال‌سازی:** {activated_at}\n---")
                text = "\n".join(text_lines)

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
            edit_message_text(chat_id, msg_id, "منوی اصلی:", main_menu_inline())


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
