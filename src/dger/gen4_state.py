from __future__ import annotations

import fcntl
import os
from dataclasses import asdict
from pathlib import Path
import secrets
import shutil
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from .gen4_primitives import (
    DgerGen4Error, ID_RE, MAX_ADMISSION_BYTES, MAX_ERROR_BYTES, MAX_REQUEST_BYTES, PROTOCOL,
    _copy_payload_verified, _fsync_dir, _json_object_no_duplicates, _validate_ready, _validate_request, atomic_bytes, atomic_json,
    canonical_digest, canonical_file_bytes, make_ready_record, payload_manifest, read_regular, sha256, utc,
)
from .gen4_contract import (
    Gen4Peers, ServiceIdentity, TrustedCorrelation, _correlation_from_dict, _correlation_to_dict, _validate_correlation,
)

class Gen4StateMixin:
    def __init__(
        self,
        transport_root: Path,
        state_root: Path,
        *,
        service_identity: ServiceIdentity,
        peers: Gen4Peers,
        fault: Callable[[str], None] | None = None,
    ) -> None:
        for root, code in ((transport_root, "UNSAFE_TRANSPORT_ROOT"), (state_root, "UNSAFE_STATE_ROOT")):
            if root.exists() and root.is_symlink():
                raise DgerGen4Error(code)
        if service_identity.actor_role != "EXECUTION_RELAY":
            raise DgerGen4Error("SERVICE_ROLE_INVALID")
        self.root = transport_root.resolve()
        self.state = state_root.resolve() / "gen4"
        self.service = service_identity
        self.peers = peers
        self.fault = fault or (lambda _name: None)
        self.ingress = self.root / "IngressV2"
        self.runs = self.root / "RunsV2"
        self.control = self.root / "Control"
        for path in (self.root, self.state, self.ingress, self.runs, self.control, self.state / "locks", self.state / "frozen", self.state / "executions", self.state / "indexes" / "gep"):
            path.mkdir(parents=True, exist_ok=True)
            if path.is_symlink():
                raise DgerGen4Error("UNSAFE_RELAY_PATH", str(path))

    def _state_path(self, request_id: str) -> Path:
        return self.state / "executions" / f"{request_id}.json"

    def _load_state(self, request_id: str) -> dict[str, Any] | None:
        path = self._state_path(request_id)
        if not path.exists():
            return None
        return _json_object_no_duplicates(read_regular(path, 1024 * 1024))

    def _save_state(self, request_id: str, value: dict[str, Any]) -> None:
        atomic_json(self._state_path(request_id), value)

    @contextmanager
    def _lock(self, request_id: str) -> Iterator[None]:
        lock = self.state / "locks" / f"{sha256(request_id.encode())}.lock"
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _status(self, request_id: str, state: str, **extra: Any) -> None:
        out = self.runs / request_id
        if out.exists() and (out.is_symlink() or not out.is_dir()):
            raise DgerGen4Error("UNSAFE_RESULT_PATH")
        out.mkdir(parents=True, exist_ok=True)
        record = {"schema": PROTOCOL, "dger_request_id": request_id, "state": state, "updated_at_utc": utc(), **extra}
        atomic_json(out / "status.json", record, 0o644)

    def _frozen_dir(self, request_id: str) -> Path:
        return self.state / "frozen" / request_id

    def _read_frozen(self, request_id: str) -> tuple[dict[str, Any], bytes, bytes, list[dict[str, Any]], str, bytes]:
        frozen = self._frozen_dir(request_id)
        request_raw = read_regular(frozen / "request.json", MAX_REQUEST_BYTES)
        admission_raw = read_regular(frozen / "admission.bin", MAX_ADMISSION_BYTES)
        ready_raw = read_regular(frozen / "READY.json", MAX_REQUEST_BYTES)
        request = _json_object_no_duplicates(request_raw)
        _validate_request(request, request_id)
        entries, total, manifest_digest = payload_manifest(frozen / "payload")
        ready = _json_object_no_duplicates(ready_raw)
        _validate_ready(ready, make_ready_record(request_raw, admission_raw, frozen / "payload", request_id))
        return request, request_raw, admission_raw, entries, manifest_digest, ready_raw

    def _freeze(self, package: Path, request_id: str) -> Path:
        self.fault("before_ingress_freeze")
        request_raw = read_regular(package / "request.json", MAX_REQUEST_BYTES)
        admission_raw = read_regular(package / "admission.bin", MAX_ADMISSION_BYTES)
        ready_raw = read_regular(package / "READY.json", MAX_REQUEST_BYTES)
        request = _json_object_no_duplicates(request_raw)
        _validate_request(request, request_id)
        entries, _, manifest_digest = payload_manifest(package / "payload")
        ready = _json_object_no_duplicates(ready_raw)
        _validate_ready(ready, make_ready_record(request_raw, admission_raw, package / "payload", request_id))
        expected = canonical_digest({
            "request_sha256": sha256(request_raw),
            "admission_sha256": sha256(admission_raw),
            "payload_manifest_sha256": manifest_digest,
            "ready_sha256": sha256(ready_raw),
        })
        final = self._frozen_dir(request_id)
        if final.exists():
            if final.is_symlink() or not final.is_dir():
                raise DgerGen4Error("FROZEN_STAGE_CONFLICT")
            existing = self._read_frozen(request_id)
            observed = canonical_digest({
                "request_sha256": sha256(existing[1]), "admission_sha256": sha256(existing[2]),
                "payload_manifest_sha256": existing[4], "ready_sha256": sha256(existing[5]),
            })
            if observed != expected:
                raise DgerGen4Error("FROZEN_STAGE_CONFLICT")
            return final
        tmp = final.with_name(f".{request_id}.freeze-{os.getpid()}-{secrets.token_hex(6)}")
        try:
            tmp.mkdir(mode=0o700)
            atomic_bytes(tmp / "request.json", request_raw)
            atomic_bytes(tmp / "admission.bin", admission_raw)
            atomic_bytes(tmp / "READY.json", ready_raw)
            _copy_payload_verified(package / "payload", tmp / "payload", entries)
            _fsync_dir(tmp)
            os.rename(tmp, final)
            _fsync_dir(final.parent)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        # Positive same-byte readback before accepted State exists.
        observed = self._read_frozen(request_id)
        got = canonical_digest({
            "request_sha256": sha256(observed[1]), "admission_sha256": sha256(observed[2]),
            "payload_manifest_sha256": observed[4], "ready_sha256": sha256(observed[5]),
        })
        if got != expected:
            raise DgerGen4Error("FROZEN_STAGE_READBACK_MISMATCH")
        self.fault("after_ingress_freeze")
        return final

    def _accept_frozen(self, request_id: str) -> dict[str, Any]:
        request, request_raw, admission_raw, entries, manifest_digest, ready_raw = self._read_frozen(request_id)
        transport_intent = canonical_digest({
            "request_sha256": sha256(request_raw), "admission_sha256": sha256(admission_raw),
            "payload_manifest_sha256": manifest_digest, "ready_sha256": sha256(ready_raw), "files": entries,
        })
        current = self._load_state(request_id)
        if current is not None:
            if current.get("transport_intent_digest") != transport_intent:
                raise DgerGen4Error("DGER_REQUEST_INTENT_CONFLICT")
            return current
        state = {
            "schema": PROTOCOL,
            "phase": "INGRESS_FROZEN",
            "dger_request_id": request_id,
            "request": request,
            "transport_intent_digest": transport_intent,
            "request_sha256": sha256(request_raw),
            "admission_sha256": sha256(admission_raw),
            "payload_manifest_sha256": manifest_digest,
            "ready_sha256": sha256(ready_raw),
            "frozen_stage": str(self._frozen_dir(request_id)),
            "accepted_at_utc": utc(),
            "service_identity_digest": self.service.identity_digest,
            "execute_reconciliation_required": False,
            "moh_execute_call_may_have_happened": False,
            "moh_execute_calls": 0,
            "moh_status_calls": 0,
            "moh_in_doubt_ever": False,
            "ahc_terminal_calls": 0,
            "chm_publish_calls": 0,
        }
        self._save_state(request_id, state)
        self._status(request_id, "INGRESS_FROZEN")
        self.fault("after_accept_state")
        return state

    def _index_gep(self, c: TrustedCorrelation, state: dict[str, Any]) -> None:
        name = sha256(c.gep_execution_id.encode("utf-8"))
        path = self.state / "indexes" / "gep" / f"{name}.json"
        value = {
            "schema": "dger-gep-execution-index/v1",
            "gep_execution_id": c.gep_execution_id,
            "dger_request_id": state["dger_request_id"],
            "transport_intent_digest": state["transport_intent_digest"],
            "correlation_digest": c.correlation_digest,
        }
        raw = canonical_file_bytes(value)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = read_regular(path, 32_768)
            if existing != raw:
                raise DgerGen4Error("GEP_EXECUTION_INTENT_CONFLICT")
            return
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw); fh.flush(); os.fsync(fh.fileno())
        _fsync_dir(path.parent)

    def _correlate(self, state: dict[str, Any]) -> None:
        request_id = state["dger_request_id"]
        if state.get("service_identity_digest") != self.service.identity_digest:
            raise DgerGen4Error("DGER_SERVICE_IDENTITY_CHANGED")
        request = state["request"]
        try:
            c = self.peers.establish_correlation(request, state["admission_sha256"], state["payload_manifest_sha256"], self.service)
        except Exception as exc:
            self._record_error(state, "correlation", exc)
            self._save_state(request_id, state)
            self._status(request_id, "PEER_CORRELATION_BLOCKED", code=self._error_code(exc))
            return
        _validate_correlation(c, request, state["admission_sha256"], state["payload_manifest_sha256"], self.service)
        self._index_gep(c, state)
        state["trusted_correlation"] = _correlation_to_dict(c)
        state["phase"] = "CORRELATED"
        state["correlated_at_utc"] = utc()
        self._save_state(request_id, state)
        self._status(request_id, "CORRELATED")
        self.fault("after_correlation")

    def _c(self, state: dict[str, Any]) -> TrustedCorrelation:
        value = state.get("trusted_correlation")
        if not isinstance(value, dict):
            raise DgerGen4Error("TRUSTED_CORRELATION_MISSING")
        if state.get("service_identity_digest") != self.service.identity_digest:
            raise DgerGen4Error("DGER_SERVICE_IDENTITY_CHANGED")
        correlation = _correlation_from_dict(value)
        _validate_correlation(
            correlation,
            state["request"],
            state["admission_sha256"],
            state["payload_manifest_sha256"],
            self.service,
        )
        return correlation

    @staticmethod
    def _error_code(exc: Exception) -> str:
        return exc.code if isinstance(exc, DgerGen4Error) else type(exc).__name__

    @staticmethod
    def _record_error(state: dict[str, Any], where: str, exc: Exception) -> None:
        state["error_generation"] = int(state.get("error_generation", 0)) + 1
        state["last_error"] = {"where": where, "code": Gen4StateMixin._error_code(exc), "detail": str(exc)[:MAX_ERROR_BYTES]}
