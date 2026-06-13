"""End-to-end автомонтаж для бота: видео + целевой язык -> готовые ролики + текст.

Шаги вынесены отдельными функциями, чтобы бот мог обновлять статус между ними:
  1) build_montage_edl  — транскрипт -> биты -> vision -> мозг -> EDL + перевод субтитров
  2) render_variant      — EDL -> MP4 в нужном стиле (a/b)
  3) make_localized_copy — описание + хэштеги на целевом языке
"""
import json
import os
import uuid

from pipeline.copywriter import generate_localized_copy, format_localized_caption
from .build_edl import make_edl
from . import render_remotion

# code -> (имя языка для LLM, подпись с флагом для кнопки/описания)
LANGUAGES = {
    "en": ("English", "🇬🇧 English"),
    "es": ("Spanish (Latin American)", "🇪🇸 Español"),
    "pt": ("Brazilian Portuguese", "🇧🇷 Português"),
    "kk": ("Kazakh", "🇰🇿 Қазақша"),
    "uz": ("Uzbek", "🇺🇿 Oʻzbekcha"),
}

STYLES = {
    "a": "Clean Mint",
    "b": "Bold Pop",
}


def lang_name(code: str) -> str:
    return LANGUAGES.get(code, ("English", ""))[0]


def lang_label(code: str) -> str:
    return LANGUAGES.get(code, ("", code))[1]


def build_montage_edl(video_path: str, workdir: str, lang_code: str) -> tuple[str, list[str]]:
    """Собрать EDL: подписи/интро/аутро и субтитры — на выбранном языке.

    Возвращает (путь к EDL, список предупреждений для пользователя). Предупреждения
    появляются, если ИИ-шаги сорвались и результат получился «сырым».
    """
    name = lang_name(lang_code)
    edl_path = os.path.join(workdir, f"job_{uuid.uuid4().hex[:8]}.edl.json")
    edl = make_edl(
        video_path,
        edl_path,
        language=None,            # язык исходного аудио — автоопределение whisper
        target_language=name,     # язык подписей/интро/аутро (мозг пишет на нём)
        translate_to=name,        # субтитры переводим на этот же язык
        workdir=os.path.join(workdir, "_edl"),
    )

    warnings: list[str] = []
    if edl.get("fallback"):
        warnings.append(
            "ИИ-редактор временно сорвался — монтаж собран по запасной схеме "
            "(без умных подписей/акцентов). Лучше прислать видео ещё раз."
        )
    if edl.get("translation_failed"):
        warnings.append(
            "Не удалось перевести субтитры — они остались на языке оригинала. "
            "Лучше прислать видео ещё раз."
        )
    return edl_path, warnings


def render_variant(edl_path: str, out_path: str, style: str) -> str:
    """Отрендерить один стиль (a/b) из EDL."""
    return render_remotion.render(edl_path, out_path, style)


def _transcript_from_edl(edl_path: str) -> str:
    """Собрать текст речи из кэша сегментов (его пишет make_edl) для копирайтера."""
    seg_cache = os.path.splitext(edl_path)[0] + ".segments.json"
    if not os.path.isfile(seg_cache):
        return ""
    try:
        with open(seg_cache, encoding="utf-8") as f:
            segments = json.load(f)
        return " ".join((s.get("text") or "").strip() for s in segments).strip()
    except (OSError, json.JSONDecodeError):
        return ""


def make_localized_copy(edl_path: str, lang_code: str) -> str:
    """Описание + хэштеги на целевом языке, готовый текст для Telegram."""
    transcript = _transcript_from_edl(edl_path)
    copy = generate_localized_copy(transcript, lang_name(lang_code))
    return format_localized_caption(copy, lang_label(lang_code))
