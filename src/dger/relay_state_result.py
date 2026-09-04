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

def _unwrap_gtg_result(value: dict[str, Any], expected_tool: str, expected_operation: str) -> tuple[dict[str, Any] | None, str | None]:
    invocation_id = value.get("invocation_id") if isinstance(value.get("invocation_id"), str) else None
    if value.get("ok") is True and isinstance(value.get("result"), dict):
        return value["result"], invocation_id
    return None, invocation_id


def _validate_moh_response(response: dict[str, Any], execution_id: str) -> str:
    if response.get("execution_id") != execution_id:
        raise DgerError("MOH_RESPONSE_EXECUTION_ID_MISMATCH")
    state = response.get("state")
    if not isinstance(state, str):
        raise DgerError("MOH_RESPONSE_STATE_MISSING")
    if state not in MOH_TERMINAL_PUBLISHABLE | MOH_UNRESOLVED | MOH_NONTERMINAL:
        raise DgerError("MOH_RESPONSE_STATE_UNKNOWN", state)
    raw = canonical_bytes(response)
    if len(raw) > MAX_MOH_RESPONSE_BYTES:
        raise DgerError("MOH_RESPONSE_TOO_LARGE")
    return state


def _compact_moh_evidence(response: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "state": response.get("state"),
        "request_digest": response.get("request_digest"),
        "receipt_digest": response.get("receipt_digest"),
        "result_digest": response.get("result_digest"),
        "failure_code": response.get("failure_code"),
        "exit_status": response.get("exit_status"),
    }
    for stream in ("stdout", "stderr"):
        value = response.get(stream)
        if isinstance(value, dict):
            out[stream] = {
                key: value.get(key)
                for key in ("digest", "total_bytes", "retained_bytes", "truncated", "evidence_ref")
                if key in value
            }
    return out


def _result_record(state: dict[str, Any], moh_response: dict[str, Any], evidence_ref: str) -> dict[str, Any]:
    envelope = state["envelope"]
    return {
        "schema": PROTOCOL,
        "execution_id": state["execution_id"],
        "dger_request_id": state["dger_request_id"],
        "logical_handoff_id": state["logical_handoff_id"],
        "terminal_disposition": moh_response["state"],
        "consumer_binding": {
            "tool_id": envelope["tool_id"],
            "repository_id": envelope["repository_id"],
            "authority_selector": envelope["authority_selector"],
            "authority_commit": envelope["authority_commit"],
            "authority_tree": envelope["authority_tree"],
            "operation_id": envelope["operation_id"],
            "operation_contract_digest": envelope["operation_contract_digest"],
            "closure_digest": envelope["closure_digest"],
        },
        "moh_binding": state["moh_binding"],
        "moh_execution": _compact_moh_evidence(moh_response),
        "bounded_result_reference": evidence_ref,
        "completed_at_utc": state["moh_terminal_at_utc"],
    }


def _chm_result(state: dict[str, Any], result_sha: str, evidence_ref: str) -> dict[str, Any]:
    envelope = state["envelope"]
    return {
        "schema": CHM_RESULT_SCHEMA,
        "logical_handoff_id": state["logical_handoff_id"],
        "execution_id": state["execution_id"],
        "terminal_disposition": state["moh_terminal_state"],
        "tool_binding": {
            "tool_id": envelope["tool_id"],
            "operation_id": envelope["operation_id"],
            "repository_id": envelope["repository_id"],
            "authority_commit": envelope["authority_commit"],
            "authority_tree": envelope["authority_tree"],
        },
        "moh_execution_identity": {
            "request_digest": state["moh_terminal_response"].get("request_digest"),
            "receipt_digest": state["moh_terminal_response"].get("receipt_digest"),
            "result_digest": state["moh_terminal_response"].get("result_digest"),
        },
        "result_evidence_digest": result_sha,
        "bounded_result_reference": evidence_ref,
        "completion_time_utc": state["moh_terminal_at_utc"],
        "completion_time_basis": "DGER_OBSERVED_MOH_TERMINAL",
        "dger_request_identity": state["dger_request_id"],
    }
