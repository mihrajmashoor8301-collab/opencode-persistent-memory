#!/usr/bin/env bash
set -euo pipefail
CFG_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
STATE="$CFG_ROOT/persistent-memory.json"
if [[ ! -f "$STATE" ]]; then echo "No persistent-memory install state found at $STATE."; exit 0; fi

# The installer writes simple one-line JSON string fields; read them without
# invoking an interpreter or loading any project dependencies.
json_value() { sed -n "s/.*\"$1\": \"\([^\"]*\)\".*/\1/p" "$STATE" | head -n1; }
VALUES=("$(json_value projectRoot)" "$(json_value memoryHome)" "$(json_value plugin)" "$(json_value tool)" "$(json_value agentsExample)")
PROJECT_DIR="${VALUES[0]}"
MEMORY_HOME="${VALUES[1]}"
PLUGIN="${VALUES[2]:-$CFG_ROOT/plugins/memory-plugin.ts}"
TOOL="${VALUES[3]:-$CFG_ROOT/tools/memory.ts}"
AGENTS_EXAMPLE="${VALUES[4]:-$CFG_ROOT/AGENTS.memory.example.md}"

# Remove integration files only when they still match this project's source.
for pair in "$PLUGIN:$PROJECT_DIR/opencode/plugins/memory-plugin.ts" "$TOOL:$PROJECT_DIR/opencode/tools/memory.ts"; do
  dest="${pair%%:*}"; src="${pair#*:}"
  if [[ -f "$dest" && -f "$src" ]] && cmp -s "$dest" "$src"; then rm -- "$dest"; fi
done
rm -f -- "$STATE"
if [[ -f "$AGENTS_EXAMPLE" && -f "$PROJECT_DIR/config/AGENTS.example.md" ]] && cmp -s "$AGENTS_EXAMPLE" "$PROJECT_DIR/config/AGENTS.example.md"; then rm -- "$AGENTS_EXAMPLE"; fi

echo "OpenCode integration removed where files were unchanged. Memory data remains at: $MEMORY_HOME"
if [[ "${1:-}" == "--remove-data" ]]; then
  marker="$MEMORY_HOME/.opencode-persistent-memory-owned"
  if [[ ! -f "$marker" ]]; then echo "Refusing data removal: no ownership marker exists (the directory may predate installation)." >&2; exit 1; fi
  [[ "$MEMORY_HOME" != "$HOME" && "$MEMORY_HOME" != / && "$MEMORY_HOME" != "$HOME/.config" ]] || { echo "Refusing unsafe memory path: $MEMORY_HOME" >&2; exit 1; }
  read -r -p "Permanently remove project-generated memory data at '$MEMORY_HOME'? [type REMOVE to confirm] " answer
  [[ "$answer" == REMOVE ]] || { echo "Data removal cancelled."; exit 1; }
  rm -rf -- "$MEMORY_HOME"
  echo "Project-generated memory data removed."
else
  echo "To remove project-generated data as well, rerun: ./uninstall.sh --remove-data"
fi
