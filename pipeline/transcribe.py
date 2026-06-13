"""Транскрипция речи из видео через fal-ai/whisper.

Текст нужен копирайтеру (описание/хэштеги) и для хука на обложке.
"""
import fal_client

from config import require_fal_key

MODEL_ID = "fal-ai/whisper"


def _short_lang(language):
    if not language:
        return None
    return language.split("-")[0].lower()


def _run(video_path: str, language: str | None, chunk_level: str | None) -> dict:
    require_fal_key()
    print(f"[whisper] Загружаю видео: {video_path}")
    audio_url = fal_client.upload_file(video_path)

    arguments = {"audio_url": audio_url, "task": "transcribe"}
    lang = _short_lang(language)
    if lang:
        arguments["language"] = lang
    if chunk_level:
        arguments["chunk_level"] = chunk_level

    print("[whisper] Распознаю речь...")
    return fal_client.subscribe(MODEL_ID, arguments=arguments, with_logs=False) or {}


def transcribe(video_path: str, language: str | None = None) -> str:
    """Вернуть распознанный текст речи. Пустая строка, если речь не распознана."""
    result = _run(video_path, language, chunk_level=None)
    text = (result.get("text") or "").strip()
    print(f"[whisper] Готово, символов: {len(text)}")
    return text


def transcribe_segments(video_path: str, language: str | None = None) -> list[dict]:
    """Вернуть сегменты речи с таймингами: [{"text", "start", "end"}, ...].

    Нужно для подписей в видео-эффектах (HyperFrames/Remotion).
    """
    result = _run(video_path, language, chunk_level="segment")
    segments: list[dict] = []
    for chunk in result.get("chunks") or []:
        ts = chunk.get("timestamp") or [None, None]
        text = (chunk.get("text") or "").strip()
        if not text or ts[0] is None:
            continue
        segments.append({
            "text": text,
            "start": float(ts[0]),
            "end": float(ts[1]) if ts[1] is not None else float(ts[0]) + 2.0,
        })
    print(f"[whisper] Сегментов: {len(segments)}")
    return segments
