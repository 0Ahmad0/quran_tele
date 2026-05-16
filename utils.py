from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

import aiohttp
import img2pdf
from hijridate import Gregorian

TOTAL_PAGES = 604
IMAGE_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/maknon/Quran/main/pages-hafs/{page}.png"
)
TMP_DIR = Path("tmp")

JUZ_START_PAGES = [
    1,
    22,
    42,
    62,
    82,
    102,
    121,
    142,
    162,
    182,
    201,
    222,
    242,
    262,
    282,
    302,
    322,
    342,
    362,
    382,
    402,
    422,
    442,
    462,
    482,
    502,
    522,
    542,
    562,
    582,
]

HIJRI_MONTHS_AR = [
    "محرم",
    "صفر",
    "ربيع الأول",
    "ربيع الآخر",
    "جمادى الأولى",
    "جمادى الآخرة",
    "رجب",
    "شعبان",
    "رمضان",
    "شوال",
    "ذو القعدة",
    "ذو الحجة",
]

DUAS = [
    "اللهم اجعل القرآن ربيع قلوبنا ونور صدورنا وجلاء أحزاننا وذهاب همومنا.",
    "اللهم علمنا من القرآن ما جهلنا وذكّرنا منه ما نسينا وارزقنا تلاوته آناء الليل وأطراف النهار.",
    "اللهم اجعلنا من أهل القرآن الذين هم أهلك وخاصتك.",
    "اللهم ارفعنا بالقرآن، وانفعنا بالقرآن، واجعله حجة لنا لا علينا.",
    "اللهم ارزقنا تدبر آياته والعمل بمحكمه والإيمان بمتشابهه.",
    "اللهم اجعل القرآن شفيعًا لنا يوم القيامة.",
    "اللهم نوّر بالقرآن أبصارنا، واشرح به صدورنا، ويسّر به أمورنا.",
    "اللهم اجعلنا ممن يتلون كتابك حق تلاوته.",
    "اللهم اجعل القرآن العظيم قائدنا إلى رضوانك وجنات النعيم.",
    "اللهم حبب إلينا تلاوة كتابك، واجعلها أنسًا لقلوبنا.",
    "اللهم اجعل لنا بكل حرف من القرآن نورًا وهدى ورحمة.",
    "اللهم لا تجعلنا ممن هجروا القرآن.",
    "اللهم اجعل القرآن العظيم سببًا لطمأنينة قلوبنا وصلاح أعمالنا.",
    "اللهم ارزقنا الإخلاص في تلاوته وحفظه وتدبره.",
    "اللهم اجعل القرآن صاحبنا في الدنيا وشفيعنا في الآخرة.",
    "اللهم اجعلنا ممن يستمعون القول فيتبعون أحسنه.",
    "اللهم اجعل القرآن العظيم نورًا في قبورنا ونورًا على الصراط.",
    "اللهم ارزقنا حفظ كتابك والعمل به على الوجه الذي يرضيك عنا.",
    "اللهم اجعل بيوتنا عامرة بذكرك وتلاوة كتابك.",
    "اللهم بارك لنا في أوقاتنا واجعل لنا وردًا لا ينقطع من كتابك.",
    "اللهم اجعلنا من الذاكرين الشاكرين التالين لكتابك.",
    "اللهم طهّر قلوبنا بالقرآن من النفاق وأعمالنا من الرياء.",
    "اللهم اجعل آخر كلامنا من الدنيا شهادة أن لا إله إلا الله.",
    "اللهم اختم لنا بخير واجعل القرآن أنيسنا عند الموت وفي القبر ويوم البعث.",
]


def clamp_page(page: int) -> int:
    return max(1, min(TOTAL_PAGES, page))


def clamp_goal(goal: int) -> int:
    return max(1, min(604, goal))


def get_juz_number(page: int) -> int:
    page = clamp_page(page)
    juz = 1
    for index, start_page in enumerate(JUZ_START_PAGES, start=1):
        if page >= start_page:
            juz = index
        else:
            break
    return juz


def format_gregorian_date(now: datetime) -> str:
    return f"{now.day}/{now.month}/{now.year}"


def format_hijri_date(now: datetime) -> str:
    hijri = Gregorian(now.year, now.month, now.day).to_hijri()
    month_name = HIJRI_MONTHS_AR[hijri.month - 1]
    return f"{hijri.day} {month_name} {hijri.year}"


def build_wird_caption(
    start_page: int,
    end_page: int,
    total_completed_khatmas: int,
    active_readers: int,
    now: datetime,
    language: str = "ar",
) -> str:
    juz = get_juz_number(start_page)
    if language == "en":
        return (
            "Peace be upon you 🌿\n\n"
            f"📿 Completed khatmas: {total_completed_khatmas}\n"
            f"📖 Quran wird for: {format_gregorian_date(now)}\n"
            f"🗓 Hijri date: {format_hijri_date(now)}\n"
            f"👥 Khatma readers: {active_readers}\n\n"
            f"📚 Juz {juz}\n"
            f"📄 Pages: {start_page} to {end_page}"
        )

    return (
        "السلام عليكم ورحمة الله وبركاته\n\n"
        f"📿 الختمات المقروءة: {total_completed_khatmas}\n"
        f"📖 ورد القرآن ليوم: {format_gregorian_date(now)}\n"
        f"🗓 {format_hijri_date(now)}\n"
        f"👥 عدد قرّاء الختمة: {active_readers}\n\n"
        f"📚 الجزء {juz}\n"
        f"📄 الصفحات: من {start_page} إلى {end_page}"
    )


def get_pages_logic(current_page: int, daily_goal: int) -> tuple[list[int], bool]:
    current_page = clamp_page(current_page)
    daily_goal = clamp_goal(daily_goal)
    remaining = TOTAL_PAGES - current_page + 1

    if remaining <= daily_goal * 1.5:
        return list(range(current_page, TOTAL_PAGES + 1)), True

    return list(
        range(current_page, min(current_page + daily_goal, TOTAL_PAGES + 1))
    ), False


async def download_page(
    session: aiohttp.ClientSession, page: int, user_id: int
) -> Path:
    TMP_DIR.mkdir(exist_ok=True)
    path = TMP_DIR / f"quran_{user_id}_{page}.png"
    url = IMAGE_URL_TEMPLATE.format(page=page)

    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
        response.raise_for_status()
        path.write_bytes(await response.read())

    return path


async def generate_quran_images(pages: Iterable[int], user_id: int) -> list[Path]:
    pages = list(pages)
    async with aiohttp.ClientSession() as session:
        return [await download_page(session, page, user_id) for page in pages]


async def generate_quran_pdf(pages: Iterable[int], user_id: int) -> Path:
    pages = list(pages)
    TMP_DIR.mkdir(exist_ok=True)
    pdf_path = TMP_DIR / f"quran_{user_id}.pdf"
    image_paths: list[Path] = []

    try:
        image_paths = await generate_quran_images(pages, user_id)
        pdf_bytes = await asyncio.to_thread(
            img2pdf.convert, [str(path) for path in image_paths]
        )
        pdf_path.write_bytes(pdf_bytes)
        return pdf_path
    finally:
        for path in image_paths:
            cleanup_file(path)


def cleanup_file(path: os.PathLike | str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
