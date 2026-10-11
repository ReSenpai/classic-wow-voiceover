#!/usr/bin/env bash
# Окружение для одной TTS-модели в WSL2 (одна модель = одно окружение: у пакетов разные
# требования к transformers/torch). Запуск из Windows:
#   wsl -d Ubuntu -- bash /mnt/c/<путь к репо>/scripts/wsl/setup_env.sh qwen
#   wsl -d Ubuntu -- bash /mnt/c/<путь к репо>/scripts/wsl/setup_env.sh f5
# Окружения: ~/voru-envs/<имя>. Код voru подключается из репозитория (editable не нужен:
# скрипты запускаются из корня репо).
set -euo pipefail

NAME="${1:?укажите окружение: qwen | f5}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh

ENV="$HOME/voru-envs/$NAME"
mkdir -p "$HOME/voru-envs"
[ -d "$ENV" ] || uv venv -q --python 3.12 "$ENV"
export VIRTUAL_ENV="$ENV"

# Общие зависимости конвейера voru (без pytest).
uv pip install -q PyYAML pymorphy3 imageio-ffmpeg mutagen huggingface_hub

case "$NAME" in
  qwen) uv pip install -q qwen-tts ;;
  f5)   uv pip install -q f5-tts ;;
  *) echo "неизвестное окружение: $NAME" >&2; exit 1 ;;
esac

"$ENV/bin/python" - <<'PY'
import torch, transformers
print("torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available(),
      "| transformers", transformers.__version__)
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0), round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1), "GiB")
PY
echo "ok: $ENV (repo: $REPO)"
