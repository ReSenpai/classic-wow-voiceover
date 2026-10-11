"""Парсер на реальных русских текстах из gossip-таблиц legacy-пака (лежат в git)."""
import re
from pathlib import Path

from voru.normalize.markup import MarkupError, parse

LEGACY_DIR = Path(__file__).resolve().parents[2] / "translator/assets/wow-classic-ru/AI_VoiceOverData_Vanilla/generated"
# quest_id_lookups.lua не подходит: там тексты обрезаны до 15+15 слов, обрезка рвёт $g...;
GOSSIP_FILES = ("npc_gossip_file_lookups.lua", "object_gossip_file_lookups.lua")
GOSSIP_KEY = re.compile(r'\["((?:[^"\\]|\\.)*)"\]\s*=\s*"[0-9a-f]{32}"')


def legacy_gossip_texts():
    texts = set()
    for name in GOSSIP_FILES:
        texts |= set(GOSSIP_KEY.findall((LEGACY_DIR / name).read_text(encoding="utf-8")))
    return sorted(texts)


def test_legacy_corpus_is_large_enough_to_mean_something():
    assert len(legacy_gossip_texts()) > 2000


# Сломанная разметка в самой локализации: такие записи должны блокироваться, а не озвучиваться.
KNOWN_BROKEN = {
    ("unclosed_stage_direction", "*Андоров мрачно смотрит на вас.>"),
}


def test_legacy_gossip_texts_parse_except_known_broken():
    failures = set()
    for text in legacy_gossip_texts():
        try:
            parse(text)
        except MarkupError as err:
            failures.add((err.reason, text[err.position:err.position + 32]))

    assert failures == KNOWN_BROKEN
