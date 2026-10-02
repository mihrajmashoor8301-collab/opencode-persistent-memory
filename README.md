# OpenCode Persistent Memory

An independent community project that adds local long-term memory to OpenCode. It combines an OpenCode plugin with SQLite, ChromaDB, and local Ollama models. It is not an official OpenCode project and does not modify your coding model or provider configuration.

## Features

- Retrieves a small set of relevant project memories before selected model requests.
- Extracts durable decisions and project state after meaningful completed tasks using a local Ollama model.
- Uses SQLite as the source of truth and ChromaDB for semantic retrieval.
- Falls back to SQLite keyword search when embeddings or the vector index fail.
- Keeps project memories scoped to their project, with explicit global/user-level scope supported.
- Redacts common secret formats before storage.
- Includes six manual tools: `memory_search`, `memory_store`, `memory_update`, `memory_forget`, `memory_list`, and `memory_stats`.
- Supports SQLite backup/restore and rebuilding Chroma from SQLite.
- Fails open: memory failures should not stop ordinary OpenCode work.
- Defaults to 100 GB active storage and 64 KiB per memory record limits.
- Runs locally; it has no cloud memory service.

## Architecture

```text
OpenCode request ──> plugin retrieval ──> small project-scoped context ──> coding model
       session idle ──> local extractor ──> SQLite (authoritative) ──> ChromaDB (rebuildable)
```

See [architecture](docs/architecture.md) and [security](docs/security.md).

## Requirements

- Linux (the installer currently supports Linux; other operating systems are untested).
- Python 3.10 or later.
- OpenCode 1.18.34 or later with the plugin hooks used here. Later versions should be checked for API compatibility.
- Ollama reachable on localhost or a configured URL.
- Embedding model `nomic-embed-text` by default.
- Recommended extraction model `gemma4:12b` by default. You may configure another local Ollama chat model.
- A coding model of your choice. The memory integration does not set or change it.

Python packages are pinned in `memory/requirements.txt` and are installed in this checkout’s virtual environment.

## Installation

```bash
git clone <your-repository-url>
cd opencode-persistent-memory
./install.sh
```

The installer creates or uses the selected memory home, checks dependencies, installs the plugin and manual tools, runs isolated backend tests, and performs a health check. It does not overwrite `opencode.jsonc`, existing `AGENTS.md`, or an existing plugin/tool with different contents. Restart OpenCode after installation.

For detailed steps and configuration, see [installation](docs/installation.md) and [configuration](docs/configuration.md).

## Usage

Start OpenCode normally in a project directory. For requests likely to need project history (for example, continuing prior work or asking about an earlier decision), the plugin searches the current project and injects only a bounded set of relevant notes in `<persistent-memory>` context. Simple trivial requests are skipped.

At session idle, the plugin uses the configured local extraction model to identify durable facts from a bounded recent exchange. It checks for near-duplicates before storing. Extraction is a separate local request and does not depend on the coding model emitting a memory tool call.

Manual tools remain available when you explicitly want to search, save, update, forget, list, or inspect statistics. See [installation](docs/installation.md#manual-tools).

## Configuration

Defaults and environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENCODE_MEMORY_HOME` | `$HOME/ai-memory` | SQLite, Chroma, logs, and backups |
| `OPENCODE_MEMORY_OLLAMA_URL` | `http://localhost:11434` | Local Ollama endpoint |
| `OPENCODE_MEMORY_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `OPENCODE_MEMORY_EXTRACTION_MODEL` | `gemma4:12b` | Local extraction model |
| `OPENCODE_MEMORY_MAX_ACTIVE_BYTES` | 100,000,000,000 (documented target) | Active storage limit; current backend default is 100 GB |
| `OPENCODE_MEMORY_MAX_RECORD_BYTES` | 65,536 (documented target) | Per-record limit; current backend default is 64 KiB |

The installer writes private machine-specific paths to `persistent-memory.json` under your OpenCode config directory. See [configuration](docs/configuration.md) for current limits and customization details. The two limit variables are reserved documentation settings; adjust constants in the backend if you need different limits.

## Privacy

Personal database, vector index, logs, and backups remain under your configured memory home and are ignored by Git. Do not commit those files. Secret redaction is best-effort pattern filtering, not a guarantee that arbitrary sensitive data is detected. Read [security](docs/security.md).

## Development

Run tests without Ollama and without touching the default memory home:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r memory/requirements.txt
.venv/bin/python -m unittest discover -s memory/tests -v
```

The tests use temporary directories and deterministic fake embeddings. Live Ollama/OpenCode end-to-end tests require a separate test profile and are not part of the unit suite.

## Troubleshooting

See [troubleshooting](docs/troubleshooting.md) for Ollama, embeddings, Chroma, plugin loading, and Python dependency issues.

## License

MIT. OpenCode, Ollama, ChromaDB, and the included Python libraries retain their respective ownership and licenses. This is an independent community integration.
