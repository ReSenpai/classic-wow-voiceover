"""Реестр TTS-провайдеров. Классы указаны строкой: импорт voru.providers не тянет torch."""
import importlib

_REGISTRY = {
    "mock": "voru.providers.mock:MockProvider",
}


def get_provider(name: str, **kwargs):
    if name not in _REGISTRY:
        raise KeyError(f"unknown TTS provider {name!r}; known: {', '.join(sorted(_REGISTRY))}")
    module_name, class_name = _REGISTRY[name].split(":")
    return getattr(importlib.import_module(module_name), class_name)(**kwargs)
