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

from .relay_state_store import _copy_payload_verified, _safe_execution_dir, _stage_digest, save_state

def materialize_moh_stage(frozen_stage: Path, moh_inbox: Path, execution_id: str, expected_stage_digest: str) -> Path:
    if moh_inbox.is_symlink():
        raise DgerError("UNSAFE_MOH_INBOX")
    moh_inbox.mkdir(parents=True, exist_ok=True)
    final = moh_inbox / execution_id
    # Crash leftovers from DGER's own unpublished temporary stage are safe to remove.
    # A final execution_id path is never deleted: it may contain MOH-visible or foreign truth.
    for orphan in moh_inbox.glob(f".{execution_id}.dger-*"):
        try:
            if orphan.is_symlink() or not orphan.is_dir():
                raise DgerError("MOH_TEMP_STAGE_UNSAFE", str(orphan))
            shutil.rmtree(orphan)
        except FileNotFoundError:
            pass
    if final.exists():
        if final.is_symlink() or not final.is_dir():
            raise DgerError("MOH_STAGE_CONFLICT")
        if _stage_digest(final) != expected_stage_digest:
            raise DgerError("MOH_STAGE_CONFLICT")
        return final
    tmp = moh_inbox / f".{execution_id}.dger-{os.getpid()}-{secrets.token_hex(6)}"
    if tmp.exists():
        raise DgerError("MOH_TEMP_COLLISION")
    try:
        tmp.mkdir(mode=0o700)
        envelope = read_regular(frozen_stage / "envelope.json", MAX_ENVELOPE_BYTES)
        atomic_bytes(tmp / "envelope.json", envelope)
        entries, _, _ = payload_manifest(frozen_stage / "payload")
        _copy_payload_verified(frozen_stage / "payload", tmp / "payload", entries)
        if _stage_digest(tmp) != expected_stage_digest:
            raise DgerError("MOH_STAGE_READBACK_MISMATCH")
        _fsync_dir(tmp)
        try:
            os.rename(tmp, final)
        except FileExistsError:
            if _stage_digest(final) != expected_stage_digest:
                raise DgerError("MOH_STAGE_CONFLICT")
            shutil.rmtree(tmp, ignore_errors=True)
        _fsync_dir(moh_inbox)
        if _stage_digest(final) != expected_stage_digest:
            raise DgerError("MOH_STAGE_READBACK_MISMATCH")
        return final
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def freeze_ingress(package: Path, state_root: Path, execution_id: str) -> tuple[Path, bytes, bytes, list[dict[str, Any]], str]:
    request_raw = read_regular(package / "request.json", MAX_REQUEST_BYTES)
    envelope_raw = read_regular(package / "envelope.json", MAX_ENVELOPE_BYTES)
    request = _json_object_no_duplicates(request_raw)
    envelope = _json_object_no_duplicates(envelope_raw)
    _validate_request(request, execution_id)
    entries, total, manifest_digest = payload_manifest(package / "payload")
    validate_moh_envelope(envelope, execution_id, entries)
    ready, _ = read_json_regular(package / "READY.json", MAX_REQUEST_BYTES)
    _validate_ready(ready, execution_id, request_raw, envelope_raw, entries, total, manifest_digest)

    frozen_parent = state_root / "frozen"
    frozen_parent.mkdir(parents=True, exist_ok=True)
    if frozen_parent.is_symlink():
        raise DgerError("UNSAFE_FROZEN_ROOT")
    final = frozen_parent / execution_id
    expected_stage_digest = canonical_digest({
        "envelope_sha256": sha256(envelope_raw),
        "payload_manifest_sha256": manifest_digest,
        "files": entries,
    })
    if final.exists():
        if final.is_symlink() or _stage_digest(final) != expected_stage_digest:
            raise DgerError("FROZEN_STAGE_CONFLICT")
        existing_request = read_regular(final / "request.json", MAX_REQUEST_BYTES)
        if existing_request != request_raw:
            raise DgerError("FROZEN_REQUEST_CONFLICT")
        return final, request_raw, envelope_raw, entries, manifest_digest

    tmp = frozen_parent / f".{execution_id}.freeze-{os.getpid()}-{secrets.token_hex(6)}"
    try:
        tmp.mkdir(mode=0o700)
        atomic_bytes(tmp / "request.json", request_raw)
        atomic_bytes(tmp / "envelope.json", envelope_raw)
        _copy_payload_verified(package / "payload", tmp / "payload", entries)
        if read_regular(tmp / "request.json", MAX_REQUEST_BYTES) != request_raw or _stage_digest(tmp) != expected_stage_digest:
            raise DgerError("FROZEN_STAGE_READBACK_MISMATCH")
        _fsync_dir(tmp)
        os.rename(tmp, final)
        _fsync_dir(frozen_parent)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final, request_raw, envelope_raw, entries, manifest_digest
