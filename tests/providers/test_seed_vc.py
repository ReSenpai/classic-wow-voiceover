"""Seed-VC: запись человека → тембр референса. Модель подменяется, проверяется контракт вызова."""
import hashlib
import wave

import pytest

from voru.providers import get_provider
from voru.providers.base import SynthesisRequest, UnsupportedOption, VoiceRef
from voru.providers.seed_vc import SEEDVC_COMMIT, SEEDVC_HF_REVISION, SeedVcProvider


def make_wav(path, seconds=1.0, rate=48000, value=4000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(int(value).to_bytes(2, "little", signed=True) * int(rate * seconds))
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def files(tmp_path):
    return make_wav(tmp_path / "rec" / "489-complete.wav"), make_wav(tmp_path / "ref.wav", 5.0, 24000)


def request(tmp_path, source, ref, **config):
    return SynthesisRequest(
        text="Ну чт+о т+ы за л+апочка!", locale="ruRU", player_gender=None,
        voice=VoiceRef("satyr-male", "10", ref, "Хе-хе..."), delivery_profile="neutral",
        generation_config={"seed": 5, "source_audio": str(source), "source_sha256": sha(source), **config},
        output_path=tmp_path / "out.wav")


class FakeRunner:
    """Вместо подпроцесса Seed-VC: пишет «преобразованный» звук и запоминает аргументы."""
    def __init__(self):
        self.calls = []

    def __call__(self, args, seed, out_dir):
        self.calls.append({"args": args, "seed": seed})
        make_wav(out_dir / "vc_result.wav", 1.0, 22050)


def loaded(provider, runner):
    provider._load = lambda: setattr(provider, "_model", {"checkpoint": "/ck.pth", "config": "/cfg.yml"})
    provider._run = runner
    return provider


def test_converts_recording_to_reference_timbre(tmp_path, files):
    source, ref = files
    runner = FakeRunner()

    result = loaded(SeedVcProvider(), runner).synthesize(request(tmp_path, source, ref, diffusion_steps=30))

    (call,) = runner.calls
    args = call["args"]
    assert args[args.index("--source") + 1] == str(source)
    assert args[args.index("--target") + 1] == str(ref)
    assert args[args.index("--diffusion-steps") + 1] == "30"
    assert args[args.index("--checkpoint") + 1] == "/ck.pth"
    assert args[args.index("--f0-condition") + 1] == "False"
    assert call["seed"] == 5
    assert result.sample_rate == 22050
    assert result.duration_ms == 1000


def test_recording_changed_after_planning_is_rejected(tmp_path, files):
    source, ref = files
    req = request(tmp_path, source, ref)
    make_wav(source, 2.0)  # перезаписал реплику на стенде

    with pytest.raises(UnsupportedOption) as err:
        SeedVcProvider().validate(req)

    assert err.value.reason == "source_changed"


def test_missing_recording_is_rejected(tmp_path, files):
    source, ref = files
    req = request(tmp_path, source, ref)
    source.unlink()

    with pytest.raises(UnsupportedOption) as err:
        SeedVcProvider().validate(req)

    assert err.value.reason == "source_missing"


def test_new_recording_changes_fingerprint(tmp_path, files):
    from voru.jobs.fingerprint import fingerprint

    source, ref = files
    before = fingerprint(SeedVcProvider().synthesis_input(request(tmp_path, source, ref), 2))
    make_wav(source, 2.0)

    assert fingerprint(SeedVcProvider().synthesis_input(request(tmp_path, source, ref), 2)) != before


def test_revision_pins_code_and_weights():
    revision = SeedVcProvider().model_revision()

    assert SEEDVC_COMMIT in revision and SEEDVC_HF_REVISION in revision
    assert len(SEEDVC_COMMIT) == 40 and len(SEEDVC_HF_REVISION) == 40


def test_reads_float_wav_written_by_seed_vc(tmp_path):
    import struct

    from voru.providers.seed_vc import read_wav_mono

    samples = [0.5, -0.25, 0.0]
    payload = struct.pack("<3f", *samples)
    fmt = struct.pack("<HHIIHH", 3, 1, 22050, 22050 * 4, 4, 32)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(payload)) + payload
    path = tmp_path / "f.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)

    assert read_wav_mono(path) == (samples, 22050)


def test_registry():
    assert isinstance(get_provider("seed-vc"), SeedVcProvider)
