import math
import wave

import pytest

from voru.qa.audio import Flag, QaThresholds, check_audio, verdict

SR = 24000


def write(path, samples, sr=SR):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(int(max(-1, min(1, s)) * 32767).to_bytes(2, "little", signed=True) for s in samples))
    return path


def tone(seconds, amp=0.3, freq=220):
    return [amp * math.sin(2 * math.pi * freq * i / SR) for i in range(int(seconds * SR))]


def silence(seconds):
    return [0.0] * int(seconds * SR)


TEXT_3S = "Прошу вас, соберите для меня грибы."  # ~35 символов ≈ 2–3 с речи


def reasons(flags):
    return {f.reason for f in flags}


def test_clean_audio_has_no_flags(tmp_path):
    path = write(tmp_path / "ok.wav", silence(0.15) + tone(2.6) + silence(0.2))

    assert check_audio(path, TEXT_3S) == []


def test_unreadable_file(tmp_path):
    path = tmp_path / "bad.wav"
    path.write_bytes(b"garbage")

    assert reasons(check_audio(path, TEXT_3S)) == {"unreadable"}


def test_empty_audio(tmp_path):
    assert "empty" in reasons(check_audio(write(tmp_path / "e.wav", []), TEXT_3S))


def test_all_silence(tmp_path):
    assert "silent" in reasons(check_audio(write(tmp_path / "s.wav", silence(3)), TEXT_3S))


def test_long_internal_silence(tmp_path):
    path = write(tmp_path / "gap.wav", tone(1.3) + silence(2.0) + tone(1.3))

    flags = check_audio(path, TEXT_3S)

    assert "long_pause" in reasons(flags)
    assert any("2.0" in f.detail for f in flags if f.reason == "long_pause")


def test_short_pauses_between_sentences_are_fine(tmp_path):
    path = write(tmp_path / "p.wav", tone(1.2) + silence(0.6) + tone(1.2))

    assert check_audio(path, TEXT_3S) == []


def test_long_leading_or_trailing_silence(tmp_path):
    lead = check_audio(write(tmp_path / "l.wav", silence(1.5) + tone(2.6)), TEXT_3S)
    trail = check_audio(write(tmp_path / "t.wav", tone(2.6) + silence(1.5)), TEXT_3S)

    assert "edge_silence" in reasons(lead)
    assert "edge_silence" in reasons(trail)


def test_clipping(tmp_path):
    path = write(tmp_path / "c.wav", tone(2.6, amp=1.6))

    assert "clipping" in reasons(check_audio(path, TEXT_3S))


def test_too_fast_means_swallowed_text(tmp_path):
    path = write(tmp_path / "f.wav", tone(0.6))

    assert "too_fast" in reasons(check_audio(path, TEXT_3S))


def test_too_slow_means_looping_or_dragging(tmp_path):
    path = write(tmp_path / "s.wav", tone(9.0))

    assert "too_slow" in reasons(check_audio(path, TEXT_3S))


def test_tempo_ignores_stress_marks_and_punctuation(tmp_path):
    path = write(tmp_path / "ok.wav", tone(2.6))

    assert check_audio(path, "Прош+у в+ас — соберит+е для мен+я гриб+ы!!!") == []


def test_thresholds_are_configurable(tmp_path):
    path = write(tmp_path / "gap.wav", tone(1.3) + silence(2.0) + tone(1.3))

    assert check_audio(path, TEXT_3S, QaThresholds(max_pause_s=3.0)) == []


# --- итоговое решение для очереди ---

def test_verdict_clean_is_generated():
    assert verdict([]) == ("generated", "")


def test_verdict_hard_failure_is_qa_failed():
    state, reason = verdict([Flag("silent", "rms 0.0001"), Flag("too_slow", "5 симв/с")])

    assert state == "qa_failed"
    assert "silent" in reason and "too_slow" in reason


def test_verdict_soft_flags_need_human_review():
    assert verdict([Flag("edge_silence", "1.2 с в начале")])[0] == "review_required"


@pytest.mark.parametrize("reason", ["unreadable", "empty", "silent", "clipping", "too_fast", "too_slow", "long_pause"])
def test_hard_reasons(reason):
    assert verdict([Flag(reason, "")])[0] == "qa_failed"
