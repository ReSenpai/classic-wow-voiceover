"""CLI конвертера: python -m voru.catquest <inspect|match|build|verify> …"""
import importlib
import sys

COMMANDS = {"inspect": "voru.catquest.inspect"}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in COMMANDS:
        print(f"использование: python -m voru.catquest {{{'|'.join(COMMANDS)}}} …", file=sys.stderr)
        sys.exit(2)
    importlib.import_module(COMMANDS[argv[0]]).main(argv[1:])


if __name__ == "__main__":
    main()
