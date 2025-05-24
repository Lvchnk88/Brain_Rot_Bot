import os
import re
import yt_dlp
import asyncio
import aiohttp
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.types import ChatType
from aiogram.utils import executor
from concurrent.futures import ThreadPoolExecutor

# Logging
load_dotenv()
logging.basicConfig(level=logging.INFO)

API_TOKEN = os.getenv("API_TOKEN")
os.makedirs("downloads", exist_ok=True)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Persistent thread pool for yt_dlp
yt_dlp_executor = ThreadPoolExecutor(max_workers=4)  # Adjust workers for your hardware

# Pre-compile regex patterns (faster)
PLATFORM_S = {
    "TikTok": re.compile(r'https?://(www\.|vm\.|vt\.)?tiktok\.com/[^\s)]+'),
    "Instagram": re.compile(r'https?://(?:www\.)?instagram\.com/reel/[^\s)]+'),
    "YouTube Shorts": re.compile(r'https?://(?:www\.)?youtube\.com/shorts/[^\s)]+'),
}

# Async Python
def yt_dlp_download_blocking(url, ydl_opts):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        return filename

# Download Video File (with persistent thread pool)
async def download_video_with_ytdlp(url):
    cookie_file = 'instagram_cookies.txt' if 'instagram.com' in url else None
    ydl_opts = {
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'format': 'bv*+ba/best',
        'merge_output_format': 'mp4',
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }, {
            'key': 'FFmpegMetadata'
        }, {
            'key': 'FFmpegEmbedSubtitle'
        }],
        'quiet': True,
        'noplaylist': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        }
    }
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    loop = asyncio.get_running_loop()
    try:
        filename = await loop.run_in_executor(yt_dlp_executor, yt_dlp_download_blocking, url, ydl_opts)
        return filename
    except Exception as e:
        logging.error(f"yt-dlp error for {url}: {e}")
        return None

# Reusable aiohttp session (for speed)
aiohttp_session = None
async def get_aiohttp_session():
    global aiohttp_session
    if aiohttp_session is None or aiohttp_session.closed:
        aiohttp_session = aiohttp.ClientSession(headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/114.0.0.0 Safari/537.36"
        })
    return aiohttp_session

# Resolve redirects for short URLs
async def resolve_redirect(url):
    try:
        session = await get_aiohttp_session()
        async with session.get(url, allow_redirects=True) as resp:
            final_url = str(resp.url)
            logging.info(f"Resolved redirect: {url} -> {final_url}")
            return final_url
    except Exception as e:
        logging.error(f"Error resolving redirect: {e}")
        return url

@dp.message_handler(content_types=types.ContentTypes.TEXT, chat_type=[ChatType.SUPERGROUP, ChatType.GROUP])
async def handle_message(message: types.Message):
    if message.reply_to_message:
        return

    text = message.text
    logging.info(f"Отримано повідомлення: {text}")

    video_url = None

    for platform_name, pattern in PLATFORM_S.items():
        match = pattern.search(text)
        if match:
            raw_url = match.group(0)
            logging.info(f"Matched {platform_name} URL: {raw_url}")

            # Resolve short TikTok links
            if "tiktok.com" in raw_url and ("vm." in raw_url or "vt." in raw_url):
                raw_url = await resolve_redirect(raw_url)
            logging.info(f"Using URL for download: {raw_url}")
            video_url = await download_video_with_ytdlp(raw_url)
            break

    if not video_url:
        return

    MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

    if video_url and os.path.exists(video_url):
        file_size = os.path.getsize(video_url)
        if file_size > MAX_TELEGRAM_FILE_SIZE:
            await message.reply(
                f"⚠️ Файл занадто потужний для завантаження (приблизно {file_size / (1024*1024):.2f} МБ)."
                " Максимальний розмір: 50 МБ.")
            os.remove(video_url)
            return

        try:
            user = message.from_user
            caption = f"Потужно надіслав: 👤{user.full_name}"

            with open(video_url, 'rb') as video_file:
                await bot.send_video(
                    chat_id=message.chat.id,
                    video=video_file,
                    caption=caption,
                    disable_notification=True
                )
            # Only delete after successful send
            os.remove(video_url)

        except Exception as e:
            logging.error(f"Error sending video {message.from_user.id}: {e}")
            await message.reply(f" ⚠️ Потужна помилка при надсиланні відео. ")
    else:
        logging.error("Download failed or file not found.")
        await message.reply("⚠️ Потужне посилання не підтримується, або не вдалося потужно завантажити.")

# Clean up aiohttp session on exit
async def on_shutdown(dp):
    global aiohttp_session
    if aiohttp_session is not None and not aiohttp_session.closed:
        await aiohttp_session.close()

if __name__ == '__main__':
    logging.info("Starting bot polling...")
    executor.start_polling(dp, skip_updates=True, on_shutdown=on_shutdown)
    logging.info("Bot polling stopped.")