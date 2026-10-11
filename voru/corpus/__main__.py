"""Выгрузка корпуса из локальной MySQL: python -m voru.corpus --revision vmangos-db-4641790 --out corpus/local/quests.jsonl"""
import argparse
from pathlib import Path

from voru.config import load_client_profile
from voru.corpus.legacy_mysql import connect, fetch_quest_records
from voru.corpus.record import write_jsonl


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="версия дампа, например vmangos-db-4641790")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    with connect() as connection:
        records = fetch_quest_records(connection, load_client_profile(), args.revision)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(records, args.out)
    missing = sum(r.locale_status == "missing_locale" for r in records)
    print(f"{len(records)} записей → {args.out} (missing_locale: {missing})")


if __name__ == "__main__":
    main()
