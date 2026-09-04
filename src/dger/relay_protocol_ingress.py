from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .relay_protocol_base import (
    CHM_TOOL_ID, DgerError, EXECUTION_ID_RE, HANDOFF_ID_RE, HEX40_RE, HEX64_RE, MAX_FILE_BYTES, MAX_FILES,
    MAX_PATH_BYTES, MAX_TOTAL_BYTES, MOH_CLOSURE_SCHEMA, MOH_ENVELOPE_SCHEMA, MOH_TOOL_ID, READY_SCHEMA,
    REQUEST_ID_RE, REQUEST_SCHEMA, SemanticGateway, canonical_digest, sha256,
)
from .relay_protocol_fs import moh_closure_digest

def _validate_request(request: dict[str, Any], execution_id: str) -> None:
    expected = {"schema", "execution_id", "logical_handoff_id", "dger_request_id"}
    if set(request) != expected or request.get("schema") != REQUEST_SCHEMA:
        raise DgerError("MALFORMED_REQUEST")
    if request.get("execution_id") != execution_id or EXECUTION_ID_RE.fullmatch(execution_id) is None:
        raise DgerError("INVALID_EXECUTION_ID")
    handoff_id = request.get("logical_handoff_id")
    if not isinstance(handoff_id, str) or HANDOFF_ID_RE.fullmatch(handoff_id) is None:
        raise DgerError("INVALID_LOGICAL_HANDOFF_ID")
    request_id = request.get("dger_request_id")
    if not isinstance(request_id, str) or REQUEST_ID_RE.fullmatch(request_id) is None:
        raise DgerError("INVALID_DGER_REQUEST_ID")


def _validate_ready(
    ready: dict[str, Any],
    execution_id: str,
    request_raw: bytes,
    envelope_raw: bytes,
    entries: list[dict[str, Any]],
    total: int,
    manifest_digest: str,
) -> None:
    expected = {
        "schema", "execution_id", "request_sha256", "request_size", "envelope_sha256",
        "envelope_size", "payload_manifest_sha256", "payload_total_bytes", "payload_file_count",
    }
    if set(ready) != expected or ready.get("schema") != READY_SCHEMA or ready.get("execution_id") != execution_id:
        raise DgerError("MALFORMED_READY")
    checks = {
        "request_sha256": sha256(request_raw),
        "request_size": len(request_raw),
        "envelope_sha256": sha256(envelope_raw),
        "envelope_size": len(envelope_raw),
        "payload_manifest_sha256": manifest_digest,
        "payload_total_bytes": total,
        "payload_file_count": len(entries),
    }
    for key, actual in checks.items():
        if ready.get(key) != actual:
            raise DgerError("INGRESS_INTEGRITY_MISMATCH", key)


def validate_moh_envelope(envelope: dict[str, Any], execution_id: str, entries: list[dict[str, Any]]) -> None:
    keys = {
        "schema", "execution_id", "upstream_correlation_id", "tool_id", "repository_id",
        "authority_selector", "authority_commit", "authority_tree", "operation_id",
        "operation_contract_digest", "closure_digest", "parameters", "parameters_digest",
        "effect_class", "launch_context", "retry_policy", "request_digest",
    }
    if set(envelope) != keys or envelope.get("schema") != MOH_ENVELOPE_SCHEMA:
        raise DgerError("INVALID_MOH_ENVELOPE")
    if envelope.get("execution_id") != execution_id:
        raise DgerError("MOH_EXECUTION_ID_MISMATCH")
    if envelope.get("authority_selector") != "refs/heads/main":
        raise DgerError("UNSUPPORTED_AUTHORITY_SELECTOR")
    if not isinstance(envelope.get("tool_id"), str) or not envelope["tool_id"]:
        raise DgerError("INVALID_CONSUMER_TOOL_ID")
    if not isinstance(envelope.get("operation_id"), str) or not envelope["operation_id"]:
        raise DgerError("INVALID_OPERATION_ID")
    for key in ("authority_commit", "authority_tree"):
        value = envelope.get(key)
        if not isinstance(value, str) or HEX40_RE.fullmatch(value) is None:
            raise DgerError("INVALID_CONSUMER_BINDING", key)
    for key in ("operation_contract_digest", "closure_digest", "parameters_digest", "request_digest"):
        value = envelope.get(key)
        if not isinstance(value, str) or HEX64_RE.fullmatch(value) is None:
            raise DgerError("INVALID_MOH_DIGEST", key)
    if envelope.get("closure_digest") != moh_closure_digest(entries):
        raise DgerError("MOH_CLOSURE_DIGEST_MISMATCH")
    body = dict(envelope)
    supplied = body.pop("request_digest")
    if canonical_digest(body) != supplied:
        raise DgerError("MOH_REQUEST_DIGEST_MISMATCH")
