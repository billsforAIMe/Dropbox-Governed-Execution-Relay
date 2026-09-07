from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .gen4_primitives import (
    DgerGen4Error, HEX64_RE, MAX_ERROR_BYTES, MAX_RESULT_BYTES, MOH_NONTERMINAL,
    MOH_SAFE_TO_FIRST_OR_PROVEN_RETRY, MOH_TERMINAL, RESULT_SCHEMA, atomic_bytes, canonical_digest,
    canonical_file_bytes, read_regular, sha256, utc,
)
from .gen4_contract import (
    AHC_TOOL_ID, CHM_TOOL_ID, AhcObservation, MohObservation, TrustedCorrelation,
    _validate_ack, _validate_ahc, _validate_moh,
)

class Gen4EffectMixin:
    def _stage(self, state: dict[str, Any]) -> None:
        c = self._c(state); rid = state["dger_request_id"]
        try:
            receipt = self.peers.stage_moh(c, Path(state["frozen_stage"]), state["payload_manifest_sha256"])
        except Exception as exc:
            self._record_error(state, "stage_moh", exc); self._save_state(rid, state); self._status(rid, "MOH_STAGE_BLOCKED", code=self._error_code(exc)); return
        if (
            receipt.gep_execution_id != c.gep_execution_id
            or receipt.admission_sha256 != state["admission_sha256"]
            or receipt.payload_manifest_sha256 != state["payload_manifest_sha256"]
            or HEX64_RE.fullmatch(receipt.stage_digest) is None
            or receipt.stage_kind != "LOCAL_MATERIALIZATION"
        ):
            raise DgerGen4Error("MOH_STAGE_RECEIPT_MISMATCH")
        state["moh_stage_receipt"] = asdict(receipt)
        state["phase"] = "MOH_STAGED"
        state["moh_stage_at_utc"] = utc()
        self._save_state(rid, state); self._status(rid, "MOH_STAGED"); self.fault("after_moh_stage")

    def _write_pre_ahc_wal(self, state: dict[str, Any]) -> None:
        rid = state["dger_request_id"]
        state["execute_reconciliation_required"] = True
        state["phase"] = "PRE_AHC_EXECUTE_WAL"
        state["pre_ahc_execute_wal_at_utc"] = utc()
        self._save_state(rid, state); self._status(rid, "PRE_AHC_EXECUTE_WAL"); self.fault("after_pre_ahc_wal")

    def _begin_ahc(self, state: dict[str, Any]) -> None:
        rid = state["dger_request_id"]; c = self._c(state)
        try:
            obs = self.peers.ahc_begin(c)
        except Exception as exc:
            self._record_error(state, "ahc_begin", exc)
            state["phase"] = "AHC_BEGIN_RECONCILE"
            state["ahc_begin_response_ambiguous"] = True
            self._save_state(rid, state); self._status(rid, "AHC_BEGIN_AMBIGUOUS", code=self._error_code(exc)); return
        _validate_ahc(obs, c, "begin_effect")
        if obs.state != "IN_DOUBT":
            raise DgerGen4Error("AHC_BEGIN_DID_NOT_ESTABLISH_IN_DOUBT", obs.state)
        state["ahc_begin_observation"] = asdict(obs)
        state["phase"] = "AHC_IN_DOUBT"
        state["ahc_in_doubt_at_utc"] = utc()
        state["pre_execute_status_required"] = True
        self._save_state(rid, state); self._status(rid, "AHC_IN_DOUBT"); self.fault("after_ahc_in_doubt")

    def _reconcile_ahc_begin(self, state: dict[str, Any]) -> None:
        rid = state["dger_request_id"]; c = self._c(state)
        try:
            obs = self.peers.ahc_status(c)
        except Exception as exc:
            self._record_error(state, "ahc_status", exc); self._save_state(rid, state); self._status(rid, "AHC_RECONCILIATION_BLOCKED", code=self._error_code(exc)); return
        _validate_ahc(obs, c, "effect_status")
        state["last_ahc_status"] = asdict(obs)
        if obs.state == "RESERVED":
            state["phase"] = "PRE_AHC_EXECUTE_WAL"
            self._save_state(rid, state)
            return
        if obs.state == "IN_DOUBT":
            state["phase"] = "AHC_IN_DOUBT"
            state["pre_execute_status_required"] = True
            self._save_state(rid, state); self._status(rid, "AHC_IN_DOUBT_RECONCILED"); return
        raise DgerGen4Error("AHC_EFFECT_ALREADY_TERMINAL_CONFLICT", obs.state)

    def _handle_moh(self, state: dict[str, Any], obs: MohObservation, via: str) -> None:
        rid = state["dger_request_id"]; c = self._c(state)
        if via not in {"status", "execute"}:
            raise DgerGen4Error("MOH_OBSERVATION_SOURCE_INVALID")
        _validate_moh(obs, c, via)
        state["last_moh_observation"] = asdict(obs)
        state["last_moh_observed_via"] = via
        if obs.state == "IN_DOUBT":
            state["moh_in_doubt_ever"] = True
            state["moh_in_doubt_source"] = "MOH_OBSERVATION"
            state["phase"] = "MOH_IN_DOUBT_AHC_PENDING"
            state["moh_in_doubt_observation"] = asdict(obs)
            self._save_state(rid, state); self._status(rid, "MOH_IN_DOUBT_AHC_PENDING")
            return
        if obs.state in MOH_TERMINAL:
            terminal = asdict(obs)
            terminal_digest = canonical_digest(terminal)
            state["moh_terminal_observation"] = terminal
            state["moh_terminal_digest"] = terminal_digest
            state["phase"] = "MOH_TERMINAL"
            state["moh_terminal_at_utc"] = utc()
            self._save_state(rid, state); self._status(rid, "MOH_TERMINAL", terminal_state=obs.state); self.fault("after_moh_terminal")
            return
        if obs.state in MOH_NONTERMINAL:
            state["phase"] = "MOH_RECONCILE"
            self._save_state(rid, state); self._status(rid, f"MOH_{obs.state}")
            return
        state["last_safe_moh_status"] = asdict(obs)
        state["phase"] = "AHC_IN_DOUBT"
        state["pre_execute_status_required"] = False
        self._save_state(rid, state)

    def _status_before_execute(self, state: dict[str, Any]) -> None:
        rid = state["dger_request_id"]; c = self._c(state)
        try:
            obs = self.peers.moh_status(c)
            state["moh_status_calls"] = int(state.get("moh_status_calls", 0)) + 1
        except Exception as exc:
            self._record_error(state, "moh_status", exc); self._save_state(rid, state); self._status(rid, "MOH_STATUS_BLOCKED", code=self._error_code(exc)); return
        _validate_moh(obs, c, "status")
        if obs.state in MOH_SAFE_TO_FIRST_OR_PROVEN_RETRY:
            state["last_safe_moh_status"] = asdict(obs)
            state["last_safe_moh_status_at_utc"] = utc()
            state["pre_execute_status_required"] = False
            state["phase"] = "AHC_IN_DOUBT"
            self._save_state(rid, state); self._status(rid, f"MOH_{obs.state}_SAFE_PROOF"); return
        self._handle_moh(state, obs, "status")

    def _execute_moh(self, state: dict[str, Any]) -> None:
        rid = state["dger_request_id"]; c = self._c(state)
        if state.get("moh_in_doubt_ever") is True:
            state["phase"] = "MOH_IN_DOUBT"; self._save_state(rid, state); return
        if state.get("pre_execute_status_required") is not False or not isinstance(state.get("last_safe_moh_status"), dict):
            raise DgerGen4Error("MOH_STATUS_PROOF_REQUIRED")
        state["moh_execute_call_may_have_happened"] = True
        state["moh_execute_calls"] = int(state.get("moh_execute_calls", 0)) + 1
        state["phase"] = "MOH_RECONCILE"
        state["moh_execute_call_wal_at_utc"] = utc()
        state["pre_execute_status_required"] = True
        self._save_state(rid, state); self._status(rid, "MOH_EXECUTE_CALL_WAL"); self.fault("after_moh_execute_wal")
        try:
            obs = self.peers.moh_execute(c)
        except Exception as exc:
            self._record_error(state, "moh_execute", exc); self._save_state(rid, state); self._status(rid, "MOH_EXECUTE_AMBIGUOUS", code=self._error_code(exc)); return
        try:
            self._handle_moh(state, obs, "execute")
        except DgerGen4Error as exc:
            self._record_error(state, "moh_execute_response", exc)
            state["moh_in_doubt_ever"] = True
            state["moh_in_doubt_source"] = "INVALID_EXECUTE_RESPONSE"
            state["moh_execute_response_invalid"] = True
            self._save_state(rid, state)
            self._status(rid, "MOH_EXECUTE_RESPONSE_INVALID", code=exc.code)
            return

    def _reconcile_moh(self, state: dict[str, Any]) -> None:
        rid = state["dger_request_id"]; c = self._c(state)
        try:
            obs = self.peers.moh_status(c)
            state["moh_status_calls"] = int(state.get("moh_status_calls", 0)) + 1
        except Exception as exc:
            self._record_error(state, "moh_status", exc); self._save_state(rid, state); self._status(rid, "MOH_RECONCILIATION_BLOCKED", code=self._error_code(exc)); return
        _validate_moh(obs, c, "status")
        if obs.state in MOH_SAFE_TO_FIRST_OR_PROVEN_RETRY:
            if state.get("moh_in_doubt_ever") is True:
                state["phase"] = "MOH_IN_DOUBT"; self._save_state(rid, state); self._status(rid, "MOH_IN_DOUBT"); return
            state["last_safe_moh_status"] = asdict(obs)
            state["pre_execute_status_required"] = False
            state["phase"] = "AHC_IN_DOUBT"
            self._save_state(rid, state); self._status(rid, f"MOH_{obs.state}_RECONCILED_SAFE"); return
        self._handle_moh(state, obs, "status")

    def _report_moh_in_doubt(self, state: dict[str, Any]) -> None:
        rid = state["dger_request_id"]; c = self._c(state)
        if state.get("moh_in_doubt_ever") is not True:
            raise DgerGen4Error("MOH_IN_DOUBT_LATCH_MISSING")
        raw = state.get("moh_in_doubt_observation")
        if not isinstance(raw, dict):
            raise DgerGen4Error("MOH_IN_DOUBT_OBSERVATION_MISSING")
        via = state.get("last_moh_observed_via")
        if via not in {"status", "execute"}:
            raise DgerGen4Error("MOH_OBSERVATION_SOURCE_INVALID")
        obs = MohObservation(**raw)
        _validate_moh(obs, c, via)
        moh_observation_digest = canonical_digest(asdict(obs))
        try:
            ack = self.peers.ahc_note_in_doubt(c, moh_observation_digest)
        except Exception as exc:
            self._record_error(state, "ahc_note_in_doubt", exc)
            self._save_state(rid, state)
            self._status(rid, "AHC_IN_DOUBT_REPORT_BLOCKED", code=self._error_code(exc))
            return
        _validate_ack(ack, AHC_TOOL_ID, "note_moh_in_doubt")
        state["ahc_in_doubt_report_digest"] = moh_observation_digest
        state["ahc_in_doubt_report_ack"] = asdict(ack)
        state["phase"] = "MOH_IN_DOUBT"
        state.pop("last_error", None)
        self._save_state(rid, state)
        self._status(rid, "MOH_IN_DOUBT")

    def _publish_terminal(self, state: dict[str, Any]) -> None:
        rid = state["dger_request_id"]; c = self._c(state)
        terminal = state.get("moh_terminal_observation")
        if not isinstance(terminal, dict) or state.get("moh_terminal_digest") != canonical_digest(terminal):
            raise DgerGen4Error("MOH_TERMINAL_STATE_INVALID")
        record = {
            "schema": RESULT_SCHEMA,
            "dger_request_id": rid,
            "gep_execution_id": c.gep_execution_id,
            "ahc_effect_reservation_id": c.ahc_effect_reservation_id,
            "moh_state": terminal["state"],
            "moh_record_id": terminal.get("record_id"),
            "moh_evidence_digest": terminal["evidence_digest"],
            "moh_invocation_evidence": terminal.get("invocation_evidence"),
            "moh_result": terminal.get("result"),
            "terminal_digest": state["moh_terminal_digest"],
        }
        raw = canonical_file_bytes(record)
        if len(raw) > MAX_RESULT_BYTES:
            raise DgerGen4Error("RESULT_RECORD_TOO_LARGE")
        out = self.runs / rid
        out.mkdir(parents=True, exist_ok=True)
        path = out / "result.json"
        if path.exists():
            existing = read_regular(path, MAX_RESULT_BYTES)
            if existing != raw:
                state["phase"] = "RESULT_CONFLICT"; self._save_state(rid, state)
                raise DgerGen4Error("RESULT_RECORD_CONFLICT")
        else:
            atomic_bytes(path, raw, 0o644)
        state["result_ref"] = f"RunsV2/{rid}/result.json"
        state["result_sha256"] = sha256(raw)
        state["phase"] = "AHC_TERMINAL_PENDING"
        self._save_state(rid, state); self._status(rid, "AHC_TERMINAL_PENDING", result_sha256=state["result_sha256"]); self.fault("after_result_publication")

    def _accept_ahc_terminal(self, state: dict[str, Any]) -> None:
        rid = state["dger_request_id"]; c = self._c(state)
        state["ahc_terminal_calls"] = int(state.get("ahc_terminal_calls", 0)) + 1
        self._save_state(rid, state)
        try:
            ack = self.peers.ahc_accept_terminal(c, state["moh_terminal_digest"], state["result_ref"], state["result_sha256"])
        except Exception as exc:
            self._record_error(state, "ahc_accept_terminal", exc); self._save_state(rid, state); self._status(rid, "AHC_TERMINAL_BLOCKED", code=self._error_code(exc)); return
        _validate_ack(ack, AHC_TOOL_ID, "accept_terminal_effect")
        state["ahc_terminal_ack"] = asdict(ack)
        state["phase"] = "CHM_PENDING" if c.chm_handoff_id is not None else "DONE"
        self._save_state(rid, state); self._status(rid, state["phase"]); self.fault("after_ahc_terminal")

    def _publish_chm(self, state: dict[str, Any]) -> None:
        rid = state["dger_request_id"]; c = self._c(state)
        if c.chm_handoff_id is None:
            state["phase"] = "DONE"; self._save_state(rid, state); return
        state["chm_publish_calls"] = int(state.get("chm_publish_calls", 0)) + 1
        self._save_state(rid, state)
        try:
            ack = self.peers.chm_publish_terminal(c, state["result_ref"], state["result_sha256"])
        except Exception as exc:
            self._record_error(state, "chm_publish_terminal", exc); self._save_state(rid, state); self._status(rid, "CHM_PUBLICATION_BLOCKED", code=self._error_code(exc)); return
        try:
            _validate_ack(ack, CHM_TOOL_ID, "publish_terminal_result")
        except DgerGen4Error:
            state["phase"] = "CHM_RESULT_CONFLICT"; self._save_state(rid, state); raise
        state["chm_terminal_ack"] = asdict(ack)
        state["phase"] = "DONE"
        self._save_state(rid, state); self._status(rid, "DONE")