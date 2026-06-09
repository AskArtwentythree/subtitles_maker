"""Провайдеры генерации субтитров.

Каждый провайдер реализует общий интерфейс SubtitleProvider, чтобы их можно было
сравнивать на одном и том же видео и легко переключать в боте.
"""
from .base import SubtitleProvider, SubtitleOptions, SubtitleResult
from .veed_fal import VeedFalProvider
from .fal_autosub import FalAutoSubProvider

PROVIDERS = {
    VeedFalProvider.name: VeedFalProvider,
    FalAutoSubProvider.name: FalAutoSubProvider,
}


def get_provider(name: str) -> SubtitleProvider:
    if name not in PROVIDERS:
        available = ", ".join(PROVIDERS)
        raise ValueError(f"Неизвестный провайдер '{name}'. Доступны: {available}")
    return PROVIDERS[name]()


__all__ = [
    "SubtitleProvider",
    "SubtitleOptions",
    "SubtitleResult",
    "VeedFalProvider",
    "FalAutoSubProvider",
    "PROVIDERS",
    "get_provider",
]
