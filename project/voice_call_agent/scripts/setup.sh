#!/usr/bin/env bash
set -euo pipefail
VOICE_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$VOICE_PROJECT_DIR"
if ! command -v brew >/dev/null; then
  echo "Instala Homebrew desde https://brew.sh y vuelve a ejecutar este script." >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Ejecuta este prototipo en Apple Silicon, sin Rosetta." >&2
  exit 1
fi
brew bundle --file "$VOICE_PROJECT_DIR/Brewfile"
uv sync --frozen --extra dev --link-mode copy --python "$(brew --prefix python@3.12)/bin/python3.12"
brew services start ollama
VOICE_START_ATTEMPTS=0
until curl --silent --fail --max-time 2 http://127.0.0.1:11434/api/version >/dev/null; do
  VOICE_START_ATTEMPTS=$((VOICE_START_ATTEMPTS + 1))
  if [[ "$VOICE_START_ATTEMPTS" -ge 20 ]]; then
    echo "Ollama no responde. Revisa: brew services info ollama" >&2
    exit 1
  fi
  sleep .5
done
ollama pull qwen3:1.7b-q4_K_M
uv run --frozen voice-call prepare
uv run --frozen voice-call doctor
echo 'Listo. Conecta auriculares y ejecuta: uv run --frozen voice-call chat'
