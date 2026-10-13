"""Синтетический пак CatQuest Voices: вымышленные ID, «аудио» — произвольные байты (reader звук не декодирует).

Как в настоящем 0.6.1: Index.lua (его играет CatQuest) — с субтитрами `c`, без модели `m`;
index.json — то же без `c`, но с `m` и с записями «только сдача», которых нет в Index.lua.
"""
import json
import zipfile

import pytest

TOC = """## Interface: 16001
## Title: CatQuest Voices
## Author: daniilcathey
## Version: {version}
## Dependencies: CatQuest

Index.lua
"""

INDEX = """-- Автогенерация: синтетический fixture
CatQuestVoicePack = CatQuestVoicePack or {}
CatQuestVoicePack.quests = {
    [900001] = { d = 3.5, v = "nightelf-male", n = { x = 20 },
        c = { x = { { 0.00, "Привет, путник." }, { 1.20, "Лес ждёт." } } },
        t = { d = 2.0, v = "nightelf-female", n = { x = 10 }, c = { x = { { 0.00, "Спасибо." } } } } },
    [900002] = { d = 4.0, g = 1, v = "human-male", n = { m = 30, f = 31 },
        c = { m = { { 0.00, "Ты готов?" } }, f = { { 0.00, "Ты готова?" } } },
        t = { d = 2.5, v = "human-male", n = { x = 12 }, c = { x = { { 0.00, "Отлично." } } } } },
    [900003] = { t = { d = 1.5, g = 1, v = "dwarf-male", n = { m = 9, f = 9 },
        c = { m = { { 0.00, "Молодец." } }, f = { { 0.00, "Умница." } } } } },
}
"""

INDEX_JSON = {
    "900001": {"d": 3.5, "v": "nightelf-male", "n": {"x": 20}, "m": "eleven_v4",
               "t": {"d": 2.0, "v": "nightelf-female", "n": {"x": 10}}},
    "900002": {"d": 4.0, "g": 1, "v": "human-male", "n": {"m": 30, "f": 31}, "m": "eleven_v4",
               "t": {"d": 2.5, "v": "human-male", "n": {"x": 12}, "m": "eleven_v4"}},
    "900003": {"t": {"d": 1.5, "g": 1, "v": "dwarf-male", "n": {"m": 9, "f": 9}}},
    "900004": {"t": {"d": 5.0, "v": "tauren-female", "n": {"x": 35}, "m": "eleven_v4"}},  # только в index.json
}

FILES = ["900001.ogg", "900001_t.ogg", "900002_m.ogg", "900002_f.ogg", "900002_t.ogg",
         "900003_t_m.ogg", "900003_t_f.ogg", "900004_t.ogg"]


def write_pack(root, version="0.6.1", index=INDEX, index_json=INDEX_JSON, files=FILES, extra=()):
    """Распакованный пак в root/CatQuest_Voices; возвращает путь к папке модуля."""
    pack = root / "CatQuest_Voices"
    (pack / "Sounds" / "q").mkdir(parents=True)
    (pack / "CatQuest_Voices.toc").write_text(TOC.format(version=version), encoding="utf-8")
    (pack / "Index.lua").write_text(index, encoding="utf-8")
    if index_json is not None:
        (pack / "index.json").write_text(json.dumps(index_json, ensure_ascii=False), encoding="utf-8")
    for name in [*files, *extra]:
        (pack / "Sounds" / "q" / name).write_bytes(b"OggS" + name.encode())
    return pack


def zip_dir(pack_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w") as z:
        for path in sorted(pack_dir.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(pack_dir.parent).as_posix())
    return zip_path


@pytest.fixture
def pack_dir(tmp_path):
    return write_pack(tmp_path / "src")


@pytest.fixture
def pack_zip(tmp_path, pack_dir):
    return zip_dir(pack_dir, tmp_path / "CatQuest_Voices-0.6.1.zip")
