"""Portable backend tests; all persistent state lives in per-test temporary dirs."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memory_service import AIMemoryService, MAX_ACTIVE_MEMORY_BYTES, MAX_MEMORY_CONTENT_BYTES


class FakeOllama:
    def embeddings(self, *, model, prompt):
        # Stable local test vector; no Ollama daemon or downloaded model needed.
        value = sum(prompt.encode("utf-8")) % 997 / 997
        return {"embedding": [value, 1.0 - value, 0.25, 0.5]}


class MemoryBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="opencode-memory-test-")
        self.home = Path(self.temporary.name)
        self.service = AIMemoryService(memory_home=str(self.home), ollama_client=FakeOllama())

    def tearDown(self):
        self.temporary.cleanup()

    def test_sqlite_chroma_crud_duplicate_redaction_search_and_stats(self):
        metadata = {"project": "/tmp/project-a", "importance": 0.8}
        test_key = "SUPER_SECRET_" + "TEST_KEY"
        test_password = "SUPER_SECRET_" + "PASSWORD"
        test_token = "SUPER_SECRET_" + "TOKEN"
        raw = f"ORANGE-TEST architecture decision API_KEY={test_key} PASSWORD={test_password} Authorization: Bearer {test_token}"
        memory_id = self.service.store_memory("DECISION", raw, metadata)
        self.assertIsNotNone(memory_id)
        record = self.service.get_memory(memory_id)
        self.assertNotIn(test_key, record.content)
        self.assertNotIn(test_password, record.content)
        self.assertNotIn(test_token, record.content)
        self.assertIn("REDACTED", record.content)
        self.assertEqual(self.service.store_memory("DECISION", raw, metadata), memory_id)
        self.assertEqual(self.service.get_memory_stats()["total_memories"], 1)
        self.assertIn(str(memory_id), self.service.collection.get(ids=[str(memory_id)])["ids"])
        self.assertIn(memory_id, [m.id for m in self.service.search_memory("ORANGE-TEST", 5, "keyword")])
        self.assertIn(memory_id, [m.id for m in self.service.search_memory("ORANGE-TEST architecture", 5)])
        self.assertTrue(self.service.update_memory(memory_id, content="ORANGE-TEST updated architecture decision"))
        self.assertEqual(self.service.get_memory(memory_id).content, "ORANGE-TEST updated architecture decision")
        self.assertTrue(self.service.delete_memory(memory_id))
        self.assertIsNone(self.service.get_memory(memory_id))

    def test_project_scope_filtering_and_global_visibility(self):
        a = self.service.store_memory("FACT", "PROJECTA-ONLY marker", {"project": "/tmp/a"})
        b = self.service.store_memory("FACT", "GLOBAL marker", {"scope": "global"})
        all_rows = {m.id: m for m in self.service.search_memory("marker", 10, "keyword")}
        self.assertIn(a, all_rows)
        self.assertIn(b, all_rows)
        # CLI applies ownership filtering; backend records preserve scope metadata.
        self.assertEqual(all_rows[a].metadata["project"], "/tmp/a")
        self.assertEqual(all_rows[b].metadata["scope"], "global")
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "memory_cli.py"),
             "search", "--query", "marker", "--type", "keyword", "--project", "/tmp/b", "--json"],
            check=True, capture_output=True, text=True,
            env={**os.environ, "OPENCODE_MEMORY_HOME": str(self.home)},
        )
        visible = json.loads(result.stdout)
        self.assertEqual([row["id"] for row in visible], [b])

    def test_limits_malformed_metadata_and_failed_embedding_keep_sqlite_authoritative(self):
        self.assertIsNone(self.service.store_memory("FACT", "x" * (MAX_MEMORY_CONTENT_BYTES + 1)))
        self.assertIsNone(self.service.store_memory("FACT", "bad metadata", {"x": object()}))
        self.service._active_storage_bytes = lambda: MAX_ACTIVE_MEMORY_BYTES
        self.assertIsNone(self.service.store_memory("FACT", "over storage limit", {}))
        broken = FakeOllama()
        broken.embeddings = lambda **_kw: (_ for _ in ()).throw(RuntimeError("offline"))
        service = AIMemoryService(memory_home=str(self.home / "offline"), ollama_client=broken)
        memory_id = service.store_memory("FACT", "OFFLINE-KEYWORD durable fallback", {"project": "/tmp/a"})
        self.assertIsNotNone(memory_id)
        self.assertEqual([m.id for m in service.search_memory("OFFLINE-KEYWORD", 5)], [memory_id])

    def test_vector_outage_keyword_fallback_and_missing_index(self):
        memory_id = self.service.store_memory("FACT", "FALLBACK-INDEX marker", {})
        original_query = self.service.collection.query
        self.service.collection.query = lambda **_kw: (_ for _ in ()).throw(RuntimeError("index unavailable"))
        try:
            self.assertIn(memory_id, [m.id for m in self.service.search_memory("FALLBACK-INDEX", 5)])
        finally:
            self.service.collection.query = original_query

    def test_missing_chroma_keeps_sqlite_keyword_mode(self):
        with patch("memory_service.chromadb", None):
            service = AIMemoryService(memory_home=str(self.home / "no-chroma"), ollama_client=FakeOllama())
        self.assertIsNone(service.collection)
        memory_id = service.store_memory("FACT", "NO-CHROMA keyword survives", {})
        self.assertIsNotNone(memory_id)
        self.assertEqual([m.id for m in service.search_memory("NO-CHROMA", 5, "keyword")], [memory_id])
        self.assertEqual([m.id for m in service.search_memory("NO-CHROMA", 5)], [memory_id])
        self.assertTrue(service.delete_memory(memory_id))
        self.assertFalse(service.rebuild_vector_index())

    def test_backup_restore_and_rebuild_index(self):
        memory_id = self.service.store_memory("FACT", "RESTORE-MARKER authoritative row", {})
        self.assertTrue(self.service.backup_memory_database())
        backups = list((self.home / "backups").glob("*.db"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(self.service.delete_memory(memory_id))
        self.assertTrue(self.service.restore_memory_database(str(backups[0])))
        self.assertEqual(self.service.get_memory(memory_id).content, "RESTORE-MARKER authoritative row")
        self.assertTrue(self.service.rebuild_vector_index())
        self.assertIn(str(memory_id), self.service.collection.get(ids=[str(memory_id)])["ids"])

    def test_paths_are_isolated_under_temporary_home(self):
        self.assertTrue(str(self.service.db_path).startswith(str(self.home)))
        self.assertTrue(str(self.service.embeddings_path).startswith(str(self.home)))
        self.assertFalse((Path.home() / "ai-memory" / "database" / "ai_memory.db").resolve() == Path(self.service.db_path).resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
