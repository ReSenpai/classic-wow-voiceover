#!/usr/bin/env bash
# Окружение для одной TTS-модели в WSL2 (одна модель = одно окружение: у пакетов разные
# требования к transformers/torch). Запуск из Windows:
#   wsl -d Ubuntu -- bash /mnt/c/<путь к репо>/scripts/wsl/setup_env.sh qwen
#   wsl -d Ubuntu -- bash /mnt/c/<путь к репо>/scripts/wsl/setup_env.sh f5
# Перед первым запуском: sudo apt-get install -y build-essential sox ffmpeg
# Окружения: ~/voru-envs/<имя>. Код voru подключается из репозитория (editable не нужен:
# скрипты запускаются из корня репо).
set -euo pipefail

NAME="${1:?укажите окружение: qwen | f5 | seedvc}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh

ENV="$HOME/voru-envs/$NAME"
mkdir -p "$HOME/voru-envs"
# Seed-VC (GPL-3.0, архив) закреплён на torch 2.4 — колёс под Python 3.12+ нет.
PYVER=3.12; [ "$NAME" = seedvc ] && PYVER=3.10
[ -d "$ENV" ] || uv venv -q --python "$PYVER" "$ENV"
export VIRTUAL_ENV="$ENV"

# Общие зависимости конвейера voru (без pytest).
uv pip install -q PyYAML pymorphy3 imageio-ffmpeg mutagen huggingface_hub

case "$NAME" in
  qwen) uv pip install -q qwen-tts ;;
  f5)   uv pip install -q f5-tts ;;
  seedvc)
    # Преобразование голоса (запись человека → тембр нашего референса). Код — снимок репозитория,
    # зависимости из его requirements.txt без GUI/реального времени (gradio, sounddevice, FreeSimpleGUI).
    SRC="$HOME/voru-envs/seedvc-src"; SEEDVC_COMMIT=51383efd921027683c89e5348211d93ff12ac2a8
    [ -d "$SRC" ] || git clone -q https://github.com/Plachtaa/seed-vc "$SRC"
    git -C "$SRC" checkout -q "$SEEDVC_COMMIT"
    uv pip install -q torch==2.4.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu121
    uv pip install -q scipy==1.13.1 librosa==0.10.2 "huggingface-hub>=0.28.1" munch==4.0.0 einops==0.8.0 \
      descript-audio-codec==1.0.0 pydub==0.25.1 transformers==4.46.3 soundfile==0.12.1 numpy==1.26.4 \
      hydra-core==1.3.2 python-dotenv accelerate resemblyzer modelscope==1.18.1 funasr==1.1.5 jiwer==3.0.3 ;;
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
