# Troubleshooting

## Ollama unavailable

Check that Ollama is running and that `${OPENCODE_MEMORY_OLLAMA_URL:-http://localhost:11434}/api/tags` responds. Memory failures should not stop ordinary OpenCode work. Keyword search remains independent of embeddings when SQLite is available.

## Embedding model unavailable

Pull the configured model with `ollama pull nomic-embed-text`, or set `OPENCODE_MEMORY_EMBEDDING_MODEL` and reinstall/update the generated config. SQLite rows remain authoritative; vector search falls back to keyword search.

## Chroma failure

Check the `embeddings/` directory under the configured memory home. Rebuild the vector index from SQLite with `.venv/bin/python memory/memory_cli.py rebuild-index`. Back up the database before restore/rebuild operations.

## Plugin not loading

Restart OpenCode after install. Confirm `plugins/memory-plugin.ts`, `tools/memory.ts`, and `persistent-memory.json` exist under the OpenCode config directory. Check OpenCode logs and `$OPENCODE_MEMORY_HOME/logs/memory_plugin.log`. Verify your OpenCode release still supports the hooks used by this project (`chat.message`, `experimental.chat.system.transform`, and `session.idle`).

## Python dependency problems

Use the checkout’s `.venv/bin/python` and `.venv/bin/python -m pip`; do not install into the system Python. Rerun `./install.sh` to create/update the isolated environment.

## Memory not retrieved or saved

Retrieval is relevance-gated and project-scoped. Verify the current OpenCode directory matches the memory’s `project` metadata. Automatic writing occurs at session idle, uses the configured local extractor, and only stores filtered durable candidates. Check that the extraction model is available with `ollama list`; inspect only metadata from plugin logs and avoid sharing personal log contents.
