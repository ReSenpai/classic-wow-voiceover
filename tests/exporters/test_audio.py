import wave

import pytest
from mutagen.oggvorbis import OggVorbis

from voru.exporters.audio import EncodeError, encode_ogg
from voru.providers.base import SynthesisRequest, VoiceRef
from voru.providers.mock import MockProvider


@pytest.fixture
def master(tmp_path):
    request = SynthesisRequest(
        text="Прошу вас, соберите для меня эти грибы.", locale="ruRU", player_gender=None,
        voice=VoiceRef("v", "1", None, None), delivery_profile="neutral",
        generation_config={"seed": 1}, output_path=tmp_path / "master.wav",
    )
    return MockProvider().synthesize(request).path


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def test_encodes_real_ogg_vorbis(master, tmp_path):
    out = tmp_path / "pack" / "sounds" / "947-accept.ogg"

    duration = encode_ogg(master, out)

    info = OggVorbis(str(out)).info  # падает, если это не Vorbis в Ogg
    assert info.channels == 1
    assert duration == pytest.approx(info.length)
    assert duration == pytest.approx(wav_seconds(master), abs=0.05)


def test_failed_encoding_leaves_no_file(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav")
    out = tmp_path / "out" / "x.ogg"

    with pytest.raises(EncodeError):
        encode_ogg(bad, out)

    assert not out.exists()
    assert not any(p.suffix == ".tmp" for p in out.parent.glob("*")) if out.parent.exists() else True


def test_reencoding_replaces_file(master, tmp_path):
    out = tmp_path / "x.ogg"
    out.write_bytes(b"old")

    encode_ogg(master, out)

    assert OggVorbis(str(out)).info.length > 0


def test_encoding_is_byte_for_byte_reproducible(master, tmp_path):
    """Ogg-муксер по умолчанию ставит случайный serial — пак не был бы воспроизводимым."""
    encode_ogg(master, tmp_path / "a.ogg")
    encode_ogg(master, tmp_path / "b.ogg")

    assert (tmp_path / "a.ogg").read_bytes() == (tmp_path / "b.ogg").read_bytes()
