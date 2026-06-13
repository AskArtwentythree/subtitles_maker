"""Перевод субтитров (и любых коротких строк) на целевой язык через fal-ai/any-llm.

Тайминги остаются прежними — переводим только текст. Все строки переводим ОДНИМ
батч-запросом (массив JSON), чтобы не плодить вызовы и не терять порядок.
"""
import json
import re

import fal_client

from config import require_fal_key

LLM_MODEL_ID = "fal-ai/any-llm"
LLM = "google/gemini-2.5-flash"


def _extract_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            return None
    return None


def translate_texts(texts: list[str], target_language: str) -> list[str]:
    """Перевести список строк на target_language, сохранив порядок и количество.

    При любой ошибке возвращаем исходные строки (лучше оригинал, чем пусто).
    """
    items = [{"id": i, "text": str(t or "")} for i, t in enumerate(texts)]
    if not items:
        return []
    require_fal_key()

    payload = json.dumps(items, ensure_ascii=False)
    prompt = (
        f"Translate the 'text' of each item into {target_language}. These are short "
        "video subtitle lines / on-screen captions. Keep it natural and spoken, keep "
        "punctuation, do NOT add quotes or extra words, do NOT merge or split items. "
        "Keep product names, brand names and latin acronyms (NFC, ZEPP, WeChat, Alipay) "
        "as-is. Return ONLY a JSON array with the same ids and the same length, shape: "
        '[{"id": 0, "text": "<translation>"}, ...].\n\n'
        f"ITEMS:\n{payload}"
    )

    try:
        result = fal_client.subscribe(
            LLM_MODEL_ID,
            arguments={"model": LLM, "prompt": prompt},
            with_logs=False,
        )
        raw = (result or {}).get("output") or (result or {}).get("text") or ""
        data = _extract_json(raw)
        if not isinstance(data, list):
            return [it["text"] for it in items]
        by_id = {}
        for row in data:
            try:
                by_id[int(row["id"])] = str(row.get("text") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue
        out = [by_id.get(i) or items[i]["text"] for i in range(len(items))]
        return out
    except Exception as e:  # переводчик не должен валить весь пайплайн
        print(f"[translate] перевод не удался ({e}), оставляю оригинал")
        return [it["text"] for it in items]


def translate_captions(edl: dict, target_language: str) -> dict:
    """Перевести все субтитры во всех клипах EDL на target_language (тайминги те же)."""
    refs = []  # (clip_idx, cap_idx)
    texts = []
    for ci, clip in enumerate(edl.get("clips", [])):
        for capi, cap in enumerate(clip.get("captions", [])):
            refs.append((ci, capi))
            texts.append(cap.get("text", ""))
    if not texts:
        return edl

    print(f"[translate] перевожу {len(texts)} субтитров -> {target_language}")
    translated = translate_texts(texts, target_language)
    for (ci, capi), new_text in zip(refs, translated):
        edl["clips"][ci]["captions"][capi]["text"] = new_text
    return edl
