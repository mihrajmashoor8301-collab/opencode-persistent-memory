# Installation

## Prerequisites

Install OpenCode 1.18.34 or later, Python 3.10+, and Ollama. Ensure Ollama is running and pull the selected embedding model (default `nomic-embed-text`). A local chat model for extraction is recommended; the default is `gemma4:12b`. The installer never installs or changes your coding model.

## Install

```bash
git clone <your-repository-url>
cd opencode-persistent-memory
./install.sh
```

Set environment variables before installing to choose a custom data directory or models:

```bash
OPENCODE_MEMORY_HOME="$HOME/.local/share/opencode-memory" \
OPENCODE_MEMORY_EXTRACTION_MODEL="your-local-chat-model" \
./install.sh
```

The installer creates a checkout-local `.venv`, installs pinned requirements there, writes the generated `persistent-memory.json`, and copies the plugin/tool to OpenCode’s config directory. It refuses to overwrite differing plugin/tool files and leaves `opencode.jsonc` and `AGENTS.md` intact. The example guidance is installed as `AGENTS.memory.example.md`.

Restart OpenCode after installation. The OpenCode integration config is at `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/persistent-memory.json`.

## Manual tools

The installed custom tools provide `memory_search`, `memory_store`, `memory_update`, `memory_forget`, `memory_list`, and `memory_stats`. They remain available for explicit actions. Automatic persistence happens at session idle through the plugin’s local extraction flow.

## Uninstall

```bash
./uninstall.sh
```

This removes unchanged integration files and installation state. It leaves memory data in place. To request deletion of data created by the installer, use `./uninstall.sh --remove-data`; deletion requires an ownership marker and typing `REMOVE`. An existing memory directory is never claimed by the installer.
