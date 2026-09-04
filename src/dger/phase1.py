from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Callable, Mapping, Protocol

EXECUTION_RE = re.compile(r"execution_[0-9a-f]{64}\Z")
HANDOFF_RE = re.compile(r"execution_handoff_[0-9a-f]{64}\Z")
TERMINAL = frozenset({"SUCCEEDED", "FAILED"})
OUTBOX_PENDING = "OUTBOX_PENDING"
DELIVERY_REQUIRED = "DELIVERY_REQUIRED"
ACKNOWLEDGED = "ACKNOWLEDGED"


class RelayPhase1Error(RuntimeError):
    pass


class CrashInjected(BaseException):
    pass


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(raw)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as fh:
            fd = -1
            fh.write(canonical(dict(value)))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        dfd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise RelayPhase1Error("UNSAFE_STATE_OBJECT")
    data = path.read_bytes()
    try:
        value = json.loads(data)
    except Exception as exc:
        raise RelayPhase1Error("INVALID_STATE_OBJECT") from exc
    if not isinstance(value, dict) or data != canonical(value):
        raise RelayPhase1Error("INVALID_STATE_OBJECT")
    return value


class CHMClient(Protocol):
    def get_handoff(self, handoff_id: str) -> dict[str, Any]: ...
    def active_capacity(self) -> list[dict[str, Any]]: ...
    def acquire_capacity(self, execution_id: str) -> dict[str, Any]: ...
    def bind_capacity(self, handoff_id: str, execution_id: str, slot: str, allocation_id: str) -> dict[str, Any]: ...
    def capacity_status(self, slot: str, allocation_id: str, status: str) -> dict[str, Any]: ...
    def publish_uncertain(self, handoff_id: str, proof: dict[str, Any]) -> dict[str, Any]: ...
    def publish_terminal(self, handoff_id: str, proof: dict[str, Any]) -> dict[str, Any]: ...


class GEPClient(Protocol):
    def reconcile(self, descriptor: dict[str, Any]) -> dict[str, Any]: ...
    def start(self, descriptor: dict[str, Any]) -> dict[str, Any]: ...


class WakeClient(Protocol):
    def deliver(self, event: dict[str, Any]) -> None: ...


@dataclass
class Phase1Relay:
    state_root: Path
    chm: CHMClient
    gep: GEPClient
    wake: WakeClient
    crash_hook: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        self.state_root = Path(self.state_root)
        if self.state_root.exists() and (self.state_root.is_symlink() or not self.state_root.is_dir()):
            raise RelayPhase1Error("UNSAFE_RELAY_STATE_ROOT")
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_root = self.state_root.resolve(strict=True)

    def _crash(self, point: str) -> None:
        if self.crash_hook is not None:
            self.crash_hook(point)

    def _state_path(self, execution_id: str) -> Path:
        if not EXECUTION_RE.fullmatch(execution_id):
            raise RelayPhase1Error("INVALID_EXECUTION_ID")
        return self.state_root / "executions" / f"{execution_id}.json"

    def _outbox_path(self, execution_id: str) -> Path:
        if not EXECUTION_RE.fullmatch(execution_id):
            raise RelayPhase1Error("INVALID_EXECUTION_ID")
        return self.state_root / "outbox" / f"{execution_id}.json"

    def _save_execution(self, execution_id: str, value: Mapping[str, Any]) -> None:
        atomic_json(self._state_path(execution_id), value)

    def _find_or_acquire_capacity(self, handoff: dict[str, Any]) -> dict[str, str]:
        existing = handoff.get("slot_allocation")
        if isinstance(existing, dict):
            return {"slot": existing["slot"], "allocation_id": existing["allocation_id"]}
        execution_id = handoff["execution_id"]
        # CHM acquire_capacity is Phase-1 acquire-once: the scan/recover/acquire
        # decision is atomic under CHM's execution-pool lock.
        acquired = self.chm.acquire_capacity(execution_id)
        allocation = {"slot": acquired["slot"], "allocation_id": acquired["allocation_id"]}
        if acquired.get("changed"):
            self._crash("after_capacity_allocation")
        self.chm.bind_capacity(handoff["handoff_id"], execution_id, allocation["slot"], allocation["allocation_id"])
        return allocation

    def _capacity_state(self, allocation: Mapping[str, str]) -> str:
        matches = [
            s for s in self.chm.active_capacity()
            if s.get("slot") == allocation["slot"] and s.get("allocation_id") == allocation["allocation_id"]
        ]
        if len(matches) != 1:
            raise RelayPhase1Error("CAPACITY_ALLOCATION_NOT_ACTIVE")
        status = matches[0].get("status")
        if status not in {"RESERVED", "RUNNING", "BLOCKED"}:
            raise RelayPhase1Error("CAPACITY_STATE_INVALID")
        return str(status)

    def _ensure_running(self, allocation: Mapping[str, str]) -> str:
        status = self._capacity_state(allocation)
        if status == "RESERVED":
            self.chm.capacity_status(allocation["slot"], allocation["allocation_id"], "RUNNING")
            status = "RUNNING"
        return status

    def _ensure_blocked(self, allocation: Mapping[str, str]) -> None:
        status = self._capacity_state(allocation)
        if status == "RUNNING":
            self.chm.capacity_status(allocation["slot"], allocation["allocation_id"], "BLOCKED")
            return
        if status != "BLOCKED":
            raise RelayPhase1Error("CAPACITY_BLOCKING_STATE_INVALID")

    def _proof_from_gep(self, descriptor: dict[str, Any], gep: dict[str, Any]) -> dict[str, Any]:
        required = ("execution_id", "descriptor_digest", "status", "result_manifest_reference", "result_manifest_digest")
        if any(k not in gep for k in required):
            raise RelayPhase1Error("GEP_TERMINAL_INCOMPLETE")
        if gep["execution_id"] != descriptor["execution_id"] or gep["status"] not in TERMINAL:
            raise RelayPhase1Error("GEP_TERMINAL_CORRELATION_CONFLICT")
        return {k: gep[k] for k in required}

    def _uncertain_proof_from_gep(self, descriptor: dict[str, Any], gep: dict[str, Any]) -> dict[str, Any]:
        required = ("execution_id", "descriptor_digest", "status", "start_intent_reference", "start_intent_digest")
        if any(k not in gep for k in required):
            raise RelayPhase1Error("GEP_UNCERTAIN_INCOMPLETE")
        if gep["execution_id"] != descriptor["execution_id"] or gep["status"] != "UNCERTAIN":
            raise RelayPhase1Error("GEP_UNCERTAIN_CORRELATION_CONFLICT")
        return {k: gep[k] for k in required}

    def _ensure_outbox_pending(self, handoff: dict[str, Any], proof: dict[str, Any]) -> dict[str, Any]:
        execution_id = handoff["execution_id"]
        path = self._outbox_path(execution_id)
        existing = load_json(path)
        expected = {
            "schema_version": "DGER_PHASE1_COMPLETION_OUTBOX_V1",
            "phase": OUTBOX_PENDING,
            "execution_id": execution_id,
            "handoff_id": handoff["handoff_id"],
            "v1_action_id": handoff["v1_action_id"],
            "terminal_proof": proof,
            "wake_event": {
                "schema_version": "DGER_PHASE1_V1_WAKE_V1",
                "v1_action_id": handoff["v1_action_id"],
                "execution_id": execution_id,
                "handoff_id": handoff["handoff_id"],
            },
            "created_at_utc": utc(),
            "wake_attempts": 0,
            "acknowledged_at_utc": None,
        }
        if existing is None:
            atomic_json(path, expected)
            return expected
        immutable = ("schema_version", "execution_id", "handoff_id", "v1_action_id", "terminal_proof", "wake_event")
        if any(existing.get(k) != expected.get(k) for k in immutable):
            raise RelayPhase1Error("OUTBOX_CONFLICT")
        return existing

    def process(self, handoff_id: str) -> dict[str, Any]:
        if not HANDOFF_RE.fullmatch(handoff_id):
            raise RelayPhase1Error("INVALID_HANDOFF_ID")
        handoff = self.chm.get_handoff(handoff_id)
        execution_id = handoff["execution_id"]
        descriptor = handoff["execution_descriptor"]
        if descriptor.get("execution_id") != execution_id or descriptor.get("chm_handoff_id") != handoff_id:
            raise RelayPhase1Error("HANDOFF_DESCRIPTOR_CONFLICT")
        self._save_execution(execution_id, {"handoff_id": handoff_id, "execution_id": execution_id, "descriptor_digest": handoff["execution_descriptor_digest"], "phase": "RECEIVED"})
        self._crash("after_request_receipt")

        allocation = self._find_or_acquire_capacity(handoff)
        capacity_state = self._ensure_running(allocation)
        self._save_execution(execution_id, {"handoff_id": handoff_id, "execution_id": execution_id, "descriptor_digest": handoff["execution_descriptor_digest"], "phase": "CAPACITY_RUNNING" if capacity_state == "RUNNING" else "CAPACITY_BLOCKED", **allocation})

        gep = self.gep.reconcile(descriptor)
        if gep.get("status") in {"ABSENT", "NOT_STARTED"}:
            if capacity_state == "BLOCKED":
                raise RelayPhase1Error("BLOCKED_CAPACITY_CANNOT_START")
            self._crash("before_gep_start_request")
            gep = self.gep.start(descriptor)
            self._crash("after_gep_start_request")
        if gep.get("status") == "UNCERTAIN":
            self._ensure_blocked(allocation)
            proof = self._uncertain_proof_from_gep(descriptor, gep)
            self._save_execution(execution_id, {"handoff_id": handoff_id, "execution_id": execution_id, "descriptor_digest": handoff["execution_descriptor_digest"], "phase": "UNCERTAIN", "uncertain_proof": proof, **allocation})
            published = self.chm.publish_uncertain(handoff_id, proof)
            if published.get("status") in TERMINAL:
                return {"status": published["status"], "execution_id": execution_id, "handoff_id": handoff_id}
            if published.get("status") != "UNCERTAIN" or published.get("uncertain_result", {}).get("descriptor_digest") != proof["descriptor_digest"]:
                raise RelayPhase1Error("CHM_UNCERTAIN_VERIFICATION_FAILED")
            return {"status": "UNCERTAIN", "execution_id": execution_id, "handoff_id": handoff_id}
        if gep.get("status") not in TERMINAL:
            return {"status": "PENDING", "execution_id": execution_id, "handoff_id": handoff_id}

        self._crash("after_gep_terminal_truth")
        proof = self._proof_from_gep(descriptor, gep)
        self._crash("before_outbox_pending")
        outbox = self._ensure_outbox_pending(handoff, proof)
        self._crash("after_outbox_pending_before_chm_publication")

        published = self.chm.publish_terminal(handoff_id, proof)
        if published.get("terminal_result") != {
            "status": proof["status"],
            "result_manifest_reference": proof["result_manifest_reference"],
            "result_manifest_digest": proof["result_manifest_digest"],
            "descriptor_digest": proof["descriptor_digest"],
        }:
            raise RelayPhase1Error("CHM_TERMINAL_VERIFICATION_FAILED")
        self._crash("after_chm_publication_before_delivery_state")

        outbox = load_json(self._outbox_path(execution_id)) or outbox
        if outbox["phase"] == OUTBOX_PENDING:
            outbox["phase"] = DELIVERY_REQUIRED
            outbox["chm_verified_at_utc"] = utc()
            atomic_json(self._outbox_path(execution_id), outbox)
        try:
            self.chm.capacity_status(allocation["slot"], allocation["allocation_id"], "RELEASED")
        except Exception:
            pass
        return self.deliver(execution_id)

    def deliver(self, execution_id: str) -> dict[str, Any]:
        path = self._outbox_path(execution_id)
        outbox = load_json(path)
        if outbox is None:
            raise RelayPhase1Error("OUTBOX_NOT_FOUND")
        if outbox["phase"] == ACKNOWLEDGED:
            return {"status": ACKNOWLEDGED, "execution_id": execution_id}
        if outbox["phase"] not in {OUTBOX_PENDING, DELIVERY_REQUIRED}:
            raise RelayPhase1Error("OUTBOX_STATE_INVALID")
        if outbox["phase"] == OUTBOX_PENDING:
            handoff = self.chm.get_handoff(outbox["handoff_id"])
            expected_terminal = {
                "status": outbox["terminal_proof"]["status"],
                "result_manifest_reference": outbox["terminal_proof"]["result_manifest_reference"],
                "result_manifest_digest": outbox["terminal_proof"]["result_manifest_digest"],
                "descriptor_digest": outbox["terminal_proof"]["descriptor_digest"],
            }
            if handoff.get("terminal_result") != expected_terminal:
                published = self.chm.publish_terminal(outbox["handoff_id"], outbox["terminal_proof"])
                if published.get("terminal_result") != expected_terminal:
                    raise RelayPhase1Error("CHM_TERMINAL_RECOVERY_FAILED")
            outbox["phase"] = DELIVERY_REQUIRED
        outbox["wake_attempts"] = int(outbox.get("wake_attempts", 0)) + 1
        outbox["last_wake_attempt_at_utc"] = utc()
        atomic_json(path, outbox)
        self._crash("during_wake")
        self.wake.deliver(dict(outbox["wake_event"]))
        self._crash("after_wake_before_acknowledgment")
        return {"status": DELIVERY_REQUIRED, "execution_id": execution_id, "wake_attempts": outbox["wake_attempts"]}

    def acknowledge(self, execution_id: str, *, v1_action_id: str, handoff_id: str) -> dict[str, Any]:
        path = self._outbox_path(execution_id)
        outbox = load_json(path)
        if outbox is None:
            raise RelayPhase1Error("OUTBOX_NOT_FOUND")
        if outbox["v1_action_id"] != v1_action_id or outbox["handoff_id"] != handoff_id:
            raise RelayPhase1Error("ACK_CORRELATION_CONFLICT")
        if outbox["phase"] == ACKNOWLEDGED:
            return {"status": ACKNOWLEDGED, "execution_id": execution_id}
        if outbox["phase"] != DELIVERY_REQUIRED:
            raise RelayPhase1Error("ACK_BEFORE_DELIVERY_REQUIRED")
        outbox["phase"] = ACKNOWLEDGED
        outbox["acknowledged_at_utc"] = utc()
        atomic_json(path, outbox)
        return {"status": ACKNOWLEDGED, "execution_id": execution_id}
