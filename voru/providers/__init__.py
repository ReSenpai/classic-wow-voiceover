"""Реестр TTS-провайдеров. Классы указаны строкой: импорт voru.providers не тянет torch."""
import importlib

_REGISTRY = {
    "mock": "voru.providers.mock:MockProvider",
    "qwen3-tts-base": "voru.providers.qwen3:Qwen3BaseProvider",
    "qwen3-tts-ru-stress": "voru.providers.qwen3:Qwen3StressProvider",
    "f5-tts-ru-v2": "voru.providers.f5_ru:F5RuV2Provider",
    "f5-tts-ru-v4": "voru.providers.f5_ru:F5RuV4Provider",
    "seed-vc": "voru.providers.seed_vc:SeedVcProvider",
}


def get_provider(name: str, **kwargs):
    if name not in _REGISTRY:
        raise KeyError(f"unknown TTS provider {name!r}; known: {', '.join(sorted(_REGISTRY))}")
    module_name, class_name = _REGISTRY[name].split(":")
    return getattr(importlib.import_module(module_name), class_name)(**kwargs)
