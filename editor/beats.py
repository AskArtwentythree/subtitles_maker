"""Биты монтажа = сегменты транскрипта + визуальное качество.

Для IRL-видео из одного непрерывного дубля естественные единицы монтажа — это
реплики (сегменты речи). По каждому биту мы:
  - вытаскиваем несколько кадров внутри [start, end];
  - оцениваем резкость/яркость (отсев тряски/смаза/темноты);
  - выбираем самый резкий кадр как «представителя» бита для vision-анализа.
"""
import os
import subprocess

from pipeline.frames import _ffmpeg_bin, _score


def _extract_at(video_path: str, ts: float, out_path: str) -> str | None:
    try:
        subprocess.run(
            [_ffmpeg_bin(), "-y", "-ss", f"{ts:.3f}", "-i", video_path,
             "-frames:v", "1", "-q:v", "2", out_path],
            capture_output=True, timeout=60,
        )
    except subprocess.SubprocessError:
        return None
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    return None


def build_beats(
    video_path: str,
    segments: list[dict],
    frames_dir: str,
    samples_per_beat: int = 3,
) -> list[dict]:
    """Собрать биты: к каждому сегменту прикрепить лучший кадр и оценку качества.

    Возвращает список:
      {idx, text, start, end, dur, frame, sharpness, brightness}
    sharpness — относительная (0..1) внутри ролика, чтобы мозгу было проще
    сравнивать «чёткие» и «смазанные» биты.
    """
    os.makedirs(frames_dir, exist_ok=True)
    beats: list[dict] = []

    for i, seg in enumerate(segments):
        start = float(seg["start"])
        end = float(seg["end"])
        dur = max(end - start, 0.1)

        # Кадры внутри бита, со сдвигом от краёв (там часто смаз перехода).
        if samples_per_beat <= 1:
            offsets = [0.5]
        else:
            offsets = [0.2 + 0.6 * j / (samples_per_beat - 1) for j in range(samples_per_beat)]

        best_path, best_sharp, best_bright = None, -1.0, 0.0
        for j, off in enumerate(offsets):
            ts = start + dur * off
            out_path = os.path.join(frames_dir, f"beat_{i:02d}_{j}.jpg")
            got = _extract_at(video_path, ts, out_path)
            if not got:
                continue
            bright, sharp = _score(got)
            if bright < 20 or bright > 240:  # почти чёрный / пересвет — пропускаем
                continue
            if sharp > best_sharp:
                best_path, best_sharp, best_bright = got, sharp, bright

        beats.append({
            "idx": i,
            "text": (seg.get("text") or "").strip(),
            "start": round(start, 3),
            "end": round(end, 3),
            "dur": round(dur, 3),
            "frame": best_path,
            "sharpness": round(max(best_sharp, 0.0), 2),
            "brightness": round(best_bright, 1),
        })

    # Нормируем резкость в 0..1 относительно максимума в ролике.
    max_sharp = max((b["sharpness"] for b in beats), default=0.0) or 1.0
    for b in beats:
        b["sharpness_norm"] = round(b["sharpness"] / max_sharp, 3)

    return beats
