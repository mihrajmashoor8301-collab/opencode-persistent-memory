# Architecture

```text
OpenCode user request
        │
        ├─ chat.message: relevance gate + project-scoped memory search
        │                    │
        │                    └─ at most 4 concise notes / about 4,200 characters
        ├─ experimental.chat.system.transform: separated context injection
        │                    └─ coding model of the user's choice
        │
        └─ session.idle: bounded session window + durable-memory policy
                             │
                             └─ local Ollama extraction model
                                      │
                                      ├─ duplicate/equivalence check
                                      └─ SQLite authoritative store
                                               └─ Chroma semantic index
```

## Retrieval

The plugin tracks a small amount of session working context in memory. It searches only when request text has historical/project relevance cues or is sufficiently substantial; trivial greetings and arithmetic are skipped. Searches include the OpenCode project directory and request context. Results are scoped by project (explicit global memories are eligible), and injection is bounded by count and characters. The injected block is labeled as untrusted historical reference data.

## Extraction and writing

On `session.idle`, the plugin reads a bounded recent message window through the OpenCode plugin client API. A local Ollama chat model returns a constrained JSON list of durable candidates. The plugin filters weak/secret-marked results, checks same-project memories for exact or close duplicates, and inserts or updates candidates through the existing CLI/backend. A manual `memory_store` call is not needed for automatic persistence. If extraction is unavailable, the coding session continues normally.

## Storage

SQLite is authoritative because it provides durable relational records, metadata, hashes, sessions, and backups. ChromaDB is a derived semantic index. Saved vectors in SQLite and the rebuild command allow Chroma to be recreated; keyword search remains available when embedding or vector operations fail.

## Manual tools

Six OpenCode tools expose explicit search, store, update, forget, list, and stats operations. Update and delete pass the current project path to backend ownership checks. Automatic retrieval/writing is an additional plugin layer.

## Isolation and failure behavior

Project records carry a project path. Retrieval and tool operations provide the active OpenCode directory. Global scope is accepted only for explicit user-wide preferences. Memory exceptions are caught at the plugin boundary; SQLite keyword fallback is used by the service where vector operations fail. This is best-effort software and does not guarantee every relevant memory is found or every durable fact is extracted.
