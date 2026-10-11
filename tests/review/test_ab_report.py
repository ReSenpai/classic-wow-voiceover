import json
import wave

import pytest

from voru.review import ReviewItem, build_ab_report, score

SYSTEMS = ("qwen3-tts-base", "f5-tts-ru-v4")


def wav(path, frames=2400):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x01\x00" * frames)
    return path


@pytest.fixture
def items(tmp_path):
    result = []
    for i in range(10):
        result.append(ReviewItem(
            item_id=f"quest:{i}:accept|-",
            title=f"Квест {i}",
            npc_name="Деналан",
            raw_text=f"Прошу вас, $N, сделайте {i}.",
            spoken_text=f"Прошу вас, сделайте {i}.",
            candidates={s: wav(tmp_path / "masters" / f"{s}-{i}.wav", 2400 + i) for s in SYSTEMS},
            flags={SYSTEMS[0]: ["edge_silence: 1.1 с в начале"]} if i == 0 else {},
        ))
    return result


@pytest.fixture
def report(tmp_path, items):
    return build_ab_report(items, tmp_path / "review", seed=7)


def test_report_files(report):
    assert (report / "index.html").exists()
    assert (report / "key.json").exists()
    assert len(list((report / "audio").glob("*.wav"))) == 20


def test_report_is_blind(report):
    html = (report / "index.html").read_text(encoding="utf-8")
    names = [p.name for p in (report / "audio").iterdir()]

    for system in SYSTEMS:
        assert system not in html
        assert not any(system in n for n in names)
    assert "qwen" not in html.lower() and "f5-tts" not in html.lower()  # «f5» может встретиться в hex-имени


def test_report_shows_texts_and_flags_without_system(report):
    html = (report / "index.html").read_text(encoding="utf-8")

    assert "Прошу вас, $N, сделайте 0." in html
    assert "Прошу вас, сделайте 0." in html
    assert "Деналан" in html
    assert "edge_silence" in html  # флаг виден, но привязан к стороне A/B, а не к модели


def test_key_maps_sides_to_systems_and_is_balanced(report):
    key = json.loads((report / "key.json").read_text(encoding="utf-8"))

    assert set(key) == {f"quest:{i}:accept|-" for i in range(10)}
    assert all(set(sides.values()) == set(SYSTEMS) for sides in key.values())
    a_counts = sum(sides["A"] == SYSTEMS[0] for sides in key.values())
    assert 3 <= a_counts <= 7


def test_same_seed_same_layout(tmp_path, items):
    a = build_ab_report(items, tmp_path / "r1", seed=7)
    b = build_ab_report(items, tmp_path / "r2", seed=7)

    assert (a / "key.json").read_text(encoding="utf-8") == (b / "key.json").read_text(encoding="utf-8")


def test_html_escapes_text(tmp_path, items):
    item = items[0]
    evil = ReviewItem(**{**item.__dict__, "spoken_text": "<script>alert(1)</script>"})

    html = (build_ab_report([evil], tmp_path / "r", seed=1) / "index.html").read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_items_must_have_two_systems(tmp_path, items):
    bad = ReviewItem(**{**items[0].__dict__, "candidates": {SYSTEMS[0]: items[0].candidates[SYSTEMS[0]]}})

    with pytest.raises(ValueError, match="2"):
        build_ab_report([bad], tmp_path / "r", seed=1)


# --- подсчёт результатов ---

def ratings(key, prefer, ties=0, natural=None, role=None):
    """Оценки: выбираем сторону, где стоит prefer; первые ties — ничьи."""
    out = {}
    for n, (item_id, sides) in enumerate(sorted(key.items())):
        winner = next(side for side, system in sides.items() if system == prefer)
        loser = "B" if winner == "A" else "A"
        out[item_id] = {
            "choice": "tie" if n < ties else winner,
            "scores": {winner: {"natural": natural or 5, "role": role or 4}, loser: {"natural": 3, "role": 3}},
            "comment": "",
        }
    return {"items": out}


def test_score_preference_excludes_ties(report):
    key = json.loads((report / "key.json").read_text(encoding="utf-8"))

    summary = score(key, ratings(key, prefer=SYSTEMS[1], ties=2))

    s = summary[SYSTEMS[1]]
    assert s["wins"] == 8 and s["losses"] == 0 and s["ties"] == 2
    assert s["preference"] == 1.0
    assert s["rated_pairs"] == 10
    assert s["median_natural"] == 5 and s["median_role"] == 4
    assert summary[SYSTEMS[0]]["preference"] == 0.0
    assert summary[SYSTEMS[0]]["median_natural"] == 3


def test_score_ignores_unrated_items(report):
    key = json.loads((report / "key.json").read_text(encoding="utf-8"))
    partial = ratings(key, prefer=SYSTEMS[0])
    for item_id in list(partial["items"])[:4]:
        del partial["items"][item_id]

    assert score(key, partial)[SYSTEMS[0]]["rated_pairs"] == 6


def test_score_rejects_ratings_for_unknown_items(report):
    key = json.loads((report / "key.json").read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="unknown"):
        score(key, {"items": {"nope": {"choice": "A", "scores": {}, "comment": ""}}})
