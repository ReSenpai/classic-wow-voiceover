#!/usr/bin/env bash
# Скорость загрузки модели в кэш HF: bash scripts/wsl/hf_cache_speed.sh Qwen--Qwen3-TTS-12Hz-1.7B-Base
DIR="$HOME/.cache/huggingface/hub/models--${1:?имя модели в формате Org--Repo}"
a=$(du -sb "$DIR" | cut -f1); sleep "${2:-20}"; b=$(du -sb "$DIR" | cut -f1)
echo "скачано $((b / 1048576)) МБ, скорость $(( (b - a) / ${2:-20} / 1024 )) КБ/с"
