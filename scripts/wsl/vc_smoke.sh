#!/usr/bin/env bash
# Пробное преобразование голоса Seed-VC: записи человека → тембр референса.
#   bash scripts/wsl/vc_smoke.sh satyr-male [diffusion_steps] [cfg_rate] [seed кандидата]
# Вход: work/recordings/<голос>/*.wav. Цель: config/voice_refs/<голос>.wav или, если указан seed,
# кандидат work/voice_design/<голос>/seed-<seed>.wav (референс в voices.yaml не меняется).
# Результат: work/vc_smoke/<голос>/<цель>-steps<N>-cfg<R>/*.wav, лог — там же.
set -euo pipefail
VOICE="${1:?голос, например satyr-male}"; STEPS="${2:-30}"; CFG="${3:-0.7}"; SEED="${4:-}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$HOME/voru-envs/seedvc-src"; PY="$HOME/voru-envs/seedvc/bin/python"
if [ -n "$SEED" ]; then
  TARGET="$REPO/work/voice_design/$VOICE/seed-$SEED.wav"; LABEL="seed$SEED"
else
  TARGET="$REPO/config/voice_refs/$VOICE.wav"; LABEL="ref"
fi
[ -f "$TARGET" ] || { echo "нет целевого файла: $TARGET" >&2; exit 1; }
OUT="$REPO/work/vc_smoke/$VOICE/$LABEL-steps$STEPS-cfg$CFG"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
mkdir -p "$OUT"
cp "$TARGET" "$OUT/target.wav"
cd "$SRC"
for f in "$REPO/work/recordings/$VOICE"/*.wav; do
  start=$(date +%s)
  "$PY" inference.py --source "$f" --target "$TARGET" --output "$OUT" \
    --diffusion-steps "$STEPS" --length-adjust 1.0 --inference-cfg-rate "$CFG" \
    --f0-condition False --auto-f0-adjust False --semi-tone-shift 0 --fp16 True >> "$OUT/run.log" 2>&1
  echo "$(basename "$f"): $(( $(date +%s) - start )) с" | tee -a "$OUT/run.log"
done
