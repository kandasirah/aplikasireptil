#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Virtual environment .venv tidak ditemukan. Buat dulu:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

export PYTHONPATH=src

exec .venv/bin/uvicorn reptil.main:app --reload --app-dir src "$@"
