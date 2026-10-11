import subprocess
import sys

import pytest

HEAVY_MODULES = ("torch", "TTS", "pymysql", "pandas")


@pytest.mark.parametrize("module", ["voru", "voru.providers", "voru.normalize.prepare"])
def test_import_does_not_pull_heavy_dependencies(module):
    code = (
        f"import sys, {module}; "
        f"print([m for m in {HEAVY_MODULES!r} if m in sys.modules])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == "[]"


def test_voru_has_version():
    import voru

    assert voru.__version__
