"""Mock TTS: тон вместо речи — для тестов и проверки конвейера в игре без GPU.

Длина ≈ 60 мс на символ (0,5–30 с), высота тона зависит от voice_id: на слух видно,
что у разных NPC разные «голоса». Детерминирован.
"""
import hashlib
import math

from voru.providers.base import Capabilities, Provider

SAMPLE_RATE = 22050
MS_PER_CHAR = 60


class MockProvider(Provider):
    name = "mock"
    adapter_version = "1"
    default_capabilities = Capabilities(
        languages=frozenset({"ru"}),
        voice_reference=True,
        requires_reference=False,
        voice_design=False,
        delivery_profiles=frozenset({"neutral"}),
        stress_marks=True,
        max_chars=5000,
        config_keys=frozenset(),
    )

    def __init__(self, capabilities=None):
        super().__init__(capabilities)
        self.load_count = 0

    def model_revision(self) -> str:
        return "mock-tone-1"

    def _load(self):
        self.load_count += 1

    def _generate(self, model_text, request):
        duration_ms = min(30_000, max(500, len(model_text) * MS_PER_CHAR))
        n = SAMPLE_RATE * duration_ms // 1000
        frequency = 180 + int(hashlib.sha256(request.voice.voice_id.encode()).hexdigest()[:4], 16) % 240
        fade = SAMPLE_RATE // 50  # 20 мс — без щелчков
        samples = [
            0.3 * min(1.0, i / fade, (n - i) / fade) * math.sin(2 * math.pi * frequency * i / SAMPLE_RATE)
            for i in range(n)
        ]
        return samples, SAMPLE_RATE
