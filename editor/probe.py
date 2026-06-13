"""Параметры исходного видео через ffprobe."""
import json
import shutil
import subprocess


def _ffprobe_bin() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def probe(video_path: str) -> dict:
    """Вернуть {width, height, fps, duration} исходного видео.

    fps считаем из r_frame_rate ("30/1" -> 30.0). Если что-то не считалось —
    разумные дефолты под вертикальный шортс.
    """
    out = subprocess.run(
        [_ffprobe_bin(), "-v", "error",
         "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-show_entries", "format=duration",
         "-of", "json", video_path],
        capture_output=True, text=True, timeout=60,
    )
    data = json.loads(out.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}

    width = int(stream.get("width") or 1080)
    height = int(stream.get("height") or 1920)

    fps = 30.0
    rate = stream.get("r_frame_rate") or "30/1"
    try:
        num, den = rate.split("/")
        if float(den) != 0:
            fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        pass

    duration = 0.0
    try:
        duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        pass

    return {
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "duration": round(duration, 3),
    }
