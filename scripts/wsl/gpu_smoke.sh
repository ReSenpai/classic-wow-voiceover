#!/usr/bin/env bash
# GPU smoke-тест моделей в окружении WSL: bash scripts/wsl/gpu_smoke.sh qwen|f5
# Результаты: лог в консоли (RTF, VRAM, ревизии), WAV — в work/gpu_smoke/.
set -euo pipefail
NAME="${1:?укажите окружение: qwen | f5}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
ENV="$HOME/voru-envs/$NAME"
export PATH="$HOME/.local/bin:$PATH" VIRTUAL_ENV="$ENV"
# Загрузчик HF xet зависал на крупных файлах без докачки (11.10.2026) — обычный HTTP надёжнее.
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
"$ENV/bin/python" -c "import pytest" 2>/dev/null || uv pip install -q pytest
cd "$REPO"
mkdir -p work/gpu_smoke
"$ENV/bin/python" -m pytest -m gpu tests/providers/test_gpu_smoke.py -s -p no:cacheprovider -q 2>&1 \
  | tee "work/gpu_smoke/$NAME.log"
