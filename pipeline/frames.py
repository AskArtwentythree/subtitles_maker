"""Нарезка кадров-кандидатов из видео (ffmpeg) и отбор по качеству.

Идея: вытащить N равномерно распределённых кадров, отсеять тёмные/засвеченные
и размытые, а из оставшихся сделать шорт-лист самых резких. Дальше шорт-лист
уходит в vision-модель, которая выбирает «обложечный» кадр.
"""
import os
import re
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageFilter


def _ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe_bin() -> str | None:
    return shutil.which("ffprobe")


def _duration_sec(video_path: str) -> float:
    """Длительность видео в секундах. 0.0, если определить не удалось."""
    probe = _ffprobe_bin()
    if probe:
        try:
            out = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True, timeout=60,
            )
            val = (out.stdout or "").strip()
            if val:
                return float(val)
        except (subprocess.SubprocessError, ValueError):
            pass

    # Фолбэк: парсим stderr ffmpeg на строку Duration: HH:MM:SS.xx
    try:
        out = subprocess.run(
            [_ffmpeg_bin(), "-i", video_path],
            capture_output=True, text=True, timeout=60,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out.stderr or "")
        if m:
            h, mm, ss = m.groups()
            return int(h) * 3600 + int(mm) * 60 + float(ss)
    except subprocess.SubprocessError:
        pass
    return 0.0


def extract_frames(video_path: str, out_dir: str, count: int = 16) -> list[str]:
    """Вытащить count кадров, равномерно по таймлайну (с отступом от краёв)."""
    os.makedirs(out_dir, exist_ok=True)
    duration = _duration_sec(video_path)

    if duration <= 0:
        # Не знаем длительность — берём по одному кадру каждые ~2 сек, до count.
        timestamps = [i * 2.0 for i in range(count)]
    else:
        start = duration * 0.05
        end = duration * 0.95
        if end <= start:
            start, end = 0.0, max(duration, 0.1)
        step = (end - start) / max(count - 1, 1)
        timestamps = [start + i * step for i in range(count)]

    paths: list[str] = []
    for i, ts in enumerate(timestamps):
        out_path = os.path.join(out_dir, f"frame_{i:02d}.jpg")
        try:
            subprocess.run(
                [_ffmpeg_bin(), "-y", "-ss", f"{ts:.3f}", "-i", video_path,
                 "-frames:v", "1", "-q:v", "2", out_path],
                capture_output=True, timeout=60,
            )
        except subprocess.SubprocessError:
            continue
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            paths.append(out_path)

    return paths


def _score(path: str) -> tuple[float, float]:
    """(яркость 0..255, резкость) для кадра. Резкость — дисперсия краёв."""
    try:
        img = Image.open(path).convert("L")
    except OSError:
        return 0.0, 0.0
    # Уменьшаем для скорости.
    w, h = img.size
    if w > 320:
        img = img.resize((320, max(1, int(320 * h / w))))
    brightness = float(np.asarray(img, dtype=np.float32).mean())
    edges = img.filter(ImageFilter.FIND_EDGES)
    sharpness = float(np.asarray(edges, dtype=np.float32).var())
    return brightness, sharpness


def shortlist(frame_paths: list[str], k: int = 5) -> list[str]:
    """Отсеять тёмные/засвеченные и вернуть k самых резких кадров."""
    scored: list[tuple[float, str]] = []
    for p in frame_paths:
        brightness, sharpness = _score(p)
        if brightness < 25 or brightness > 235:  # почти чёрный / пересвет
            continue
        scored.append((sharpness, p))

    if not scored:
        return frame_paths[:k]

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:k]]
