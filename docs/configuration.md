# Configuration

The installer writes generated local paths to `persistent-memory.json` inside the OpenCode config directory. Do not commit that file. It includes:

- `projectRoot`, `python`, and `cli`: checkout and virtual environment paths.
- `memoryHome`: database and runtime data root.
- `ollamaUrl`, `embeddingModel`, and `extractionModel`.

Environment variables override defaults before installation and are forwarded to backend child processes:

- `OPENCODE_MEMORY_HOME`: default `$HOME/ai-memory`.
- `OPENCODE_MEMORY_OLLAMA_URL`: default `http://localhost:11434` (`OLLAMA_HOST` is a fallback).
- `OPENCODE_MEMORY_EMBEDDING_MODEL`: default `nomic-embed-text`.
- `OPENCODE_MEMORY_EXTRACTION_MODEL`: default `gemma4:12b`.

The backend currently limits active SQLite plus Chroma storage to 100 GB and each content/metadata field to 64 KiB. Plugin retrieval currently uses at most 4 memories, approximately 4,200 characters, and a bounded recent message window. Project isolation uses the current OpenCode working directory; only explicitly global records can cross projects.

Backups are written under `$OPENCODE_MEMORY_HOME/backups`. Restore and index rebuild are available through the backend CLI:

```bash
.venv/bin/python memory/memory_cli.py backup
.venv/bin/python memory/memory_cli.py restore --backup-file /path/to/backup.db
.venv/bin/python memory/memory_cli.py rebuild-index
```

The CLI uses the environment-selected memory home. Always verify the selected path before restore.
