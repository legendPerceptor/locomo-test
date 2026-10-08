"""Request-correlated oGMemory ingestion; never infer success from Docker logs."""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import sys
import uuid
from pathlib import Path

import requests

PROTOCOL = "after-turn-wait-v1"


def bounded_chunks(turns: list[str], header: str, max_chars: int) -> list[str]:
    """Pack whole dialogue turns; split oversized turns losslessly as a last resort.

    Every chunk retains the conversation date and participants. The character
    ceiling includes the header; it is deliberately not advertised as a token count.
    """
    capacity = max_chars - len(header) - 2
    if capacity < 128:
        raise ValueError("ogmem.chunk_chars leaves less than 128 characters for dialogue")
    pieces = []
    for turn in turns:
        # Repeat the speaker label when a single turn exceeds the bound.
        speaker, sep, body = turn.partition(": ")
        prefix = speaker + sep if sep else ""
        body = body if sep else turn
        size = capacity - len(prefix)
        if size < 1:
            raise ValueError("speaker label exceeds the chunk size")
        pieces.extend(prefix + body[i:i + size] for i in range(0, len(body), size))
        if not body:
            pieces.append(prefix)
    chunks, current = [], ""
    for piece in pieces:
        candidate = current + "\n\n" + piece if current else piece
        if len(candidate) > capacity:
            chunks.append(header + "\n\n" + current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(header + "\n\n" + current)
    if not chunks:
        raise ValueError("Cannot ingest an empty conversation")
    return chunks


def fingerprint(cfg, chunks: list[str]) -> str:
    identity = [
        PROTOCOL, cfg.name, cfg.user, cfg.agent_id, cfg.ogmem.api_url,
        cfg.ogmem.account_id, cfg.ogmem.user_id, chunks,
    ]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def _save(path: Path, state: dict) -> None:
    """Persist intent before sending, so crashes cannot cause blind replay."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _post(cfg, method: str, payload: dict, timeout: float) -> dict:
    headers = {}
    if cfg.ogmem.api_key:
        headers["Authorization"] = f"Bearer {cfg.ogmem.api_key}"
    # No retries: a lost response is not evidence that the write failed.
    response = requests.post(
        f"{cfg.ogmem.api_url.rstrip('/')}/api/v1/{method}",
        json=payload, headers=headers, timeout=(10, timeout),
    )
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(f"oGMemory {method}: non-JSON HTTP {response.status_code}") from exc
    if not response.ok:
        raise RuntimeError(f"oGMemory {method}: HTTP {response.status_code}: {result}")
    if not isinstance(result, dict):
        raise RuntimeError(f"oGMemory {method}: invalid response object")
    return result


def validate_extraction(result: dict, request_id: str) -> None:
    if result.get("ok") is not True or result.get("status") != "completed":
        raise RuntimeError(f"oGMemory extraction did not complete: {result}")
    if result.get("client_request_id") != request_id:
        raise RuntimeError("oGMemory completion request ID mismatch")
    if result.get("writes_failed", 0):
        raise RuntimeError(f"oGMemory extraction has failed writes: {result}")
    commit = result.get("commit", {})
    if (commit.get("archived") is not True or commit.get("status") != "completed"
            or not commit.get("archive_id") or commit.get("error")):
        raise RuntimeError(f"oGMemory archive did not complete: {commit}")
    drain = result.get("drain")
    if not isinstance(drain, dict) or drain.get("failed") or drain.get("error"):
        raise RuntimeError(f"oGMemory indexing drain failed or missing: {drain}")


def wait_for_index(cfg, scope: dict) -> dict:
    result = _post(
        cfg, "call/wait_until_idle",
        {**scope, "waitOutbox": True, "drainOutbox": False,
         "timeoutSeconds": cfg.ogmem.wait_timeout},
        cfg.ogmem.wait_timeout + 15,
    )
    counts = result.get("outbox", {})
    # Old servers cannot certify absence of dead-lettered events. Fail closed.
    if isinstance(counts, dict) and "failed" not in counts and "total" in counts:
        raise RuntimeError(
            "oGMemory backend compatibility check failed: outbox.failed is missing. "
            "The running backend does not expose failed-indexing counts; deploy "
            "the completion-tracking backend patch from AntTrail/deploy. "
            "idle=true alone does not certify successful indexing. "
            f"Response: {result}"
        )
    if (result.get("idle") is not True or counts.get("supported") is False
            or counts.get("error") or counts.get("failed") != 0
            or counts.get("total") != 0):
        raise RuntimeError(f"oGMemory indexing not verified complete: {result}")
    return result


def ingest_chunks(cfg, output_dir: str, record_key: str, chunks: list[str],
                  created_at: str | None = None) -> dict:
    lock_dir = Path(output_dir) / ".ogmem_chunks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / (hashlib.sha256(record_key.encode()).hexdigest() + ".lock")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another process is ingesting this session") from exc
        return _ingest_chunks_locked(cfg, output_dir, record_key, chunks, created_at)


def _ingest_chunks_locked(cfg, output_dir: str, record_key: str, chunks: list[str],
                          created_at: str | None = None) -> dict:
    digest = fingerprint(cfg, chunks)
    path = Path(output_dir) / ".ogmem_chunks" / (
        hashlib.sha256(record_key.encode()).hexdigest() + ".json"
    )
    state = json.loads(path.read_text()) if path.exists() else {
        "protocol": PROTOCOL, "fingerprint": digest, "chunks": {},
    }
    if state.get("fingerprint") != digest:
        raise RuntimeError("Ingestion input/config changed; use a fresh run/output namespace")
    scope = {"agentId": cfg.agent_id}
    if cfg.ogmem.account_id:
        scope["accountId"] = cfg.ogmem.account_id
    if cfg.ogmem.user_id:
        scope["userId"] = cfg.ogmem.user_id
    archives = []
    for index, content in enumerate(chunks):
        key = str(index)
        request_id = hashlib.sha256(f"{digest}:{record_key}:{index}".encode()).hexdigest()
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "ogmem-ingest:" + request_id))
        chunk_scope = {**scope, "sessionId": session_id}
        saved = state["chunks"].get(key, {})
        if saved.get("status") == "completed":
            archives.append(saved["archive_id"])
            continue
        print(f"    [ogmem] chunk {index + 1}/{len(chunks)} "
              f"({len(content)} chars), session={session_id}", file=sys.stderr)
        if saved.get("status") in {"submitted", "failed"}:
            raise RuntimeError(
                f"Chunk {index + 1} has an unresolved previous write ({session_id}). "
                "Reconcile its archive before retrying, or use a fresh memory/run namespace. "
                f"Checkpoint: {path}"
            )
        if saved.get("status") != "extracted":
            state["chunks"][key] = {"status": "submitted", "session_id": session_id,
                                    "client_request_id": request_id}
            _save(path, state)
            message = {"role": "user", "content": content}
            if created_at:
                message["created_at"] = created_at
            try:
                result = _post(
                    cfg, "after_turn",
                    {**chunk_scope, "clientRequestId": request_id, "wait": True,
                     "forceExtract": True, "messages": [message], "prePromptMessageCount": 0},
                    cfg.ogmem.wait_timeout,
                )
                validate_extraction(result, request_id)
            except Exception as exc:
                state["chunks"][key].update(status="failed", error=str(exc))
                _save(path, state)
                raise
            state["chunks"][key].update(
                status="extracted", archive_id=result["commit"]["archive_id"],
                extraction_run_id=result.get("extraction_run_id"),
            )
            _save(path, state)
        # An indexing retry never re-sends an already archived chunk.
        wait_for_index(cfg, chunk_scope)
        state["chunks"][key]["status"] = "completed"
        _save(path, state)
        archives.append(state["chunks"][key]["archive_id"])
        print(f"    [ogmem] chunk {index + 1}/{len(chunks)} archived and indexed",
              file=sys.stderr)
    return {"protocol": PROTOCOL, "fingerprint": digest,
            "chunk_count": len(chunks), "archive_ids": archives}
