from __future__ import annotations

import asyncio
import json
import os
import random
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

# Limit concurrent image downloads to avoid memory spikes on free tier
_download_sem = asyncio.Semaphore(3)

# Shared aiohttp session (initialized lazily)
_shared_session: aiohttp.ClientSession | None = None

DUAS_FILE = Path("duas.json")


def load_duas() -> list[str]:
    if DUAS_FILE.exists():
        try:
            data = json.loads(DUAS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return []


def save_duas(duas: list[str]) -> None:
    DUAS_FILE.write_text(json.dumps(duas, ensure_ascii=False, indent=2), encoding="utf-8")


def get_random_dua() -> str:
    duas = load_duas()
    if not duas:
        return "اللهم اجعل القرآن ربيع قلوبنا ونور صدورنا وجلاء أحزاننا وذهاب همومنا."
    return random.choice(duas)


async def _get_shared_session() -> aiohttp.ClientSession:
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        _shared_session = aiohttp.ClientSession()
    return _shared_session

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
    now: datetime,
    language: str = "ar",
    khatma_number: int = 0,
    completed_khatmas: int = 0,
) -> str:
    juz = get_juz_number(start_page)
    if language == "en":
        return (
            "Peace be upon you 🌿\n\n"
            f"🗓 {format_hijri_date(now)}\n"
            f"📅 {format_gregorian_date(now)}\n\n"
            f"📚 Juz {juz}\n"
            f"📄 Pages: {start_page} to {end_page}\n\n"
            f"📖 Khatmas: {khatma_number}\n"
            f"✅ Completed khatmas: {completed_khatmas}"
        )

    return (
        "السلام عليكم ورحمة الله وبركاته\n\n"
        f"🗓 {format_hijri_date(now)}\n"
        f"📅 الموافق لـ {format_gregorian_date(now)}\n\n"
        f"📚 الجزء {juz}\n"
        f"📄 الصفحات: من {start_page} إلى {end_page}\n\n"
        f"📖 عدد الختمات: {khatma_number}\n"
        f"✅ عدد الختمات المقروءة: {completed_khatmas}"
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

    async with _download_sem:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
            response.raise_for_status()
            path.write_bytes(await response.read())

    return path


async def generate_quran_images(pages: Iterable[int], user_id: int) -> list[Path]:
    pages = list(pages)
    session = await _get_shared_session()
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


async def close_shared_session() -> None:
    global _shared_session
    if _shared_session and not _shared_session.closed:
        await _shared_session.close()
        _shared_session = None


def cleanup_file(path: os.PathLike | str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
