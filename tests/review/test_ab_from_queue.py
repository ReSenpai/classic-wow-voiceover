"""A/B-отчёт по пилоту из очереди: мастера двух провайдеров для одних и тех же реплик."""
import json

import pytest

from voru.config import REPO_ROOT
from voru.corpus.record import read_jsonl, write_jsonl
from voru.pipeline import build_pilot
from voru.providers.mock import MockProvider
from voru.review import build_pilot_ab


class MockB(MockProvider):
    name = "mock-b"


class SilentB(MockProvider):
    name = "mock-b"

    def _generate(self, model_text, request):
        samples, sr = super()._generate(model_text, request)
        return [0.0] * len(samples), sr


@pytest.fixture
def corpus(tmp_path):
    records = {r.text_key: r for r in read_jsonl(REPO_ROOT / "corpus" / "pilot" / "teldrassil.jsonl")}
    path = tmp_path / "corpus.jsonl"
    write_jsonl([records[k] for k in ("quest:489:accept", "quest:997:accept", "quest:488:complete")], path)
    return path


def synth(corpus, tmp_path, monkeypatch, second=MockB):
    import voru.providers

    monkeypatch.setattr(f"{__name__}.SECOND", second, raising=False)
    monkeypatch.setitem(voru.providers._REGISTRY, "mock-b", f"{__name__}:SECOND")
    for name in ("mock", "mock-b"):
        build_pilot([corpus], name, work_dir=tmp_path / "work", pack=False)


def test_report_pairs_both_providers(corpus, tmp_path, monkeypatch):
    synth(corpus, tmp_path, monkeypatch)

    out = build_pilot_ab([corpus], "mock", "mock-b", tmp_path / "work", tmp_path / "review", seed=1)

    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    assert len(key) == 5  # 3 реплики, две из них с вариантами пола
    assert all(set(sides.values()) == {"mock", "mock-b"} for sides in key.values())
    assert "Зенн" in (out / "index.html").read_text(encoding="utf-8")


def test_limit_is_deterministic(corpus, tmp_path, monkeypatch):
    synth(corpus, tmp_path, monkeypatch)

    a = build_pilot_ab([corpus], "mock", "mock-b", tmp_path / "work", tmp_path / "r1", seed=1, limit=2)
    b = build_pilot_ab([corpus], "mock", "mock-b", tmp_path / "work", tmp_path / "r2", seed=1, limit=2)

    assert len(json.loads((a / "key.json").read_text(encoding="utf-8"))) == 2
    assert (a / "key.json").read_text(encoding="utf-8") == (b / "key.json").read_text(encoding="utf-8")


def test_qa_failed_audio_is_not_offered_for_listening(corpus, tmp_path, monkeypatch):
    synth(corpus, tmp_path, monkeypatch, second=SilentB)

    with pytest.raises(ValueError, match="нет пар"):
        build_pilot_ab([corpus], "mock", "mock-b", tmp_path / "work", tmp_path / "review", seed=1)
