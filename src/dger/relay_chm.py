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
    SemanticGateway, _intent_digest, _json_object_no_duplicates, _safe_rel, _validate_consumer_binding,
    _validate_ready, _validate_request, atomic_bytes, atomic_json, canonical_bytes,
    canonical_digest, canonical_file_bytes, moh_closure_digest, payload_manifest, read_json_regular,
    read_regular, resolve_tool_binding, sha256, utc, validate_moh_envelope,
)
from .relay_state import (
    _chm_result, _result_record, _safe_execution_dir, _stage_digest, _unwrap_gtg_result, _validate_moh_response, freeze_ingress,
    load_state, materialize_moh_stage, save_state,
)

class RelayChmMixin:
    def _publish_chm(self, state: dict[str, Any]) -> None:
        execution_id = state["execution_id"]
        if state["phase"] not in {"CHM_PENDING", "CHM_ATTACHED"}:
            return
        handoff_id = state["logical_handoff_id"]
        chm_result = _chm_result(state, state["result_sha256"], state["result_ref"])
        chm_digest = canonical_digest(chm_result)
        if "chm_result_digest" in state and state["chm_result_digest"] != chm_digest:
            raise DgerError("CHM_LOCAL_RESULT_CONFLICT")
        state["chm_result_digest"] = chm_digest
        save_state(self.state, execution_id, state)

        try:
            if state["phase"] == "CHM_PENDING":
                state["chm_publish_calls"] = int(state.get("chm_publish_calls", 0)) + 1
                save_state(self.state, execution_id, state)
                self._verify_frozen_binding(state, "chm_binding", CHM_TOOL_ID, "handoff_attach_result")
                wrapped = self.gateway.invoke(CHM_TOOL_ID, "handoff_attach_result", {"handoff_id": handoff_id, "result": chm_result})
                result, invocation_id = _unwrap_gtg_result(wrapped, CHM_TOOL_ID, "handoff_attach_result")
                if invocation_id:
                    state["last_chm_invocation_id"] = invocation_id
                if result is None:
                    raise DgerError("CHM_ATTACH_AMBIGUOUS", str(wrapped.get("code", "")))
                if result.get("ok") is not True:
                    code = str(result.get("code", "CHM_ATTACH_FAILED"))
                    if code == "HANDOFF_RESULT_CONFLICT":
                        state["phase"] = "CHM_RESULT_CONFLICT"
                        save_state(self.state, execution_id, state)
                        self._status(execution_id, "CHM_RESULT_CONFLICT")
                        return
                    raise DgerError(code)
                state["phase"] = "CHM_ATTACHED"
                state["chm_attached_at_utc"] = utc()
                save_state(self.state, execution_id, state)
                self._status(execution_id, "CHM_RESULT_ATTACHED")

            self._verify_frozen_binding(state, "chm_binding", CHM_TOOL_ID, "handoff_resolve")
            wrapped = self.gateway.invoke(CHM_TOOL_ID, "handoff_resolve", {"handoff_id": handoff_id})
            result, invocation_id = _unwrap_gtg_result(wrapped, CHM_TOOL_ID, "handoff_resolve")
            if invocation_id:
                state["last_chm_invocation_id"] = invocation_id
            if result is None or result.get("ok") is not True:
                raise DgerError("CHM_RESOLVE_AMBIGUOUS", str(wrapped.get("code", "")))
            state["phase"] = "DONE"
            state["completed_at_utc"] = utc()
            save_state(self.state, execution_id, state)
            self._status(execution_id, "DONE", terminal_disposition=state["moh_terminal_state"], result_sha256=state["result_sha256"])
        except DgerError as exc:
            if state.get("phase") != "CHM_RESULT_CONFLICT":
                state["last_chm_error"] = str(exc)[:512]
                save_state(self.state, execution_id, state)
                self._status(execution_id, "CHM_PUBLICATION_PENDING", detail=exc.code)
        except Exception as exc:
            state["last_chm_error"] = str(exc)[:512]
            save_state(self.state, execution_id, state)
            self._status(execution_id, "CHM_PUBLICATION_PENDING", detail="CHM_TRANSPORT_ERROR")
