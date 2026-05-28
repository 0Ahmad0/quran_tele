from __future__ import annotations

import asyncio
import gc
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from random import choice

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import UpdateType
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramUnauthorizedError,
)
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from database import DBManager
from utils import (
    DUAS,
    build_wird_caption,
    cleanup_file,
    close_shared_session,
    generate_quran_images,
    generate_quran_pdf,
    get_pages_logic,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHECK_TIMEZONE = os.getenv("TIMEZONE", "Africa/Cairo")

if not BOT_TOKEN:
    raise RuntimeError(
        "Missing BOT_TOKEN. Add it to your .env file or hosting environment variables."
    )

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = DBManager()
scheduler = AsyncIOScheduler(timezone=CHECK_TIMEZONE)
health_runner: web.AppRunner | None = None

# Limit concurrent daily-sends to avoid memory spikes on free tier
_send_sem = asyncio.Semaphore(5)

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

BTN_SEND_NOW = "📖 أرسل الورد الآن"
BTN_AZKAR = "🤲 ذكر/دعاء الآن"
BTN_STATUS = "📌 إعداداتي"
BTN_SET_TIME = "⏰ ضبط وقت الإرسال"
BTN_SET_GOAL = "🔢 ضبط عدد الصفحات"
BTN_SET_PAGE = "📍 ضبط الصفحة الحالية"
BTN_PAUSE = "⏸ إيقاف مؤقت"
BTN_RESUME = "▶️ استئناف"
BTN_LANGUAGE = "🌐 تغيير اللغة"
BTN_READ_KHATMA = "✅ قرأت الختمة"
BTN_NOT_READ_KHATMA = "❌ لم أقرأ الختمة"
BTN_SET_KHATMA = "🔢 تعيين الختمة"
BTN_ADMIN_STATS = "📊 إحصائيات"
BTN_ADMIN_BROADCAST = "📢 تعميم"
BTN_ADMIN_SEND_DUA = "🤲 إرسال دعاء للجميع"
BTN_ADMIN_DB = "💾 سحب قاعدة البيانات"
BTN_TEST_SEND = "🧪 معاينة الورد"
BTN_CALIBRATE = "⚙️ معايرة"
BTN_SEND_TYPE = "🖼 نوع الإرسال"

BUTTON_ALIASES = {
    BTN_SEND_NOW: "send_now",
    "📖 Send wird now": "send_now",
    BTN_AZKAR: "azkar",
    "🤲 Dua now": "azkar",
    BTN_STATUS: "status",
    "📌 My settings": "status",
    BTN_SET_TIME: "set_time",
    "⏰ Set send time": "set_time",
    BTN_SET_GOAL: "set_goal",
    "🔢 Set daily pages": "set_goal",
    BTN_SET_PAGE: "set_page",
    "📍 Set current page": "set_page",
    BTN_PAUSE: "pause",
    "⏸ Pause": "pause",
    BTN_RESUME: "resume",
    "▶️ Resume": "resume",
    BTN_LANGUAGE: "language",
    "🌐 Change language": "language",
    BTN_READ_KHATMA: "read_khatma",
    BTN_NOT_READ_KHATMA: "not_read_khatma",
    BTN_SET_KHATMA: "set_khatma",
    "🔢 Set Khatma": "set_khatma",
    BTN_ADMIN_STATS: "admin_stats",
    "📊 Statistics": "admin_stats",
    BTN_ADMIN_BROADCAST: "admin_broadcast",
    "📢 Broadcast": "admin_broadcast",
    BTN_ADMIN_SEND_DUA: "admin_send_dua",
    "🤲 Send Dua to All": "admin_send_dua",
    BTN_ADMIN_DB: "admin_db",
    "💾 Download Database": "admin_db",
    BTN_TEST_SEND: "test_send",
    "🧪 Preview Wird": "test_send",
    BTN_CALIBRATE: "calibrate",
    "⚙️ Calibration": "calibrate",
    BTN_SEND_TYPE: "send_type",
    "🖼 Send Type": "send_type",
}

PENDING_ACTIONS: dict[int, tuple[str, int]] = {}

TEXTS = {
    "ar": {
        "send_now": BTN_SEND_NOW,
        "azkar": BTN_AZKAR,
        "status": BTN_STATUS,
        "set_time": BTN_SET_TIME,
        "set_goal": BTN_SET_GOAL,
        "set_page": BTN_SET_PAGE,
        "pause": BTN_PAUSE,
        "resume": BTN_RESUME,
        "language": BTN_LANGUAGE,
        "choose_language": "🌐 اختر اللغة / Choose language",
        "language_updated": "تم تغيير اللغة إلى العربية ✅",
        "read_khatma": BTN_READ_KHATMA,
        "not_read_khatma": BTN_NOT_READ_KHATMA,
        "set_khatma": BTN_SET_KHATMA,
        "admin_stats": BTN_ADMIN_STATS,
        "admin_broadcast": BTN_ADMIN_BROADCAST,
        "admin_send_dua": BTN_ADMIN_SEND_DUA,
        "admin_db": BTN_ADMIN_DB,
        "test_send": BTN_TEST_SEND,
        "calibrate": BTN_CALIBRATE,
        "send_type": BTN_SEND_TYPE,
        "preview_label": "🧪 معاينة",
        "text_only_note": "\n📝 وضع النص فقط",
    },
    "en": {
        "send_now": "📖 Send wird now",
        "azkar": "🤲 Dua now",
        "status": "📌 My settings",
        "set_time": "⏰ Set send time",
        "set_goal": "🔢 Set daily pages",
        "set_page": "📍 Set current page",
        "pause": "⏸ Pause",
        "resume": "▶️ Resume",
        "language": "🌐 Change language",
        "choose_language": "🌐 Choose language / اختر اللغة",
        "language_updated": "Language changed to English ✅",
        "read_khatma": "✅ I read the Khatma",
        "not_read_khatma": "❌ I didn't read the Khatma",
        "set_khatma": "🔢 Set Khatma",
        "admin_stats": "📊 Statistics",
        "admin_broadcast": "📢 Broadcast",
        "admin_send_dua": "🤲 Send Dua to All",
        "admin_db": "💾 Download Database",
        "test_send": "🧪 Preview Wird",
        "calibrate": "⚙️ Calibration",
        "send_type": "🖼 Send Type",
        "preview_label": "🧪 Preview",
        "text_only_note": "\n📝 Text only mode",
    },
}


def get_text(language: str, key: str) -> str:
    return TEXTS.get(language, TEXTS["ar"]).get(key, TEXTS["ar"].get(key, key))


ALL_BUTTON_TEXTS = [
    BTN_SEND_NOW, "📖 Send wird now",
    BTN_AZKAR, "🤲 Dua now",
    BTN_STATUS, "📌 My settings",
    BTN_SET_TIME, "⏰ Set send time",
    BTN_SET_GOAL, "🔢 Set daily pages",
    BTN_SET_PAGE, "📍 Set current page",
    BTN_PAUSE, "⏸ Pause",
    BTN_RESUME, "▶️ Resume",
    BTN_LANGUAGE, "🌐 Change language",
    BTN_SET_KHATMA, "🔢 Set Khatma",
    BTN_ADMIN_STATS, "📊 Statistics",
    BTN_ADMIN_BROADCAST, "📢 Broadcast",
    BTN_ADMIN_SEND_DUA, "🤲 Send Dua to All",
    BTN_ADMIN_DB, "💾 Download Database",
    BTN_TEST_SEND, "🧪 Preview Wird",
    BTN_CALIBRATE, "⚙️ Calibration",
    BTN_SEND_TYPE, "🖼 Send Type",
]


def main_keyboard(language: str = "ar", is_admin_user: bool = False, is_group: bool = False) -> types.ReplyKeyboardMarkup:
    rows = [
        [
            types.KeyboardButton(text=get_text(language, "send_now")),
            types.KeyboardButton(text=get_text(language, "azkar")),
        ],
        [
            types.KeyboardButton(text=get_text(language, "status")),
            types.KeyboardButton(text=get_text(language, "set_time")),
        ],
        [
            types.KeyboardButton(text=get_text(language, "set_goal")),
            types.KeyboardButton(text=get_text(language, "set_page")),
        ],
        [
            types.KeyboardButton(text=get_text(language, "pause")),
            types.KeyboardButton(text=get_text(language, "resume")),
        ],
        [
            types.KeyboardButton(text=get_text(language, "set_khatma")),
            types.KeyboardButton(text=get_text(language, "language")),
        ],
        [
            types.KeyboardButton(text=get_text(language, "test_send")),
            types.KeyboardButton(text=get_text(language, "calibrate")),
        ],
        [
            types.KeyboardButton(text=get_text(language, "send_type")),
        ],
    ]
    if is_admin_user and not is_group:
        rows.append([
            types.KeyboardButton(text=get_text(language, "admin_stats")),
            types.KeyboardButton(text=get_text(language, "admin_broadcast")),
        ])
        rows.append([
            types.KeyboardButton(text=get_text(language, "admin_send_dua")),
            types.KeyboardButton(text=get_text(language, "admin_db")),
        ])
    return types.ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="اختر من الأزرار أو اكتب أمرًا...",
    )


def language_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="العربية 🇸🇦", callback_data="lang:ar"),
                types.InlineKeyboardButton(text="English 🇬🇧", callback_data="lang:en"),
            ]
        ]
    )


START_MESSAGE = """
رفيقك الذكي للمحافظة على وردك اليومي من القرآن الكريم.

في زحمة الحياة وكثرة المشاغل، قد ننسى وردنا أو نؤجله، فجاء هذا البوت ليكون تذكيرًا لطيفًا ورفيقًا ثابتًا يعينك على الاستمرار مع كتاب الله.

✨ أهم المميزات:

📖 إرسال ورد القرآن يوميًا تلقائيًا
يصلك وردك في الوقت الذي تختاره دون الحاجة للتذكير اليدوي.

⏰ جدولة مرنة
حدد وقت الإرسال المناسب لك، صباحًا أو مساءً، والبوت يتكفل بالباقي.

🔢 ورد يناسبك
اختر عدد الصفحات اليومية حسب طاقتك وجدولك.

📍 متابعة تلقائية للختمة
البوت يعرف آخر صفحة وصلت إليها ويكمل منها مباشرة.

🖼 صور واضحة للصفحات
للقراءة السريعة والمريحة من داخل Telegram.

📄 تحويل تلقائي إلى PDF
إذا كان الورد أكثر من 10 صفحات، يتم تجهيزه كملف PDF مرتب وسهل التصفح.

🤲 أذكار وأدعية بضغطة زر
احصل على دعاء قصير أو ذكر في أي وقت.

🎉 تهنئة عند ختم القرآن
وعند إتمام الختمة يبدأ البوت معك ختمة جديدة بإذن الله.

👨‍💻 المطور:
تم تطوير البوت بواسطة م.أحمد الحريري، بعناية واهتمام ليكون أداة نافعة لخدمة كتاب الله ومساعدة المسلمين على الثبات على الورد اليومي.

نسأل الله أن يجعله صدقة جارية وأن ينفع به كل من استخدمه وشاركه.

ابدأ الآن، واجعل القرآن رفيق يومك 🌿
""".strip()


HELP_TEXT = """
أهلًا بك في بوت ورد القرآن اليومي 🌿

الأوامر المتاحة:
/start - الاشتراك أو إعادة التفعيل
/help - عرض هذه المساعدة
/status - عرض إعداداتك الحالية
/goal 5 - ضبط عدد صفحات الورد اليومي
/time 08:00 - ضبط وقت الإرسال اليومي بنظام 24 ساعة
/page 1 - ضبط الصفحة الحالية
/khatma 5 - تعيين رقم الختمة الحالية
/send_now - إرسال ورد اليوم الآن
/azkar - إرسال دعاء/ذكر الآن
/dua - إرسال دعاء/ذكر الآن
/pause - إيقاف الإرسال مؤقتًا
/resume - استئناف الإرسال

أوامر المدير:
/admin_stats - عدد المشتركين النشطين
/broadcast النص - إرسال تعميم للجميع
/admin_send_dua - إرسال دعاء للجميع
/set_khatma_count معرف_المستخدم رقم_الختمة - ضبط ختمة مستخدم
/download_db - سحب نسخة من قاعدة البيانات
""".strip()


def is_admin(message: types.Message) -> bool:
    return bool(message.from_user and message.from_user.id == ADMIN_ID)


async def is_group_admin(message: types.Message) -> bool:
    if message.chat.type == "private":
        return True
    if message.from_user and message.from_user.id == ADMIN_ID:
        return True
    if message.from_user is None:
        return False
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


async def delete_message_safe(chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def cleanup_group_messages(message: types.Message, *response_messages: types.Message, delay: int = 300) -> None:
    if message.chat.type not in ("group", "supergroup"):
        return
    await delete_message_safe(message.chat.id, message.message_id)
    if response_messages and delay > 0:
        msg_ids = [msg.message_id for msg in response_messages]

        async def _delete_after_delay():
            await asyncio.sleep(delay)
            for msg_id in msg_ids:
                await delete_message_safe(message.chat.id, msg_id)

        asyncio.create_task(_delete_after_delay())


def normalize_digits(value: str) -> str:
    translation = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return value.translate(translation)


def parse_positive_int(value: str, minimum: int, maximum: int) -> int | None:
    try:
        number = int(normalize_digits(value))
    except ValueError:
        return None

    if minimum <= number <= maximum:
        return number
    return None


def get_subscription_id(message: types.Message) -> int:
    return message.chat.id


def get_subscription_name(message: types.Message) -> str | None:
    if message.chat.type == "private" and message.from_user:
        return message.from_user.username
    return message.chat.title or message.chat.username


async def ensure_user(message: types.Message) -> None:
    chat_type = "group" if message.chat.type in ("group", "supergroup") else "private"
    db.add_user(get_subscription_id(message), get_subscription_name(message), chat_type)


def get_subscription_language(subscription_id: int) -> str:
    user = db.get_user(subscription_id)
    if user:
        return user["language"]
    return "ar"


def check_and_mark_setup(user_id: int) -> None:
    user = db.get_user(user_id)
    if user and not user.get("is_setup", 0):
        if user["daily_goal"] != 1 or user["send_time"] != "08:00":
            db.update_settings(user_id, is_setup=True)
            db.clear_last_sent_date(user_id)
            language = user["language"]
            is_group = user.get("chat_type", "private") == "group"
            asyncio.create_task(
                bot.send_message(
                    user_id,
                    "✅ تم اكتمال إعدادك بنجاح!\n\n"
                    "سيتم إرسال وردك اليومي تلقائيًا في الوقت المحدد.\n\n"
                    f"📖 الورد: {user['daily_goal']} صفحة يوميًا\n"
                    f"⏰ وقت الإرسال: {user['send_time']}\n"
                    f"📍 الصفحة الحالية: {user['current_page']}",
                    reply_markup=main_keyboard(language, user_id == ADMIN_ID, is_group),
                )
            )


async def health_check(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "quran-tele"})


async def start_health_server() -> web.AppRunner | None:
    port = os.getenv("PORT")
    if not port:
        return None

    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(port))
    await site.start()
    logger.info("Health server started on port %s", port)
    return runner


async def send_daily_quran(user_id: int, goal: int, current_page: int, preview: bool = False, send_images: bool = True) -> bool:
    async with _send_sem:
        pages, is_finish = get_pages_logic(current_page, goal)
        language = get_subscription_language(user_id)
        total_completed_khatmas = db.count_total_completed_khatmas()
        total_khatma_readers = db.count_total_khatma_readers()
        khatma_number = db.get_khatma_number(user_id)
        caption = build_wird_caption(
            start_page=pages[0],
            end_page=pages[-1],
            total_completed_khatmas=total_completed_khatmas,
            total_khatma_readers=total_khatma_readers,
            now=datetime.now(scheduler.timezone),
            khatma_number=khatma_number,
            language=language,
        )
        if preview:
            if language == "en":
                caption = f"[{get_text(language, 'preview_label')}]\n\n{caption}"
            else:
                caption = f"[{get_text(language, 'preview_label')}]\n\n{caption}"
        if not send_images:
            if language == "en":
                caption += get_text(language, "text_only_note")
            else:
                caption += get_text(language, "text_only_note")

        pdf_file = None
        image_files = []

        try:
            logger.info(
                "Preparing daily Quran for user=%s goal=%s current_page=%s pages=%s-%s count=%s preview=%s send_images=%s",
                user_id,
                goal,
                current_page,
                pages[0],
                pages[-1],
                len(pages),
                preview,
                send_images,
            )

            if not send_images:
                await bot.send_message(user_id, caption)
            elif len(pages) > 10:
                pdf_file = await generate_quran_pdf(pages, user_id)
                await bot.send_document(
                    user_id,
                    types.FSInputFile(pdf_file),
                    caption=f"{caption}\nتم إرساله كملف PDF لسهولة التصفح.",
                )
            else:
                image_files = await generate_quran_images(pages, user_id)
                if len(image_files) == 1:
                    await bot.send_photo(
                        user_id,
                        photo=types.FSInputFile(image_files[0]),
                        caption=caption,
                    )
                else:
                    media = [
                        types.InputMediaPhoto(
                            media=types.FSInputFile(image_file),
                            caption=caption if index == 0 else None,
                        )
                        for index, image_file in enumerate(image_files)
                    ]
                    await bot.send_media_group(user_id, media)

            if not preview:
                if is_finish:
                    khatma_keyboard = types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                types.InlineKeyboardButton(
                                    text=get_text(language, "read_khatma"),
                                    callback_data="khatma:read",
                                ),
                                types.InlineKeyboardButton(
                                    text=get_text(language, "not_read_khatma"),
                                    callback_data="khatma:not_read",
                                ),
                            ]
                        ]
                    )
                    await bot.send_message(
                        user_id,
                        "🎉 هنيئًا لكم ختم القرآن الكريم!\n\n"
                        "اللهم اجعل القرآن العظيم ربيع قلوبنا ونور صدورنا وجلاء أحزاننا وذهاب همومنا.\n\n"
                        "هل قرأت الختمة كاملة؟",
                        reply_markup=khatma_keyboard,
                    )
                    db.update_settings(user_id, page=1)
                else:
                    db.update_settings(user_id, page=pages[-1] + 1)

            return True
        except TelegramForbiddenError:
            logger.info("User %s blocked the bot. Deactivating user.", user_id)
            db.update_settings(user_id, is_active=False)
            return False
        except TelegramBadRequest as exc:
            logger.warning("Telegram rejected daily Quran send for %s: %s", user_id, exc)
            return False
        except Exception:
            logger.exception("Failed to send daily Quran to user %s", user_id)
            return False
        finally:
            if pdf_file:
                cleanup_file(pdf_file)
            for image_file in image_files:
                cleanup_file(image_file)
            # Force garbage collection after heavy image/pdf operations
            gc.collect()


async def check_due_daily_quran() -> None:
    now = datetime.now(scheduler.timezone)
    current_time = now.strftime("%H:%M")
    pdf_prepare_datetime = now + timedelta(minutes=1)
    pdf_prepare_time = (
        pdf_prepare_datetime.strftime("%H:%M")
        if pdf_prepare_datetime.date() == now.date()
        else current_time
    )
    today = now.date().isoformat()
    users = db.get_users_due(current_time, pdf_prepare_time, today)

    if not users:
        return

    logger.info(
        "Sending daily Quran to %s due users at %s, PDF pre-start window=%s",
        len(users),
        current_time,
        pdf_prepare_time,
    )
    for user in users:
        sent = await send_daily_quran(
            user["user_id"], user["daily_goal"], user["current_page"],
            send_images=bool(user.get("send_images", 1)),
        )
        if sent:
            db.update_settings(user["user_id"], last_sent_date=today)
        # Slightly longer sleep to reduce CPU/RAM pressure on free tier
        await asyncio.sleep(0.3)
        gc.collect()


async def send_dua_to_all() -> None:
    dua = choice(DUAS)
    users = db.get_all_active_users(private_only=True)
    if not users:
        return

    logger.info("Sending dua to %s active users (private only)", len(users))
    for user in users:
        try:
            await bot.send_message(user["user_id"], f"🤲 دعاء مأثور\n\n{dua}")
        except TelegramForbiddenError:
            db.update_settings(user["user_id"], is_active=False)
        except Exception:
            logger.exception("Failed to send dua to user %s", user["user_id"])
        await asyncio.sleep(0.3)
        gc.collect()


NOT_ADMIN_GROUP_MESSAGE = (
    "⚠️ يجب رفع البوت إلى مشرف (Admin) لكي يعمل بشكل صحيح.\n\n"
    "خطوات الرفع:\n"
    "1. افتح معلومات المجموعة\n"
    "2. اضغط على المشرفين\n"
    "3. اضغط إضافة مشرف\n"
    "4. اختر البوت\n\n"
    "بعد رفع البوت مشرفًا، ستظهر رسالة الترحيب تلقائيًا."
)


async def send_group_welcome(chat_id: int, chat_title: str | None = None) -> None:
    db.add_user(chat_id, chat_title, "group")
    db.update_settings(chat_id, is_active=True, chat_type="group")
    language = get_subscription_language(chat_id)
    admin = chat_id == ADMIN_ID
    await bot.send_message(
        chat_id,
        START_MESSAGE,
        reply_markup=main_keyboard(language, admin, is_group=True),
        parse_mode="HTML",
    )
    await bot.send_message(
        chat_id,
        "📍 لكي نبدأ، يرجى ضبط الصفحة الحالية.\n\n"
        "استخدم زر 📍 ضبط الصفحة الحالية أو اكتب /page متبوعًا برقم الصفحة (مثال: /page 25)",
        reply_markup=main_keyboard(language, admin, is_group=True),
    )
    await bot.send_message(
        chat_id,
        "🔢 الآن ضبط عدد صفحات الورد اليومي.\n\n"
        "استخدم زر 🔢 ضبط عدد الصفحات أو اكتب /goal متبوعًا بالعدد (مثال: /goal 5)",
        reply_markup=main_keyboard(language, admin, is_group=True),
    )
    await bot.send_message(
        chat_id,
        "⏰ وأخيرًا، ضبط وقت الإرسال اليومي.\n\n"
        "استخدم زر ⏰ ضبط وقت الإرسال أو اكتب /time متبوعًا بالوقت (مثال: /time 21:00)",
        reply_markup=main_keyboard(language, admin, is_group=True),
    )


@dp.my_chat_member()
async def on_bot_chat_member_updated(event: ChatMemberUpdated):
    chat = event.chat
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status

    if chat.type not in ("group", "supergroup"):
        return

    chat_id = chat.id
    chat_title = chat.title or chat.username or str(chat_id)

    if new_status in ("left", "kicked"):
        user = db.get_user(chat_id)
        if user:
            db.update_settings(chat_id, is_active=False)
        return

    if new_status in ("administrator", "creator"):
        await send_group_welcome(chat_id, chat_title)
        return

    if new_status == "member":
        db.add_user(chat_id, chat_title, "group")
        db.update_settings(chat_id, is_active=True, chat_type="group")
        try:
            await bot.send_message(chat_id, NOT_ADMIN_GROUP_MESSAGE)
        except Exception:
            logger.exception("Failed to send not-admin message to group %s", chat_id)


@dp.message(Command("start"))
async def start(message: types.Message):
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    language = get_subscription_language(subscription_id)

    if message.chat.type in ("group", "supergroup"):
        try:
            bot_member = await bot.get_chat_member(message.chat.id, bot.id)
            if bot_member.status not in ("administrator", "creator"):
                resp1 = await message.answer(NOT_ADMIN_GROUP_MESSAGE)
                await cleanup_group_messages(message, resp1)
                return
        except Exception:
            resp1 = await message.answer(NOT_ADMIN_GROUP_MESSAGE)
            await cleanup_group_messages(message, resp1)
            return

        admin = message.from_user and message.from_user.id == ADMIN_ID
        resp1 = await message.answer(
            START_MESSAGE,
            reply_markup=main_keyboard(language, admin, is_group=True),
            parse_mode="HTML",
        )
        resp2 = await message.answer(
            "📍 لكي نبدأ، يرجى ضبط الصفحة الحالية.\n\n"
            "استخدم زر 📍 ضبط الصفحة الحالية أو اكتب /page متبوعًا برقم الصفحة (مثال: /page 25)",
            reply_markup=main_keyboard(language, admin, is_group=True),
        )
        resp3 = await message.answer(
            "🔢 الآن ضبط عدد صفحات الورد اليومي.\n\n"
            "استخدم زر 🔢 ضبط عدد الصفحات أو اكتب /goal متبوعًا بالعدد (مثال: /goal 5)",
            reply_markup=main_keyboard(language, admin, is_group=True),
        )
        resp4 = await message.answer(
            "⏰ وأخيرًا، ضبط وقت الإرسال اليومي.\n\n"
            "استخدم زر ⏰ ضبط وقت الإرسال أو اكتب /time متبوعًا بالوقت (مثال: /time 21:00)",
            reply_markup=main_keyboard(language, admin, is_group=True),
        )
        await cleanup_group_messages(message, resp1, resp2, resp3, resp4)
        return

    admin = subscription_id == ADMIN_ID
    await message.answer(
        START_MESSAGE,
        reply_markup=main_keyboard(language, admin),
        parse_mode="HTML",
    )
    await message.answer(
        "🔢 لكي نبدأ، يرجى ضبط عدد صفحات الورد اليومي.\n\n"
        "استخدم زر 🔢 ضبط عدد الصفحات أو اكتب /goal متبوعًا بالعدد (مثال: /goal 5)",
        reply_markup=main_keyboard(language, admin),
    )
    await message.answer(
        "⏰ الآن ضبط وقت الإرسال اليومي.\n\n"
        "استخدم زر ⏰ ضبط وقت الإرسال أو اكتب /time متبوعًا بالوقت (مثال: /time 08:00)",
        reply_markup=main_keyboard(language, admin),
    )


@dp.message(Command("help"))
async def help_command(message: types.Message):
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    language = get_subscription_language(subscription_id)
    is_group = message.chat.type in ("group", "supergroup")
    admin = message.from_user and message.from_user.id == ADMIN_ID
    resp = await message.answer(
        HELP_TEXT if is_admin(message) else
        "استخدم الأزرار في الأسفل للتحكم بإعداداتك.\n\n"
        "لأي استفسار تواصل مع المطور.",
        reply_markup=main_keyboard(language, admin, is_group),
    )
    await cleanup_group_messages(message, resp)


@dp.message(Command("status"))
async def status(message: types.Message):
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    user = db.get_user(subscription_id)
    if not user:
        resp = await message.answer("استخدم /start أولًا لتفعيل اشتراكك.")
        await cleanup_group_messages(message, resp)
        return

    active_text = "نشط ✅" if user["is_active"] else "متوقف مؤقتًا ⏸"
    setup_text = "مكتمل ✅" if user.get("is_setup", 0) else "غير مكتمل ❌"
    khatma_num = user.get("khatma_number", 0)
    send_type_text = "📷 مع صور" if user.get("send_images", 1) else "📝 نص فقط"
    admin = message.from_user and message.from_user.id == ADMIN_ID
    is_group = message.chat.type in ("group", "supergroup")
    resp = await message.answer(
        "📌 إعداداتك الحالية:\n\n"
        f"الحالة: {active_text}\n"
        f"الإعداد: {setup_text}\n"
        f"الختمة الحالية: {khatma_num}\n"
        f"الورد اليومي: {user['daily_goal']} صفحة\n"
        f"الصفحة الحالية: {user['current_page']}\n"
        f"وقت الإرسال: {user['send_time']}\n"
        f"نوع الإرسال: {send_type_text}",
        reply_markup=main_keyboard(user["language"], admin, is_group),
    )
    await cleanup_group_messages(message, resp)


@dp.message(Command("goal"))
async def set_goal(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        resp = await message.answer("اكتب عدد الصفحات هكذا: /goal 5")
        await cleanup_group_messages(message, resp)
        return

    goal = parse_positive_int(parts[1].strip(), 1, 604)
    if goal is None:
        resp = await message.answer("عدد الصفحات يجب أن يكون رقمًا بين 1 و 604.")
        await cleanup_group_messages(message, resp)
        return

    subscription_id = get_subscription_id(message)
    db.update_settings(subscription_id, goal=goal)
    resp = await message.answer(f"تم ضبط الورد اليومي على {goal} صفحة ✅")
    await cleanup_group_messages(message, resp)
    check_and_mark_setup(subscription_id)


@dp.message(Command("time"))
async def set_time(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    parts = message.text.split(maxsplit=1)
    send_time = normalize_digits(parts[1].strip()) if len(parts) >= 2 else ""
    if not TIME_PATTERN.match(send_time):
        resp = await message.answer("اكتب الوقت بصيغة 24 ساعة هكذا: /time 08:00")
        await cleanup_group_messages(message, resp)
        return
    subscription_id = get_subscription_id(message)
    db.update_settings(subscription_id, send_time=send_time)
    db.clear_last_sent_date(subscription_id)
    resp = await message.answer(
        f"تم ضبط وقت الإرسال اليومي على {send_time} ✅\n"
        "إذا كان الوقت قد حان أو مرّ اليوم، سيتم الإرسال خلال أقل من دقيقة."
    )
    await cleanup_group_messages(message, resp)
    check_and_mark_setup(subscription_id)


@dp.message(Command("page"))
async def set_page(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        resp = await message.answer("اكتب رقم الصفحة هكذا: /page 25")
        await cleanup_group_messages(message, resp)
        return

    page = parse_positive_int(parts[1].strip(), 1, 604)
    if page is None:
        resp = await message.answer("رقم الصفحة يجب أن يكون بين 1 و 604.")
        await cleanup_group_messages(message, resp)
        return

    db.update_settings(get_subscription_id(message), page=page)
    resp = await message.answer(f"تم ضبط صفحة البداية الحالية على {page} ✅")
    await cleanup_group_messages(message, resp)


@dp.message(Command("khatma"))
async def set_khatma(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        resp = await message.answer(
            "اكتب رقم الختمة هكذا: /khatma 5\n\n"
            "رقم الختمة هو رقم الختمة الحالية التي تقرأ فيها."
        )
        await cleanup_group_messages(message, resp)
        return

    khatma_num = parse_positive_int(parts[1].strip(), 1, 9999)
    if khatma_num is None:
        resp = await message.answer("رقم الختمة يجب أن يكون رقمًا بين 1 و 9999.")
        await cleanup_group_messages(message, resp)
        return

    subscription_id = get_subscription_id(message)
    db.update_settings(subscription_id, khatma_number=khatma_num)
    resp = await message.answer(f"✅ تم تعيين رقم الختمة إلى {khatma_num}")
    await cleanup_group_messages(message, resp)


@dp.message(Command("azkar", "dua"))
async def send_azkar(message: types.Message):
    await ensure_user(message)
    resp = await message.answer(f"🤲 ذكر ودعاء\n\n{choice(DUAS)}")
    await cleanup_group_messages(message, resp, delay=120)


@dp.message(Command("pause"))
async def pause(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    db.update_settings(get_subscription_id(message), is_active=False)
    resp = await message.answer("تم إيقاف الورد اليومي مؤقتًا ⏸\nيمكنك استئنافه عبر /resume")
    await cleanup_group_messages(message, resp)


@dp.message(Command("resume"))
async def resume(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    db.update_settings(get_subscription_id(message), is_active=True)
    db.clear_last_sent_date(get_subscription_id(message))
    resp = await message.answer("تم استئناف الورد اليومي ✅")
    await cleanup_group_messages(message, resp)


@dp.message(Command("send_now"))
async def send_now(message: types.Message):
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    user = db.get_user(subscription_id)
    if not user:
        resp = await message.answer("استخدم /start أولًا لتفعيل اشتراكك.")
        await cleanup_group_messages(message, resp)
        return

    loading_msg = await message.answer("جاري تجهيز وردك الآن... ⏳")
    sent = await send_daily_quran(
        user["user_id"], user["daily_goal"], user["current_page"],
        send_images=bool(user.get("send_images", 1)),
    )
    try:
        await loading_msg.delete()
    except Exception:
        pass
    if not sent:
        resp = await message.answer("تعذر إرسال الورد الآن. حاول لاحقًا.")
        await cleanup_group_messages(message, resp)
    else:
        await delete_message_safe(message.chat.id, message.message_id)


@dp.message(F.text.in_([BTN_SEND_NOW, "📖 Send wird now"]))
async def send_now_button(message: types.Message):
    await send_now(message)


@dp.message(F.text.in_([BTN_AZKAR, "🤲 Dua now"]))
async def azkar_button(message: types.Message):
    await send_azkar(message)


@dp.message(F.text.in_([BTN_STATUS, "📌 My settings"]))
async def status_button(message: types.Message):
    await status(message)


@dp.message(F.text.in_([BTN_SET_TIME, "⏰ Set send time"]))
async def ask_time_button(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    PENDING_ACTIONS[get_subscription_id(message)] = ("time", message.from_user.id)
    resp = await message.answer(
        "⏰ أرسل وقت الإرسال اليومي بصيغة 24 ساعة.\n\n"
        "مثال: 08:00 أو 21:30\n"
        "إذا كان الوقت قد حان أو مرّ اليوم، سيرسل البوت خلال أقل من دقيقة."
    )
    await cleanup_group_messages(message, resp)


@dp.message(F.text.in_([BTN_SET_GOAL, "🔢 Set daily pages"]))
async def ask_goal_button(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    PENDING_ACTIONS[get_subscription_id(message)] = ("goal", message.from_user.id)
    resp = await message.answer(
        "🔢 أرسل عدد صفحات الورد اليومي.\n\n"
        "مثال: 1 أو 5 أو 10\n"
        "إذا كان أكثر من 10 صفحات سيتم تجهيزه كملف PDF."
    )
    await cleanup_group_messages(message, resp)


@dp.message(F.text.in_([BTN_SET_PAGE, "📍 Set current page"]))
async def ask_page_button(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    PENDING_ACTIONS[get_subscription_id(message)] = ("page", message.from_user.id)
    resp = await message.answer("📍 أرسل رقم الصفحة الحالية بين 1 و 604.\n\nمثال: 25")
    await cleanup_group_messages(message, resp)


@dp.message(F.text.in_([BTN_SET_KHATMA, "🔢 Set Khatma"]))
async def ask_khatma_button(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    PENDING_ACTIONS[get_subscription_id(message)] = ("set_khatma_user", message.from_user.id)
    resp = await message.answer(
        "🔢 أرسل رقم الختمة الحالية.\n\n"
        "رقم الختمة هو رقم الختمة التي تقرأ فيها الآن.\n"
        "مثال: 5"
    )
    await cleanup_group_messages(message, resp)


@dp.message(F.text.in_([BTN_PAUSE, "⏸ Pause"]))
async def pause_button(message: types.Message):
    await pause(message)


@dp.message(F.text.in_([BTN_RESUME, "▶️ Resume"]))
async def resume_button(message: types.Message):
    await resume(message)


@dp.message(F.text.in_([BTN_LANGUAGE, "🌐 Change language"]))
async def language_button(message: types.Message):
    await ensure_user(message)
    language = get_subscription_language(get_subscription_id(message))
    await message.answer(
        get_text(language, "choose_language"), reply_markup=language_keyboard()
    )


@dp.message(F.text.in_([BTN_TEST_SEND, "🧪 Preview Wird"]))
async def test_send_button(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    user = db.get_user(subscription_id)
    if not user:
        resp = await message.answer("استخدم /start أولًا لتفعيل اشتراكك.")
        await cleanup_group_messages(message, resp)
        return

    loading_msg = await message.answer("جاري تجهيز معاينة الورد... ⏳")
    sent = await send_daily_quran(
        user["user_id"], user["daily_goal"], user["current_page"],
        preview=True, send_images=bool(user.get("send_images", 1)),
    )
    try:
        await loading_msg.delete()
    except Exception:
        pass
    if not sent:
        resp = await message.answer("تعذر إرسال الورد الآن. حاول لاحقًا.")
        await cleanup_group_messages(message, resp)
    else:
        await delete_message_safe(message.chat.id, message.message_id)


@dp.message(F.text.in_([BTN_CALIBRATE, "⚙️ Calibration"]))
async def calibrate_button(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    language = get_subscription_language(get_subscription_id(message))
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="⏩ سبق يوم" if language == "ar" else "⏩ Skip a day",
                    callback_data="calibrate:forward",
                ),
                types.InlineKeyboardButton(
                    text="⏪ قصر يوم" if language == "ar" else "⏪ Go back a day",
                    callback_data="calibrate:backward",
                ),
            ]
        ]
    )
    user = db.get_user(get_subscription_id(message))
    if user:
        resp = await message.answer(
            f"⚙️ معايرة الصفحة الحالية\n\n"
            f"📍 الصفحة الحالية: {user['current_page']}\n"
            f"🔢 الورد اليومي: {user['daily_goal']} صفحة\n\n"
            f"⏩ سبق يوم: تقديم الصفحة بورد يوم كامل\n"
            f"⏪ قصر يوم: تأخير الصفحة بورد يوم كامل",
            reply_markup=keyboard,
        )
    else:
        resp = await message.answer("⚙️ Calibration", reply_markup=keyboard)
    await cleanup_group_messages(message, resp)


@dp.message(F.text.in_([BTN_SEND_TYPE, "🖼 Send Type"]))
async def send_type_button(message: types.Message):
    if message.chat.type in ("group", "supergroup") and not await is_group_admin(message):
        await message.answer("⚠️ فقط مشرفو المجموعة يمكنهم تعديل الإعدادات.")
        await delete_message_safe(message.chat.id, message.message_id)
        return
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    user = db.get_user(subscription_id)
    language = get_subscription_language(subscription_id)
    current = bool(user.get("send_images", 1)) if user else True
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📷 مع صور" + (" ✅" if current else ""),
                    callback_data="images:on",
                ),
                types.InlineKeyboardButton(
                    text="📝 نص فقط" + ("" if current else " ✅"),
                    callback_data="images:off",
                ),
            ]
        ]
    )
    if language == "en":
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="📷 With images" + (" ✅" if current else ""),
                        callback_data="images:on",
                    ),
                    types.InlineKeyboardButton(
                        text="📝 Text only" + ("" if current else " ✅"),
                        callback_data="images:off",
                    ),
                ]
            ]
        )
        resp = await message.answer(
            f"🖼 Send type\n\n"
            f"Current: {'With images' if current else 'Text only'}\n\n"
            f"📷 With images: sends pages as images or PDF\n"
            f"📝 Text only: sends only the juz and page info as text",
            reply_markup=keyboard,
        )
    else:
        resp = await message.answer(
            f"🖼 نوع الإرسال\n\n"
            f"الحالي: {'📷 مع صور' if current else '📝 نص فقط'}\n\n"
            f"📷 مع صور: يرسل صفحات القرآن كصور أو PDF\n"
            f"📝 نص فقط: يرسل فقط معلومات الجزء والصفحات كنص",
            reply_markup=keyboard,
        )
    await cleanup_group_messages(message, resp)


@dp.callback_query(F.data.startswith("calibrate:"))
async def handle_calibrate(callback: types.CallbackQuery):
    action = callback.data.split(":", 1)[1]
    user_id = callback.message.chat.id
    user = db.get_user(user_id)
    if not user:
        await callback.answer("استخدم /start أولًا.")
        return

    language = user.get("language", "ar")
    daily_goal = user["daily_goal"]
    current_page = user["current_page"]

    if action == "forward":
        new_page = min(current_page + daily_goal, 604)
        db.update_settings(user_id, page=new_page)
        if language == "en":
            await callback.answer(f"Skipped ahead: page {current_page} → {new_page}")
            await callback.message.edit_text(
                f"⏩ Skipped a day\n\n"
                f"Page: {current_page} → {new_page}\n"
                f"Daily goal: {daily_goal} pages"
            )
        else:
            await callback.answer(f"تم السبق: صفحة {current_page} ← {new_page}")
            await callback.message.edit_text(
                f"⏩ تم سبق يوم\n\n"
                f"الصفحة: {current_page} ← {new_page}\n"
                f"الورد اليومي: {daily_goal} صفحة"
            )
    elif action == "backward":
        new_page = max(current_page - daily_goal, 1)
        db.update_settings(user_id, page=new_page)
        if language == "en":
            await callback.answer(f"Went back: page {current_page} → {new_page}")
            await callback.message.edit_text(
                f"⏪ Went back a day\n\n"
                f"Page: {current_page} → {new_page}\n"
                f"Daily goal: {daily_goal} pages"
            )
        else:
            await callback.answer(f"تم القصر: صفحة {current_page} ← {new_page}")
            await callback.message.edit_text(
                f"⏪ تم قصر يوم\n\n"
                f"الصفحة: {current_page} ← {new_page}\n"
                f"الورد اليومي: {daily_goal} صفحة"
            )


@dp.callback_query(F.data.startswith("images:"))
async def handle_images_toggle(callback: types.CallbackQuery):
    action = callback.data.split(":", 1)[1]
    user_id = callback.message.chat.id
    language = get_subscription_language(user_id)

    if action == "on":
        db.update_settings(user_id, send_images=True)
        if language == "en":
            await callback.answer("Send type: With images ✅")
            await callback.message.edit_text(
                "🖼 Send type updated\n\n"
                "📷 With images: pages will be sent as images or PDF."
            )
        else:
            await callback.answer("نوع الإرسال: مع صور ✅")
            await callback.message.edit_text(
                "🖼 تم تحديث نوع الإرسال\n\n"
                "📷 مع صور: سيتم إرسال صفحات القرآن كصور أو PDF."
            )
    elif action == "off":
        db.update_settings(user_id, send_images=False)
        if language == "en":
            await callback.answer("Send type: Text only ✅")
            await callback.message.edit_text(
                "🖼 Send type updated\n\n"
                "📝 Text only: only juz and page info will be sent as text."
            )
        else:
            await callback.answer("نوع الإرسال: نص فقط ✅")
            await callback.message.edit_text(
                "🖼 تم تحديث نوع الإرسال\n\n"
                "📝 نص فقط: سيتم إرسال معلومات الجزء والصفحات كنص فقط."
            )


@dp.callback_query(F.data.startswith("lang:"))
async def change_language(callback: types.CallbackQuery):
    language = callback.data.split(":", 1)[1]
    if language not in TEXTS:
        await callback.answer("Unsupported language", show_alert=True)
        return

    subscription_id = callback.message.chat.id
    db.update_settings(subscription_id, language=language)
    await callback.answer()
    is_group = callback.message.chat.type in ("group", "supergroup")
    admin = callback.from_user and callback.from_user.id == ADMIN_ID
    await callback.message.answer(
        get_text(language, "language_updated"), reply_markup=main_keyboard(language, admin, is_group)
    )


@dp.callback_query(F.data.startswith("khatma:"))
async def handle_khatma_response(callback: types.CallbackQuery):
    action = callback.data.split(":", 1)[1]
    user_id = callback.message.chat.id

    if action == "read":
        db.increment_completed_khatmas(user_id)
        db.increment_khatma_read_count(user_id)
        current_khatma = db.get_khatma_number(user_id)
        db.update_settings(user_id, khatma_number=current_khatma + 1)
        await callback.answer("جزاكم الله خيرًا! تم تسجيل ختمتك ✅")
        await callback.message.edit_text(
            "🎉 تم تسجيل ختمتك بحمد الله!\n\n"
            "اللهم تقبل منا ومنكم صالح الأعمال.\n\n"
            "سنبدأ ختمة جديدة في الورد القادم بإذن الله."
        )
    else:
        current_khatma = db.get_khatma_number(user_id)
        db.update_settings(user_id, khatma_number=current_khatma + 1)
        await callback.answer("تم تسجيل أنك لم تقرأ الختمة")
        await callback.message.edit_text(
            "📝 تم تسجيل أنك لم تقرأ الختمة.\n\n"
            "لا بأس، يمكنك قراءتها لاحقًا إن شاء الله.\n\n"
            "سنبدأ ختمة جديدة في الورد القادم بإذن الله."
        )

    db.update_settings(user_id, page=1)


@dp.message(F.text, lambda message: get_subscription_id_no_ensure(message) in PENDING_ACTIONS)
async def handle_pending_input(message: types.Message):
    subscription_id = get_subscription_id(message)
    entry = PENDING_ACTIONS.pop(subscription_id, None)
    if entry is None:
        return
    action, original_user_id = entry

    if message.chat.type in ("group", "supergroup"):
        if message.from_user and message.from_user.id != original_user_id:
            PENDING_ACTIONS[subscription_id] = (action, original_user_id)
            return
        await delete_message_safe(message.chat.id, message.message_id)

    await ensure_user(message)
    text = message.text.strip()
    is_group = message.chat.type in ("group", "supergroup")
    admin = message.from_user and message.from_user.id == ADMIN_ID

    if action == "time":
        normalized = normalize_digits(text)
        if not TIME_PATTERN.match(normalized):
            PENDING_ACTIONS[subscription_id] = ("time", original_user_id)
            resp = await message.answer(
                "صيغة الوقت غير صحيحة. أرسل الوقت هكذا: 08:00 أو 21:30"
            )
            await cleanup_group_messages(message, resp)
            return
        db.update_settings(subscription_id, send_time=normalized)
        db.clear_last_sent_date(subscription_id)
        resp = await message.answer(
            f"تم ضبط وقت الإرسال اليومي على {normalized} ✅\n"
            "إذا كان الوقت قد حان أو مرّ اليوم، سيتم الإرسال خلال أقل من دقيقة.",
            reply_markup=main_keyboard(get_subscription_language(subscription_id), admin, is_group),
        )
        await cleanup_group_messages(message, resp)
        check_and_mark_setup(subscription_id)
        return

    if action == "goal":
        goal = parse_positive_int(normalize_digits(text), 1, 604)
        if goal is None:
            PENDING_ACTIONS[subscription_id] = ("goal", original_user_id)
            resp = await message.answer("عدد الصفحات يجب أن يكون رقمًا بين 1 و 604.")
            await cleanup_group_messages(message, resp)
            return
        db.update_settings(subscription_id, goal=goal)
        resp = await message.answer(
            f"تم ضبط الورد اليومي على {goal} صفحة ✅", reply_markup=main_keyboard(get_subscription_language(subscription_id), admin, is_group)
        )
        await cleanup_group_messages(message, resp)
        check_and_mark_setup(subscription_id)
        return

    if action == "page":
        page = parse_positive_int(normalize_digits(text), 1, 604)
        if page is None:
            PENDING_ACTIONS[subscription_id] = ("page", original_user_id)
            resp = await message.answer("رقم الصفحة يجب أن يكون بين 1 و 604.")
            await cleanup_group_messages(message, resp)
            return
        db.update_settings(subscription_id, page=page)
        resp = await message.answer(
            f"تم ضبط صفحة البداية الحالية على {page} ✅", reply_markup=main_keyboard(get_subscription_language(subscription_id), admin, is_group)
        )
        await cleanup_group_messages(message, resp)
        return

    if action == "set_khatma_user":
        khatma_num = parse_positive_int(normalize_digits(text), 1, 9999)
        if khatma_num is None:
            PENDING_ACTIONS[subscription_id] = ("set_khatma_user", original_user_id)
            resp = await message.answer("رقم الختمة يجب أن يكون بين 1 و 9999.")
            await cleanup_group_messages(message, resp)
            return
        db.update_settings(subscription_id, khatma_number=khatma_num)
        resp = await message.answer(
            f"✅ تم تعيين رقم الختمة إلى {khatma_num}",
            reply_markup=main_keyboard(get_subscription_language(subscription_id), admin, is_group),
        )
        await cleanup_group_messages(message, resp)
        return

    if action == "broadcast":
        if not is_admin(message):
            PENDING_ACTIONS.pop(subscription_id, None)
            return
        if not text:
            PENDING_ACTIONS[subscription_id] = ("broadcast", original_user_id)
            await message.answer("الرجاء إرسال نص التعميم:")
            return
        users = db.get_all_active_users()
        sent_count = 0
        for user in users:
            try:
                await bot.send_message(user["user_id"], text)
                sent_count += 1
            except TelegramForbiddenError:
                db.update_settings(user["user_id"], is_active=False)
            except Exception:
                logger.exception("Broadcast failed for user %s", user["user_id"])
            await asyncio.sleep(0.1)
        resp = await message.answer(
            f"✅ تم إرسال التعميم إلى {sent_count} مستخدم.",
            reply_markup=main_keyboard(get_subscription_language(subscription_id), admin, is_group),
        )
        await cleanup_group_messages(message, resp)
        return

    if action == "set_khatma":
        if not is_admin(message):
            PENDING_ACTIONS.pop(subscription_id, None)
            return
        parts = text.split()
        if len(parts) != 2:
            PENDING_ACTIONS[subscription_id] = ("set_khatma", original_user_id)
            resp = await message.answer("الصيغة غير صحيحة. أرسل: رقم_المستخدم رقم_الختمة\nمثال: 123456 20")
            await cleanup_group_messages(message, resp)
            return
        try:
            user_id = int(parts[0])
            khatma_number = int(parts[1])
        except ValueError:
            PENDING_ACTIONS[subscription_id] = ("set_khatma", original_user_id)
            resp = await message.answer("يجب أن يكونا أرقامًا صحيحة. مثال: 123456 20")
            await cleanup_group_messages(message, resp)
            return
        user = db.get_user(user_id)
        if not user:
            resp = await message.answer("المستخدم غير موجود.")
            await cleanup_group_messages(message, resp)
            return
        db.update_settings(user_id, khatma_number=khatma_number)
        resp = await message.answer(
            f"✅ تم ضبط رقم الختمة للمستخدم {user_id} على {khatma_number}",
            reply_markup=main_keyboard(get_subscription_language(subscription_id), admin, is_group),
        )
        await cleanup_group_messages(message, resp)
        return


def get_subscription_id_no_ensure(message: types.Message) -> int:
    return message.chat.id


@dp.message(Command("admin_stats"), F.from_user.id == ADMIN_ID)
async def admin_stats(message: types.Message):
    await message.answer(f"📊 عدد المشتركين النشطين: {db.count_active_users()}")


@dp.message(Command("broadcast"), F.from_user.id == ADMIN_ID)
async def broadcast(message: types.Message):
    text = message.text.replace("/broadcast", "", 1).strip()
    if not text:
        await message.answer("اكتب الرسالة بعد الأمر هكذا: /broadcast السلام عليكم")
        return

    users = db.get_all_active_users()
    sent_count = 0
    for user in users:
        try:
            await bot.send_message(user["user_id"], text)
            sent_count += 1
        except TelegramForbiddenError:
            db.update_settings(user["user_id"], is_active=False)
        except Exception:
            logger.exception("Broadcast failed for user %s", user["user_id"])
        await asyncio.sleep(0.1)

    await message.answer(f"✅ تم إرسال التعميم إلى {sent_count} مشترك.")


@dp.message(Command("admin_send_dua"), F.from_user.id == ADMIN_ID)
async def admin_send_dua(message: types.Message):
    await send_dua_to_all()
    await message.answer("✅ تم إرسال دعاء للمشتركين النشطين.")


@dp.message(Command("set_khatma_count"), F.from_user.id == ADMIN_ID)
async def set_khatma_count(message: types.Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("اكتب الأمر هكذا: /set_khatma_count <user_id> <khatma_number>\nمثال: /set_khatma_count 123456 20")
        return

    try:
        user_id = int(parts[1])
        khatma_number = int(parts[2])
    except ValueError:
        await message.answer("رقم المستخدم ورقم الختمة يجب أن يكونا أرقامًا صحيحة.")
        return

    user = db.get_user(user_id)
    if not user:
        await message.answer("المستخدم غير موجود.")
        return

    db.update_settings(user_id, khatma_number=khatma_number)
    await message.answer(f"✅ تم ضبط رقم الختمة للمستخدم {user_id} على {khatma_number}")


@dp.message(F.text.in_([BTN_ADMIN_STATS, "📊 Statistics"]))
async def admin_stats_button(message: types.Message):
    if not is_admin(message):
        return
    await message.answer(f"📊 عدد المشتركين النشطين: {db.count_active_users()}")


@dp.message(F.text.in_([BTN_ADMIN_BROADCAST, "📢 Broadcast"]))
async def admin_broadcast_button(message: types.Message):
    if not is_admin(message):
        return
    PENDING_ACTIONS[get_subscription_id(message)] = ("broadcast", message.from_user.id)
    await message.answer("📢 أرسل نص التعميم الذي تريد إرساله لجميع المشتركين:")


@dp.message(F.text.in_([BTN_ADMIN_SEND_DUA, "🤲 Send Dua to All"]))
async def admin_send_dua_button(message: types.Message):
    if not is_admin(message):
        return
    await send_dua_to_all()
    await message.answer("✅ تم إرسال دعاء للمشتركين النشطين.")


@dp.message(Command("download_db"), F.from_user.id == ADMIN_ID)
async def download_db_command(message: types.Message):
    db_path = Path.home() / "QuranBotData" / "quran_bot.db"
    if not db_path.exists():
        await message.answer("⚠️ ملف قاعدة البيانات غير موجود.")
        return
    await message.answer_document(
        document=types.FSInputFile(str(db_path), filename="quran_bot.db"),
        caption="💾 نسخة من قاعدة البيانات",
    )


@dp.message(F.text.in_([BTN_ADMIN_DB, "💾 Download Database"]))
async def admin_db_button(message: types.Message):
    if not is_admin(message):
        return
    await download_db_command(message)


@dp.message(F.text, F.chat.type == "private")
async def fallback_private(message: types.Message):
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    if message.text.strip() in ALL_BUTTON_TEXTS:
        return
    admin = subscription_id == ADMIN_ID
    user = db.get_user(subscription_id)
    if user and user["daily_goal"] == 1 and user["send_time"] == "08:00" and user["current_page"] == 1:
        await message.answer(
            "يرجى ضبط إعداداتك أولاً لاستخدام البوت.\n\n"
            "استخدم زر 🔢 ضبط عدد الصفحات لضبط عدد الصفحات اليومية.\n"
            "استخدم زر ⏰ ضبط وقت الإرسال لضبط وقت الإرسال.",
            reply_markup=main_keyboard(user["language"], admin),
        )
        return
    await message.answer(
        "لم أفهم الأمر. استخدم الأزرار في الأسفل أو /help لعرض الأوامر المتاحة.",
        reply_markup=main_keyboard(get_subscription_language(subscription_id), admin),
    )


@dp.message(F.text, F.chat.type.in_({"group", "supergroup"}))
async def fallback_group(message: types.Message):
    pass


async def set_bot_commands() -> None:
    user_commands_ar = [
        types.BotCommand(command="start", description="بدء الاشتراك في الورد اليومي"),
        types.BotCommand(command="status", description="عرض إعداداتك الحالية"),
        types.BotCommand(command="goal", description="ضبط عدد الصفحات /goal 5"),
        types.BotCommand(command="time", description="ضبط وقت الإرسال /time 08:00"),
        types.BotCommand(command="page", description="ضبط الصفحة الحالية /page 25"),
        types.BotCommand(command="khatma", description="تعيين رقم الختمة /khatma 5"),
        types.BotCommand(command="send_now", description="إرسال ورد اليوم الآن"),
        types.BotCommand(command="azkar", description="ذكر أو دعاء الآن"),
        types.BotCommand(command="pause", description="إيقاف الإرسال مؤقتاً"),
        types.BotCommand(command="resume", description="استئناف الإرسال"),
    ]
    user_commands_en = [
        types.BotCommand(command="start", description="Subscribe to daily Quran wird"),
        types.BotCommand(command="status", description="View your current settings"),
        types.BotCommand(command="goal", description="Set daily pages /goal 5"),
        types.BotCommand(command="time", description="Set send time /time 08:00"),
        types.BotCommand(command="page", description="Set current page /page 25"),
        types.BotCommand(command="khatma", description="Set khatma number /khatma 5"),
        types.BotCommand(command="send_now", description="Send today's portion now"),
        types.BotCommand(command="azkar", description="Get a dua or dhikr now"),
        types.BotCommand(command="pause", description="Pause daily sending"),
        types.BotCommand(command="resume", description="Resume daily sending"),
    ]
    admin_commands_ar = [
        types.BotCommand(command="admin_stats", description="عدد المشتركين النشطين"),
        types.BotCommand(command="broadcast", description="تعميم رسالة للجميع"),
        types.BotCommand(command="admin_send_dua", description="إرسال دعاء للجميع"),
        types.BotCommand(command="set_khatma_count", description="ضبط رقم الختمة لمستخدم"),
        types.BotCommand(command="download_db", description="سحب نسخة من قاعدة البيانات"),
    ]
    admin_commands_en = [
        types.BotCommand(command="admin_stats", description="Active subscribers count"),
        types.BotCommand(command="broadcast", description="Broadcast message to all"),
        types.BotCommand(command="admin_send_dua", description="Send dua to all users"),
        types.BotCommand(command="set_khatma_count", description="Set khatma number for user"),
        types.BotCommand(command="download_db", description="Download database backup"),
    ]
    try:
        await bot.set_my_commands(user_commands_ar, scope=types.BotCommandScopeAllPrivateChats(), language_code="ar")
        await bot.set_my_commands(user_commands_en, scope=types.BotCommandScopeAllPrivateChats(), language_code="en")
        await bot.set_my_commands(admin_commands_ar, scope=types.BotCommandScopeAllChatAdministrators(), language_code="ar")
        await bot.set_my_commands(admin_commands_en, scope=types.BotCommandScopeAllChatAdministrators(), language_code="en")
        logger.info("Bot commands registered successfully")
    except Exception:
        logger.exception("Failed to set bot commands")


async def main() -> None:
    try:
        try:
            bot_info = await bot.get_me()
            logger.info("Authorized as @%s", bot_info.username)
        except TelegramUnauthorizedError as exc:
            raise RuntimeError(
                "Telegram rejected BOT_TOKEN as Unauthorized. Generate a new token from "
                "@BotFather, update your .env BOT_TOKEN, then run python main.py again."
            ) from exc

        global health_runner
        health_runner = await start_health_server()

        await set_bot_commands()

        scheduler.add_job(
            check_due_daily_quran, "interval", seconds=20, max_instances=1
        )
        scheduler.add_job(send_dua_to_all, "interval", hours=8, max_instances=1)
        scheduler.start()

        logger.info("Quran bot started")
        await dp.start_polling(bot, allowed_updates=[UpdateType.MESSAGE, UpdateType.CALLBACK_QUERY, UpdateType.MY_CHAT_MEMBER])
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        if health_runner:
            await health_runner.cleanup()
        await close_shared_session()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())