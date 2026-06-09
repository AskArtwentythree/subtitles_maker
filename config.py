"""Загрузка конфигурации из окружения / .env."""
import os
from dotenv import load_dotenv

load_dotenv()

FAL_KEY = os.getenv("FAL_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Язык исходного аудио по умолчанию (BCP-47), напр. ru-RU / en-US.
# Veed и так умеет автоопределение, но autosub без языка считает аудио английским,
# поэтому для русского контента дефолт важен. Пусто = автоопределение у Veed.
DEFAULT_SUBTITLE_LANGUAGE = os.getenv("DEFAULT_SUBTITLE_LANGUAGE", "ru-RU").strip()


def require_telegram_token() -> str:
    """Вернуть TELEGRAM_BOT_TOKEN или упасть с понятной ошибкой."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан. Получи токен у @BotFather и впиши в .env "
            "(см. .env.example)."
        )
    return TELEGRAM_BOT_TOKEN


def require_fal_key() -> str:
    """Вернуть FAL_KEY или упасть с понятной ошибкой.

    fal-client сам читает переменную окружения FAL_KEY, поэтому здесь мы только
    проверяем её наличие, чтобы дать осмысленную подсказку вместо невнятного 401.
    """
    if not FAL_KEY:
        raise RuntimeError(
            "FAL_KEY не задан. Создай файл .env (см. .env.example) и впиши ключ "
            "с https://fal.ai/dashboard/keys"
        )
    # Гарантируем, что fal-client увидит ключ, даже если он пришёл из .env.
    os.environ["FAL_KEY"] = FAL_KEY
    return FAL_KEY
