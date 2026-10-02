#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OS="$(uname -s)"
[[ "$OS" == Linux ]] || { echo "Supported platform: Linux. Detected: $OS" >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3 is required." >&2; exit 1; }
command -v opencode >/dev/null || { echo "OpenCode is required; install it before this project." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required for the Ollama health check." >&2; exit 1; }
command -v ollama >/dev/null || echo "Warning: ollama CLI not found; Ollama may be installed separately."

PYTHON_BOOTSTRAP="$(command -v python3)"
PYVER="$($PYTHON_BOOTSTRAP -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
$PYTHON_BOOTSTRAP -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' || { echo "Python 3.10 or later is required (found $PYVER)." >&2; exit 1; }
OPENCODE_VERSION="$(opencode --version 2>/dev/null | head -n1 || true)"
if [[ -z "$OPENCODE_VERSION" ]]; then
  echo "Could not determine OpenCode version." >&2
  exit 1
fi
VERSION_NUMBER="$(printf '%s' "$OPENCODE_VERSION" | grep -oE '[0-9]+([.][0-9]+)+' | head -n1 || true)"
if [[ -z "$VERSION_NUMBER" ]] || [[ "$(printf '%s\n%s\n' 1.18.34 "$VERSION_NUMBER" | sort -V | head -n1)" != "1.18.34" ]]; then
  echo "OpenCode 1.18.34 or later is required; detected '$OPENCODE_VERSION'." >&2
  exit 1
fi
echo "OpenCode: $OPENCODE_VERSION; supported plugin hooks are used."

MEMORY_HOME="${OPENCODE_MEMORY_HOME:-$HOME/ai-memory}"
EMBED_MODEL="${OPENCODE_MEMORY_EMBEDDING_MODEL:-nomic-embed-text}"
EXTRACT_MODEL="${OPENCODE_MEMORY_EXTRACTION_MODEL:-gemma4:12b}"
OLLAMA_URL="${OPENCODE_MEMORY_OLLAMA_URL:-${OLLAMA_HOST:-http://localhost:11434}}"
VENV="$PROJECT_DIR/.venv"
CFG_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
PLUGIN_DEST="$CFG_ROOT/plugins/memory-plugin.ts"
TOOLS_DEST="$CFG_ROOT/tools/memory.ts"
STATE_DEST="$CFG_ROOT/persistent-memory.json"

if [[ -f "$MEMORY_HOME/database/ai_memory.db" ]]; then
  echo "A database already exists at $MEMORY_HOME/database/ai_memory.db."
  echo "It will not be modified or claimed by this installer. Set OPENCODE_MEMORY_HOME to a fresh directory or explicitly choose to use this existing store."
  read -r -p "Use this existing memory directory without claiming its data? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || exit 1
fi

for pair in "$PLUGIN_DEST:$PROJECT_DIR/opencode/plugins/memory-plugin.ts" "$TOOLS_DEST:$PROJECT_DIR/opencode/tools/memory.ts"; do
  dest="${pair%%:*}"; src="${pair#*:}"
  if [[ -e "$dest" ]] && ! cmp -s "$src" "$dest"; then
    echo "Refusing to overwrite existing OpenCode file: $dest" >&2
    echo "Move it or merge it yourself, then rerun installation." >&2
    exit 1
  fi
done
if [[ -e "$STATE_DEST" ]]; then
  for expected in \
    '"projectRoot": "'"$PROJECT_DIR"'"' \
    '"python": "'"$VENV/bin/python"'"' \
    '"cli": "'"$PROJECT_DIR/memory/memory_cli.py"'"' \
    '"memoryHome": "'"$MEMORY_HOME"'"' \
    '"ollamaUrl": "'"$OLLAMA_URL"'"' \
    '"embeddingModel": "'"$EMBED_MODEL"'"' \
    '"extractionModel": "'"$EXTRACT_MODEL"'"'; do
    grep -Fq "$expected" "$STATE_DEST" || { echo "Refusing to overwrite differing config: $STATE_DEST" >&2; exit 1; }
  done
fi

HOME_PREEXISTED=0
[[ -e "$MEMORY_HOME" ]] && HOME_PREEXISTED=1
mkdir -m 700 -p "$MEMORY_HOME" "$MEMORY_HOME/database" "$MEMORY_HOME/embeddings" "$MEMORY_HOME/logs" "$MEMORY_HOME/backups" "$CFG_ROOT/plugins" "$CFG_ROOT/tools"
if [[ "$HOME_PREEXISTED" == 0 ]]; then
  : > "$MEMORY_HOME/.opencode-persistent-memory-owned"
  chmod 600 "$MEMORY_HOME/.opencode-persistent-memory-owned"
  chmod 700 "$MEMORY_HOME" "$MEMORY_HOME/database" "$MEMORY_HOME/embeddings" "$MEMORY_HOME/logs" "$MEMORY_HOME/backups"
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON_BOOTSTRAP" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -r "$PROJECT_DIR/memory/requirements.txt"

if curl -fsS --max-time 2 "${OLLAMA_URL%/}/api/tags" >/dev/null 2>&1; then
  if ! curl -fsS --max-time 5 "${OLLAMA_URL%/}/api/tags" | grep -Fq '"name":"'"$EMBED_MODEL"; then
    if command -v ollama >/dev/null && [[ "$OLLAMA_URL" == http://localhost:* || "$OLLAMA_URL" == http://127.0.0.1:* ]]; then
      read -r -p "Embedding model '$EMBED_MODEL' is missing. Pull it now? [y/N] " answer
      if [[ "$answer" =~ ^[Yy]$ ]]; then ollama pull "$EMBED_MODEL"; fi
    else
      echo "Embedding model '$EMBED_MODEL' is missing. Pull it with: ollama pull '$EMBED_MODEL'"
    fi
  fi
  if ! curl -fsS --max-time 5 "${OLLAMA_URL%/}/api/tags" | grep -Fq '"name":"'"$EXTRACT_MODEL"; then
    echo "Optional extraction model '$EXTRACT_MODEL' is not currently listed. Install it with: ollama pull '$EXTRACT_MODEL'"
  fi
else
  echo "Warning: Ollama is not reachable at $OLLAMA_URL. OpenCode will continue normally; memory operations will use fallback behavior where possible."
fi

install -m 600 "$PROJECT_DIR/opencode/plugins/memory-plugin.ts" "$PLUGIN_DEST"
install -m 600 "$PROJECT_DIR/opencode/tools/memory.ts" "$TOOLS_DEST"
if [[ ! -e "$CFG_ROOT/AGENTS.memory.example.md" ]]; then
  install -m 600 "$PROJECT_DIR/config/AGENTS.example.md" "$CFG_ROOT/AGENTS.memory.example.md"
fi
cat > "$STATE_DEST" <<EOF
{
  "projectRoot": "$PROJECT_DIR",
  "python": "$VENV/bin/python",
  "cli": "$PROJECT_DIR/memory/memory_cli.py",
  "memoryHome": "$MEMORY_HOME",
  "ollamaUrl": "$OLLAMA_URL",
  "embeddingModel": "$EMBED_MODEL",
  "extractionModel": "$EXTRACT_MODEL"
}
EOF
chmod 600 "$STATE_DEST"

export OPENCODE_MEMORY_HOME="$MEMORY_HOME" OPENCODE_MEMORY_OLLAMA_URL="$OLLAMA_URL" OPENCODE_MEMORY_EMBEDDING_MODEL="$EMBED_MODEL"
"$VENV/bin/python" -m unittest discover -s "$PROJECT_DIR/memory/tests" -v
"$VENV/bin/python" "$PROJECT_DIR/memory/memory_cli.py" stats

echo
echo "Installation complete. Restart OpenCode to load the plugin and manual tools."
echo "Memory home: $MEMORY_HOME"
echo "Extraction model: $EXTRACT_MODEL (optional; set OPENCODE_MEMORY_EXTRACTION_MODEL to change it)"
echo "Your opencode.jsonc and primary coding model were not modified."
