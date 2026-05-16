from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from random import choice

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramUnauthorizedError,
)
from aiogram.filters import Command
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from database import DBManager
from utils import (
    DUAS,
    build_wird_caption,
    cleanup_file,
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
}

PENDING_ACTIONS: dict[int, str] = {}

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
    },
}


def get_text(language: str, key: str) -> str:
    return TEXTS.get(language, TEXTS["ar"]).get(key, TEXTS["ar"].get(key, key))


def main_keyboard(language: str = "ar") -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[
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
            [types.KeyboardButton(text=get_text(language, "language"))],
        ],
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
/page 1 - ضبط صفحة البداية الحالية
/send_now - إرسال ورد اليوم الآن
/azkar - إرسال دعاء/ذكر الآن
/dua - إرسال دعاء/ذكر الآن
/pause - إيقاف الإرسال مؤقتًا
/resume - استئناف الإرسال

أوامر المدير:
/admin_stats - عدد المشتركين النشطين
/broadcast النص - إرسال تعميم للجميع
""".strip()


def is_admin(message: types.Message) -> bool:
    return bool(message.from_user and message.from_user.id == ADMIN_ID)


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
    db.add_user(get_subscription_id(message), get_subscription_name(message))


def get_subscription_language(subscription_id: int) -> str:
    user = db.get_user(subscription_id)
    if user:
        return user["language"]
    return "ar"


def check_and_mark_setup(user_id: int) -> None:
    user = db.get_user(user_id)
    if user and not user.get("is_setup", False):
        if user["daily_goal"] > 1 and user["send_time"] != "08:00":
            db.update_settings(user_id, is_setup=True)
            language = user["language"]
            asyncio.create_task(
                bot.send_message(
                    user_id,
                    "✅ تم اكتمال إعدادك بنجاح!\n\n"
                    "سيتم إرسال وردك اليومي تلقائيًا في الوقت المحدد.\n\n"
                    f"📖 الورد: {user['daily_goal']} صفحة يوميًا\n"
                    f"⏰ وقت الإرسال: {user['send_time']}\n"
                    f"📍 الصفحة الحالية: {user['current_page']}",
                    reply_markup=main_keyboard(language),
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


async def send_daily_quran(user_id: int, goal: int, current_page: int) -> bool:
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
    pdf_file = None
    image_files = []

    try:
        logger.info(
            "Preparing daily Quran for user=%s goal=%s current_page=%s pages=%s-%s count=%s",
            user_id,
            goal,
            current_page,
            pages[0],
            pages[-1],
            len(pages),
        )

        if len(pages) > 10:
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
            user["user_id"], user["daily_goal"], user["current_page"]
        )
        if sent:
            db.update_settings(user["user_id"], last_sent_date=today)
        await asyncio.sleep(0.1)


async def send_dua_to_all() -> None:
    dua = choice(DUAS)
    users = db.get_all_active_users()
    if not users:
        return

    logger.info("Sending dua to %s active users", len(users))
    for user in users:
        try:
            await bot.send_message(user["user_id"], f"🤲 دعاء مأثور\n\n{dua}")
        except TelegramForbiddenError:
            db.update_settings(user["user_id"], is_active=False)
        except Exception:
            logger.exception("Failed to send dua to user %s", user["user_id"])
        await asyncio.sleep(0.1)


@dp.message(Command("start"))
async def start(message: types.Message):
    await ensure_user(message)
    language = get_subscription_language(get_subscription_id(message))
    await message.answer(
        START_MESSAGE,
        reply_markup=main_keyboard(language),
        parse_mode="HTML",
    )
    await message.answer(
        "🔢 لكي نبدأ، يرجى ضبط عدد صفحات الورد اليومي.\n\n"
        "استخدم زر 🔢 ضبط عدد الصفحات أو اكتب /goal متبوعًا بالعدد (مثال: /goal 5)",
        reply_markup=main_keyboard(language),
    )
    await message.answer(
        "⏰ الآن ضبط وقت الإرسال اليومي.\n\n"
        "استخدم زر ⏰ ضبط وقت الإرسال أو اكتب /time متبوعًا بالوقت (مثال: /time 08:00)",
        reply_markup=main_keyboard(language),
    )


@dp.message(Command("help"))
async def help_command(message: types.Message):
    await ensure_user(message)
    language = get_subscription_language(get_subscription_id(message))
    if not is_admin(message):
        await message.answer(
            "استخدم الأزرار في الأسفل للتحكم بإعداداتك.\n\n"
            "لأي استفسار تواصل مع المطور.",
            reply_markup=main_keyboard(language),
        )
        return
    await message.answer(HELP_TEXT, reply_markup=main_keyboard(language))


@dp.message(Command("status"))
async def status(message: types.Message):
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    user = db.get_user(subscription_id)
    if not user:
        await message.answer("استخدم /start أولًا لتفعيل اشتراكك.")
        return

    active_text = "نشط ✅" if user["is_active"] else "متوقف مؤقتًا ⏸"
    setup_text = "مكتمل ✅" if user.get("is_setup", False) else "غير مكتمل ❌"
    khatma_num = user.get("khatma_number", 0)
    await message.answer(
        "📌 إعداداتك الحالية:\n\n"
        f"الحالة: {active_text}\n"
        f"الإعداد: {setup_text}\n"
        f"الختمة الحالية: {khatma_num}\n"
        f"الورد اليومي: {user['daily_goal']} صفحة\n"
        f"الصفحة الحالية: {user['current_page']}\n"
        f"وقت الإرسال: {user['send_time']}",
        reply_markup=main_keyboard(user["language"]),
    )


@dp.message(Command("goal"))
async def set_goal(message: types.Message):
    await ensure_user(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("اكتب عدد الصفحات هكذا: /goal 5")
        return

    goal = parse_positive_int(parts[1].strip(), 1, 604)
    if goal is None:
        await message.answer("عدد الصفحات يجب أن يكون رقمًا بين 1 و 604.")
        return

    subscription_id = get_subscription_id(message)
    db.update_settings(subscription_id, goal=goal)
    await message.answer(f"تم ضبط الورد اليومي على {goal} صفحة ✅")
    check_and_mark_setup(subscription_id)


@dp.message(Command("time"))
async def set_time(message: types.Message):
    await ensure_user(message)
    parts = message.text.split(maxsplit=1)
    send_time = normalize_digits(parts[1].strip()) if len(parts) >= 2 else ""
    if not TIME_PATTERN.match(send_time):
        await message.answer("اكتب الوقت بصيغة 24 ساعة هكذا: /time 08:00")
        return
    subscription_id = get_subscription_id(message)
    db.update_settings(subscription_id, send_time=send_time)
    db.clear_last_sent_date(subscription_id)
    await message.answer(
        f"تم ضبط وقت الإرسال اليومي على {send_time} ✅\n"
        "إذا كان الوقت قد حان أو مرّ اليوم، سيتم الإرسال خلال أقل من دقيقة."
    )
    check_and_mark_setup(subscription_id)


@dp.message(Command("page"))
async def set_page(message: types.Message):
    await ensure_user(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("اكتب رقم الصفحة هكذا: /page 25")
        return

    page = parse_positive_int(parts[1].strip(), 1, 604)
    if page is None:
        await message.answer("رقم الصفحة يجب أن يكون بين 1 و 604.")
        return

    db.update_settings(get_subscription_id(message), page=page)
    await message.answer(f"تم ضبط صفحة البداية الحالية على {page} ✅")


@dp.message(Command("azkar", "dua"))
async def send_azkar(message: types.Message):
    await ensure_user(message)
    await message.answer(f"🤲 ذكر ودعاء\n\n{choice(DUAS)}")


@dp.message(Command("pause"))
async def pause(message: types.Message):
    await ensure_user(message)
    db.update_settings(get_subscription_id(message), is_active=False)
    await message.answer("تم إيقاف الورد اليومي مؤقتًا ⏸\nيمكنك استئنافه عبر /resume")


@dp.message(Command("resume"))
async def resume(message: types.Message):
    await ensure_user(message)
    db.update_settings(get_subscription_id(message), is_active=True)
    await message.answer("تم استئناف الورد اليومي ✅")


@dp.message(Command("send_now"))
async def send_now(message: types.Message):
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    user = db.get_user(subscription_id)
    if not user:
        await message.answer("استخدم /start أولًا لتفعيل اشتراكك.")
        return

    loading_msg = await message.answer("جاري تجهيز وردك الآن... ⏳")
    sent = await send_daily_quran(
        user["user_id"], user["daily_goal"], user["current_page"]
    )
    try:
        await loading_msg.delete()
    except Exception:
        pass
    if not sent:
        await message.answer("تعذر إرسال الورد الآن. حاول لاحقًا.")


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
    await ensure_user(message)
    PENDING_ACTIONS[get_subscription_id(message)] = "time"
    await message.answer(
        "⏰ أرسل وقت الإرسال اليومي بصيغة 24 ساعة.\n\n"
        "مثال: 08:00 أو 21:30\n"
        "إذا كان الوقت قد حان أو مرّ اليوم، سيرسل البوت خلال أقل من دقيقة."
    )


@dp.message(F.text.in_([BTN_SET_GOAL, "🔢 Set daily pages"]))
async def ask_goal_button(message: types.Message):
    await ensure_user(message)
    PENDING_ACTIONS[get_subscription_id(message)] = "goal"
    await message.answer(
        "🔢 أرسل عدد صفحات الورد اليومي.\n\n"
        "مثال: 1 أو 5 أو 10\n"
        "إذا كان أكثر من 10 صفحات سيتم تجهيزه كملف PDF."
    )


@dp.message(F.text.in_([BTN_SET_PAGE, "📍 Set current page"]))
async def ask_page_button(message: types.Message):
    await ensure_user(message)
    PENDING_ACTIONS[get_subscription_id(message)] = "page"
    await message.answer("📍 أرسل رقم الصفحة الحالية بين 1 و 604.\n\nمثال: 25")


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


@dp.callback_query(F.data.startswith("lang:"))
async def change_language(callback: types.CallbackQuery):
    language = callback.data.split(":", 1)[1]
    if language not in TEXTS:
        await callback.answer("Unsupported language", show_alert=True)
        return

    subscription_id = callback.message.chat.id
    db.update_settings(subscription_id, language=language)
    await callback.answer()
    await callback.message.answer(
        get_text(language, "language_updated"), reply_markup=main_keyboard(language)
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


@dp.message(F.text, lambda message: message.chat.id in PENDING_ACTIONS)
async def handle_pending_input(message: types.Message):
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    action = PENDING_ACTIONS.pop(subscription_id)
    text = normalize_digits(message.text.strip())

    if action == "time":
        if not TIME_PATTERN.match(text):
            PENDING_ACTIONS[subscription_id] = "time"
            await message.answer(
                "صيغة الوقت غير صحيحة. أرسل الوقت هكذا: 08:00 أو 21:30"
            )
            return
        db.update_settings(subscription_id, send_time=text)
        db.clear_last_sent_date(subscription_id)
        await message.answer(
            f"تم ضبط وقت الإرسال اليومي على {text} ✅\n"
            "إذا كان الوقت قد حان أو مرّ اليوم، سيتم الإرسال خلال أقل من دقيقة.",
            reply_markup=main_keyboard(),
        )
        check_and_mark_setup(subscription_id)
        return

    if action == "goal":
        goal = parse_positive_int(text, 1, 604)
        if goal is None:
            PENDING_ACTIONS[subscription_id] = "goal"
            await message.answer("عدد الصفحات يجب أن يكون رقمًا بين 1 و 604.")
            return
        db.update_settings(subscription_id, goal=goal)
        await message.answer(
            f"تم ضبط الورد اليومي على {goal} صفحة ✅", reply_markup=main_keyboard()
        )
        check_and_mark_setup(subscription_id)
        return

    if action == "page":
        page = parse_positive_int(text, 1, 604)
        if page is None:
            PENDING_ACTIONS[subscription_id] = "page"
            await message.answer("رقم الصفحة يجب أن يكون بين 1 و 604.")
            return
        db.update_settings(subscription_id, page=page)
        await message.answer(
            f"تم ضبط صفحة البداية الحالية على {page} ✅", reply_markup=main_keyboard()
        )


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

    await message.answer(f"✅ تم إرسال التعميم إلى {sent_count} مستخدم.")


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
]


@dp.message(F.text, F.chat.type == "private")
async def fallback(message: types.Message):
    await ensure_user(message)
    subscription_id = get_subscription_id(message)
    if subscription_id in PENDING_ACTIONS:
        await handle_pending_input(message)
        return
    if message.text.strip() in ALL_BUTTON_TEXTS:
        return
    user = db.get_user(subscription_id)
    if user and user["daily_goal"] == 1 and user["send_time"] == "08:00" and user["current_page"] == 1:
        await message.answer(
            "يرجى ضبط إعداداتك أولاً لاستخدام البوت.\n\n"
            "استخدم زر 🔢 ضبط عدد الصفحات لضبط عدد الصفحات اليومية.\n"
            "استخدم زر ⏰ ضبط وقت الإرسال لضبط وقت الإرسال.",
            reply_markup=main_keyboard(user["language"]),
        )
        return
    await message.answer(
        "لم أفهم الأمر. استخدم الأزرار في الأسفل أو /help لعرض الأوامر المتاحة.",
        reply_markup=main_keyboard(get_subscription_language(subscription_id)),
    )


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

        scheduler.add_job(
            check_due_daily_quran, "interval", seconds=20, max_instances=1
        )
        scheduler.add_job(send_dua_to_all, "interval", hours=8, max_instances=1)
        scheduler.start()

        logger.info("Quran bot started")
        await dp.start_polling(bot)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        if health_runner:
            await health_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
