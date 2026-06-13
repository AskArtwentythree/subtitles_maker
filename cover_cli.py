"""CLI для локального теста пайплайна обложки и описания.

Прогоняет на локальном видео то же, что делает бот (кроме субтитров):
транскрипт -> подбор кадра -> тексты -> сборка обложки.

Примеры:
  # полный прогон: обложка + описание
  python cover_cli.py samples/features.mov

  # только нарезать кадры-кандидаты и шорт-лист (без fal, бесплатно)
  python cover_cli.py samples/features.mov --frames-only

  # задать язык речи и папку вывода
  python cover_cli.py samples/features.mov --language ru-RU --out-dir output
"""
import argparse
import json
import os
import shutil
import sys

# Чтобы испанский/русский в консоли Windows не превращался в кракозябры.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from config import DEFAULT_SUBTITLE_LANGUAGE, require_fal_key
from pipeline.frames import extract_frames, shortlist
from pipeline.cover import select_best_frame, compose_cover
from pipeline.transcribe import transcribe
from pipeline.copywriter import generate_copy, format_caption


def _base_name(video_path: str) -> str:
    return os.path.splitext(os.path.basename(video_path))[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Тест обложки/описания на локальном видео.")
    parser.add_argument("video", help="Путь к видеофайлу (mp4/mov/...).")
    parser.add_argument("--out-dir", default="output", help="Куда складывать результат (default: output).")
    parser.add_argument(
        "--language", default=DEFAULT_SUBTITLE_LANGUAGE or None,
        help="Язык речи (BCP-47, напр. ru-RU). По умолчанию — из .env.",
    )
    parser.add_argument("--count", type=int, default=16, help="Сколько кадров нарезать (default: 16).")
    parser.add_argument(
        "--frames-only", action="store_true",
        help="Только нарезать кадры и показать шорт-лист (без вызовов fal, бесплатно).",
    )
    parser.add_argument(
        "--hook", default=None,
        help="Задать текст-хук вручную (пропустить транскрипт+копирайтер).",
    )
    parser.add_argument("--keep-frames", action="store_true", help="Не удалять папку с кадрами.")
    args = parser.parse_args()

    if not os.path.isfile(args.video):
        parser.error(f"Файл не найден: {args.video}")

    name = _base_name(args.video)
    os.makedirs(args.out_dir, exist_ok=True)
    frames_dir = os.path.join(args.out_dir, f"{name}_frames")

    print(f"== Нарезаю кадры ({args.count}) ==")
    frame_paths = extract_frames(args.video, frames_dir, count=args.count)
    if not frame_paths:
        print("Не удалось нарезать кадры. Проверь, что ffmpeg установлен и видео валидно.")
        return 1
    print(f"Кадров получено: {len(frame_paths)} -> {frames_dir}")

    short = shortlist(frame_paths, k=5)
    print("Шорт-лист (самые резкие):")
    for p in short:
        print(f"  {p}")

    if args.frames_only:
        print("\n--frames-only: остановился на кадрах. Открой папку и посмотри кандидатов.")
        return 0

    require_fal_key()

    copy = {}
    # (язык, хук) — какие обложки собираем.
    covers: list[tuple[str, str]] = []
    if args.hook is not None:
        covers = [("es", args.hook)]
    else:
        print("\n== Транскрибирую речь (fal-ai/whisper) ==")
        transcript = transcribe(args.video, args.language)
        if transcript:
            preview = transcript[:200] + ("…" if len(transcript) > 200 else "")
            print(f"Транскрипт: {preview}")
        else:
            print("Речь не распознана — копирайтер сгенерит общий текст.")

        print("\n== Генерирую тексты (fal-ai/any-llm) ==")
        copy = generate_copy(transcript)
        print(f"Хук (ES): {copy.get('hook_es', '')}")
        print(f"Хук (EN): {copy.get('hook_en', '')}")
        covers = [("es", copy.get("hook_es", "")), ("en", copy.get("hook_en", ""))]

    print("\n== Выбираю лучший кадр (fal-ai/any-llm/vision) ==")
    best = select_best_frame(frame_paths)
    print(f"Выбран кадр: {best}")

    print("\n== Собираю обложки ==")
    for lang_key, hook in covers:
        cover_path = os.path.join(args.out_dir, f"{name}_cover_{lang_key}.jpg")
        compose_cover(best, hook, cover_path)
        print(f"Обложка ({lang_key.upper()}): {cover_path}")

    if copy:
        caption = format_caption(copy)
        print("\n== Описание для публикации ==")
        print(caption)
        copy_path = os.path.join(args.out_dir, f"{name}_copy.json")
        with open(copy_path, "w", encoding="utf-8") as f:
            json.dump(copy, f, ensure_ascii=False, indent=2)
        txt_path = os.path.join(args.out_dir, f"{name}_caption.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(caption)
        print(f"\nСохранено: {copy_path}, {txt_path}")

    if not args.keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
