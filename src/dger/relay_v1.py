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

from .relay_runtime import RelayRuntimeMixin
from .relay_accept import RelayAcceptMixin
from .relay_moh import RelayMohMixin
from .relay_chm import RelayChmMixin

class Relay(RelayRuntimeMixin, RelayAcceptMixin, RelayMohMixin, RelayChmMixin):
    def process_one(self, package: Path) -> bool:
        execution_id = package.name
        if EXECUTION_ID_RE.fullmatch(execution_id) is None or package.is_symlink() or not package.is_dir():
            return False
        ready = package / "READY.json"
        if not ready.exists():
            return False
        with self.execution_lock(execution_id):
            current = load_state(self.state, execution_id)
            if current is None:
                try:
                    current = self._accept_new(package, execution_id)
                except DgerError as exc:
                    self._status(execution_id, "REJECTED", code=exc.code, detail=exc.detail)
                    return True
            else:
                try:
                    self._assert_same_intent(package, current)
                except DgerError as exc:
                    if exc.code == "EXECUTION_ID_INTENT_CONFLICT":
                        self._status(execution_id, "IDENTITY_INTENT_CONFLICT", code=exc.code)
                        return True
                    self._status(execution_id, "REJECTED_REPLAY", code=exc.code, detail=exc.detail)
                    return True

            if current["phase"] in {"DONE", "CHM_RESULT_CONFLICT"}:
                return True
            if current["phase"] in {"ACCEPTED", "MOH_STAGE_COMPLETE", "MOH_RECONCILE", "MOH_IN_DOUBT"}:
                try:
                    self._reconcile_moh(current)
                except DgerError as exc:
                    current["last_reconcile_error"] = {"code": exc.code, "detail": exc.detail[:512]}
                    save_state(self.state, execution_id, current)
                    self._status(execution_id, "MOH_RECONCILIATION_BLOCKED", code=exc.code, detail=exc.detail[:512])
                    return True
                current = load_state(self.state, execution_id) or current
            if current["phase"] in {"CHM_PENDING", "CHM_ATTACHED"}:
                self._publish_chm(current)
            return True

    def scan_once(self) -> None:
        packages: list[Path] = []
        for path in self.ingress.iterdir():
            try:
                if path.is_dir() and not path.is_symlink():
                    packages.append(path)
            except OSError:
                continue
        degraded = False
        for path in sorted(packages, key=lambda p: p.name):
            try:
                self.process_one(path)
            except Exception:
                degraded = True
        atomic_json(self.control / "health.json", {
            "schema": PROTOCOL,
            "updated_at_utc": utc(),
            "relay_state": "DEGRADED" if degraded else "IDLE",
            "accepted_execution_count": len(list((self.state / "executions").glob("*.json"))) if (self.state / "executions").exists() else 0,
        }, 0o644)

    def run(self) -> None:
        while True:
            self.scan_once()
            self.sleep(EXPECTED_INTERVAL_SECONDS)
