#!/usr/bin/env python3
"""
AI Memory Service for OpenCode - Layered Memory Architecture
Portable local memory backend for OpenCode.
"""

import os
import json
import sqlite3
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from ollama import Client as OllamaClient
try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:  # SQLite keyword mode remains useful without the vector extra.
    chromadb = None
    embedding_functions = None

logger = logging.getLogger('AIMemoryService')
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())

MAX_ACTIVE_MEMORY_BYTES = 100 * 1000**3
MAX_MEMORY_CONTENT_BYTES = 64 * 1024

@dataclass
class Memory:
    """Data class representing a memory item"""
    id: Optional[int]
    type: str
    content: str
    metadata: Dict[str, Any]
    created_at: datetime
    session_id: Optional[str] = None

class AIMemoryService:
    """Core AI Memory Service with layered storage architecture"""

    def __init__(self, db_path: Optional[str] = None, *, memory_home: Optional[str] = None,
                 embeddings_path: Optional[str] = None, ollama_host: Optional[str] = None,
                 embedding_model: Optional[str] = None, ollama_client=None):
        self.memory_home = Path(memory_home or os.environ.get(
            'OPENCODE_MEMORY_HOME', str(Path.home() / 'ai-memory'))).expanduser()
        self.memory_home.mkdir(parents=True, exist_ok=True)
        self.db_path = str(Path(db_path).expanduser() if db_path else self.memory_home / 'database' / 'ai_memory.db')
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.embeddings_path = str(Path(embeddings_path).expanduser() if embeddings_path else self.memory_home / 'embeddings')
        self.backups_path = str(self.memory_home / 'backups')
        self.embedding_model = embedding_model or os.environ.get('OPENCODE_MEMORY_EMBEDDING_MODEL', 'nomic-embed-text')
        host = ollama_host or os.environ.get('OPENCODE_MEMORY_OLLAMA_URL') or os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
        self.ollama_client = ollama_client or OllamaClient(host=host)
        log_dir = self.memory_home / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = str(log_dir / 'memory_system.log')
        if not any(getattr(handler, 'baseFilename', None) == log_file for handler in logger.handlers):
            handler = logging.FileHandler(log_file)
            handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(handler)
        self.chroma_client = None
        self.collection = None
        self.embedding_function = None
        if chromadb is not None:
            try:
                self.chroma_client = chromadb.PersistentClient(path=self.embeddings_path)
                self.embedding_function = embedding_functions.DefaultEmbeddingFunction()
                self.collection = self.chroma_client.get_or_create_collection(
                    name="memories", embedding_function=self.embedding_function
                )
            except Exception as error:
                logger.warning("Chroma unavailable; using SQLite keyword fallback: %s", error)
        self._init_database()
        logger.info("AI Memory Service initialized")

    def _active_storage_bytes(self) -> int:
        """Return active SQLite + Chroma size, excluding backups and logs."""
        total = 0
        for path in (self.db_path, self.embeddings_path):
            if os.path.isfile(path):
                total += os.path.getsize(path)
            elif os.path.isdir(path):
                for current, _, filenames in os.walk(path):
                    for filename in filenames:
                        try:
                            total += os.path.getsize(os.path.join(current, filename))
                        except OSError:
                            continue
        return total

    def _init_database(self):
        """Initialize SQLite database with proper schema"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create or update memories table to ensure all columns exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    session_id TEXT,
                    category TEXT,
                    embedding_vector BLOB,
                    hash TEXT UNIQUE
                )
            ''')

            # Check and add missing columns to ensure backward compatibility
            try:
                cursor.execute('SELECT hash FROM memories LIMIT 1')
            except sqlite3.OperationalError:
                # If hash column doesn't exist, add it
                cursor.execute('ALTER TABLE memories ADD COLUMN hash TEXT')

            try:
                cursor.execute('SELECT embedding_vector FROM memories LIMIT 1')
            except sqlite3.OperationalError:
                # If embedding_vector column doesn't exist, add it
                cursor.execute('ALTER TABLE memories ADD COLUMN embedding_vector BLOB')

            # Create sessions table for tracking user sessions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMP,
                    description TEXT
                )
            ''')

            # Create categories table for memory organization
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.commit()
            conn.close()
            logger.info("Database schema initialized successfully")

        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

    def _redact_secrets(self, content: str) -> str:
        """Detect and redact potential secrets from content"""
        # Simple regex patterns for common secret types
        import re

        redacted = content
        patterns = [
            # Common assignments, including .env names such as API_KEY and AWS_SECRET_ACCESS_KEY.
            (r'\b[A-Za-z0-9_]*(?:password|passwd|pwd|api[_-]?key|secret|token|access[_-]?key|private[_-]?key)[A-Za-z0-9_]*\s*[:=]\s*[^\s,;]+', 'REDACTED'),
            # HTTP authorization and cookie headers.
            (r'\b(?:Authorization\s*:\s*)?(?:Bearer|Basic)\s+[A-Za-z0-9._~+/-]+=*', 'REDACTED'),
            (r'\b(?:Cookie|Set-Cookie)\s*:\s*[^\r\n]+', 'REDACTED'),
            # Credentials embedded in a URL.
            (r'(\b[a-z][a-z0-9+.-]*://[^:/\s@]+:)[^@\s/]+(@)', r'\1REDACTED\2'),
            # PEM encoded private keys.
            (r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----', 'REDACTED_PRIVATE_KEY'),
        ]
        for pattern, replacement in patterns:
            redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)
        return redacted

    def _generate_hash(self, content: str, metadata: Dict[str, Any]) -> str:
        """Generate unique hash for memory content to prevent duplicates"""
        data_str = f"{content}{json.dumps(metadata, sort_keys=True)}"
        return hashlib.md5(data_str.encode()).hexdigest()

    def store_memory(self, memory_type: str, content: str,
                    metadata: Optional[Dict[str, Any]] = None,
                    session_id: Optional[str] = None,
                    category: Optional[str] = None) -> Optional[int]:
        """
        Store a memory in the layered storage system
        Returns memory ID if successful, None otherwise
        """
        try:
            # Redact potential secrets
            redacted_content = self._redact_secrets(content)
            content_bytes = len(redacted_content.encode("utf-8"))
            if content_bytes > MAX_MEMORY_CONTENT_BYTES:
                logger.warning("Memory content exceeds the 64 KiB per-record limit; not storing")
                return None

            # Generate unique hash to prevent duplicates
            hash_value = self._generate_hash(redacted_content, metadata or {})
            metadata_str = json.dumps(metadata) if metadata else "{}"
            if len(metadata_str.encode("utf-8")) > MAX_MEMORY_CONTENT_BYTES:
                logger.warning("Memory metadata exceeds the 64 KiB per-record limit; not storing")
                return None

            # Initialize database connection
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Check for existing memory with same hash
            cursor.execute('SELECT id FROM memories WHERE hash = ?', (hash_value,))
            existing = cursor.fetchone()
            if existing:
                logger.info(f"Memory with hash {hash_value} already exists, skipping...")
                conn.close()
                return existing[0]

            estimated_growth = content_bytes * 2 + len(metadata_str.encode("utf-8")) + 32 * 1024
            if self._active_storage_bytes() + estimated_growth > MAX_ACTIVE_MEMORY_BYTES:
                logger.warning("Active memory storage would exceed the 100 GiB limit; not storing")
                conn.close()
                return None

            # Insert into SQLite database
            cursor.execute('''
                INSERT INTO memories (type, content, metadata, session_id, category, hash)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (memory_type, redacted_content, metadata_str, session_id, category, hash_value))

            memory_id = cursor.lastrowid

            # Create embedding using Ollama
            try:
                embedding_response = self.ollama_client.embeddings(
                    model=self.embedding_model,
                    prompt=redacted_content
                )
                embedding_vector = embedding_response['embedding']

                # Store embedding in ChromaDB
                self.collection.add(
                    ids=[str(memory_id)],
                    embeddings=[embedding_vector],
                    documents=[redacted_content]
                )

                # Update memory with embedding vector (stored as binary)
                cursor.execute('UPDATE memories SET embedding_vector = ? WHERE id = ?',
                              (json.dumps(embedding_vector), memory_id))
                conn.commit()

            except Exception as e:
                logger.warning(f"Failed to create embedding for memory {memory_id}: {e}")
                # Continue without embedding (fallback to metadata search)
                # SQLite is authoritative, so keep the row even when Ollama or
                # Chroma is unavailable.
                conn.commit()

            conn.close()
            logger.info(f"Memory stored with ID: {memory_id}")
            return memory_id

        except Exception as e:
            logger.error(f"Error storing memory: {e}")
            if 'conn' in locals():
                conn.close()
            return None

    def get_memory(self, memory_id: int) -> Optional[Memory]:
        """Retrieve a specific memory by ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, type, content, metadata, created_at, session_id
                FROM memories
                WHERE id = ?
            ''', (memory_id,))

            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            return Memory(
                id=row[0],
                type=row[1],
                content=row[2],
                metadata=json.loads(row[3]) if row[3] else {},
                created_at=datetime.fromisoformat(row[4]),
                session_id=row[5]
            )

        except Exception as e:
            logger.error(f"Error retrieving memory {memory_id}: {e}")
            return None

    def search_memory(self, query: str, limit: int = 10,
                     search_type: str = 'hybrid') -> List[Memory]:
        """
        Search memories using hybrid approach (vector + keyword)
        Returns list of Memory objects
        """
        try:
            if search_type == 'keyword':
                # Keyword fallback must not depend on Ollama or Chroma.
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                search_term = f"%{query}%"
                cursor.execute('''
                    SELECT id, type, content, metadata, created_at, session_id
                    FROM memories
                    WHERE content LIKE ? OR metadata LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (search_term, search_term, limit))

                rows = cursor.fetchall()
                conn.close()

                return [
                    Memory(
                        id=row[0],
                        type=row[1],
                        content=row[2],
                        metadata=json.loads(row[3]) if row[3] else {},
                        created_at=datetime.fromisoformat(row[4]),
                        session_id=row[5]
                    ) for row in rows
                ]

            # Vector and hybrid searches use local Ollama embeddings.
            query_embedding = self.ollama_client.embeddings(
                model=self.embedding_model,
                prompt=query
            )['embedding']

            if search_type == 'vector':
                results = self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=limit,
                    include=['documents', 'metadatas']
                )
            else:  # hybrid (default)
                # Hybrid search with vector + keyword results
                vector_results = self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(20, limit*2),  # Get more to rank
                    include=['documents', 'metadatas', 'distances']
                )

                # Keyword search as fallback for context
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                search_term = f"%{query}%"
                cursor.execute('''
                    SELECT id, type, content, metadata, created_at, session_id
                    FROM memories
                    WHERE content LIKE ? OR metadata LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (search_term, search_term, limit * 2))

                keyword_rows = cursor.fetchall()
                conn.close()

                # Combine and rank results - for simplicity, we'll prioritize vector results
                vectors_results_dict = {int(id): dist for id, dist in
                                      zip(vector_results['ids'][0], vector_results['distances'][0])}
                memories_from_vector = [
                    self.get_memory(int(_id))
                    for _id in vector_results['ids'][0] if self.get_memory(int(_id))
                ]

                # For keyword results, we don't have distance measure so we'll score them lower
                memories_from_keyword = [
                    Memory(
                        id=row[0],
                        type=row[1],
                        content=row[2],
                        metadata=json.loads(row[3]) if row[3] else {},
                        created_at=datetime.fromisoformat(row[4]),
                        session_id=row[5]
                    ) for row in keyword_rows
                ]

                # Simple ranking: vector results first, then keyword results
                combined_results = memories_from_vector + memories_from_keyword

                # Remove duplicates and limit
                seen_ids = set()
                unique_results = []
                for mem in combined_results:
                    if mem.id not in seen_ids:
                        seen_ids.add(mem.id)
                        unique_results.append(mem)

                return unique_results[:limit]

            # Process vector search results
            ids = vector_results['ids'][0]
            docs = vector_results['documents'][0]
            metadatas = vector_results['metadatas'][0] if 'metadatas' in vector_results else None

            memories = []
            for i, (mem_id, doc) in enumerate(zip(ids, docs)):
                try:
                    mem_id_int = int(mem_id)
                    memory = self.get_memory(mem_id_int)
                    if memory:
                        memories.append(memory)
                except ValueError:
                    # Skip invalid IDs
                    continue

            return memories[:limit]

        except Exception as e:
            # Fallback to keyword-only search if embeddings fail
            if search_type == 'keyword':
                logger.error(f"Keyword search failed: {e}")
                return []
            logger.warning(f"Vector search failed, falling back to keyword search: {e}")
            return self.search_memory(query, limit, 'keyword')

    def update_memory(self, memory_id: int, content: Optional[str] = None,
                     metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Update an existing memory"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get existing memory
            cursor.execute('SELECT id FROM memories WHERE id = ?', (memory_id,))
            if not cursor.fetchone():
                conn.close()
                return False

            cursor.execute('SELECT type, content, metadata FROM memories WHERE id = ?', (memory_id,))
            existing_row = cursor.fetchone()
            memory_type, existing_content, existing_metadata = existing_row
            updated_content = self._redact_secrets(content) if content is not None else existing_content
            updated_metadata = metadata if metadata is not None else (json.loads(existing_metadata) if existing_metadata else {})
            if len(updated_content.encode("utf-8")) > MAX_MEMORY_CONTENT_BYTES:
                logger.warning("Updated memory exceeds the 64 KiB per-record limit; not updating")
                conn.close()
                return False
            metadata_str = json.dumps(updated_metadata)
            if len(metadata_str.encode("utf-8")) > MAX_MEMORY_CONTENT_BYTES:
                logger.warning("Memory metadata exceeds the 64 KiB per-record limit; not updating")
                conn.close()
                return False
            old_size = len(existing_content.encode("utf-8")) * 2 + len((existing_metadata or "{}").encode("utf-8"))
            new_size = len(updated_content.encode("utf-8")) * 2 + len(metadata_str.encode("utf-8"))
            if self._active_storage_bytes() + max(0, new_size - old_size) > MAX_ACTIVE_MEMORY_BYTES:
                logger.warning("Active memory storage would exceed the 100 GiB limit; not updating")
                conn.close()
                return False
            updated_hash = self._generate_hash(updated_content, updated_metadata)

            if content is not None:
                cursor.execute('UPDATE memories SET content = ? WHERE id = ?', (updated_content, memory_id))

                # Regenerate embedding for updated content
                try:
                    embedding_response = self.ollama_client.embeddings(
                        model=self.embedding_model,
                        prompt=updated_content
                    )
                    embedding_vector = embedding_response['embedding']

                    # Update ChromaDB
                    self.collection.update(
                        ids=[str(memory_id)],
                        embeddings=[embedding_vector],
                        documents=[updated_content]
                    )

                    cursor.execute('UPDATE memories SET embedding_vector = ? WHERE id = ?',
                                  (json.dumps(embedding_vector), memory_id))
                except Exception as e:
                    logger.warning(f"Could not update embedding for memory {memory_id}: {e}")

            metadata_str = json.dumps(updated_metadata)
            cursor.execute('UPDATE memories SET metadata = ?, hash = ? WHERE id = ?',
                           (metadata_str, updated_hash, memory_id))

            conn.commit()
            conn.close()
            logger.info(f"Memory {memory_id} updated successfully")
            return True

        except Exception as e:
            logger.error(f"Error updating memory {memory_id}: {e}")
            if 'conn' in locals():
                conn.close()
            return False

    def delete_memory(self, memory_id: int) -> bool:
        """Delete a memory from all storage layers"""
        try:
            # Remove from SQLite database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('DELETE FROM memories WHERE id = ?', (memory_id,))
            deleted_rows = cursor.rowcount

            conn.commit()
            conn.close()

            # Remove from ChromaDB
            try:
                self.collection.delete(ids=[str(memory_id)])
            except Exception as e:
                logger.warning(f"Could not delete from ChromaDB: {e}")

            return deleted_rows > 0

        except Exception as e:
            logger.error(f"Error deleting memory {memory_id}: {e}")
            return False

    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent sessions"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, start_time, end_time, description
                FROM sessions
                ORDER BY start_time DESC
                LIMIT ?
            ''', (limit,))

            rows = cursor.fetchall()
            conn.close()

            return [
                {
                    'id': row[0],
                    'start_time': row[1],
                    'end_time': row[2],
                    'description': row[3]
                } for row in rows
            ]

        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            return []

    def start_session(self, session_id: str, description: str = "") -> bool:
        """Start a new session"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO sessions (id, description)
                VALUES (?, ?)
            ''', (session_id, description))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            logger.error(f"Error starting session {session_id}: {e}")
            return False

    def end_session(self, session_id: str) -> bool:
        """End a session"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE sessions
                SET end_time = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (session_id,))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            logger.error(f"Error ending session {session_id}: {e}")
            return False

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about the memory system"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get counts
            cursor.execute('SELECT COUNT(*) FROM memories')
            total_memories = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM sessions')
            total_sessions = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(DISTINCT category) FROM memories WHERE category IS NOT NULL')
            total_categories = cursor.fetchone()[0]

            conn.close()

            return {
                'total_memories': total_memories,
                'total_sessions': total_sessions,
                'total_categories': total_categories
            }

        except Exception as e:
            logger.error(f"Error getting memory stats: {e}")
            return {}

    def backup_memory_database(self, backup_path: Optional[str] = None) -> bool:
        """Create a consistent SQLite backup using SQLite's online backup API."""
        try:
            # Create backup directory if it doesn't exist
            backup_path = backup_path or self.backups_path
            os.makedirs(backup_path, exist_ok=True)

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_filename = f"ai_memory_backup_{timestamp}.db"
            backup_file = os.path.join(backup_path, backup_filename)

            source = sqlite3.connect(self.db_path)
            destination = sqlite3.connect(backup_file)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()

            logger.info(f"Database backed up to {backup_file}")
            return True

        except Exception as e:
            logger.error(f"Error backing up memory database: {e}")
            return False

    def rebuild_vector_index(self) -> bool:
        """Rebuild Chroma from authoritative SQLite rows and saved vectors."""
        import uuid

        if self.chroma_client is None or chromadb is None:
            logger.warning("Cannot rebuild vector index because ChromaDB is unavailable")
            return False

        staging_name = f"memories_rebuild_{uuid.uuid4().hex[:12]}"
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT id, type, content, metadata, embedding_vector FROM memories ORDER BY id"
            ).fetchall()
            conn.close()

            staging = self.chroma_client.create_collection(
                name=staging_name,
                embedding_function=self.embedding_function,
            )
            ids, documents, embeddings, metadatas = [], [], [], []
            for memory_id, memory_type, content, metadata_json, vector_blob in rows:
                if vector_blob:
                    vector = json.loads(vector_blob.decode() if isinstance(vector_blob, bytes) else vector_blob)
                else:
                    vector = self.ollama_client.embeddings(
                        model=self.embedding_model, prompt=content
                    )["embedding"]
                ids.append(str(memory_id))
                documents.append(content)
                embeddings.append(vector)
                metadata = json.loads(metadata_json) if metadata_json else {}
                metadatas.append({"type": memory_type, "category": str(metadata.get("category", ""))})

            for offset in range(0, len(ids), 100):
                staging.add(
                    ids=ids[offset:offset + 100],
                    documents=documents[offset:offset + 100],
                    embeddings=embeddings[offset:offset + 100],
                    metadatas=metadatas[offset:offset + 100],
                )

            previous_name = f"memories_previous_{uuid.uuid4().hex[:12]}"
            try:
                current = self.chroma_client.get_collection("memories")
            except Exception:
                current = None
            if current:
                current.modify(name=previous_name)
            try:
                staging.modify(name="memories")
            except Exception:
                if current:
                    current.modify(name="memories")
                raise
            if current:
                self.chroma_client.delete_collection(previous_name)
            self.collection = self.chroma_client.get_collection(
                name="memories", embedding_function=self.embedding_function
            )
            logger.info("Chroma vector index rebuilt from SQLite (%d memories)", len(ids))
            return True
        except Exception as e:
            logger.error("Could not rebuild Chroma index from SQLite: %s", e)
            try:
                self.chroma_client.delete_collection(staging_name)
            except Exception:
                pass
            return False

    def restore_memory_database(self, backup_file: str) -> bool:
        """Restore SQLite from a validated backup, then rebuild Chroma from SQLite."""
        from urllib.parse import quote

        if not os.path.isfile(backup_file):
            logger.error("Backup file does not exist: %s", backup_file)
            return False
        if os.path.abspath(backup_file) == os.path.abspath(self.db_path):
            logger.error("Refusing to restore the live database as its own backup")
            return False
        try:
            if not self.backup_memory_database():
                raise RuntimeError("Could not create a safety backup before restore")
            source = sqlite3.connect(f"file:{quote(os.path.abspath(backup_file))}?mode=ro", uri=True)
            try:
                check = source.execute("PRAGMA quick_check").fetchone()
                tables = {row[0] for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                if not check or check[0] != "ok" or "memories" not in tables:
                    raise ValueError("Backup failed SQLite integrity/schema validation")
                destination = sqlite3.connect(self.db_path)
                try:
                    source.backup(destination)
                finally:
                    destination.close()
            finally:
                source.close()

            self._init_database()
            index_ok = self.rebuild_vector_index()
            if not index_ok:
                # Avoid serving stale vector results; hybrid search will retain SQLite keyword fallback.
                try:
                    self.chroma_client.delete_collection("memories")
                    self.collection = self.chroma_client.get_or_create_collection(
                        name="memories", embedding_function=self.embedding_function
                    )
                except Exception as e:
                    logger.warning("Could not reset stale Chroma index after restore: %s", e)
            return True
        except Exception as e:
            logger.error("Error restoring memory database: %s", e)
            return False


def main():
    """Run one explicit production operation; never execute demo writes."""
    import argparse

    parser = argparse.ArgumentParser(description="AI Memory service operations")
    parser.add_argument("--action", required=True,
                        choices=("stats", "search", "store", "update", "forget", "delete", "backup", "restore", "rebuild-index"))
    parser.add_argument("--query")
    parser.add_argument("--content")
    parser.add_argument("--type", dest="memory_type", default="note")
    parser.add_argument("--metadata")
    parser.add_argument("--id", type=int)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--backup-file")
    args = parser.parse_args()

    metadata = json.loads(args.metadata) if args.metadata else None
    service = AIMemoryService()
    if args.action == "stats":
        print(json.dumps(service.get_memory_stats(), indent=2))
    elif args.action == "search":
        if not args.query:
            parser.error("--query is required for search")
        print(json.dumps([m.__dict__ for m in service.search_memory(args.query, args.limit)], default=str))
    elif args.action == "store":
        if args.content is None:
            parser.error("--content is required for store")
        result = service.store_memory(args.memory_type, args.content, metadata)
        print(f"Memory stored with ID: {result}" if result else "Failed to store memory")
    elif args.action == "update":
        if args.id is None:
            parser.error("--id is required for update")
        print("Memory updated successfully" if service.update_memory(args.id, args.content, metadata) else "Failed to update memory")
    elif args.action in ("forget", "delete"):
        if args.id is None:
            parser.error("--id is required for delete")
        print("Memory deleted successfully" if service.delete_memory(args.id) else "Failed to delete memory")
    elif args.action == "backup":
        print("Database backed up successfully" if service.backup_memory_database() else "Backup failed")
    elif args.action == "restore":
        if not args.backup_file:
            parser.error("--backup-file is required for restore")
        print("Database restored and vector index rebuilt" if service.restore_memory_database(args.backup_file) else "Restore failed")
    elif args.action == "rebuild-index":
        print("Vector index rebuilt from SQLite" if service.rebuild_vector_index() else "Vector index rebuild failed")


if __name__ == "__main__":
    main()
