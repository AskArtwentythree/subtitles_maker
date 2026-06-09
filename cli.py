"""CLI для тестирования провайдеров субтитров на локальном видео.

Примеры:
    python cli.py samples/feature.mp4
    python cli.py samples/feature.mp4 --preset glass --language ru-RU
    python cli.py samples/feature.mov --compare --language ru-RU
    python cli.py samples/feature.mov --provider autosub --language ru \\
        --opt font_size=140 --opt highlight_color=yellow --opt words_per_subtitle=3
    python cli.py --list-presets
"""
import argparse
import os
import sys
import time

from providers import get_provider, PROVIDERS
from providers.base import SubtitleOptions
from providers.veed_fal import DYNAMIC_PRESETS, BASIC_PRESETS, ALL_PRESETS

# Шорт-лист для --compare: пресеты с упором на читаемость на пёстром/светлом фоне
# (запись экрана приложения). От плашки до жирной обводки.
COMPARE_PRESETS = ["glass", "backdrop", "backdrop2", "hustle"]


def _coerce(value: str):
    """Привести строку из --opt key=value к int/float/bool, иначе оставить строкой."""
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _parse_opts(pairs) -> dict:
    extra = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--opt ждёт формат key=value, получено: {pair!r}")
        key, value = pair.split("=", 1)
        extra[key.strip()] = _coerce(value.strip())
    return extra


def _default_output(video_path: str, provider: str, preset: str) -> str:
    base = os.path.splitext(os.path.basename(video_path))[0]
    return os.path.join("output", f"{base}__{provider}__{preset}.mp4")


def list_presets() -> None:
    print("Динамические пресеты (reels-стиль, 2x цена):")
    print("  " + ", ".join(sorted(DYNAMIC_PRESETS)))
    print("\nБазовые пресеты (1x цена):")
    print("  " + ", ".join(sorted(BASIC_PRESETS)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Генерация субтитров для видео.")
    parser.add_argument("video", nargs="?", help="Путь к локальному видеофайлу")
    parser.add_argument(
        "--provider", default="veed", choices=list(PROVIDERS),
        help="Провайдер субтитров (по умолчанию: veed)",
    )
    parser.add_argument(
        "--preset", default="hustle",
        help="Пресет стиля (см. --list-presets)",
    )
    parser.add_argument(
        "--language", default=None,
        help="Язык исходного аудио (BCP-47), напр. ru-RU, en-US. "
             "Не указывать = автоопределение.",
    )
    parser.add_argument(
        "--translation-language", default=None,
        help="Перевести субтитры на этот язык (BCP-47).",
    )
    parser.add_argument(
        "--position", default=None, choices=["top", "center", "bottom"],
        help="Положение субтитров.",
    )
    parser.add_argument(
        "--shadow", default=None, choices=["none", "min", "mid", "max"],
        help="Интенсивность тени.",
    )
    parser.add_argument(
        "--font", default=None,
        help="Шрифт (Google Font), напр. Montserrat. Veed: размер задаётся пресетом.",
    )
    parser.add_argument(
        "--weight", type=int, default=None,
        help="Насыщенность шрифта 100..900 (>=700 = жирный).",
    )
    parser.add_argument(
        "--color", default=None, help="Цвет текста в hex, напр. #FFFFFF.",
    )
    parser.add_argument(
        "--hl-font", default=None, help="Шрифт выделенных слов (highlighted).",
    )
    parser.add_argument(
        "--hl-weight", type=int, default=None,
        help="Насыщенность выделенных слов 100..900.",
    )
    parser.add_argument(
        "--hl-color", default=None, help="Цвет выделенных слов в hex.",
    )
    parser.add_argument(
        "--opt", action="append", default=None, metavar="KEY=VALUE",
        help="Провайдер-специфичный параметр (можно несколько раз). "
             "Напр. для autosub: --opt font_size=140 --opt words_per_subtitle=3.",
    )
    parser.add_argument("--output", default=None, help="Куда сохранить результат")
    parser.add_argument(
        "--compare", action="store_true",
        help="Прогнать видео через несколько пресетов для сравнения читаемости.",
    )
    parser.add_argument(
        "--presets", default=None,
        help="Список пресетов через запятую для --compare, либо 'all' для всех "
             f"(по умолчанию: {','.join(COMPARE_PRESETS)}).",
    )
    parser.add_argument(
        "--exclude", default=None,
        help="Пресеты через запятую, которые исключить из --compare.",
    )
    parser.add_argument(
        "--list-presets", action="store_true", help="Показать пресеты и выйти",
    )

    args = parser.parse_args()

    if args.list_presets:
        list_presets()
        return 0

    if not args.video:
        parser.error("укажи путь к видео или используй --list-presets")

    if not os.path.isfile(args.video):
        print(f"Файл не найден: {args.video}", file=sys.stderr)
        return 1

    provider = get_provider(args.provider)

    try:
        extra = _parse_opts(args.opt)
    except ValueError as e:
        parser.error(str(e))

    def build_opts(preset: str) -> SubtitleOptions:
        return SubtitleOptions(
            preset=preset,
            language=args.language,
            translation_language=args.translation_language,
            position=args.position,
            shadow=args.shadow,
            font=args.font,
            font_weight=args.weight,
            text_color=args.color,
            highlight_font=args.hl_font,
            highlight_weight=args.hl_weight,
            highlight_color=args.hl_color,
            extra=extra,
        )

    if args.compare and provider.name != "veed":
        parser.error("--compare работает только с провайдером veed (пресеты).")

    if args.compare:
        if not args.presets:
            presets = list(COMPARE_PRESETS)
        elif args.presets.strip().lower() == "all":
            presets = sorted(ALL_PRESETS)
        else:
            presets = [p.strip() for p in args.presets.split(",") if p.strip()]

        if args.exclude:
            excluded = {p.strip() for p in args.exclude.split(",") if p.strip()}
            presets = [p for p in presets if p not in excluded]

        if not presets:
            print("Список пресетов пуст после фильтрации.", file=sys.stderr)
            return 1

        print(f"Сравнение {len(presets)} пресетов: {', '.join(presets)}")
        print(f"Язык: {args.language or 'auto'}\n")
        results = []
        for i, preset in enumerate(presets, 1):
            out_path = _default_output(args.video, provider.name, preset)
            print(f"--- [{i}/{len(presets)}] preset={preset} ---")
            started = time.time()
            try:
                res = provider.generate(args.video, build_opts(preset), out_path)
                results.append((preset, res.output_path, time.time() - started, None))
            except Exception as e:  # noqa: BLE001
                print(f"  Ошибка: {e}", file=sys.stderr)
                results.append((preset, None, time.time() - started, str(e)))
            print()

        print("=== Итог сравнения ===")
        for preset, path, elapsed, err in results:
            status = f"OK  {path}" if path else f"FAIL  {err}"
            print(f"  {preset:<12} {elapsed:6.1f}c  {status}")
        return 0 if any(p for _, p, _, _ in results) else 1

    out_path = args.output or _default_output(args.video, provider.name, args.preset)
    opts = build_opts(args.preset)

    print(f"Провайдер: {provider.name} | пресет: {opts.preset} | язык: {opts.language or 'auto'}")
    started = time.time()
    try:
        result = provider.generate(args.video, opts, out_path)
    except Exception as e:  # noqa: BLE001 — в CLI хотим понятное сообщение
        print(f"\nОшибка: {e}", file=sys.stderr)
        return 1

    elapsed = time.time() - started
    print("\n=== Результат ===")
    print(f"Файл:     {result.output_path}")
    print(f"URL:      {result.remote_url}")
    print(f"Время:    {elapsed:.1f} c")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
