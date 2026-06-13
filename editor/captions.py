"""Ре-тайминг субтитров под обрезанный таймлайн.

После отбора клипов исходные тайминги речи «рвутся». Привязываем реплики к
клипам и переводим их во ВРЕМЯ КЛИПА (от 0). Рендереру остаётся сместить на
выходную позицию клипа — переходы при этом не ломают синхрон.
"""


def attach_captions(edl: dict, segments: list[dict]) -> dict:
    """Прикрепить к каждому клипу его субтитры (в локальном времени клипа)."""
    for clip in edl.get("clips", []):
        s = clip["src_start"]
        e = clip["src_end"]
        clip_dur = e - s
        caps = []
        for seg in segments:
            seg_s = float(seg["start"])
            seg_e = float(seg["end"])
            # Пересечение реплики с диапазоном клипа.
            ov_s = max(seg_s, s)
            ov_e = min(seg_e, e)
            if ov_e - ov_s < 0.15:  # почти не пересекается
                continue
            caps.append({
                "text": (seg.get("text") or "").strip(),
                "start": round(ov_s - s, 3),
                "end": round(min(ov_e - s, clip_dur), 3),
            })
        clip["captions"] = caps
    return edl
