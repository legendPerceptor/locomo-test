import copy
import fcntl
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from locomo_test.config import Config, OgmemEnv
from locomo_test.ogmem_ingest import (
    bounded_chunks, ingest_chunks, validate_extraction, wait_for_index,
)
from locomo_test.eval import require_verified_ogmem_ingestion, run_ingest


def successful(request_id):
    return {
        "ok": True, "status": "completed", "client_request_id": request_id,
        "writes_failed": 0, "drain": {"failed": 0},
        "commit": {"archived": True, "archive_id": "archive-1", "status": "completed"},
    }


IDLE = {"idle": True, "outbox": {"pending": 0, "processing": 0, "failed": 0, "total": 0}}


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(name="unit", memory_mode="ogmem", ogmem=OgmemEnv())

    def test_success_requires_matching_request(self):
        validate_extraction(successful("a"), "a")
        with self.assertRaisesRegex(RuntimeError, "mismatch"):
            validate_extraction(successful("another-session"), "a")

    def test_reject_partial_and_legacy_success(self):
        mutations = [
            {"status": "duplicate"}, {"status": "accumulating"},
            {"ok": False, "error": "LLM tool output truncated"},
            {"writes_failed": 1}, {"drain": {"failed": 1}},
            {"commit": {"archived": False, "status": "completed"}},
            {"commit": {"archived": True, "status": "failed", "error": "disk"}},
        ]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                validate_extraction({**successful("a"), **change}, "a")

    def test_indexing_fails_closed(self):
        for result in [
            {"idle": False}, {"idle": True},
            {"idle": True, "outbox": {"total": 0}},  # old server lacks FAILED count
            {"idle": True, "outbox": {"total": 0, "failed": 1}},
            {"idle": True, "outbox": {"total": 0, "failed": 0, "supported": False}},
            {"idle": True, "outbox": {"total": 1, "failed": 0}},
        ]:
            with self.subTest(result=result), patch(
                "locomo_test.ogmem_ingest._post", return_value=result
            ), self.assertRaises(RuntimeError):
                wait_for_index(self.cfg, {})

    def test_old_backend_reports_actionable_compatibility_error(self):
        result = {"extraction_in_progress": False, "idle": True,
                  "outbox": {"pending": 0, "processing": 0, "total": 0},
                  "reason": "session_not_found"}
        with patch("locomo_test.ogmem_ingest._post", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "outbox.failed is missing"):
                wait_for_index(self.cfg, {})

    def test_verified_chunks_are_checkpointed_and_not_resent(self):
        calls = []
        def post(cfg, method, payload, timeout):
            calls.append((method, payload))
            if method == "after_turn":
                self.assertTrue(payload["wait"])
                self.assertTrue(payload["forceExtract"])
                return successful(payload["clientRequestId"])
            return copy.deepcopy(IDLE)
        with tempfile.TemporaryDirectory() as directory, patch(
            "locomo_test.ogmem_ingest._post", side_effect=post
        ):
            result = ingest_chunks(self.cfg, directory, "key", ["one", "two"])
            self.assertEqual(result["chunk_count"], 2)
            self.assertEqual(len(calls), 4)
            ingest_chunks(self.cfg, directory, "key", ["one", "two"])
            self.assertEqual(len(calls), 4)
            ids = [p["sessionId"] for m, p in calls if m == "after_turn"]
            self.assertNotEqual(ids[0], ids[1])
            with self.assertRaisesRegex(RuntimeError, "changed"):
                ingest_chunks(self.cfg, directory, "key", ["changed"])

    def test_timeout_is_never_resent(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "locomo_test.ogmem_ingest._post", side_effect=requests.Timeout("lost response")
        ) as post:
            with self.assertRaises(requests.Timeout):
                ingest_chunks(self.cfg, directory, "key", ["one"])
            with self.assertRaisesRegex(RuntimeError, "unresolved previous write"):
                ingest_chunks(self.cfg, directory, "key", ["one"])
            self.assertEqual(post.call_count, 1)

    def test_concurrent_session_writer_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "locomo_test.ogmem_ingest._post"
        ) as post:
            lock_dir = Path(directory, ".ogmem_chunks")
            lock_dir.mkdir()
            lock_path = lock_dir / (hashlib.sha256(b"key").hexdigest() + ".lock")
            with lock_path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(RuntimeError, "Another process"):
                    ingest_chunks(self.cfg, directory, "key", ["one"])
            post.assert_not_called()

    def test_preflight_failure_prevents_writes(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "locomo_test.eval.load_locomo_data", return_value=[]
        ), patch("locomo_test.ogmem_ingest._post", return_value={"idle": True}) as post:
            with self.assertRaisesRegex(RuntimeError, "not verified"):
                run_ingest(self.cfg, directory)
            self.assertEqual([c.args[1] for c in post.call_args_list],
                             ["call/wait_until_idle"])

    def test_index_retry_does_not_reextract(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "locomo_test.ogmem_ingest._post",
            side_effect=lambda c, m, p, t: successful(p["clientRequestId"]),
        ) as post, patch("locomo_test.ogmem_ingest.wait_for_index") as wait:
            wait.side_effect = RuntimeError("still processing")
            with self.assertRaises(RuntimeError):
                ingest_chunks(self.cfg, directory, "key", ["one"])
            wait.side_effect = None
            wait.return_value = IDLE
            ingest_chunks(self.cfg, directory, "key", ["one"])
            self.assertEqual(post.call_count, 1)

    def test_qa_rejects_missing_and_legacy_records(self):
        sample = {"sample_id": "s", "conversation": {
            "speaker_a": "A", "speaker_b": "B", "session_1_date_time": "1 pm on 1 May, 2023",
            "session_1": [{"speaker": "A", "text": "Hello"}],
        }}
        with tempfile.TemporaryDirectory() as directory, patch(
            "locomo_test.eval.load_locomo_data", return_value=[sample]
        ):
            for records in [{}, {"main:eval-1:s:session_1": {"success": True, "meta": {}}}]:
                Path(directory, ".ingest_record.json").write_text(json.dumps(records))
                with self.assertRaisesRegex(RuntimeError, "QA blocked"):
                    require_verified_ogmem_ingestion(self.cfg, directory)

    def test_direct_ingestion_and_qa_gate(self):
        sample = {"sample_id": "s", "conversation": {
            "speaker_a": "A", "speaker_b": "B", "session_1_date_time": "1 pm on 1 May, 2023",
            "session_1": [{"speaker": "A", "text": "Hello"}],
        }}
        def post(cfg, method, payload, timeout):
            return successful(payload["clientRequestId"]) if method == "after_turn" else IDLE
        with tempfile.TemporaryDirectory() as directory, patch(
            "locomo_test.eval.load_locomo_data", return_value=[sample]
        ), patch("locomo_test.ogmem_ingest._post", side_effect=post) as api, patch(
            "locomo_test.eval.send_message_with_retry"
        ) as gateway, patch("locomo_test.eval.query_ogmem_token_stats", return_value={}):
            results, _, _ = run_ingest(self.cfg, directory)
            self.assertEqual(len(results), 1)
            gateway.assert_not_called()
            require_verified_ogmem_ingestion(self.cfg, directory)
            writes = sum(c.args[1] == "after_turn" for c in api.call_args_list)
            run_ingest(self.cfg, directory)
            self.assertEqual(writes, sum(c.args[1] == "after_turn" for c in api.call_args_list))
            sample["conversation"]["session_1"][0]["text"] = "Changed"
            with self.assertRaisesRegex(RuntimeError, "QA blocked"):
                require_verified_ogmem_ingestion(self.cfg, directory)

    def test_pipeline_restores_stderr_on_failed_qa_gate(self):
        import sys
        from locomo_test.pipeline import run_pipeline
        original = sys.stderr
        with tempfile.TemporaryDirectory() as directory, patch(
            "locomo_test.pipeline.resolve_output_dir", return_value=directory
        ), patch("locomo_test.pipeline.resolve_data_file", return_value="unused"), patch(
            "locomo_test.pipeline.require_verified_ogmem_ingestion",
            side_effect=RuntimeError("QA blocked"),
        ), patch("locomo_test.pipeline.run_qa") as qa:
            with self.assertRaisesRegex(RuntimeError, "QA blocked"):
                run_pipeline(self.cfg, only=["qa"])
            self.assertIs(sys.stderr, original)
            qa.assert_not_called()


class ChunkTests(unittest.TestCase):
    def test_turns_and_headers_preserved(self):
        turns = ["Alice: " + "a" * 160, "Bob: " + "b" * 170, "Alice: hello"]
        header = "[date: May 2023]\n[participants: Alice & Bob]"
        chunks = bounded_chunks(turns, header, 300)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 300 and c.startswith(header) for c in chunks))
        reconstructed = "\n\n".join(c[len(header) + 2:] for c in chunks)
        self.assertEqual(reconstructed, "\n\n".join(turns))

    def test_large_turn_splits_losslessly_with_speaker(self):
        content = "你好世界 " * 200
        chunks = bounded_chunks(["Alice: " + content], "[date]", 256)
        self.assertTrue(all(len(c) <= 256 for c in chunks))
        restored = "".join(c.split("\n\n", 1)[1].removeprefix("Alice: ") for c in chunks)
        self.assertEqual(restored, content)

    def test_empty_conversation_is_not_success(self):
        with self.assertRaises(ValueError):
            bounded_chunks([], "header", 512)


if __name__ == "__main__":
    unittest.main()
