"""Фиксация входа (lock) и inspect (дизайн CQ §2, §6, §13)."""
import pytest
import yaml

from voru.catquest.inspect import LockMismatch, check_lock, inspect_pack, load_lock, main
from voru.catquest.reader import read_pack


def lock_for(pack, **override):
    data = {"source": {"version": pack.version, "sha256": pack.source_sha256}}
    data["source"].update(override)
    return data


def test_summary_counts_lines_not_quests(pack_zip):
    report = inspect_pack(read_pack(pack_zip))

    assert report["quests"] == 3
    assert report["lines"] == 7
    assert report["by_stage"] == {"accept": {"x": 1, "m": 1, "f": 1}, "complete": {"x": 2, "m": 1, "f": 1}}
    assert report["quests_with_accept"] == 2
    assert report["quests_with_complete"] == 3
    assert report["voices"] == 4
    assert report["models"] == {"eleven_v4": 4, "unknown": 3}
    assert report["without_text"] == 0
    assert report["missing_audio"] == []
    assert report["unused_audio"] == ["Sounds/q/900004_t.ogg"]
    assert report["json_only_quests"] == [900004]
    assert report["index_hours"] == pytest.approx((3.5 + 2.0 + 4.0 * 2 + 2.5 + 1.5 * 2) / 3600, abs=1e-4)


def test_lock_matches(pack_zip):
    pack = read_pack(pack_zip)

    check_lock(pack, lock_for(pack))


@pytest.mark.parametrize("field, value", [("sha256", "0" * 64), ("version", "0.6.2")])
def test_changed_input_is_not_silently_accepted(pack_zip, field, value):
    pack = read_pack(pack_zip)

    with pytest.raises(LockMismatch, match=field):
        check_lock(pack, lock_for(pack, **{field: value}))


def test_unpacked_directory_cannot_prove_the_lock(pack_dir, pack_zip):
    pack = read_pack(pack_zip)

    with pytest.raises(LockMismatch, match="ZIP"):
        check_lock(read_pack(pack_dir), lock_for(pack))


def test_repo_lock_is_complete():
    lock = load_lock()

    assert lock["source"]["curseforge_file_id"] == 9142066
    assert len(lock["source"]["sha256"]) == 64
    assert lock["source"]["license"] == "CC BY-NC-SA 4.0"
    assert lock["target"]["profile"] == "forever-ruru"
    assert lock["voiceover"]["base_commit"].startswith("f5476e7")


def test_cli_writes_report_and_checks_lock(pack_zip, tmp_path, capsys):
    pack = read_pack(pack_zip)
    lock = tmp_path / "lock.yaml"
    lock.write_text(yaml.safe_dump(lock_for(pack)), encoding="utf-8")
    out = tmp_path / "inspect.json"

    main(["--source", str(pack_zip), "--lock", str(lock), "--out", str(out)])

    assert out.exists()
    assert "реплик: 7" in capsys.readouterr().out


def test_cli_fails_on_lock_mismatch(pack_zip, tmp_path):
    lock = tmp_path / "lock.yaml"
    lock.write_text(yaml.safe_dump({"source": {"version": "0.6.1", "sha256": "0" * 64}}), encoding="utf-8")

    with pytest.raises(SystemExit) as err:
        main(["--source", str(pack_zip), "--lock", str(lock)])

    assert err.value.code != 0
