from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Mapping

from .phase1 import Phase1Relay, RelayPhase1Error, atomic_json, canonical, load_json

HANDOFF_RE = re.compile(r"execution_handoff_[0-9a-f]{64}\Z")
EXECUTION_RE = re.compile(r"execution_[0-9a-f]{64}\Z")
ACTION_RE = re.compile(r"[0-9a-f]{64}\Z")
GIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")


def _run_json(argv: list[str], *, timeout: int = 60, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=None if env is None else dict(env))
    try:
        value = json.loads(cp.stdout)
    except Exception as exc:
        raise RelayPhase1Error("GOVERNED_TOOL_INVALID_RESULT") from exc
    if not isinstance(value, dict) or cp.returncode not in (0, 2):
        raise RelayPhase1Error("GOVERNED_TOOL_INVOCATION_FAILED")
    return value


def _temp_json(value: Mapping[str, Any]):
    class TempJson:
        def __enter__(self):
            fd, raw = tempfile.mkstemp(prefix="dger-phase1-", suffix=".json")
            self.path = Path(raw)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as fh:
                fh.write(canonical(dict(value)))
                fh.flush()
                os.fsync(fh.fileno())
            return self.path

        def __exit__(self, exc_type, exc, tb):
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
    return TempJson()


class CHMCLI:
    def __init__(self, executable: Path, principal_git_identity: str, context_file: Path) -> None:
        self.executable = Path(executable)
        self.principal = principal_git_identity
        self.context_file = Path(context_file)
        if not self.executable.is_file() or self.executable.is_symlink() or not os.access(self.executable, os.X_OK):
            raise RelayPhase1Error("CHM_UNAVAILABLE")
        if not GIT_RE.fullmatch(self.principal):
            raise RelayPhase1Error("PRINCIPAL_GIT_IDENTITY_INVALID")
        if not self.context_file.is_file() or self.context_file.is_symlink():
            raise RelayPhase1Error("CHM_CONTEXT_UNAVAILABLE")

    def _call(self, args: list[str]) -> dict[str, Any]:
        env = os.environ.copy()
        env["HANDOFF_MANAGER_CONTEXT_FILE"] = str(self.context_file)
        value = _run_json([str(self.executable), *args], env=env)
        if not value.get("ok"):
            raise RelayPhase1Error(f"CHM_{value.get('code', 'FAILED')}")
        return value

    def get_handoff(self, handoff_id: str) -> dict[str, Any]:
        return self._call(["execution-handoff", "get", handoff_id])

    def active_capacity(self) -> list[dict[str, Any]]:
        value = self._call(["execution", "active"])
        active = value.get("active")
        if not isinstance(active, list):
            raise RelayPhase1Error("CHM_EXECUTION_ACTIVE_INVALID")
        return active

    def acquire_capacity(self, execution_id: str) -> dict[str, Any]:
        return self._call(["execution", "acquire", "ai-me", execution_id, self.principal])

    def bind_capacity(self, handoff_id: str, execution_id: str, slot: str, allocation_id: str) -> dict[str, Any]:
        return self._call(["execution-handoff", "bind-slot", handoff_id, execution_id, slot, allocation_id])

    def capacity_status(self, slot: str, allocation_id: str, status: str) -> dict[str, Any]:
        return self._call(["execution", "status", slot, allocation_id, status])

    def publish_terminal(self, handoff_id: str, proof: dict[str, Any]) -> dict[str, Any]:
        with _temp_json(proof) as path:
            return self._call(["execution-handoff", "publish-terminal", handoff_id, str(path)])


class GEPCLI:
    def __init__(self, launcher: Path) -> None:
        self.launcher = Path(launcher)
        if not self.launcher.is_file() or self.launcher.is_symlink() or not os.access(self.launcher, os.X_OK):
            raise RelayPhase1Error("GEP_LAUNCHER_UNAVAILABLE")

    def _call(self, operation: str, descriptor: dict[str, Any]) -> dict[str, Any]:
        if operation not in {"execution-start", "execution-reconcile"}:
            raise RelayPhase1Error("GEP_OPERATION_INVALID")
        with _temp_json(descriptor) as path:
            value = _run_json([str(self.launcher), operation, str(path)], timeout=180)
        if value.get("ok") is False:
            raise RelayPhase1Error(f"GEP_{value.get('code', 'FAILED')}")
        return value

    def reconcile(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        return self._call("execution-reconcile", descriptor)

    def start(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        return self._call("execution-start", descriptor)


class DropboxWake:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise RelayPhase1Error("WAKE_ROOT_UNSAFE")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = self.root.resolve(strict=True)

    def deliver(self, event: dict[str, Any]) -> None:
        execution_id = event.get("execution_id")
        if not isinstance(execution_id, str) or not EXECUTION_RE.fullmatch(execution_id):
            raise RelayPhase1Error("WAKE_EXECUTION_ID_INVALID")
        path = self.root / f"{execution_id}.json"
        existing = load_json(path)
        if existing is not None:
            if existing != event:
                raise RelayPhase1Error("WAKE_CONFLICT")
            return
        atomic_json(path, event)
        os.chmod(path, 0o644)


class Phase1Transport:
    """Dropbox carries only a pointer to an already-durable CHM Execution Handoff."""

    def __init__(self, transport_root: Path, relay: Phase1Relay) -> None:
        self.root = Path(transport_root)
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise RelayPhase1Error("PHASE1_TRANSPORT_UNSAFE")
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve(strict=True)
        self.ingress = self.root / "Ingress"
        self.runs = self.root / "Runs"
        self.acks = self.root / "Acks"
        for path in (self.ingress, self.runs, self.acks):
            if path.exists() and path.is_symlink():
                raise RelayPhase1Error("PHASE1_TRANSPORT_UNSAFE")
            path.mkdir(parents=True, exist_ok=True)
        self.relay = relay

    @staticmethod
    def _load_request(path: Path) -> dict[str, Any]:
        value = load_json(path)
        if value is None:
            raise RelayPhase1Error("PHASE1_REQUEST_MISSING")
        required = {"schema_version", "handoff_id"}
        if set(value) != required or value.get("schema_version") != "DGER_PHASE1_REQUEST_V1":
            raise RelayPhase1Error("PHASE1_REQUEST_INVALID")
        if not isinstance(value.get("handoff_id"), str) or not HANDOFF_RE.fullmatch(value["handoff_id"]):
            raise RelayPhase1Error("PHASE1_REQUEST_INVALID")
        return value

    @staticmethod
    def _load_ready(path: Path, request_bytes: bytes, handoff_id: str) -> None:
        value = load_json(path)
        if value is None:
            raise RelayPhase1Error("PHASE1_READY_MISSING")
        required = {"schema_version", "handoff_id", "request_sha256", "request_size"}
        if set(value) != required or value.get("schema_version") != "DGER_PHASE1_READY_V1" or value.get("handoff_id") != handoff_id:
            raise RelayPhase1Error("PHASE1_READY_INVALID")
        if value.get("request_size") != len(request_bytes) or value.get("request_sha256") != hashlib.sha256(request_bytes).hexdigest():
            raise RelayPhase1Error("PHASE1_REQUEST_INTEGRITY_MISMATCH")

    def process_dir(self, directory: Path) -> None:
        if directory.is_symlink() or not directory.is_dir() or not HANDOFF_RE.fullmatch(directory.name):
            return
        request_path = directory / "request.json"
        ready_path = directory / "READY.json"
        if not ready_path.exists() or not request_path.exists():
            return
        request = self._load_request(request_path)
        request_bytes = request_path.read_bytes()
        if request_bytes != canonical(request):
            raise RelayPhase1Error("PHASE1_REQUEST_NONCANONICAL")
        self._load_ready(ready_path, request_bytes, request["handoff_id"])
        if request["handoff_id"] != directory.name:
            raise RelayPhase1Error("PHASE1_HANDOFF_PATH_MISMATCH")
        result = self.relay.process(request["handoff_id"])
        atomic_json(self.runs / f"{directory.name}.json", result)
        os.chmod(self.runs / f"{directory.name}.json", 0o644)

    def process_acks(self) -> None:
        for path in sorted(self.acks.glob("execution_*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            value = load_json(path)
            if value is None:
                continue
            required = {"schema_version", "execution_id", "v1_action_id", "handoff_id"}
            if set(value) != required or value.get("schema_version") != "DGER_PHASE1_ACK_V1":
                continue
            execution_id = value.get("execution_id")
            if not isinstance(execution_id, str) or not EXECUTION_RE.fullmatch(execution_id):
                continue
            if not isinstance(value.get("v1_action_id"), str) or not ACTION_RE.fullmatch(value["v1_action_id"]):
                continue
            if not isinstance(value.get("handoff_id"), str) or not HANDOFF_RE.fullmatch(value["handoff_id"]):
                continue
            self.relay.acknowledge(execution_id, v1_action_id=value["v1_action_id"], handoff_id=value["handoff_id"])

    def recover_outbox(self) -> None:
        outbox_root = self.relay.state_root / "outbox"
        if not outbox_root.exists():
            return
        for path in sorted(outbox_root.glob("execution_*.json")):
            value = load_json(path)
            if value is None or value.get("phase") == "ACKNOWLEDGED":
                continue
            execution_id = value.get("execution_id")
            if isinstance(execution_id, str) and EXECUTION_RE.fullmatch(execution_id):
                self.relay.deliver(execution_id)

    def scan_once(self) -> None:
        self.process_acks()
        self.recover_outbox()
        for directory in sorted(self.ingress.iterdir(), key=lambda p: p.name):
            try:
                self.process_dir(directory)
            except RelayPhase1Error:
                continue
