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


from .relay_moh_invoke import RelayMohInvokeMixin

class RelayMohMixin(RelayMohInvokeMixin):
    def _reconcile_moh(self, state: dict[str, Any]) -> None:
        execution_id = state["execution_id"]
        if state["phase"] == "ACCEPTED":
            materialize_moh_stage(Path(state["frozen_stage"]), self.moh_home / "inbox", execution_id, state["frozen_stage_digest"])
            state["phase"] = "MOH_STAGE_COMPLETE"
            state["moh_stage_completed_at_utc"] = utc()
            save_state(self.state, execution_id, state)
            self._status(execution_id, "MOH_STAGE_COMPLETE")
        if state["phase"] == "MOH_STAGE_COMPLETE":
            # Re-read the exact immutable stage immediately before the first execute.
            # MOH independently revalidates envelope/payload on admission, so this is
            # defense-in-depth against stage substitution without moving execution truth.
            final_stage = self.moh_home / "inbox" / execution_id
            if final_stage.is_symlink() or _stage_digest(final_stage) != state["frozen_stage_digest"]:
                raise DgerError("MOH_STAGE_SUBSTITUTED")
            response = self._invoke_moh(state, "execute")
            if response is not None:
                self._handle_moh_response(state, response)
            return
        if state["phase"] in {"MOH_RECONCILE", "MOH_IN_DOUBT"}:
            response = self._invoke_moh(state, "status")
            if response is None:
                return
            if response["state"] == "NOT_FOUND":
                if state.get("moh_in_doubt_ever") is True:
                    # IN_DOUBT is an irreversible safety latch. Once observed, no later
                    # transport ambiguity, phase transition, or NOT_FOUND can restore
                    # permission for DGER to call execute for this execution_id.
                    state["phase"] = "MOH_IN_DOUBT"
                    state["last_moh_response"] = response
                    save_state(self.state, execution_id, state)
                    self._status(execution_id, "MOH_IN_DOUBT", failure_code="PRIOR_IN_DOUBT_NOT_FOUND")
                    return
                # A prior execute response may have been lost before MOH admission. Only when
                # DGER has never observed IN_DOUBT may NOT_FOUND permit another same-ID execute.
                # _invoke_moh durably records execute-may-have-happened / MOH_RECONCILE before
                # it performs the external effect, so process death can never restart here as
                # another blind execute.
                response = self._invoke_moh(state, "execute")
                if response is None:
                    return
            self._handle_moh_response(state, response)
