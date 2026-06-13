"""«Мозг» автомонтажа: из битов+vision собирает EDL (Edit Decision List).

Решает по-человечески: что оставить, что выкинуть как филлер/брак, где сделать
аккуратный зум-акцент, где повесить короткую подпись-плашку, какой переход между
клипами. Главный принцип — НЕ ПЕРЕБАРЩИВАТЬ: чистый динамичный шортс, а не цирк.
"""
import json
import re

import fal_client

from config import require_fal_key

LLM_MODEL_ID = "fal-ai/any-llm"
LLM = "google/gemini-2.5-flash"

SYSTEM = (
    "You are a senior short-form video editor (Reels/TikTok/Shorts). You take a "
    "transcript broken into timed beats plus per-beat visual analysis, and you "
    "produce a tight, punchy edit decision list. You have great taste: you cut "
    "filler and weak shots, keep momentum, and add effects ONLY where they earn "
    "their place. You return STRICT JSON only."
)

# Допустимые значения — рендерер умеет ровно это.
TRANSITIONS = {"none", "fade", "whip", "slide", "zoom_blur"}
EFFECTS = {"zoom", "label", "highlight"}
LABEL_POS = {"top", "center", "bottom"}


def _build_prompt(beats: list[dict], meta: dict, target_language: str,
                  target_min: float, target_max: float) -> str:
    lines = []
    for b in beats:
        v = b.get("vision") or {}
        lines.append(json.dumps({
            "idx": b["idx"],
            "t": [b["start"], b["end"]],
            "dur": b["dur"],
            "text": b["text"],
            "quality": round(float(v.get("quality", b.get("sharpness_norm", 0.5))), 2),
            "subject_visible": v.get("subject_visible", True),
            "visual": v.get("visual", ""),
            "focus": v.get("focus", [0.5, 0.5]),
        }, ensure_ascii=False))
    beats_block = "\n".join(lines)

    return f"""SOURCE VIDEO: {meta['width']}x{meta['height']} vertical, {meta['fps']} fps, {meta['duration']}s.
It is ONE continuous handheld take of a product demo. Your job: turn it into a tight
{target_min:.0f}-{target_max:.0f}s vertical Short by selecting the best beats and
adding tasteful effects. Keep the beats in chronological order (it's a spoken walkthrough).

Each beat (one per line) has: idx, t=[start,end] seconds in the SOURCE, dur, the spoken
text, a visual quality 0..1, whether the subject is clearly visible, a short visual
description, and the focus point [x,y] in 0..1.

BEATS:
{beats_block}

Return ONLY a JSON object (no markdown) with this shape:
{{
  "intro": {{"title": "<2-4 word hook, language={target_language}>", "subtitle": "<optional 2-5 words>"}},
  "clips": [
    {{
      "src_start": <seconds, within the chosen beat's range, you may trim a little>,
      "src_end": <seconds>,
      "transition_in": "none|fade|whip|slide|zoom_blur",
      "effects": [
        {{"type": "zoom", "to": 1.08, "focus": [x,y]}},
        {{"type": "label", "text": "<short callout, <=4 words, language={target_language}>"}},
        {{"type": "highlight", "focus": [x,y]}}
      ]
    }}
  ],
  "outro": {{"cta": "<short call to action, language={target_language}>"}}
}}

EDITING RULES (taste matters — follow strictly):
- SELECT, don't keep everything. Drop filler/hesitations/redundant or low-quality beats
  (e.g. quality < 0.35 or subject not visible, unless the line is essential). Aim for a
  total of {target_min:.0f}-{target_max:.0f}s across all clips.
- Keep chronological order. Do NOT reorder clips.
- transition_in: first clip MUST be "none". Use transitions sparingly (at most ~half the
  cuts), prefer "fade"/"whip"; "zoom_blur"/"slide" only for a notable topic change.
- effects: AT MOST 2 per clip, usually 0-1. A subtle "zoom" (to between 1.05 and 1.15
  toward the focus) adds life. Add a "label" ONLY when the beat names a concrete feature
  worth captioning on screen (e.g. a feature, a spec, a price); keep it <=4 words. Labels
  always render pinned at the TOP of the frame (subtitles live at the bottom, the product
  is in the center), so write them short enough to fit one or two lines. Use
  "highlight" rarely, only to point at a specific on-screen element.
- NEVER put a label on every clip. Most clips need 0-1 effects. Restraint reads as quality.
- src_start/src_end must stay inside the beat's [start,end] and be >= 0.8s long.

Output JSON only.
"""


def _extract_json_obj(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            return {}
    return {}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _validate(edl: dict, beats: list[dict], meta: dict) -> dict:
    """Привести EDL к безопасному виду: клипы в границах, эффекты из белого списка."""
    duration = meta.get("duration") or 0.0
    clips_in = edl.get("clips") or []
    clips: list[dict] = []

    for i, c in enumerate(clips_in):
        try:
            s = float(c.get("src_start"))
            e = float(c.get("src_end"))
        except (TypeError, ValueError):
            continue
        s = _clamp(s, 0.0, max(duration - 0.1, 0.1))
        e = _clamp(e, s + 0.1, duration if duration else s + 5.0)
        if e - s < 0.8:  # слишком короткий клип — пропускаем
            continue

        trans = c.get("transition_in") if c.get("transition_in") in TRANSITIONS else "fade"
        if i == 0:
            trans = "none"

        effects_out = []
        for fx in (c.get("effects") or [])[:2]:
            t = fx.get("type")
            if t not in EFFECTS:
                continue
            if t == "zoom":
                to = _clamp(float(fx.get("to", 1.1) or 1.1), 1.0, 1.25)
                focus = fx.get("focus") or [0.5, 0.5]
                effects_out.append({"type": "zoom", "to": round(to, 3),
                                    "focus": [_clamp(float(focus[0]), 0, 1), _clamp(float(focus[1]), 0, 1)]})
            elif t == "label":
                txt = str(fx.get("text") or "").strip()
                if not txt:
                    continue
                # Плашка всегда сверху: субтитры внизу, продукт в центре — верх свободен,
                # поэтому подписи не налезают ни на субтитры, ни на сам объект.
                effects_out.append({"type": "label", "text": txt[:48], "position": "top"})
            elif t == "highlight":
                focus = fx.get("focus") or [0.5, 0.5]
                effects_out.append({"type": "highlight",
                                    "focus": [_clamp(float(focus[0]), 0, 1), _clamp(float(focus[1]), 0, 1)]})

        clips.append({
            "src_start": round(s, 3),
            "src_end": round(e, 3),
            "transition_in": trans,
            "transition_dur": 0.0 if trans == "none" else 0.35,
            "effects": effects_out,
        })

    intro = edl.get("intro") or {}
    outro = edl.get("outro") or {}
    return {
        "intro": {"title": str(intro.get("title") or "").strip()[:40],
                  "subtitle": str(intro.get("subtitle") or "").strip()[:40]},
        "clips": clips,
        "outro": {"cta": str(outro.get("cta") or "").strip()[:40]},
    }


def _fallback(beats: list[dict], meta: dict, target_max: float) -> dict:
    """Если LLM недоступен — берём самые качественные биты по порядку до target_max."""
    ranked = sorted(beats, key=lambda b: (b.get("vision") or {}).get("quality", b.get("sharpness_norm", 0)), reverse=True)
    chosen = sorted(ranked[: max(4, len(beats) // 2)], key=lambda b: b["start"])
    clips = []
    total = 0.0
    for i, b in enumerate(chosen):
        if total >= target_max:
            break
        clips.append({
            "src_start": b["start"], "src_end": b["end"],
            "transition_in": "none" if i == 0 else "fade",
            "transition_dur": 0.0 if i == 0 else 0.35,
            "effects": [{"type": "zoom", "to": 1.08, "focus": (b.get("vision") or {}).get("focus", [0.5, 0.5])}],
        })
        total += b["dur"]
    return {"intro": {"title": "", "subtitle": ""}, "clips": clips, "outro": {"cta": ""}}


ATTEMPTS = 3  # LLM иногда отдаёт невалидный JSON или разово сбоит сеть — повторяем


def build_edl(beats: list[dict], meta: dict, target_language: str = "ru",
              target_min: float = 22.0, target_max: float = 38.0) -> dict:
    """Главный вход: биты+мета -> провалидированный EDL (без субтитров)."""
    require_fal_key()
    prompt = _build_prompt(beats, meta, target_language, target_min, target_max)

    print("[brain] Думаю над монтажом...")
    edl = None
    last_err = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            result = fal_client.subscribe(
                LLM_MODEL_ID,
                arguments={"model": LLM, "system_prompt": SYSTEM, "prompt": prompt},
                with_logs=False,
            )
            raw = (result or {}).get("output") or (result or {}).get("text") or ""
            candidate = _validate(_extract_json_obj(raw), beats, meta)
            if candidate["clips"]:
                edl = candidate
                break
            print(f"[brain] попытка {attempt}/{ATTEMPTS}: LLM не дал клипов")
        except Exception as e:
            last_err = e
            print(f"[brain] попытка {attempt}/{ATTEMPTS}: LLM-монтаж не удался ({e})")

    if edl is None:
        print(f"[brain] все попытки исчерпаны (last_err={last_err}), фолбэк по качеству")
        edl = _fallback(beats, meta, target_max)
        edl["fallback"] = True  # флаг для бота: монтаж получился «сырым», без подписей

    edl["meta"] = meta
    edl["target_language"] = target_language
    kept = sum(c["src_end"] - c["src_start"] for c in edl["clips"])
    print(f"[brain] Клипов: {len(edl['clips'])}, суммарно ~{kept:.1f}s")
    return edl
