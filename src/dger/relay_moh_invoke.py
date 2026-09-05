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
    SemanticGateway, _intent_digest, _invocation_attestation, _json_object_no_duplicates, _safe_rel,
    _validate_consumer_binding, _validate_ready, _validate_request, atomic_bytes, atomic_json,
    canonical_bytes, canonical_digest, canonical_file_bytes, moh_closure_digest, payload_manifest,
    read_json_regular, read_regular, resolve_tool_binding, sha256, utc, validate_moh_envelope,
)
from .relay_state import (
    _chm_result, _result_record, _safe_execution_dir, _stage_digest, _unwrap_gtg_result,
    _validate_moh_response, freeze_ingress, load_state, materialize_moh_stage, save_state,
)


class RelayMohInvokeMixin:
    def _invoke_moh(self, state: dict[str, Any], operation: str) -> dict[str, Any] | None:
        execution_id = state["execution_id"]
        key = "moh_execute_calls" if operation == "execute" else "moh_status_calls"
        state[key] = int(state.get(key, 0)) + 1

        # Write-ahead safety boundary: before any effectful execute can leave DGER,
        # durable State says that execute may already have happened. A process/power
        # loss after MOH receives the call therefore restarts in status reconciliation,
        # never directly in another execute path.
        if operation == "execute":
            state["moh_execute_may_have_happened"] = True
            state["phase"] = "MOH_RECONCILE"
            state["moh_execute_intent_at_utc"] = utc()
        save_state(self.state, execution_id, state)
        try:
            wrapped = self.gateway.invoke(
                MOH_TOOL_ID,
                operation,
                {"execution_id": execution_id},
            )
        except Exception as exc:
            state["last_moh_transport_error"] = str(exc)[:512]
            state["phase"] = "MOH_IN_DOUBT" if state.get("moh_in_doubt_ever") is True else "MOH_RECONCILE"
            save_state(self.state, execution_id, state)
            self._status(execution_id, "MOH_RESPONSE_AMBIGUOUS", operation=operation)
            return None
        result, invocation_id = _unwrap_gtg_result(wrapped, MOH_TOOL_ID, operation)
        if invocation_id:
            state["last_moh_invocation_id"] = invocation_id
        if result is None:
            state["last_moh_gateway_response"] = {
                key: wrapped.get(key) for key in ("code", "status", "execution_may_have_completed", "message") if key in wrapped
            }
            state["phase"] = "MOH_IN_DOUBT" if state.get("moh_in_doubt_ever") is True else "MOH_RECONCILE"
            save_state(self.state, execution_id, state)
            self._status(execution_id, "MOH_RESPONSE_AMBIGUOUS", operation=operation, invocation_id=invocation_id)
            return None
        try:
            attestation = _invocation_attestation(wrapped, MOH_TOOL_ID, operation)
        except DgerError as exc:
            # A successful Tool result without exact GTG identity attestation is not
            # trusted as a completed semantic observation. For execute this remains
            # reconcile-only because the effect may already have happened.
            state["last_moh_attestation_error"] = {"code": exc.code, "detail": exc.detail[:512]}
            state["phase"] = "MOH_IN_DOUBT" if state.get("moh_in_doubt_ever") is True else "MOH_RECONCILE"
            save_state(self.state, execution_id, state)
            self._status(execution_id, "MOH_ATTESTATION_UNAVAILABLE", operation=operation, code=exc.code)
            return None
        state["last_moh_attestation"] = attestation
        state["last_moh_operation"] = operation
        if operation == "execute":
            state["moh_execute_attestation"] = attestation
        else:
            state["moh_status_attestation"] = attestation
        save_state(self.state, execution_id, state)

        response_json = result.get("response_json")
        if not isinstance(response_json, str) or len(response_json.encode("utf-8")) > MAX_MOH_RESPONSE_BYTES:
            raise DgerError("MOH_GATEWAY_RESULT_INVALID")
        response = _json_object_no_duplicates(response_json.encode("utf-8"))
        _validate_moh_response(response, execution_id)
        return response

    def _resume_terminal_publication(self, state: dict[str, Any]) -> None:
        """Finish durable result publication from an already-saved MOH terminal truth."""
        execution_id = state["execution_id"]
        response = state.get("moh_terminal_response")
        if not isinstance(response, dict) or response.get("state") not in MOH_TERMINAL_PUBLISHABLE:
            raise DgerError("MOH_TERMINAL_STATE_INVALID")
        record = _result_record(state, response, f"Runs/{execution_id}/result.json")
        result_sha, ref = self._publish_result(execution_id, record)
        state["result_sha256"] = result_sha
        state["result_ref"] = ref
        state["phase"] = "CHM_PENDING"
        save_state(self.state, execution_id, state)
        self._status(
            execution_id,
            "CHM_PENDING",
            terminal_disposition=state["moh_terminal_state"],
            result_sha256=result_sha,
        )

    def _handle_moh_response(self, state: dict[str, Any], response: dict[str, Any]) -> None:
        execution_id = state["execution_id"]
        moh_state = response["state"]
        state["last_moh_response"] = response
        if moh_state in MOH_TERMINAL_PUBLISHABLE:
            state["phase"] = "MOH_TERMINAL"
            state["moh_terminal_state"] = moh_state
            state["moh_terminal_response"] = response
            state["moh_terminal_at_utc"] = utc()
            state["moh_terminal_attestation"] = state.get("last_moh_attestation")
            state["moh_terminal_observed_via"] = state.get("last_moh_operation")
            save_state(self.state, execution_id, state)
            self._resume_terminal_publication(state)
            return
        if moh_state in MOH_UNRESOLVED:
            state["phase"] = "MOH_IN_DOUBT"
            state["moh_in_doubt_ever"] = True
            state["moh_in_doubt_response"] = response
            save_state(self.state, execution_id, state)
            self._status(execution_id, "MOH_IN_DOUBT", failure_code=response.get("failure_code"))
            return
        state["phase"] = "MOH_RECONCILE"
        save_state(self.state, execution_id, state)
        self._status(execution_id, f"MOH_{moh_state}")