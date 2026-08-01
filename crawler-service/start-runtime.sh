#!/bin/zsh
set -eu

feimi_root="${FEIMI_DATA_DIR:-$HOME/Library/Application Support/Feimi}"
secrets_file="$feimi_root/secrets.env"
if [[ -r "$secrets_file" ]]; then
  while IFS='=' read -r key value; do
    case "$key" in
      FLYAI_API_KEY|DASHSCOPE_API_KEY) export "$key=$value" ;;
    esac
  done < "$secrets_file"
fi

exec "$feimi_root/crawler/.venv/bin/uvicorn" \
  main:app --host 127.0.0.1 --port 8001
