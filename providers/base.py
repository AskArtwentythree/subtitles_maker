"""Общий интерфейс провайдеров субтитров."""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import requests


@dataclass
class SubtitleOptions:
    """Опции генерации субтитров (надмножество — не все провайдеры используют всё)."""

    # Пресет стиля. Для Veed это reels-подобные стили (см. veed_fal.PRESETS).
    preset: str = "hustle"

    # Язык исходного аудио в формате BCP-47, напр. "ru-RU", "en-US".
    # None = автоопределение провайдером.
    language: Optional[str] = None

    # Перевести субтитры на этот язык (BCP-47). None = оставить язык оригинала.
    translation_language: Optional[str] = None

    # Положение статичных субтитров: "top" | "center" | "bottom".
    position: Optional[str] = None

    # Интенсивность тени для читаемости: "none" | "min" | "mid" | "max".
    shadow: Optional[str] = None

    # Переопределение текста (для Veed — поля text_customizations.baseline).
    # ВНИМАНИЕ: размер шрифта Veed API не поддерживает — только эти три.
    font: Optional[str] = None          # имя Google Font, напр. "Montserrat"
    font_weight: Optional[int] = None   # 100..900, >=700 = жирный
    text_color: Optional[str] = None    # hex, напр. "#FFFFFF"

    # Стиль выделенных (highlighted) слов — вторая «полка» text_customizations.
    # Размера тоже нет, только font/weight/color.
    highlight_font: Optional[str] = None
    highlight_weight: Optional[int] = None
    highlight_color: Optional[str] = None

    # Провайдер-специфичные параметры, которые не входят в общий интерфейс
    # (напр. для autosub: font_size, stroke_width, words_per_subtitle и т.п.).
    extra: dict = field(default_factory=dict)

    # Готовый SRT-текст. Если задан — транскрипция пропускается.
    srt_content: Optional[str] = None

    # Словарь брендов/терминов для исправления распознавания.
    # Формат элемента: {"word": "NutriApp", "replaces": ["nutri app", "nutria"]}
    vocabulary: list = field(default_factory=list)


@dataclass
class SubtitleResult:
    """Результат работы провайдера."""

    output_path: str  # путь к локальному MP4 с вшитыми субтитрами
    provider: str
    remote_url: Optional[str] = None  # исходный URL результата у провайдера
    duration_sec: Optional[float] = None
    cost_usd: Optional[float] = None  # приблизительная оценка стоимости
    raw: dict = field(default_factory=dict)  # сырой ответ API


class SubtitleProvider(ABC):
    """Базовый класс провайдера: видео на входе -> видео с субтитрами на выходе."""

    name: str = "base"

    @abstractmethod
    def generate(
        self,
        video_path: str,
        opts: SubtitleOptions,
        out_path: str,
    ) -> SubtitleResult:
        """Сгенерировать субтитры и сохранить результат в out_path."""
        raise NotImplementedError


def download_file(url: str, out_path: str) -> None:
    """Скачать файл по URL в out_path (создаёт директории при необходимости)."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
