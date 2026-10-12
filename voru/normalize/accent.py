"""Автоматические ударения и «ё» через RUAccent (MIT) с кэшем в git.

RUAccent нужен transformers 4.x, а окружению F5 — 5.x, поэтому ударения считаются один раз
в Windows-окружении (python -m voru.normalize.accent warm) и хранятся в corpus/accents.jsonl.
Окружения моделей только читают кэш: нет записи — реплика блокируется (accent_missing),
а не уходит в синтез без ударений. Кэш в git: изменения ударений видны в diff.

Из RUAccent берутся только «+» и «ё»: он теряет тире и сдваивает пробелы, поэтому разметка
переносится на исходный текст слово в слово; несовпадение слов — ошибка, не тихая порча.
Поверх работает наш словарь (имена, исключения) — он применяется последним.
"""
import argparse
import json
import re
from pathlib import Path

from voru.config import REPO_ROOT

ACCENTS_PATH = REPO_ROOT / "corpus" / "accents.jsonl"
OMOGRAPH_MODEL = "turbo3.1"
_WORD = re.compile(r"[А-Яа-яЁё]+")
_MARKED_WORD = re.compile(r"[А-Яа-яЁё+]+")


class AccentMissing(KeyError):
    """Текста нет в кэше ударений — запустите python -m voru.normalize.accent warm."""


class AccentAlignmentError(ValueError):
    pass


def _skeleton(word: str) -> str:
    return word.replace("+", "").lower().replace("ё", "е")


def _mark(original: str, accented: str) -> str:
    out, i = [], 0
    for ch in accented:
        if ch == "+":
            out.append("+")
            continue
        source = original[i]
        if ch.lower() == "ё" and source in "еЕ":
            source = "Ё" if source == "Е" else "ё"
        out.append(source)
        i += 1
    return "".join(out)


def transfer_accents(original: str, accented: str) -> str:
    words = list(_WORD.finditer(original))
    marked = _MARKED_WORD.findall(accented)
    if [_skeleton(w.group()) for w in words] != [_skeleton(m) for m in marked]:
        raise AccentAlignmentError(f"RUAccent изменил слова: {original[:60]!r} → {accented[:60]!r}")
    out, last = [], 0
    for word, mark in zip(words, marked):
        out.append(original[last:word.start()])
        out.append(_mark(word.group(), mark))
        last = word.end()
    out.append(original[last:])
    return "".join(out)


class Accentuator:
    def __init__(self, path=ACCENTS_PATH, engine=None):
        self.path = Path(path)
        self.engine = engine
        self.cache = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self.cache[entry["text"]] = entry["accented"]

    def __call__(self, text: str) -> str:
        if text not in self.cache:
            if self.engine is None:
                raise AccentMissing(text)
            self.cache[text] = transfer_accents(text, self.engine(text))
        return self.cache[text]

    def save(self):
        lines = [json.dumps({"text": t, "accented": a}, ensure_ascii=False) for t, a in sorted(self.cache.items())]
        self.path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def ruaccent_engine():
    """Настоящий RUAccent (только Windows-окружение: transformers<5, onnxruntime)."""
    from ruaccent import RUAccent

    model = RUAccent()
    model.load(omograph_model_size=OMOGRAPH_MODEL, use_dictionary=True, tiny_mode=False)
    return model.process_all


class _Collect:
    def __init__(self):
        self.texts = set()

    def __call__(self, text):
        self.texts.add(text)
        return text


def warm(corpus_paths) -> tuple:
    """Расставляет ударения для всех текстов корпусов и дописывает их в кэш."""
    from voru.normalize.prepare import load_overrides, prepare_text
    from voru.pipeline import read_corpora

    collect, overrides = _Collect(), load_overrides()
    for record in read_corpora(corpus_paths):
        prepare_text(record.text_key, record.raw_text, overrides, accentuator=collect)
    accentuator = Accentuator(engine=ruaccent_engine())
    new = sorted(collect.texts - set(accentuator.cache))
    for text in new:
        accentuator(text)
    accentuator.save()
    return len(collect.texts), len(new)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("warm")
    w.add_argument("--corpus", type=Path, action="append")
    args = parser.parse_args(argv)

    from voru.pipeline import PILOT_CORPUS, SMOKE_CORPUS

    total, new = warm(args.corpus or [PILOT_CORPUS, SMOKE_CORPUS])
    print(f"текстов {total}, новых ударений {new} → {ACCENTS_PATH}")


if __name__ == "__main__":
    main()
