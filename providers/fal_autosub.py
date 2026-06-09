"""Провайдер субтитров на базе fal-ai/workflow-utilities/auto-subtitle.

Karaoke-style субтитры с word-level подсветкой. В отличие от Veed, поддерживает
прямой числовой font_size, обводку (stroke), фон и words_per_subtitle.
"""
import os
import fal_client

from config import require_fal_key
from .base import SubtitleProvider, SubtitleOptions, SubtitleResult, download_file

MODEL_ID = "fal-ai/workflow-utilities/auto-subtitle"

# Цена этой утилиты на fal.
RATE_USD_PER_MIN = 0.03

# Параметры, которые можно прокинуть через opts.extra (имена = поля API).
PASSTHROUGH = {
    "font_size",          # int, по умолчанию 100 (крупный TikTok-стиль)
    "font_weight",        # normal | bold | black
    "font_color",         # enum цветов (не hex!)
    "highlight_color",    # enum: цвет активного слова (караоке)
    "stroke_width",       # int, пикс. обводка
    "stroke_color",       # enum
    "background_color",   # enum | none | transparent
    "background_opacity", # float 0..1
    "y_offset",           # int, сдвиг по вертикали
    "words_per_subtitle", # int: 1 = по слову, 8-12 = предложения
    "enable_animation",   # bool: bounce-анимация появления
}


def _short_lang(language):
    """'ru-RU' -> 'ru'. Эта модель ждёт 2-/3-буквенный код, по умолчанию 'en'."""
    if not language:
        return None
    return language.split("-")[0].lower()


class FalAutoSubProvider(SubtitleProvider):
    name = "autosub"

    def generate(
        self,
        video_path: str,
        opts: SubtitleOptions,
        out_path: str,
    ) -> SubtitleResult:
        require_fal_key()

        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Видео не найдено: {video_path}")

        print(f"[autosub] Загружаю видео на fal storage: {video_path}")
        video_url = fal_client.upload_file(video_path)
        print(f"[autosub] URL: {video_url}")

        arguments = {"video_url": video_url}

        lang = _short_lang(opts.language)
        if lang:
            arguments["language"] = lang
        if opts.font:
            arguments["font_name"] = opts.font
        if opts.position:
            arguments["position"] = opts.position

        # Провайдер-специфичные параметры (font_size, stroke, фон и т.д.).
        for key, value in (opts.extra or {}).items():
            if key in PASSTHROUGH:
                arguments[key] = value

        print(f"[autosub] Запускаю auto-subtitle...")

        def on_update(update):
            logs = getattr(update, "logs", None)
            if logs:
                for log in logs:
                    msg = log.get("message") if isinstance(log, dict) else None
                    if msg:
                        print(f"[autosub][log] {msg}")

        result = fal_client.subscribe(
            MODEL_ID,
            arguments=arguments,
            with_logs=True,
            on_queue_update=on_update,
        )

        video = (result or {}).get("video") or {}
        remote_url = video.get("url")
        if not remote_url:
            raise RuntimeError(f"Неожиданный ответ от auto-subtitle: {result!r}")

        download_file(remote_url, out_path)
        print(f"[autosub] Готово -> {out_path}")

        return SubtitleResult(
            output_path=out_path,
            provider=self.name,
            remote_url=remote_url,
            raw=result,
        )
