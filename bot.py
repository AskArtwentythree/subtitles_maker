"""Telegram-бот: принимает озвученное видео и возвращает пакет для Shorts/Reels.

Сценарий:
  1) пользователь присылает видео с озвучкой;
  2) выбирает язык кнопками (EN / ES / PT / KK / UZ);
  3) бот делает АВТОМОНТАЖ в двух стилях (Clean Mint / Bold Pop) на выбранном языке:
     отбирает кадры, режет лишнее, добавляет переходы, зум-акценты, подписи-плашки,
     стрелки и СУБТИТРЫ на выбранном языке;
  4) присылает оба готовых ролика и описание для шортса с хэштегами на этом языке.

Запуск:  python bot.py
Нужны переменные окружения (см. .env.example): TELEGRAM_BOT_TOKEN, FAL_KEY.
Рендер использует проект Remotion в ./my-video (нужны Node 18+ и установленные зависимости).
"""
import asyncio
import logging
import os
import tempfile
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import Conflict
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import require_fal_key, require_telegram_token
from editor.auto_montage import (
    LANGUAGES,
    STYLES,
    build_montage_edl,
    lang_label,
    make_localized_copy,
    render_variant,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("nutr_bot")

# Лимит Telegram Bot API на скачивание файла ботом (getFile) — 20 МБ.
TELEGRAM_DOWNLOAD_LIMIT = 20 * 1024 * 1024
ALLOWED_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def _lang_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-кнопки выбора языка (по 2 в ряд)."""
    buttons = [
        InlineKeyboardButton(label, callback_data=f"lang:{code}")
        for code, (_name, label) in LANGUAGES.items()
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я делаю авто-монтаж для Shorts/Reels из твоего озвученного видео.\n\n"
        "Как это работает:\n"
        "1) пришли видео с голосом;\n"
        "2) выбери язык кнопками;\n"
        "3) я соберу монтаж в 2 стилях (отбор кадров, переходы, акценты, субтитры) "
        "на выбранном языке;\n"
        "4) пришлю оба ролика + описание с хэштегами.\n\n"
        "⚠️ Из-за ограничений Telegram бот может скачать файл размером до 20 МБ."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Пришли видео (mp4/mov) с озвучкой и выбери язык — верну 2 варианта авто-монтажа "
        "с субтитрами и описание для шортса. Обработка занимает несколько минут."
    )


def _extract_file(update: Update):
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


async def _send_video(update: Update, out_path: str, caption: str) -> bool:
    """Залить локальный mp4 с большими таймаутами (рендер — локальный файл)."""
    chat = update.effective_chat
    try:
        with open(out_path, "rb") as f:
            await chat.send_video(
                video=f,
                caption=caption,
                supports_streaming=True,
                read_timeout=180,
                connect_timeout=60,
                write_timeout=600,
                pool_timeout=60,
            )
        return True
    except Exception as e:
        logger.exception("Не удалось отправить видео (%s)", e)
        try:
            await chat.send_message(f"⚠️ {caption}: видео готово, но отправить не вышло ({e}).")
        except Exception:
            pass
        return False


def _cleanup(workdir: Optional[str]) -> None:
    if not workdir or not os.path.isdir(workdir):
        return
    import shutil

    shutil.rmtree(workdir, ignore_errors=True)


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    file_id, file_name, file_size = _extract_file(update)
    if not file_id:
        await update.message.reply_text("Не вижу видео. Пришли запись файлом или как видео.")
        return

    if file_size and file_size > TELEGRAM_DOWNLOAD_LIMIT:
        mb = file_size / (1024 * 1024)
        await update.message.reply_text(
            f"Файл {mb:.1f} МБ — больше лимита Telegram Bot API (20 МБ), я не смогу его скачать.\n"
            "Сократи/сожми ролик до 20 МБ и пришли снова."
        )
        return

    # Если уже было незавершённое видео — подчистим его временную папку.
    prev = context.user_data.pop("pending", None)
    if prev:
        _cleanup(prev.get("workdir"))

    status = await update.message.reply_text("Получил видео. Скачиваю…")
    workdir = tempfile.mkdtemp(prefix="nutr_bot_")
    in_path = os.path.join(workdir, f"input{_suffix(file_name)}")

    try:
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(custom_path=in_path)
    except Exception as e:
        logger.exception("Не удалось скачать файл")
        await status.edit_text(
            "Не получилось скачать видео (возможно, оно больше 20 МБ — лимит Telegram Bot API).\n"
            f"Ошибка: {e}"
        )
        _cleanup(workdir)
        return

    context.user_data["pending"] = {"workdir": workdir, "in_path": in_path}
    await status.edit_text("Видео получено. На каком языке сделать субтитры и описание?")
    await update.message.reply_text("Выбери язык:", reply_markup=_lang_keyboard())


async def on_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    code = (query.data or "").split(":", 1)[-1]
    if code not in LANGUAGES:
        await query.edit_message_text("Неизвестный язык. Пришли видео заново.")
        return

    pending = context.user_data.get("pending")
    if not pending or not os.path.isfile(pending.get("in_path", "")):
        await query.edit_message_text("Видео не найдено (возможно, истекло). Пришли его заново.")
        return

    workdir = pending["workdir"]
    in_path = pending["in_path"]
    label = lang_label(code)
    chat = update.effective_chat

    await query.edit_message_text(f"Язык: {label}. Делаю авто-монтаж — это займёт несколько минут.")

    try:
        # 1) EDL: анализ материала + монтаж + субтитры на выбранном языке.
        await chat.send_chat_action(ChatAction.TYPING)
        await chat.send_message("🧠 Анализирую материал и собираю монтаж…")
        edl_path, warnings = await asyncio.to_thread(build_montage_edl, in_path, workdir, code)
        for w in warnings:
            await chat.send_message(f"⚠️ {w}")

        # 2) Рендер двух стилей.
        ok = 0
        for i, (style, style_name) in enumerate(STYLES.items(), start=1):
            await chat.send_chat_action(ChatAction.UPLOAD_VIDEO)
            await chat.send_message(f"🎬 Рендерю вариант {i}/{len(STYLES)}: {style_name}…")
            out_path = os.path.join(workdir, f"variant_{style}.mp4")
            try:
                await asyncio.to_thread(render_variant, edl_path, out_path, style)
            except Exception as e:
                logger.exception("Рендер %s упал", style)
                await chat.send_message(f"❌ Вариант «{style_name}» не отрендерился: {e}")
                continue
            if os.path.isfile(out_path):
                if await _send_video(update, out_path, f"🎬 {style_name} · {label}"):
                    ok += 1
            else:
                await chat.send_message(f"❌ Вариант «{style_name}»: файл не получен.")

        # 3) Описание + хэштеги на выбранном языке.
        await chat.send_chat_action(ChatAction.TYPING)
        await chat.send_message("📝 Пишу описание и хэштеги…")
        try:
            caption = await asyncio.to_thread(make_localized_copy, edl_path, code)
            if caption:
                await chat.send_message(caption, disable_web_page_preview=True)
        except Exception as e:
            logger.exception("Копирайтинг упал")
            await chat.send_message(f"⚠️ Описание сделать не вышло: {e}")

        if ok:
            await chat.send_message(f"Готово ✅ Отправил {ok} из {len(STYLES)} вариантов.")
        else:
            await chat.send_message("Не удалось отрендерить ни одного варианта 😕 Загляни в логи.")
    except Exception as e:
        logger.exception("Пайплайн авто-монтажа упал")
        await chat.send_message(f"⚠️ Что-то пошло не так: {e}")
    finally:
        context.user_data.pop("pending", None)
        _cleanup(workdir)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, Conflict):
        logger.warning(
            "Conflict getUpdates — параллельный опрос (обычно overlap при редеплое). "
            "Если повторяется постоянно — проверь, что не запущен второй экземпляр бота."
        )
        return
    logger.error("Необработанная ошибка", exc_info=context.error)


def build_app() -> Application:
    token = require_telegram_token()
    require_fal_key()

    app = (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(True)
        .read_timeout(180)
        .write_timeout(600)
        .connect_timeout(60)
        .pool_timeout(60)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(on_language, pattern=r"^lang:"))
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
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
