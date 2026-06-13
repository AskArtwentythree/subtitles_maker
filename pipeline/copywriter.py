"""Генерация текстов для публикации через fal-ai/any-llm.

Из транскрипта делаем: короткий хук для обложки, заголовок, описание на
испанском (рынок ЛатАм) + дубли на русском и английском, и хэштеги.
"""
import json
import re

import fal_client

from config import require_fal_key

LLM_MODEL_ID = "fal-ai/any-llm"
LLM = "google/gemini-2.5-flash"

SYSTEM = (
    "Eres un copywriter de redes sociales para una app de nutricion en LATAM. "
    "Escribes ganchos y descripciones para Shorts/Reels verticales: claros, "
    "humanos, sin sonar a IA, sin promesas medicas exageradas."
)

_PROMPT_TMPL = """A partir de la transcripcion (puede estar en ruso o ingles) de un video corto
que muestra una funcion de la app, genera el contenido para publicarlo.

Devuelve SOLO un objeto JSON valido, sin markdown ni texto extra, con esta forma:
{{
  "hook_es": "gancho MUY corto para la portada en espanol, 3-6 palabras",
  "hook_en": "el mismo gancho para la portada en ingles, 3-6 palabras",
  "title_es": "titulo corto en espanol (max 70 caracteres)",
  "description_es": "descripcion en espanol neutro LATAM, 2-3 frases + llamada a la accion",
  "description_ru": "la misma descripcion traducida al ruso",
  "description_en": "la misma descripcion traducida al ingles",
  "hashtags": ["#ejemplo", "#nutricion", "..."]
}}

Reglas:
- 5 a 8 hashtags relevantes (nutricion, salud, app), en espanol/ingles, sin espacios.
- Nada de afirmaciones medicas absolutas ni curas milagrosas.
- Si la transcripcion esta vacia o es ruido, infiere algo generico y util sobre una funcion de la app.

Transcripcion:
\"\"\"{transcript}\"\"\"
"""


def _extract_json(text: str) -> dict:
    """Достать JSON-объект из ответа LLM (с возможными ```-обёртками)."""
    if not text:
        return {}
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            return {}
    return {}


def generate_copy(transcript: str) -> dict:
    """Вернуть dict с полями hook_es/title_es/description_*/hashtags."""
    require_fal_key()

    transcript = (transcript or "").strip()[:6000]
    prompt = _PROMPT_TMPL.format(transcript=transcript or "(sin audio reconocible)")

    print("[copy] Генерирую тексты...")
    result = fal_client.subscribe(
        LLM_MODEL_ID,
        arguments={"model": LLM, "system_prompt": SYSTEM, "prompt": prompt},
        with_logs=False,
    )
    raw = (result or {}).get("output") or (result or {}).get("text") or ""
    data = _extract_json(raw)

    hashtags = data.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = hashtags.split()

    return {
        "hook_es": (data.get("hook_es") or "").strip(),
        "hook_en": (data.get("hook_en") or "").strip(),
        "title_es": (data.get("title_es") or "").strip(),
        "description_es": (data.get("description_es") or "").strip(),
        "description_ru": (data.get("description_ru") or "").strip(),
        "description_en": (data.get("description_en") or "").strip(),
        "hashtags": [str(h).strip() for h in hashtags if str(h).strip()],
    }


def format_caption(copy: dict) -> str:
    """Собрать готовый к копированию текст-описание для Telegram."""
    parts: list[str] = []
    if copy.get("title_es"):
        parts.append(f"🎬 {copy['title_es']}")
    if copy.get("description_es"):
        parts.append(f"\n🇪🇸 ES:\n{copy['description_es']}")
    if copy.get("description_ru"):
        parts.append(f"\n🇷🇺 RU:\n{copy['description_ru']}")
    if copy.get("description_en"):
        parts.append(f"\n🇬🇧 EN:\n{copy['description_en']}")
    if copy.get("hashtags"):
        parts.append("\n" + " ".join(copy["hashtags"]))
    return "\n".join(parts).strip()


# Нейтральный копирайтер: тема выводится из самого видео, без привязки к нише.
SYSTEM_GENERIC = (
    "You are a versatile short-form social media copywriter. You write hooks and "
    "descriptions for vertical Shorts/Reels on ANY topic. You first figure out what "
    "the video is actually about, then write clear, human, native-sounding copy and "
    "adapt the tone to that subject. No clickbait, no false promises."
)

_LOCALIZED_TMPL = """From the transcript (it may be in any language) of a short vertical video,
first figure out what the video is actually about (its topic / niche), then write
publish-ready copy for a Short/Reel about THAT.

Write EVERYTHING in {lang_name}. Return ONLY a valid JSON object, no markdown, shape:
{{
  "title": "short catchy title in {lang_name} (max 70 chars)",
  "description": "description in {lang_name}, 2-3 sentences + a call to action",
  "hashtags": ["#example", "#topic", "..."]
}}

Rules:
- Infer the real topic from the transcript. Do NOT assume any specific product, app,
  brand or industry — match the actual content of the video.
- 5 to 8 hashtags that are relevant to the real topic, no spaces. Hashtags may stay in
  english/latin script even if the language is different.
- Avoid absolute medical/financial guarantees and anything that misrepresents the video.
- If the transcript is empty or noise, infer the topic from any available context and
  keep it generic but on-topic.

Transcript:
\"\"\"{transcript}\"\"\"
"""


def generate_localized_copy(transcript: str, lang_name: str) -> dict:
    """Описание + заголовок + хэштеги для шортса на заданном языке (lang_name).

    Тема определяется по содержимому видео — без привязки к конкретной нише.
    """
    require_fal_key()
    transcript = (transcript or "").strip()[:6000]
    prompt = _LOCALIZED_TMPL.format(
        lang_name=lang_name, transcript=transcript or "(no recognizable audio)"
    )

    print(f"[copy] Генерирую тексты на {lang_name}...")
    result = fal_client.subscribe(
        LLM_MODEL_ID,
        arguments={"model": LLM, "system_prompt": SYSTEM_GENERIC, "prompt": prompt},
        with_logs=False,
    )
    raw = (result or {}).get("output") or (result or {}).get("text") or ""
    data = _extract_json(raw)

    hashtags = data.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = hashtags.split()

    return {
        "title": (data.get("title") or "").strip(),
        "description": (data.get("description") or "").strip(),
        "hashtags": [str(h).strip() for h in hashtags if str(h).strip()],
    }


def format_localized_caption(copy: dict, lang_label: str) -> str:
    """Готовый к публикации текст: заголовок + описание + хэштеги (один язык)."""
    parts: list[str] = []
    if copy.get("title"):
        parts.append(f"🎬 {copy['title']}")
    if copy.get("description"):
        parts.append(f"\n{copy['description']}")
    if copy.get("hashtags"):
        parts.append("\n" + " ".join(copy["hashtags"]))
    body = "\n".join(parts).strip()
    return f"📝 {lang_label}\n\n{body}" if body else ""
