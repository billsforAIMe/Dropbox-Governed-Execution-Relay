from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
from typing import Any

from .relay_protocol_base import (
    DgerError, MAX_FILE_BYTES, MAX_FILES, MAX_PATH_BYTES, MAX_RESULT_RECORD_BYTES, MAX_TOTAL_BYTES, MOH_CLOSURE_SCHEMA, PAYLOAD_MANIFEST_SCHEMA,
    canonical_bytes, canonical_digest, canonical_file_bytes, sha256,
)

def _json_object_no_duplicates(data: bytes) -> dict[str, Any]:
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise DgerError("DUPLICATE_JSON_KEY", key)
            out[key] = value
        return out

    def reject_constant(value: str) -> None:
        raise DgerError("INVALID_JSON_NUMBER", value)

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=hook, parse_constant=reject_constant)
    except DgerError:
        raise
    except Exception as exc:
        raise DgerError("INVALID_JSON", str(exc)) from exc
    if not isinstance(value, dict):
        raise DgerError("JSON_OBJECT_REQUIRED")

    def walk(item: Any, depth: int = 0) -> None:
        if depth > 12:
            raise DgerError("JSON_TOO_DEEP")
        if item is None or isinstance(item, (bool, int)):
            return
        if isinstance(item, float):
            import math
            if not math.isfinite(item):
                raise DgerError("INVALID_JSON_NUMBER")
            return
        if isinstance(item, str):
            if len(item) > 8192:
                raise DgerError("JSON_STRING_TOO_LONG")
            return
        if isinstance(item, list):
            if len(item) > 128:
                raise DgerError("JSON_ARRAY_TOO_LONG")
            for child in item:
                walk(child, depth + 1)
            return
        if isinstance(item, dict):
            if len(item) > 64:
                raise DgerError("JSON_OBJECT_TOO_LARGE")
            for key, child in item.items():
                if len(key) > 8192:
                    raise DgerError("JSON_KEY_TOO_LONG")
                walk(child, depth + 1)
            return
        raise DgerError("UNSUPPORTED_JSON_TYPE")

    walk(value)
    return value


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise DgerError("UNSAFE_PARENT", str(path.parent))
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
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


def read_regular(path: Path, max_bytes: int) -> bytes:
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise DgerError("UNSAFE_FILE_TYPE", str(path))
    if st.st_size > max_bytes:
        raise DgerError("FILE_TOO_LARGE", str(path))
    data = path.read_bytes()
    if len(data) != st.st_size:
        raise DgerError("FILE_CHANGED_DURING_READ", str(path))
    return data


def read_json_regular(path: Path, max_bytes: int = MAX_RESULT_RECORD_BYTES) -> tuple[dict[str, Any], bytes]:
    data = read_regular(path, max_bytes)
    return _json_object_no_duplicates(data), data


def _safe_rel(path: str) -> None:
    p = PurePosixPath(path)
    if p.is_absolute() or not p.parts or any(part in {"", ".", ".."} for part in p.parts):
        raise DgerError("UNSAFE_PAYLOAD_PATH", path)
    if len(path.encode("utf-8")) > MAX_PATH_BYTES:
        raise DgerError("PAYLOAD_PATH_TOO_LONG", path)


def payload_manifest(root: Path) -> tuple[list[dict[str, Any]], int, str]:
    if root.is_symlink() or not root.is_dir():
        raise DgerError("PAYLOAD_MISSING_OR_UNSAFE")
    entries: list[dict[str, Any]] = []
    total = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        base_path = Path(base)
        for name in dirs:
            full = base_path / name
            if full.is_symlink():
                raise DgerError("PAYLOAD_SYMLINK_FORBIDDEN", str(full))
        for name in files:
            full = base_path / name
            st = full.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                raise DgerError("PAYLOAD_REGULAR_FILES_ONLY", str(full))
            rel = full.relative_to(root).as_posix()
            _safe_rel(rel)
            if st.st_size > MAX_FILE_BYTES:
                raise DgerError("PAYLOAD_FILE_TOO_LARGE", rel)
            total += st.st_size
            if total > MAX_TOTAL_BYTES:
                raise DgerError("PAYLOAD_TOO_LARGE")
            data = full.read_bytes()
            if len(data) != st.st_size:
                raise DgerError("PAYLOAD_CHANGED_DURING_READ", rel)
            entries.append({"path": rel, "size": st.st_size, "sha256": sha256(data)})
            if len(entries) > MAX_FILES:
                raise DgerError("PAYLOAD_TOO_MANY_FILES")
    entries.sort(key=lambda item: item["path"])
    if not entries:
        raise DgerError("EMPTY_PAYLOAD")
    manifest_digest = canonical_digest({"schema": PAYLOAD_MANIFEST_SCHEMA, "files": entries})
    return entries, total, manifest_digest


def moh_closure_digest(entries: list[dict[str, Any]]) -> str:
    return canonical_digest({"schema": MOH_CLOSURE_SCHEMA, "files": entries})
