from __future__ import annotations

import fcntl
import os
from pathlib import Path
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from .relay_protocol import (
    CHM_TOOL_ID, DgerError, EXECUTION_ID_RE, EXPECTED_INTERVAL_SECONDS, MAX_ENVELOPE_BYTES,
    MAX_MOH_RESPONSE_BYTES, MAX_REQUEST_BYTES, MAX_RESULT_RECORD_BYTES, MOH_TERMINAL_PUBLISHABLE,
    MOH_TOOL_ID, MOH_UNRESOLVED, PROTOCOL, READY_SCHEMA, REQUEST_SCHEMA, REQUIRED_CHM_OPERATIONS,
    SemanticGateway, _intent_digest, _json_object_no_duplicates, _safe_rel, _validate_consumer_binding,
    _validate_ready, _validate_request, atomic_bytes, atomic_json, canonical_bytes,
    canonical_digest, canonical_file_bytes, moh_closure_digest, payload_manifest, read_json_regular,
    read_regular, resolve_tool_binding, sha256, utc, validate_moh_envelope,
)
from .relay_state import (
    _chm_result, _result_record, _safe_execution_dir, _stage_digest, _unwrap_gtg_result, _validate_moh_response, freeze_ingress,
    load_state, materialize_moh_stage, save_state,
)

class RelayRuntimeMixin:
    def __init__(
        self,
        transport_root: Path,
        state_root: Path,
        *,
        moh_home: Path,
        gateway: SemanticGateway,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        for root, code in ((transport_root, "UNSAFE_TRANSPORT_ROOT"), (state_root, "UNSAFE_STATE_ROOT"), (moh_home, "UNSAFE_MOH_HOME")):
            if root.exists() and root.is_symlink():
                raise DgerError(code)
        self.root = transport_root.resolve()
        self.state = state_root.resolve()
        self.moh_home = moh_home.resolve()
        self.gateway = gateway
        self.sleep = sleep
        self.ingress = self.root / "Ingress"
        self.runs = self.root / "Runs"
        self.control = self.root / "Control"
        for path in (self.root, self.state, self.moh_home, self.ingress, self.runs, self.control, self.state / "locks"):
            path.mkdir(parents=True, exist_ok=True)
            if path.is_symlink():
                raise DgerError("UNSAFE_RELAY_PATH", str(path))

    @contextmanager
    def execution_lock(self, execution_id: str) -> Iterator[None]:
        lock_path = self.state / "locks" / f"{execution_id}.lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _status(self, execution_id: str, state: str, **extra: Any) -> None:
        out = _safe_execution_dir(self.runs, execution_id)
        atomic_json(out / "status.json", {
            "schema": PROTOCOL,
            "execution_id": execution_id,
            "state": state,
            "updated_at_utc": utc(),
            **extra,
        }, 0o644)

    def _result_path(self, execution_id: str) -> Path:
        return _safe_execution_dir(self.runs, execution_id) / "result.json"

    def _publish_result(self, execution_id: str, record: dict[str, Any]) -> tuple[str, str]:
        raw = canonical_file_bytes(record)
        if len(raw) > MAX_RESULT_RECORD_BYTES:
            raise DgerError("RESULT_RECORD_TOO_LARGE")
        path = self._result_path(execution_id)
        if path.exists():
            existing = read_regular(path, MAX_RESULT_RECORD_BYTES)
            if existing != raw:
                raise DgerError("RESULT_RECORD_CONFLICT")
        else:
            atomic_bytes(path, raw, 0o644)
        ref = f"Runs/{execution_id}/result.json"
        return sha256(raw), ref
