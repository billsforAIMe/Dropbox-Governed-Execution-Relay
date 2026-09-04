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

class RelayAcceptMixin:
    def _accept_new(self, package: Path, execution_id: str) -> dict[str, Any]:
        frozen, request_raw, envelope_raw, _entries, manifest_digest = freeze_ingress(package, self.state, execution_id)
        request = _json_object_no_duplicates(request_raw)
        envelope = _json_object_no_duplicates(envelope_raw)

        moh_binding = resolve_tool_binding(self.gateway, MOH_TOOL_ID, ("execute", "status"))
        chm_binding = resolve_tool_binding(self.gateway, CHM_TOOL_ID, REQUIRED_CHM_OPERATIONS)
        consumer_binding = resolve_tool_binding(self.gateway, envelope["tool_id"], (envelope["operation_id"],))
        _validate_consumer_binding(envelope, consumer_binding)

        # Validate the actual logical handoff before any MOH-visible stage exists.
        # The invoke itself is bound atomically to the exact Doctor projection; a
        # gateway that cannot provide frozen-binding CAS must fail before dispatch.
        try:
            wrapped = self.gateway.invoke_frozen(
                CHM_TOOL_ID,
                "handoff_get",
                {"handoff_id": request["logical_handoff_id"]},
                chm_binding,
            )
        except Exception as exc:
            raise DgerError("GTG_ATOMIC_BINDING_CAS_UNAVAILABLE", str(exc)[:512]) from exc
        handoff, _ = _unwrap_gtg_result(wrapped, CHM_TOOL_ID, "handoff_get")
        if handoff is None or handoff.get("ok") is not True:
            raise DgerError("CHM_HANDOFF_PREFLIGHT_FAILED", str(wrapped.get("code", "")))
        if handoff.get("handoff_id") != request["logical_handoff_id"]:
            raise DgerError("CHM_HANDOFF_ID_MISMATCH")
        if handoff.get("state") != "STARTED" or handoff.get("result") is not None:
            raise DgerError("CHM_HANDOFF_NOT_EXECUTION_READY", str(handoff.get("state", "")))

        # Keep the post-read currentness check as a conservative acceptance fence.
        # The atomic invoke protects the read itself; this check prevents accepting
        # a now-stale binding immediately after the read.
        chm_after_get = resolve_tool_binding(self.gateway, CHM_TOOL_ID, REQUIRED_CHM_OPERATIONS)
        if chm_after_get != chm_binding:
            raise DgerError("GTG_BINDING_CHANGED_DURING_ACCEPTANCE", CHM_TOOL_ID)

        intent = _intent_digest(request_raw, envelope_raw, manifest_digest, moh_binding, chm_binding, consumer_binding)
        stage_digest = _stage_digest(frozen)
        state = {
            "schema": PROTOCOL,
            "execution_id": execution_id,
            "dger_request_id": request["dger_request_id"],
            "logical_handoff_id": request["logical_handoff_id"],
            "intent_digest": intent,
            "request_sha256": sha256(request_raw),
            "envelope_sha256": sha256(envelope_raw),
            "payload_manifest_sha256": manifest_digest,
            "frozen_stage_digest": stage_digest,
            "frozen_stage": str(frozen),
            "envelope": envelope,
            "moh_binding": moh_binding,
            "chm_binding": chm_binding,
            "consumer_binding": consumer_binding,
            "phase": "ACCEPTED",
            "accepted_at_utc": utc(),
            "moh_execute_calls": 0,
            "moh_status_calls": 0,
            "chm_publish_calls": 0,
            "moh_in_doubt_ever": False,
        }
        save_state(self.state, execution_id, state)
        self._status(execution_id, "ACCEPTED")
        return state

    def _assert_same_intent(self, package: Path, current: dict[str, Any]) -> None:
        execution_id = current["execution_id"]
        request_raw = read_regular(package / "request.json", MAX_REQUEST_BYTES)
        envelope_raw = read_regular(package / "envelope.json", MAX_ENVELOPE_BYTES)
        request = _json_object_no_duplicates(request_raw)
        envelope = _json_object_no_duplicates(envelope_raw)
        _validate_request(request, execution_id)
        entries, total, manifest_digest = payload_manifest(package / "payload")
        validate_moh_envelope(envelope, execution_id, entries)
        ready, _ = read_json_regular(package / "READY.json", MAX_REQUEST_BYTES)
        _validate_ready(ready, execution_id, request_raw, envelope_raw, entries, total, manifest_digest)
        intent = _intent_digest(
            request_raw, envelope_raw, manifest_digest,
            current["moh_binding"], current["chm_binding"], current["consumer_binding"],
        )
        if intent != current.get("intent_digest"):
            raise DgerError("EXECUTION_ID_INTENT_CONFLICT")

    def _verify_frozen_binding(self, state: dict[str, Any], key: str, tool_id: str, operation: str) -> None:
        current = resolve_tool_binding(self.gateway, tool_id, (operation,))
        frozen = state[key]
        comparable_frozen = {k: frozen[k] for k in ("tool_id", "authoritative_binding", "tool_identity", "tool_tree", "registry_identity")}
        comparable_current = {k: current[k] for k in comparable_frozen}
        if comparable_current != comparable_frozen:
            raise DgerError("FROZEN_PROVIDER_BINDING_UNAVAILABLE", f"{tool_id}:{operation}")
