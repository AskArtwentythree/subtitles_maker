"""Vision-анализ кадров-представителей битов (openrouter/router/vision).

Один батч-вызов по всем кадрам сразу (дёшево). Возвращаем только визуальные
факты: насколько кадр годен, что видно, где главный объект (точка фокуса).
Решения про подписи/акценты принимает «мозг» (brain.py) уже с текстом реплик.
"""
import json
import re

import fal_client

from config import require_fal_key

VISION_MODEL_ID = "openrouter/router/vision"
VISION_LLM = "google/gemini-2.5-flash"
VISION_SYSTEM = (
    "You are a video editor's visual analyst. You return STRICT JSON only, "
    "no markdown, no commentary."
)


def _extract_json_array(text: str) -> list:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    m = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return []


def analyze_beats(beats: list[dict]) -> list[dict]:
    """Дополнить биты полями vision: visual, quality(0..1), focus[x,y], subject_visible.

    Биты без кадра (тёмные/смазанные) получают quality=0.0 и не выкидываются —
    решение оставляет мозг.
    """
    indexed = [b for b in beats if b.get("frame")]
    if not indexed:
        for b in beats:
            b["vision"] = {"visual": "", "quality": 0.0, "focus": [0.5, 0.5], "subject_visible": False}
        return beats

    require_fal_key()
    urls = []
    for b in indexed:
        try:
            urls.append(fal_client.upload_file(b["frame"]))
        except Exception:
            urls.append(None)

    valid = [(b, u) for b, u in zip(indexed, urls) if u]
    if not valid:
        for b in beats:
            b.setdefault("vision", {"visual": "", "quality": 0.0, "focus": [0.5, 0.5], "subject_visible": False})
        return beats

    prompt = (
        "These are representative frames from one continuous vertical (9:16) "
        "handheld video, a hands-on product demo. They are numbered from 0 in "
        "the given order. For EACH image return an object in a JSON array:\n"
        '{"i": <index>, "visual": "<5-8 word description of what is shown>", '
        '"quality": <0.0-1.0 how clean/sharp/well-lit and usable for a Reel; '
        'penalize blur, motion, clutter, bad framing>, '
        '"subject_visible": <true if the main product/screen is clearly visible>, '
        '"focus": [<x 0-1>, <y 0-1> center of the main subject]}\n'
        "Return ONLY the JSON array with one object per image, same order."
    )

    out_array: list = []
    try:
        result = fal_client.subscribe(
            VISION_MODEL_ID,
            arguments={
                "prompt": prompt,
                "image_urls": [u for _, u in valid],
                "model": VISION_LLM,
                "system_prompt": VISION_SYSTEM,
            },
            with_logs=False,
        )
        text = ((result or {}).get("output") or (result or {}).get("text") or "")
        usage = (result or {}).get("usage") or {}
        if usage.get("cost") is not None:
            print(f"[vision] cost: ${usage['cost']:.5f}")
        out_array = _extract_json_array(str(text))
    except Exception as e:
        print(f"[vision] анализ не удался ({e}), ставлю нейтральные оценки")

    # Раскладываем ответ по битам (по позиции в valid).
    by_pos = {}
    for obj in out_array:
        if isinstance(obj, dict) and "i" in obj:
            try:
                by_pos[int(obj["i"])] = obj
            except (TypeError, ValueError):
                pass

    for pos, (b, _) in enumerate(valid):
        obj = by_pos.get(pos, {})
        focus = obj.get("focus") or [0.5, 0.5]
        try:
            fx, fy = float(focus[0]), float(focus[1])
        except (TypeError, ValueError, IndexError):
            fx, fy = 0.5, 0.5
        b["vision"] = {
            "visual": str(obj.get("visual") or "").strip(),
            "quality": float(obj.get("quality") or b.get("sharpness_norm", 0.5)),
            "subject_visible": bool(obj.get("subject_visible", True)),
            "focus": [round(min(max(fx, 0.0), 1.0), 3), round(min(max(fy, 0.0), 1.0), 3)],
        }

    for b in beats:
        b.setdefault("vision", {"visual": "", "quality": 0.0, "focus": [0.5, 0.5], "subject_visible": False})
    return beats
