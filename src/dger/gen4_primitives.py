from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
from datetime import datetime, timezone
from typing import Any

PROTOCOL = "DGER_EXECUTION_RELAY_V2"
REQUEST_SCHEMA = "dger-execution-relay-request/v2"
READY_SCHEMA = "dger-execution-relay-ready/v2"
RESULT_SCHEMA = "dger-external-effect-result/v2"
SERVICE_IDENTITY_SCHEMA = "dger-execution-relay-service-identity/v1"
TRUSTED_CORRELATION_SCHEMA = "dger-trusted-correlation/v1"

MAX_REQUEST_BYTES = 32_768
MAX_ADMISSION_BYTES = 128 * 1024
MAX_FILES = 64
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_PATH_BYTES = 240
MAX_RESULT_BYTES = 512 * 1024
MAX_PEER_OBSERVATION_BYTES = 512 * 1024
MAX_ERROR_BYTES = 512

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

MOH_SAFE_TO_FIRST_OR_PROVEN_RETRY = {"NOT_FOUND", "ADMITTED"}
MOH_NONTERMINAL = {"START_INTENT_COMMITTED", "RUNNING"}
MOH_TERMINAL = {"SUCCEEDED", "FAILED", "REJECTED_PRECONDITION", "REJECTED_DUPLICATE_MISMATCH"}
MOH_ALL = MOH_SAFE_TO_FIRST_OR_PROVEN_RETRY | MOH_NONTERMINAL | MOH_TERMINAL | {"IN_DOUBT"}


class DgerGen4Error(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_file_bytes(value: Any) -> bytes:
    return canonical_bytes(value) + b"\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: Any) -> str:
    return sha256(canonical_bytes(value))


def _json_object_no_duplicates(raw: bytes) -> dict[str, Any]:
    def hook(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise DgerGen4Error("DUPLICATE_JSON_KEY", key)
            out[key] = value
        return out
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=hook)
    except DgerGen4Error:
        raise
    except Exception as exc:
        raise DgerGen4Error("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise DgerGen4Error("JSON_OBJECT_REQUIRED")
    return value


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_regular(path: Path, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise DgerGen4Error("UNSAFE_OR_MISSING_FILE", path.name) from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise DgerGen4Error("UNSAFE_FILE_TYPE", path.name)
        if st.st_size > limit:
            raise DgerGen4Error("FILE_TOO_LARGE", path.name)
        raw = os.read(fd, st.st_size + 1)
        if len(raw) != st.st_size:
            raise DgerGen4Error("FILE_CHANGED_DURING_READ", path.name)
        return raw
    finally:
        os.close(fd)


def read_protected_regular(path: Path, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise DgerGen4Error("PROTECTED_FILE_UNSAFE_OR_MISSING", path.name) from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077:
            raise DgerGen4Error("PROTECTED_FILE_PERMISSIONS", path.name)
        if st.st_size > limit:
            raise DgerGen4Error("PROTECTED_FILE_TOO_LARGE", path.name)
        raw = os.read(fd, st.st_size + 1)
        if len(raw) != st.st_size:
            raise DgerGen4Error("PROTECTED_FILE_CHANGED", path.name)
        return raw
    finally:
        os.close(fd)


def atomic_bytes(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise DgerGen4Error("UNSAFE_PARENT", str(path.parent))
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def atomic_json(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    atomic_bytes(path, canonical_file_bytes(value), mode)


def _safe_id(value: Any, code: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise DgerGen4Error(code)
    return value


def _safe_rel(value: str) -> PurePosixPath:
    if len(value.encode("utf-8")) > MAX_PATH_BYTES:
        raise DgerGen4Error("PAYLOAD_PATH_TOO_LONG")
    p = PurePosixPath(value)
    if p.is_absolute() or not p.parts or any(part in {"", ".", ".."} for part in p.parts):
        raise DgerGen4Error("UNSAFE_PAYLOAD_PATH", value)
    return p


def payload_manifest(root: Path) -> tuple[list[dict[str, Any]], int, str]:
    if root.is_symlink() or not root.is_dir():
        raise DgerGen4Error("PAYLOAD_ROOT_UNSAFE")
    entries: list[dict[str, Any]] = []
    total = 0
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        rel = path.relative_to(root).as_posix()
        _safe_rel(rel)
        try:
            st = path.lstat()
        except OSError as exc:
            raise DgerGen4Error("PAYLOAD_STAT_FAILED", rel) from exc
        if stat.S_ISDIR(st.st_mode):
            if path.is_symlink():
                raise DgerGen4Error("PAYLOAD_SYMLINK_FORBIDDEN", rel)
            continue
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise DgerGen4Error("PAYLOAD_NONREGULAR_FORBIDDEN", rel)
        if len(entries) >= MAX_FILES:
            raise DgerGen4Error("PAYLOAD_FILE_LIMIT")
        raw = read_regular(path, MAX_FILE_BYTES)
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise DgerGen4Error("PAYLOAD_TOTAL_LIMIT")
        entries.append({"path": rel, "size": len(raw), "sha256": sha256(raw)})
    manifest = canonical_digest({"files": entries, "total_bytes": total})
    return entries, total, manifest


def _copy_payload_verified(source: Path, target: Path, entries: list[dict[str, Any]]) -> None:
    target.mkdir(parents=True, exist_ok=False)
    for item in entries:
        rel = _safe_rel(item["path"])
        src = source.joinpath(*rel.parts)
        raw = read_regular(src, MAX_FILE_BYTES)
        if len(raw) != item["size"] or sha256(raw) != item["sha256"]:
            raise DgerGen4Error("PAYLOAD_CHANGED_DURING_COPY", item["path"])
        dst = target.joinpath(*rel.parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.parent.is_symlink():
            raise DgerGen4Error("UNSAFE_PAYLOAD_TARGET", item["path"])
        atomic_bytes(dst, raw)
    observed, _, _ = payload_manifest(target)
    if observed != entries:
        raise DgerGen4Error("PAYLOAD_COPY_READBACK_MISMATCH")


def _validate_request(value: dict[str, Any], package_id: str) -> None:
    expected = {"schema", "dger_request_id", "gep_execution_id", "ahc_effect_reservation_id", "chm_handoff_id"}
    if set(value) != expected or value.get("schema") != REQUEST_SCHEMA:
        raise DgerGen4Error("MALFORMED_REQUEST")
    request_id = _safe_id(value.get("dger_request_id"), "INVALID_DGER_REQUEST_ID")
    if request_id != package_id:
        raise DgerGen4Error("DGER_REQUEST_ID_DIRECTORY_MISMATCH")
    _safe_id(value.get("gep_execution_id"), "INVALID_GEP_EXECUTION_ID")
    _safe_id(value.get("ahc_effect_reservation_id"), "INVALID_AHC_EFFECT_ID")
    handoff = value.get("chm_handoff_id")
    if handoff is not None:
        _safe_id(handoff, "INVALID_CHM_HANDOFF_ID")


def make_ready_record(request_raw: bytes, admission_raw: bytes, payload_root: Path, dger_request_id: str) -> dict[str, Any]:
    """Deterministic transport-only producer helper; it grants no execution authority."""
    entries, total, manifest_digest = payload_manifest(payload_root)
    return {
        "schema": READY_SCHEMA,
        "dger_request_id": dger_request_id,
        "request_sha256": sha256(request_raw),
        "request_size": len(request_raw),
        "admission_sha256": sha256(admission_raw),
        "admission_size": len(admission_raw),
        "payload_manifest_sha256": manifest_digest,
        "payload_total_bytes": total,
        "payload_file_count": len(entries),
    }


def _validate_ready(value: dict[str, Any], expected: dict[str, Any]) -> None:
    if set(value) != set(expected) or value != expected:
        raise DgerGen4Error("INGRESS_INTEGRITY_MISMATCH")
