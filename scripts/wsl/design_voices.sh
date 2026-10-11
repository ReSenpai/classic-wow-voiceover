#!/usr/bin/env bash
# Кандидаты голосов через Qwen3-TTS VoiceDesign в окружении WSL и страница для прослушивания.
#   bash scripts/wsl/design_voices.sh 4 dryad-female narrator     # 4 новых варианта для голосов
#   bash scripts/wsl/design_voices.sh 3 --all
# Результат: work/voice_design/index.html (новые варианты дописываются к старым).
set -euo pipefail
COUNT="${1:?число вариантов}"; shift
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$HOME/voru-envs/qwen/bin/python"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
cd "$REPO"
if [ "${1:-}" = "--all" ]; then
  ARGS=(--all)
else
  ARGS=(); for voice in "$@"; do ARGS+=(--voice "$voice"); done
fi
"$PY" -m voru.casting.design generate "${ARGS[@]}" --count "$COUNT" >> work/voice_design.log 2>&1
"$PY" -c 'from voru.casting.design import candidates_page; print(candidates_page("work"))'
