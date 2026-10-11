import subprocess
import sys

HEAVY_MODULES = ("torch", "TTS", "pymysql", "pandas")


def test_import_voru_does_not_pull_heavy_dependencies():
    code = (
        "import sys, voru; "
        f"print([m for m in {HEAVY_MODULES!r} if m in sys.modules])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == "[]"


def test_voru_has_version():
    import voru

    assert voru.__version__
