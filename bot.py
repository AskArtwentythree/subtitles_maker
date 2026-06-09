"""Telegram-бот: принимает озвученную запись экрана и возвращает видео с субтитрами.

На одно входящее видео бот генерирует 3 варианта оформления субтитров:
  1) autosub_hustle — fal-ai/auto-subtitle, крупный шрифт по 2 слова в строке;
  2) shadeplay      — Veed, пресет shadeplay;
  3) hustle         — Veed, пресет hustle.

Запуск:
  python bot.py

Нужны переменные окружения (см. .env.example): TELEGRAM_BOT_TOKEN, FAL_KEY.
"""
import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    DEFAULT_SUBTITLE_LANGUAGE,
    require_fal_key,
    require_telegram_token,
)
from providers import SubtitleOptions, get_provider

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("nutr_bot")

# Лимит Telegram Bot API на скачивание файла ботом (getFile) — 20 МБ.
TELEGRAM_DOWNLOAD_LIMIT = 20 * 1024 * 1024

# Поддерживаемые расширения входного видео.
ALLOWED_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


@dataclass
class Variant:
    """Один вариант оформления субтитров."""

    key: str            # короткий ключ для имён файлов
    label: str          # подпись для пользователя
    provider: str       # имя провайдера: "veed" | "autosub"
    preset: str = "hustle"
    extra: Optional[dict] = None

    def build_opts(self, language: Optional[str]) -> SubtitleOptions:
        return SubtitleOptions(
            preset=self.preset,
            language=language,
            extra=dict(self.extra or {}),
        )


# Три запрошенных варианта.
VARIANTS = [
    Variant(
        key="autosub_hustle",
        label="1/3 · autosub (крупный, по 2 слова)",
        provider="autosub",
        extra={
            "font_size": 50,
            "words_per_subtitle": 2,
            "stroke_width": 4,  # обводка для читаемости поверх любого фона
        },
    ),
    Variant(
        key="shadeplay",
        label="2/3 · Veed · shadeplay",
        provider="veed",
        preset="shadeplay",
    ),
    Variant(
        key="hustle",
        label="3/3 · Veed · hustle",
        provider="veed",
        preset="hustle",
    ),
]


def _run_variant(video_path: str, variant: Variant, out_path: str, language: Optional[str]):
    """Синхронный вызов провайдера (выполняется в отдельном потоке)."""
    provider = get_provider(variant.provider)
    opts = variant.build_opts(language)
    return provider.generate(video_path, opts, out_path)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я делаю субтитры в стиле Reels/Shorts.\n\n"
        "Пришли мне запись экрана с озвучкой (видео или файл), и я верну 3 варианта:\n"
        "1) autosub — крупный текст, по 2 слова в строке;\n"
        "2) Veed · shadeplay;\n"
        "3) Veed · hustle.\n\n"
        f"Язык распознавания по умолчанию: {DEFAULT_SUBTITLE_LANGUAGE or 'авто'}.\n"
        "⚠️ Из-за ограничений Telegram бот может скачать файл размером до 20 МБ."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Просто отправь видео (mp4/mov) с голосом — пришлю 3 версии с субтитрами.\n"
        "Обработка занимает ~1–2 минуты на все варианты."
    )


def _extract_file(update: Update):
    """Достать (file_id, имя, размер) из видео/документа/кружка."""
    msg = update.message
    if msg.video:
        v = msg.video
        return v.file_id, v.file_name or "video.mp4", v.file_size
    if msg.video_note:
        v = msg.video_note
        return v.file_id, "video_note.mp4", v.file_size
    if msg.document:
        d = msg.document
        return d.file_id, d.file_name or "video.mp4", d.file_size
    return None, None, None


def _suffix(file_name: str) -> str:
    ext = os.path.splitext(file_name)[1].lower()
    return ext if ext in ALLOWED_EXTS else ".mp4"


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    file_id, file_name, file_size = _extract_file(update)
    if not file_id:
        await update.message.reply_text("Не вижу видео в сообщении. Пришли запись экрана файлом или как видео.")
        return

    if file_size and file_size > TELEGRAM_DOWNLOAD_LIMIT:
        mb = file_size / (1024 * 1024)
        await update.message.reply_text(
            f"Файл {mb:.1f} МБ — это больше лимита Telegram Bot API (20 МБ), "
            "я не смогу его скачать.\n"
            "Сократи/сожми ролик до 20 МБ и пришли снова."
        )
        return

    status = await update.message.reply_text("Получил видео. Скачиваю…")

    workdir = tempfile.mkdtemp(prefix="nutr_bot_")
    in_path = os.path.join(workdir, f"input{_suffix(file_name)}")

    try:
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(custom_path=in_path)
    except Exception as e:  # размер >20МБ или иные ошибки getFile
        logger.exception("Не удалось скачать файл")
        await status.edit_text(
            "Не получилось скачать видео (возможно, оно больше 20 МБ — это лимит "
            f"Telegram Bot API).\nОшибка: {e}"
        )
        _cleanup(workdir)
        return

    language = DEFAULT_SUBTITLE_LANGUAGE or None

    await status.edit_text(
        f"Готово, файл получен. Делаю {len(VARIANTS)} варианта субтитров — это займёт ~1–2 минуты."
    )

    ok_count = 0
    for variant in VARIANTS:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
        out_path = os.path.join(workdir, f"{variant.key}.mp4")
        try:
            await asyncio.to_thread(_run_variant, in_path, variant, out_path, language)
        except Exception as e:
            logger.exception("Вариант %s упал", variant.key)
            await update.message.reply_text(f"❌ {variant.label}: ошибка — {e}")
            continue

        if not os.path.isfile(out_path):
            await update.message.reply_text(f"❌ {variant.label}: результат не получен.")
            continue

        try:
            with open(out_path, "rb") as f:
                await update.message.reply_video(
                    video=f,
                    caption=variant.label,
                    supports_streaming=True,
                )
            ok_count += 1
        except Exception as e:
            logger.exception("Не удалось отправить вариант %s", variant.key)
            await update.message.reply_text(
                f"⚠️ {variant.label}: видео готово, но не удалось отправить ({e}). "
                "Возможно, оно больше 50 МБ."
            )

    if ok_count:
        await status.edit_text(f"Готово ✅ Отправил {ok_count} из {len(VARIANTS)} вариантов.")
    else:
        await status.edit_text("Не удалось сделать ни одного варианта 😕 Загляни в логи.")

    _cleanup(workdir)


def _cleanup(workdir: str) -> None:
    try:
        for name in os.listdir(workdir):
            try:
                os.remove(os.path.join(workdir, name))
            except OSError:
                pass
        os.rmdir(workdir)
    except OSError:
        pass


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Необработанная ошибка", exc_info=context.error)


def build_app() -> Application:
    token = require_telegram_token()
    require_fal_key()  # упадём сразу, если ключа нет

    app = (
        ApplicationBuilder()
        .token(token)
        .read_timeout(120)
        .write_timeout(300)  # отправка видео может быть долгой
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(
        MessageHandler(
            filters.VIDEO | filters.VIDEO_NOTE | filters.Document.VIDEO,
            handle_video,
        )
    )
    app.add_error_handler(on_error)
    return app


def main() -> None:
    app = build_app()
    logger.info("Бот запущен. Жду видео…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
