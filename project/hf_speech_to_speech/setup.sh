#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
brew bundle --file=Brewfile
uv sync --frozen --extra dev --python "$(brew --prefix python@3.12)/bin/python3.12"
brew services start ollama
ollama pull qwen3:1.7b-q4_K_M
ollama create voice-call-es:1.7b -f Modelfile
.venv/bin/hf-voice doctor
.venv/bin/hf-voice prepare
echo 'Listo. Ejecuta .venv/bin/hf-voice chat'
