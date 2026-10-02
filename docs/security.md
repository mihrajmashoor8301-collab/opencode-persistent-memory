# Security and privacy

## Local processing

The plugin calls the configured Ollama endpoint for embeddings and extraction. The default endpoint is localhost. The project contains no cloud memory API, remote database, or telemetry integration. If you point Ollama at a non-local endpoint, the local-only property no longer applies.

## Stored content

The extractor is asked to retain concise durable project facts, decisions, fixes, workflows, progress, and explicit long-term preferences. It is instructed to avoid secrets, temporary output, and irrelevant conversation. Common password/key/token assignments, authorization/cookie headers, URL credentials, and PEM private-key blocks are redacted by the backend before insertion. This pattern-based redaction can miss secrets and can redact benign text; do not treat it as a complete data-loss prevention system.

## Isolation

Project memories carry a project directory. Retrieval and manual update/delete operations use the active project path. Global scope is intended only for explicit user-level preferences. A local database is accessible to processes and users that can read its files; filesystem permissions and host security still matter.

## Database and backups

The SQLite database, Chroma index, logs, and backups live under the configured memory home, outside this source repository by default. Backups contain the same sensitive information as the database. Protect and encrypt them according to your needs. Never commit database, index, log, or backup files; the repository ignore rules exclude common runtime formats.

## Threat model and limitations

This integration reduces accidental persistence of common credentials and limits context injection, but does not protect against a compromised host, malicious local process/model, prompt injection inside stored notes, undiscovered secret formats, or filesystem/backup exposure. Injected memories are marked as untrusted reference data, but models may still mishandle them. Review memories periodically and use the forget tool when needed. OpenCode, Ollama, and their dependencies have their own security properties and licenses.
