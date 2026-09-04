from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .relay_protocol_base import (
    CHM_TOOL_ID, DgerError, EXECUTION_ID_RE, HANDOFF_ID_RE, HEX40_RE, HEX64_RE, INVOCATION_ID_RE,
    MAX_FILE_BYTES, MAX_FILES, MAX_PATH_BYTES, MAX_TOTAL_BYTES, MOH_CLOSURE_SCHEMA, MOH_ENVELOPE_SCHEMA,
    MOH_TOOL_ID, READY_SCHEMA, REQUEST_ID_RE, REQUEST_SCHEMA, SemanticGateway, canonical_digest, sha256,
)
from .relay_protocol_fs import moh_closure_digest


def _binding_projection(doctor: dict[str, Any]) -> dict[str, Any]:
    if doctor.get("schema") != "gtg-doctor/v2" or doctor.get("ok") is not True:
        raise DgerError("GTG_DOCTOR_INVALID")
    if doctor.get("callability_state") != "READY":
        raise DgerError("GTG_CAPABILITY_UNAVAILABLE", str(doctor.get("reason", "")))
    authority = doctor.get("authoritative_binding")
    delivered = doctor.get("delivered_binding")
    if not isinstance(authority, dict) or not isinstance(delivered, dict):
        raise DgerError("GTG_BINDING_MISSING")
    tool_identity = delivered.get("tool_identity")
    tool_tree = delivered.get("tool_tree")
    registry_identity = delivered.get("registry_identity") or doctor.get("registry_identity")
    if not isinstance(tool_identity, str) or HEX40_RE.fullmatch(tool_identity) is None:
        raise DgerError("GTG_TOOL_IDENTITY_INVALID")
    if not isinstance(tool_tree, str) or HEX40_RE.fullmatch(tool_tree) is None:
        raise DgerError("GTG_TOOL_TREE_INVALID")
    if not isinstance(registry_identity, str) or HEX40_RE.fullmatch(registry_identity) is None:
        raise DgerError("GTG_REGISTRY_IDENTITY_INVALID")
    return {
        "authoritative_binding": authority,
        "tool_identity": tool_identity,
        "tool_tree": tool_tree,
        "registry_identity": registry_identity,
    }


def resolve_tool_binding(gateway: SemanticGateway, tool_id: str, operations: tuple[str, ...]) -> dict[str, Any]:
    resolved: dict[str, Any] | None = None
    for operation in operations:
        projection = _binding_projection(gateway.doctor(tool_id, operation))
        if resolved is None:
            resolved = projection
        elif projection != resolved:
            raise DgerError("GTG_BINDING_CHANGED_DURING_ACCEPTANCE", tool_id)
    assert resolved is not None
    return {"tool_id": tool_id, "operations": list(operations), **resolved}


def _invocation_attestation(value: dict[str, Any], expected_tool: str, expected_operation: str) -> dict[str, Any]:
    """Validate GTG's exact invocation-time identity evidence for a successful call."""
    if value.get("ok") is not True:
        raise DgerError("GTG_INVOCATION_NOT_SUCCESSFUL", str(value.get("code", "")))
    invocation_id = value.get("invocation_id")
    if not isinstance(invocation_id, str) or INVOCATION_ID_RE.fullmatch(invocation_id) is None:
        raise DgerError("GTG_INVOCATION_ID_INVALID")
    attestation = value.get("identity_attestation")
    if not isinstance(attestation, dict) or set(attestation) != {"tool_identity", "tool_tree", "gtg_identity"}:
        raise DgerError("GTG_IDENTITY_ATTESTATION_REQUIRED")
    for key in ("tool_identity", "tool_tree", "gtg_identity"):
        observed = attestation.get(key)
        if not isinstance(observed, str) or HEX40_RE.fullmatch(observed) is None:
            raise DgerError("GTG_IDENTITY_ATTESTATION_INVALID", key)
    evidence = value.get("evidence")
    if not isinstance(evidence, dict):
        raise DgerError("GTG_INVOCATION_EVIDENCE_MISSING")
    if evidence.get("tool_id") != expected_tool:
        raise DgerError("GTG_INVOCATION_TOOL_MISMATCH")
    if evidence.get("tool_identity") != attestation["tool_identity"]:
        raise DgerError("GTG_INVOCATION_IDENTITY_MISMATCH")
    registry_identity = evidence.get("registry_identity")
    if not isinstance(registry_identity, str) or HEX40_RE.fullmatch(registry_identity) is None:
        raise DgerError("GTG_INVOCATION_REGISTRY_IDENTITY_INVALID")
    return {
        "tool_id": expected_tool,
        "operation": expected_operation,
        "invocation_id": invocation_id,
        "tool_identity": attestation["tool_identity"],
        "tool_tree": attestation["tool_tree"],
        "gtg_identity": attestation["gtg_identity"],
        "registry_identity": registry_identity,
    }


def _validate_consumer_binding(envelope: dict[str, Any], binding: dict[str, Any]) -> None:
    if binding.get("tool_identity") != envelope.get("authority_commit") or binding.get("tool_tree") != envelope.get("authority_tree"):
        raise DgerError("CONSUMER_BINDING_NOT_CURRENT_COMPATIBLE")
    authority = binding.get("authoritative_binding")
    if not isinstance(authority, dict):
        raise DgerError("CONSUMER_AUTHORITY_MISSING")
    if str(authority.get("repository_id")) != str(envelope.get("repository_id")):
        raise DgerError("CONSUMER_REPOSITORY_ID_MISMATCH")
    selector = authority.get("selector")
    if selector is not None and selector != envelope.get("authority_selector"):
        raise DgerError("CONSUMER_SELECTOR_MISMATCH")


def _intent_digest(
    request_raw: bytes,
    envelope_raw: bytes,
    manifest_digest: str,
    moh_binding: dict[str, Any],
    chm_binding: dict[str, Any],
    consumer_binding: dict[str, Any],
) -> str:
    return canonical_digest({
        "request_sha256": sha256(request_raw),
        "envelope_sha256": sha256(envelope_raw),
        "payload_manifest_sha256": manifest_digest,
        "moh_binding": moh_binding,
        "chm_binding": chm_binding,
        "consumer_binding": consumer_binding,
    })