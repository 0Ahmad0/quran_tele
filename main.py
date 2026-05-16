from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from random import choice

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramUnauthorizedError,
)
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from database import DBManager
from utils import (
    DUAS,
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

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


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
/pause - إيقاف الإرسال مؤقتًا
/resume - استئناف الإرسال

أوامر المدير:
/admin_stats - عدد المشتركين النشطين
/broadcast النص - إرسال تعميم للجميع
""".strip()


def is_admin(message: types.Message) -> bool:
    return bool(message.from_user and message.from_user.id == ADMIN_ID)


def parse_positive_int(value: str, minimum: int, maximum: int) -> int | None:
    try:
        number = int(value)
    except ValueError:
        return None

    if minimum <= number <= maximum:
        return number
    return None


async def ensure_user(message: types.Message) -> None:
    user = message.from_user
    if user:
        db.add_user(user.id, user.username)


async def send_daily_quran(user_id: int, goal: int, current_page: int) -> bool:
    pages, is_finish = get_pages_logic(current_page, goal)
    caption = f"📖 وردكم اليومي: الصفحات من {pages[0]} إلى {pages[-1]}"
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
                    types.InputMediaPhoto(media=types.FSInputFile(image_file))
                    for image_file in image_files
                ]
                media[0].caption = caption
                await bot.send_media_group(user_id, media)

        if is_finish:
            await bot.send_message(
                user_id,
                "🎉 هنيئًا لكم ختم القرآن الكريم!\n\n"
                "اللهم اجعل القرآن العظيم ربيع قلوبنا ونور صدورنا وجلاء أحزاننا وذهاب همومنا.\n\n"
                "سنبدأ ختمة جديدة في الورد القادم بإذن الله.",
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
    send_time = now.strftime("%H:%M")
    today = now.date().isoformat()
    users = db.get_users_due(send_time, today)

    if not users:
        return

    logger.info("Sending daily Quran to %s users for time %s", len(users), send_time)
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
    await message.answer(
        "تم تفعيل اشتراكك في ورد القرآن اليومي ✅\n\n"
        "الإعدادات الافتراضية:\n"
        "• الورد: صفحة واحدة يوميًا\n"
        "• وقت الإرسال: 08:00\n"
        "• صفحة البداية: 1\n\n"
        "استخدم /help لعرض كل الأوامر."
    )


@dp.message(Command("help"))
async def help_command(message: types.Message):
    await ensure_user(message)
    await message.answer(HELP_TEXT)


@dp.message(Command("status"))
async def status(message: types.Message):
    await ensure_user(message)
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("استخدم /start أولًا لتفعيل اشتراكك.")
        return

    active_text = "نشط ✅" if user["is_active"] else "متوقف مؤقتًا ⏸"
    await message.answer(
        "📌 إعداداتك الحالية:\n\n"
        f"الحالة: {active_text}\n"
        f"الورد اليومي: {user['daily_goal']} صفحة\n"
        f"الصفحة الحالية: {user['current_page']}\n"
        f"وقت الإرسال: {user['send_time']}"
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

    db.update_settings(message.from_user.id, goal=goal)
    await message.answer(f"تم ضبط الورد اليومي على {goal} صفحة ✅")


@dp.message(Command("time"))
async def set_time(message: types.Message):
    await ensure_user(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not TIME_PATTERN.match(parts[1].strip()):
        await message.answer("اكتب الوقت بصيغة 24 ساعة هكذا: /time 08:00")
        return

    send_time = parts[1].strip()
    db.update_settings(message.from_user.id, send_time=send_time)
    await message.answer(f"تم ضبط وقت الإرسال اليومي على {send_time} ✅")


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

    db.update_settings(message.from_user.id, page=page)
    await message.answer(f"تم ضبط صفحة البداية الحالية على {page} ✅")


@dp.message(Command("pause"))
async def pause(message: types.Message):
    await ensure_user(message)
    db.update_settings(message.from_user.id, is_active=False)
    await message.answer("تم إيقاف الورد اليومي مؤقتًا ⏸\nيمكنك استئنافه عبر /resume")


@dp.message(Command("resume"))
async def resume(message: types.Message):
    await ensure_user(message)
    db.update_settings(message.from_user.id, is_active=True)
    await message.answer("تم استئناف الورد اليومي ✅")


@dp.message(Command("send_now"))
async def send_now(message: types.Message):
    await ensure_user(message)
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("استخدم /start أولًا لتفعيل اشتراكك.")
        return

    await message.answer("جاري تجهيز وردك الآن... ⏳")
    sent = await send_daily_quran(
        user["user_id"], user["daily_goal"], user["current_page"]
    )
    if not sent:
        await message.answer("تعذر إرسال الورد الآن. حاول لاحقًا.")


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


@dp.message()
async def fallback(message: types.Message):
    await ensure_user(message)
    await message.answer("لم أفهم الأمر. استخدم /help لعرض الأوامر المتاحة.")


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

        scheduler.add_job(check_due_daily_quran, "interval", minutes=1, max_instances=1)
        scheduler.add_job(send_dua_to_all, "interval", hours=8, max_instances=1)
        scheduler.start()

        logger.info("Quran bot started")
        await dp.start_polling(bot)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
