"""Провайдер субтитров на базе VEED через fal.ai (модель veed/subtitles).

Делает всё в один вызов: транскрипция -> стилизация -> вшивание субтитров -> рендер.
Возвращает готовый MP4.
"""
import os
import fal_client

from config import require_fal_key
from .base import SubtitleProvider, SubtitleOptions, SubtitleResult, download_file

MODEL_ID = "veed/subtitles"

# Динамические пресеты (множитель 2x по цене): богатый reels/shorts-стиль
# с покадровой подсветкой слов — то, что выглядит «как в шортс».
DYNAMIC_PRESETS = {
    "glass", "whisper", "glide2", "fusion", "glide",
    "terminal", "handwritten", "backdrop", "backdrop2",
}

# Базовые пресеты (множитель 1x): фиксированный, предсказуемый стиль.
BASIC_PRESETS = {
    "simple", "plain", "beans", "corpo", "boo", "shadeplay", "casper", "capri",
    "lowkey", "vinta", "diego", "ali", "slay", "kitty", "hustle", "karl",
    "sprout", "flex", "mint", "rizz", "vegas",
}

ALL_PRESETS = DYNAMIC_PRESETS | BASIC_PRESETS

# Базовая ставка fal за veed/subtitles.
BASE_RATE_USD_PER_MIN = 0.10


class VeedFalProvider(SubtitleProvider):
    name = "veed"

    def generate(
        self,
        video_path: str,
        opts: SubtitleOptions,
        out_path: str,
    ) -> SubtitleResult:
        require_fal_key()

        if opts.preset not in ALL_PRESETS:
            raise ValueError(
                f"Неизвестный пресет '{opts.preset}'. "
                f"Доступные: {', '.join(sorted(ALL_PRESETS))}"
            )

        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Видео не найдено: {video_path}")

        print(f"[veed] Загружаю видео на fal storage: {video_path}")
        video_url = fal_client.upload_file(video_path)
        print(f"[veed] URL: {video_url}")

        arguments = {"video_url": video_url, "preset": opts.preset}
        if opts.language:
            arguments["language"] = opts.language
        if opts.translation_language:
            arguments["translation_language"] = opts.translation_language
        if opts.srt_content:
            arguments["srt_content"] = opts.srt_content
        if opts.vocabulary:
            arguments["vocabulary"] = opts.vocabulary

        customization = {}
        if opts.position:
            customization["position"] = opts.position
        if opts.shadow:
            customization["shadow"] = opts.shadow

        # Veed не даёт числовой размер шрифта — только font/weight/color
        # для двух «полок»: baseline (все слова) и highlighted (выделенные).
        baseline = {}
        if opts.font:
            baseline["font"] = opts.font
        if opts.font_weight:
            baseline["weight"] = opts.font_weight
        if opts.text_color:
            baseline["color"] = opts.text_color

        highlighted = {}
        if opts.highlight_font:
            highlighted["font"] = opts.highlight_font
        if opts.highlight_weight:
            highlighted["weight"] = opts.highlight_weight
        if opts.highlight_color:
            highlighted["color"] = opts.highlight_color

        text_customizations = {}
        if baseline:
            text_customizations["baseline"] = baseline
        if highlighted:
            text_customizations["highlighted"] = highlighted
        if text_customizations:
            customization["text_customizations"] = text_customizations

        if customization:
            arguments["customization"] = customization

        print(f"[veed] Запускаю veed/subtitles (preset={opts.preset})...")

        def on_update(update):
            logs = getattr(update, "logs", None)
            if logs:
                for log in logs:
                    msg = log.get("message") if isinstance(log, dict) else None
                    if msg:
                        print(f"[veed][log] {msg}")

        result = fal_client.subscribe(
            MODEL_ID,
            arguments=arguments,
            with_logs=True,
            on_queue_update=on_update,
        )

        video = (result or {}).get("video") or {}
        remote_url = video.get("url")
        if not remote_url:
            raise RuntimeError(f"Неожиданный ответ от veed/subtitles: {result!r}")

        download_file(remote_url, out_path)
        print(f"[veed] Готово -> {out_path}")

        return SubtitleResult(
            output_path=out_path,
            provider=self.name,
            remote_url=remote_url,
            raw=result,
        )
