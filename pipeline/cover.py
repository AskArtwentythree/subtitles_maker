"""Выбор лучшего кадра (fal vision) и сборка обложки 9:16 с текстом-хуком.

Принцип: обложка — это РЕАЛЬНЫЙ кадр записи экрана + аккуратная типографика.
Никакой генерации картинки нейросетью (иначе выглядит как нейрослоп).
"""
import os
import re

import fal_client
from PIL import Image, ImageDraw, ImageFont

from config import require_fal_key
from .frames import shortlist

# Vision через OpenRouter-роутер: шире каталог моделей и прозрачная цена за токены
# (в ответе есть usage.cost). Совместим по полям с any-llm/vision.
VISION_MODEL_ID = "openrouter/router/vision"
VISION_LLM = "google/gemini-2.5-flash"
VISION_SYSTEM = (
    "Responde unicamente con el numero del indice solicitado, sin texto adicional "
    "ni markdown."
)

# Целевой размер вертикальной обложки (9:16).
COVER_W, COVER_H = 1080, 1920

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
HOOK_FONT = os.path.join(_ASSETS, "Anton-Regular.ttf")
SUB_FONT = os.path.join(_ASSETS, "Montserrat-Bold.ttf")


def select_best_frame(frame_paths: list[str]) -> str:
    """Выбрать самый «обложечный» кадр. Шорт-лист эвристикой + vision-модель."""
    if not frame_paths:
        raise ValueError("Нет кадров для выбора обложки")

    candidates = shortlist(frame_paths, k=5)
    if len(candidates) == 1:
        return candidates[0]

    try:
        require_fal_key()
        urls = [fal_client.upload_file(p) for p in candidates]
        prompt = (
            "Estas eligiendo la miniatura (thumbnail) para un video vertical corto "
            "sobre una funcion de una app de nutricion. Te paso varias imagenes "
            "numeradas desde 0 en el orden dado. Elige UNA: la que muestre la "
            "interfaz de forma clara y nitida, bien iluminada, sin desenfoque ni "
            "transiciones, visualmente limpia y representativa. "
            "Responde SOLO con el numero del indice (0-based), sin texto adicional."
        )
        result = fal_client.subscribe(
            VISION_MODEL_ID,
            arguments={
                "prompt": prompt,
                "image_urls": urls,
                "model": VISION_LLM,
                "system_prompt": VISION_SYSTEM,
            },
            with_logs=False,
        )
        text = ((result or {}).get("output") or (result or {}).get("text") or "")
        usage = (result or {}).get("usage") or {}
        if usage.get("cost") is not None:
            print(f"[cover] vision cost: ${usage['cost']:.5f}")
        m = re.search(r"\d+", str(text))
        if m:
            idx = int(m.group())
            if 0 <= idx < len(candidates):
                print(f"[cover] vision выбрал кадр #{idx}")
                return candidates[idx]
    except Exception as e:  # vision не критичен — фолбэк на самый резкий
        print(f"[cover] vision-выбор не удался ({e}), беру самый резкий кадр")

    return candidates[0]


def _cover_crop(img: Image.Image) -> Image.Image:
    """Масштабировать с заполнением и обрезать по центру до 9:16."""
    img = img.convert("RGB")
    src_ratio = img.width / img.height
    dst_ratio = COVER_W / COVER_H
    if src_ratio > dst_ratio:
        new_h = COVER_H
        new_w = int(round(new_h * src_ratio))
    else:
        new_w = COVER_W
        new_h = int(round(new_w / src_ratio))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - COVER_W) // 2
    top = (new_h - COVER_H) // 2
    return img.crop((left, top, left + COVER_W, top + COVER_H))


def _bottom_scrim(height_frac: float = 0.42, max_alpha: int = 220) -> Image.Image:
    """Полупрозрачный градиент снизу (тёмный -> прозрачный) для читаемости текста."""
    scrim = Image.new("RGBA", (COVER_W, COVER_H), (0, 0, 0, 0))
    band_h = int(COVER_H * height_frac)
    top = COVER_H - band_h
    px = scrim.load()
    for y in range(top, COVER_H):
        t = (y - top) / max(band_h - 1, 1)
        alpha = int(max_alpha * (t ** 1.4))
        for x in range(COVER_W):
            px[x, y] = (0, 0, 0, alpha)
    return scrim


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.getlength(test) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_font(text: str, font_path: str, max_w: int, max_h: int,
              start: int = 130, min_size: int = 54) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Подобрать размер шрифта так, чтобы текст влез в (max_w, max_h)."""
    size = start
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines = _wrap(text, font, max_w)
        line_h = int(size * 1.12)
        total_h = line_h * len(lines)
        if total_h <= max_h and all(font.getlength(l) <= max_w for l in lines):
            return font, lines
        size -= 6
    font = ImageFont.truetype(font_path, min_size)
    return font, _wrap(text, font, max_w)


def compose_cover(frame_path: str, hook: str, out_path: str) -> str:
    """Собрать обложку: кадр 9:16 + нижний градиент + крупный текст-хук."""
    base = _cover_crop(Image.open(frame_path))
    base = Image.alpha_composite(base.convert("RGBA"), _bottom_scrim())

    draw = ImageDraw.Draw(base)
    margin = 80
    max_w = COVER_W - 2 * margin
    hook = (hook or "").strip().upper()

    if hook:
        max_text_h = int(COVER_H * 0.34)
        font, lines = _fit_font(hook, HOOK_FONT, max_w, max_text_h)
        line_h = int(font.size * 1.12)
        total_h = line_h * len(lines)
        y = COVER_H - margin - total_h
        for line in lines:
            w = font.getlength(line)
            x = (COVER_W - w) / 2
            draw.text(
                (x, y), line, font=font, fill=(255, 255, 255),
                stroke_width=max(3, font.size // 22), stroke_fill=(0, 0, 0),
            )
            y += line_h

    out = base.convert("RGB")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out.save(out_path, "JPEG", quality=90)
    print(f"[cover] Обложка готова -> {out_path}")
    return out_path
