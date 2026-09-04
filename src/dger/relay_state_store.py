from __future__ import annotations

import os
from pathlib import Path
import secrets
import shutil
from typing import Any

from .relay_protocol import (
    CHM_RESULT_SCHEMA, DgerError, EXECUTION_ID_RE, MAX_ENVELOPE_BYTES, MAX_FILE_BYTES,
    MAX_MOH_RESPONSE_BYTES, MAX_REQUEST_BYTES, MOH_NONTERMINAL, MOH_TERMINAL_PUBLISHABLE,
    MOH_UNRESOLVED, PROTOCOL, _fsync_dir, _json_object_no_duplicates, _validate_ready,
    _validate_request, atomic_bytes, atomic_json, canonical_bytes, canonical_digest,
    payload_manifest, read_json_regular, read_regular, sha256, validate_moh_envelope,
)

def _state_path(state_root: Path, execution_id: str) -> Path:
    return state_root / "executions" / f"{execution_id}.json"


def load_state(state_root: Path, execution_id: str) -> dict[str, Any] | None:
    path = _state_path(state_root, execution_id)
    if not path.exists():
        return None
    value, _ = read_json_regular(path)
    return value


def save_state(state_root: Path, execution_id: str, value: dict[str, Any]) -> None:
    atomic_json(_state_path(state_root, execution_id), value)


def _safe_execution_dir(parent: Path, execution_id: str, *, create: bool = True) -> Path:
    if EXECUTION_ID_RE.fullmatch(execution_id) is None:
        raise DgerError("INVALID_EXECUTION_ID")
    if parent.is_symlink():
        raise DgerError("UNSAFE_PARENT", str(parent))
    if create:
        parent.mkdir(parents=True, exist_ok=True)
    child = parent / execution_id
    if child.exists() and child.is_symlink():
        raise DgerError("UNSAFE_EXECUTION_PATH", str(child))
    if create:
        child.mkdir(exist_ok=True)
    if child.exists() and (child.is_symlink() or not child.is_dir()):
        raise DgerError("UNSAFE_EXECUTION_PATH", str(child))
    return child


def _copy_payload_verified(source: Path, target: Path, expected_entries: list[dict[str, Any]]) -> None:
    target.mkdir(parents=True, exist_ok=False)
    for entry in expected_entries:
        rel = entry["path"]
        src = source / rel
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        data = read_regular(src, MAX_FILE_BYTES)
        if len(data) != entry["size"] or sha256(data) != entry["sha256"]:
            raise DgerError("PAYLOAD_CHANGED_DURING_COPY", rel)
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    actual, _, _ = payload_manifest(target)
    if actual != expected_entries:
        raise DgerError("PAYLOAD_COPY_VERIFY_FAILED")


def _stage_digest(stage: Path) -> str:
    envelope = read_regular(stage / "envelope.json", MAX_ENVELOPE_BYTES)
    entries, _, manifest = payload_manifest(stage / "payload")
    return canonical_digest({"envelope_sha256": sha256(envelope), "payload_manifest_sha256": manifest, "files": entries})
