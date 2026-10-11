import json
import math
import wave

from voru.casting.design import candidates_page


def wav(path, seconds, amp=0.3):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(24000 * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"".join(int(amp * 32767 * math.sin(i / 10)).to_bytes(2, "little", signed=True)
                               for i in range(n)))
    path.with_suffix(".json").write_text(json.dumps({"text": "Пусть луна <осветит> путь.", "instruct": "calm",
                                                     "seed": 1}, ensure_ascii=False), encoding="utf-8")


def test_page_lists_candidates_with_pick_commands_and_warnings(tmp_path):
    root = tmp_path / "voice_design"
    wav(root / "dryad-female" / "seed-10.wav", 9.0)
    wav(root / "nightelf-male-elder" / "seed-20.wav", 16.0)
    wav(root / "nightelf-male-elder" / "seed-21.wav", 3.0, amp=0.0)  # тишина — брак

    page = candidates_page(tmp_path)

    html = page.read_text(encoding="utf-8")
    assert page == root / "index.html"
    assert 'src="dryad-female/seed-10.wav"' in html
    assert "pick --voice dryad-female --seed 10" in html
    assert "&lt;осветит&gt;" in html
    assert "длиннее 12 с" in html  # F5 обрежет референс — транскрипт перестанет совпадать
    assert "silent" in html


def test_page_shows_prompt_per_candidate(tmp_path):
    root = tmp_path / "voice_design"
    wav(root / "dryad-female" / "seed-10.wav", 6.0)
    wav(root / "dryad-female" / "seed-11.wav", 6.0)
    meta = root / "dryad-female" / "seed-11.json"
    meta.write_text(json.dumps({"text": "Привет.", "instruct": "energetic young woman", "seed": 11}), encoding="utf-8")

    html = candidates_page(tmp_path).read_text(encoding="utf-8")

    assert "calm" in html and "energetic young woman" in html
