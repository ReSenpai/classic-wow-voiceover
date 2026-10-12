#!/usr/bin/env bash
# Синтез пилота настоящими моделями в WSL (без сборки пака):
#   bash scripts/wsl/pilot_synth.sh f5 f5-tts-ru-v4 f5-tts-ru-v2
#   bash scripts/wsl/pilot_synth.sh qwen qwen3-tts-base
# Очередь и мастера — ~/voru-work (диск WSL: SQLite на /mnt/c ненадёжен). Лог — work/pilot_<env>.log.
set -euo pipefail
ENV_NAME="${1:?окружение: qwen | f5}"; shift
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$HOME/voru-envs/$ENV_NAME/bin/python"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
cd "$REPO"
# Записи человека (стенд пишет в work/recordings репозитория) → рабочая папка запуска.
if [ -d work/recordings ]; then
  mkdir -p "$HOME/voru-work/recordings" && cp -r work/recordings/. "$HOME/voru-work/recordings/"
fi
for provider in "$@"; do
  echo "== $provider $(date -Is)" | tee -a "work/pilot_$ENV_NAME.log"
  "$PY" -m voru.pipeline --provider "$provider" --corpus corpus/pilot/teldrassil.jsonl \
    --work-dir "$HOME/voru-work" --no-pack 2>&1 | grep -E "синтез:|заблокировано|нет голоса|Error|Traceback" \
    | tee -a "work/pilot_$ENV_NAME.log"
  echo "== $provider done $(date -Is)" | tee -a "work/pilot_$ENV_NAME.log"
done
