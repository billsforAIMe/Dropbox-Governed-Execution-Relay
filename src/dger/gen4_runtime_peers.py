from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from typing import Any, Mapping, Protocol

from .gen4_contract import (
    AHC_TOOL_ID, CHM_TOOL_ID, MOH_TOOL_ID, Ack, AhcObservation,
    InvocationEvidence, MohObservation, ServiceIdentity, StageReceipt,
    TrustedCorrelation, _validate_invocation_evidence,
)
from .gen4_delegation import (
    DelegatedServiceContext, parse_delegated_service_context,
    require_protected_service_match,
)
from .gen4_gep14_correlation import AuthenticatedPeerRead, Gep14CorrelationPeers
from .gen4_primitives import (
    DgerGen4Error, HEX64_RE, MAX_ADMISSION_BYTES, MAX_PEER_OBSERVATION_BYTES,
    _copy_payload_verified, _fsync_dir, _json_object_no_duplicates, _safe_id,
    atomic_bytes, canonical_digest, canonical_file_bytes, payload_manifest,
    read_regular, sha256,
)

GEP_CORRELATION_OPERATION = "correlation_read"
AHC_EFFECT_READ_OPERATION = "effect_read"
AHC_BEGIN_OPERATION = "begin_effect"
AHC_STATUS_OPERATION = "effect_status"
AHC_NOTE_IN_DOUBT_OPERATION = "note_moh_in_doubt"
AHC_ACCEPT_TERMINAL_OPERATION = "accept_terminal_effect"
CHM_HANDOFF_READ_OPERATION = "handoff_read"
CHM_PUBLISH_TERMINAL_OPERATION = "publish_terminal_result"
MOH_EXECUTE_OPERATION = "execute"
MOH_STATUS_OPERATION = "status"

_AHC_PROJECTION_KEYS = {
    "ok", "code", "effect_id", "execution_claim_id", "effect_class", "status",
    "workstream_id", "workstream_revision", "provisioned_fleet_epoch",
    "origin_context_digest", "origin_invocation_id", "gep_execution_id",
    "gep_request_digest", "reconciliation_mode", "terminal_evidence_digest", "replayed",
}
_AHC_NOTE_KEYS = _AHC_PROJECTION_KEYS | {"moh_observation_digest", "state_revision"}
_AHC_TERMINAL_KEYS = _AHC_PROJECTION_KEYS | {
    "terminal_digest", "result_ref", "result_sha256", "terminal_acceptance", "state_revision",
}
_CHM_PUBLISH_KEYS = {
    "ok", "code", "handoff_id", "status", "namespace_binding", "project_binding",
    "target_role", "review_episode_id", "external_execution", "terminal_result",
    "execution_authority", "authorizes_moh_execution", "ahc_effect_truth",
    "gep_execution_admission", "reused",
}
_CHM_TERMINAL_KEYS = {
    "schema", "ahc_effect_id", "gep_execution_id", "result_digest", "result",
    "relay_service_id", "relay_service_deployment_id", "relay_context_digest",
    "relay_delegation_invocation_id",
}
_MOH_WRAPPER_KEYS = {"ok", "state", "response_json"}
_MOH_ALLOWED = {
    "NOT_FOUND", "ADMITTED", "START_INTENT_COMMITTED", "RUNNING", "SUCCEEDED",
    "FAILED", "REJECTED_PRECONDITION", "REJECTED_DUPLICATE_MISMATCH", "IN_DOUBT",
}
_MOH_FALSE_OK = {"FAILED", "IN_DOUBT", "REJECTED_PRECONDITION", "REJECTED_DUPLICATE_MISMATCH"}


@dataclass(frozen=True)
class AuthenticatedPeerInvocation:
    """One successful protected GTG/GTC relay invocation."""
    result: Mapping[str, Any]
    delegated_context: Mapping[str, Any]
    invocation_evidence: InvocationEvidence | dict[str, Any]


class AuthenticatedPeerInvoker(Protocol):
    """Internal protected boundary, deliberately not a public GTG wire contract."""
    def invoke(
        self,
        tool_id: str,
        operation: str,
        authority_class: str,
        arguments: Mapping[str, Any],
        service_identity: ServiceIdentity,
    ) -> AuthenticatedPeerInvocation: ...


class UnavailableAuthenticatedPeerInvoker:
    def invoke(self, *_: Any, **__: Any) -> AuthenticatedPeerInvocation:
        raise DgerGen4Error("GEN4_PROTECTED_GTG_RELAY_UNAVAILABLE")


class InvokerCorrelationReader:
    def __init__(self, invoker: AuthenticatedPeerInvoker) -> None:
        self.invoker = invoker

    def invoke_read(self, tool_id, operation, arguments, service_identity):
        row = self.invoker.invoke(tool_id, operation, "READ", arguments, service_identity)
        return AuthenticatedPeerRead(row.result, row.delegated_context, row.invocation_evidence)


def _mapping(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DgerGen4Error(code)
    return dict(value)


def _context_for_call(raw, c, service, tool_id, operation, authority_class):
    context = parse_delegated_service_context(dict(raw))
    require_protected_service_match(context, service)
    if f"tool:{tool_id}:{operation}" not in context.authorized_operations:
        raise DgerGen4Error("DELEGATED_CONTEXT_OPERATION_NOT_AUTHORIZED")
    if authority_class not in context.authorized_capability_classes:
        raise DgerGen4Error("DELEGATED_CONTEXT_CAPABILITY_NOT_AUTHORIZED")
    checks = (
        (context.tenant_id, c.origin.tenant_id),
        (context.principal_id, c.origin.principal_id),
        (context.deployment_id, c.origin.deployment_id),
        (context.origin_actor_role, c.origin.actor_role),
        (context.provisioned_fleet_epoch, c.origin.fleet_epoch),
        (context.origin_context_digest, c.origin.context_digest),
        (context.origin_invocation_id, c.origin.originating_invocation_id),
    )
    if any(observed != expected for observed, expected in checks):
        raise DgerGen4Error("PEER_ORIGIN_CONTEXT_MISMATCH")
    return context


def _ahc_arguments(c: TrustedCorrelation) -> dict[str, Any]:
    return {
        "execution_claim_id": c.ahc_execution_claim_id,
        "effect_id": c.ahc_effect_reservation_id,
        "gep_execution_id": c.gep_execution_id,
        "gep_request_digest": c.gep_request_digest,
    }


def _validate_ahc(result, c, context, *, keys, codes):
    if set(result) != keys or result.get("ok") is not True or result.get("code") not in codes:
        raise DgerGen4Error("AHC_RELAY_RESULT_INVALID")
    revision = result.get("workstream_revision")
    epoch = result.get("provisioned_fleet_epoch")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise DgerGen4Error("AHC_RELAY_RESULT_INVALID")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
        raise DgerGen4Error("AHC_RELAY_RESULT_INVALID")
    _safe_id(result.get("effect_class"), "AHC_RELAY_RESULT_INVALID")
    _safe_id(result.get("workstream_id"), "AHC_RELAY_RESULT_INVALID")
    if result.get("reconciliation_mode") != "INDEPENDENT" or not isinstance(result.get("replayed"), bool):
        raise DgerGen4Error("AHC_RELAY_RESULT_INVALID")
    terminal = result.get("terminal_evidence_digest")
    if terminal is not None and (
        not isinstance(terminal, str) or not terminal.startswith("sha256:")
        or HEX64_RE.fullmatch(terminal[7:]) is None
    ):
        raise DgerGen4Error("AHC_RELAY_RESULT_INVALID")
    checks = (
        (result.get("effect_id"), c.ahc_effect_reservation_id, "AHC_EFFECT_MISMATCH"),
        (result.get("execution_claim_id"), c.ahc_execution_claim_id, "AHC_CLAIM_MISMATCH"),
        (str(revision), c.ahc_work_revision, "AHC_WORK_REVISION_MISMATCH"),
        (epoch, c.origin.fleet_epoch, "AHC_FLEET_EPOCH_MISMATCH"),
        (result.get("origin_context_digest"), c.origin.context_digest, "AHC_ORIGIN_CONTEXT_MISMATCH"),
        (result.get("origin_invocation_id"), c.origin.originating_invocation_id, "AHC_ORIGIN_CONTEXT_MISMATCH"),
        (result.get("gep_execution_id"), c.gep_execution_id, "GEP_EXECUTION_MISMATCH"),
        (result.get("gep_request_digest"), c.gep_request_digest, "GEP_REQUEST_DIGEST_MISMATCH"),
        (context.origin_context_digest, c.origin.context_digest, "AHC_ORIGIN_CONTEXT_MISMATCH"),
    )
    for observed, expected, code in checks:
        if observed != expected:
            raise DgerGen4Error(code)


class Gen4RuntimePeers:
    """DGER-owned effect adapter over a future protected EXECUTION_RELAY invoker."""
    def __init__(self, *, moh_home: Path, service_identity: ServiceIdentity, invoker: AuthenticatedPeerInvoker) -> None:
        self.moh_home = moh_home
        self.service = service_identity
        self.invoker = invoker

    def _invoke(self, c, tool_id, operation, authority_class, arguments):
        if (
            c.service_principal_id != self.service.service_principal_id
            or c.service_deployment_id != self.service.service_deployment_id
            or c.service_role != self.service.actor_role
        ):
            raise DgerGen4Error("WRONG_DGER_SERVICE_DEPLOYMENT")
        row = self.invoker.invoke(tool_id, operation, authority_class, arguments, self.service)
        result = _mapping(row.result, "PEER_RESULT_INVALID")
        context = _context_for_call(
            row.delegated_context, c, self.service, tool_id, operation, authority_class
        )
        evidence = _validate_invocation_evidence(
            row.invocation_evidence, expected_tool=tool_id, expected_operation=operation
        )
        return result, context, evidence

    def stage_moh(self, c, frozen_stage, payload_manifest_sha256):
        admission = read_regular(frozen_stage / "admission.bin", MAX_ADMISSION_BYTES)
        admission_sha = sha256(admission)
        entries, _, observed_manifest = payload_manifest(frozen_stage / "payload")
        if observed_manifest != payload_manifest_sha256:
            raise DgerGen4Error("PAYLOAD_MANIFEST_DIGEST_MISMATCH")
        if admission_sha != c.gep_admission_sha256:
            raise DgerGen4Error("GEP_ADMISSION_MISMATCH")
        inbox = self.moh_home / "inbox"
        if inbox.is_symlink():
            raise DgerGen4Error("UNSAFE_MOH_INBOX")
        inbox.mkdir(parents=True, exist_ok=True)
        if inbox.is_symlink() or not inbox.is_dir():
            raise DgerGen4Error("UNSAFE_MOH_INBOX")
        final = inbox / c.gep_execution_id

        def matches(path: Path) -> bool:
            if path.is_symlink() or not path.is_dir():
                return False
            try:
                observed_admission = read_regular(path / "envelope.json", MAX_ADMISSION_BYTES)
                _, _, observed_payload = payload_manifest(path / "payload")
            except DgerGen4Error:
                return False
            return sha256(observed_admission) == admission_sha and observed_payload == observed_manifest

        for orphan in inbox.glob(f".{c.gep_execution_id}.dger-gen4-*"):
            if orphan.is_symlink() or not orphan.is_dir():
                raise DgerGen4Error("MOH_TEMP_STAGE_UNSAFE")
            shutil.rmtree(orphan)
        if final.exists():
            if not matches(final):
                raise DgerGen4Error("MOH_STAGE_CONFLICT")
        else:
            tmp = inbox / f".{c.gep_execution_id}.dger-gen4-{os.getpid()}-{os.urandom(6).hex()}"
            if tmp.exists() or tmp.is_symlink():
                raise DgerGen4Error("MOH_TEMP_COLLISION")
            try:
                tmp.mkdir(mode=0o700)
                atomic_bytes(tmp / "envelope.json", admission)
                _copy_payload_verified(frozen_stage / "payload", tmp / "payload", entries)
                if not matches(tmp):
                    raise DgerGen4Error("MOH_STAGE_READBACK_MISMATCH")
                _fsync_dir(tmp)
                try:
                    os.rename(tmp, final)
                except OSError:
                    if not final.exists() or not matches(final):
                        raise
                    shutil.rmtree(tmp, ignore_errors=True)
                _fsync_dir(inbox)
                if not matches(final):
                    raise DgerGen4Error("MOH_STAGE_READBACK_MISMATCH")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return StageReceipt(
            c.gep_execution_id, admission_sha, observed_manifest,
            canonical_digest({
                "gep_execution_id": c.gep_execution_id,
                "admission_sha256": admission_sha,
                "payload_manifest_sha256": observed_manifest,
            }),
        )

    def ahc_begin(self, c):
        result, context, evidence = self._invoke(c, AHC_TOOL_ID, AHC_BEGIN_OPERATION, "EFFECT", _ahc_arguments(c))
        _validate_ahc(result, c, context, keys=_AHC_PROJECTION_KEYS, codes={"AHC_EFFECT_IN_DOUBT", "AHC_EFFECT_ALREADY_IN_DOUBT"})
        if result.get("status") != "IN_DOUBT":
            raise DgerGen4Error("AHC_BEGIN_DID_NOT_ESTABLISH_IN_DOUBT")
        if (result["code"] == "AHC_EFFECT_IN_DOUBT") != (result["replayed"] is False):
            raise DgerGen4Error("AHC_RELAY_RESULT_INVALID")
        if (result["code"] == "AHC_EFFECT_ALREADY_IN_DOUBT") != (result["replayed"] is True):
            raise DgerGen4Error("AHC_RELAY_RESULT_INVALID")
        return AhcObservation(c.ahc_effect_reservation_id, c.gep_execution_id, "IN_DOUBT", canonical_digest(result), evidence)

    def ahc_status(self, c):
        result, context, evidence = self._invoke(c, AHC_TOOL_ID, AHC_STATUS_OPERATION, "READ", _ahc_arguments(c))
        _validate_ahc(result, c, context, keys=_AHC_PROJECTION_KEYS, codes={"AHC_EFFECT_STATUS"})
        if result.get("status") not in {"RESERVED", "IN_DOUBT", "SUCCEEDED", "FAILED"}:
            raise DgerGen4Error("AHC_RELAY_RESULT_INVALID")
        return AhcObservation(c.ahc_effect_reservation_id, c.gep_execution_id, result["status"], canonical_digest(result), evidence)

    @staticmethod
    def _moh_observation(c, result, evidence):
        if set(result) != _MOH_WRAPPER_KEYS:
            raise DgerGen4Error("MOH_WRAPPER_INVALID")
        raw = result.get("response_json")
        if not isinstance(raw, str) or len(raw.encode()) > MAX_PEER_OBSERVATION_BYTES:
            raise DgerGen4Error("MOH_WRAPPER_INVALID")
        inner = _json_object_no_duplicates(raw.encode())
        state = result.get("state")
        if state not in _MOH_ALLOWED or inner.get("state") != state:
            raise DgerGen4Error("MOH_STATE_INVALID")
        if inner.get("execution_id") != c.gep_execution_id:
            raise DgerGen4Error("MOH_EXECUTION_MISMATCH")
        if inner.get("schema") not in {"moh-status/v1", "moh-execute/v1"}:
            raise DgerGen4Error("MOH_RESPONSE_SCHEMA_INVALID")
        if result.get("ok") is not (state not in _MOH_FALSE_OK):
            raise DgerGen4Error("MOH_WRAPPER_OK_MISMATCH")
        receipt = inner.get("receipt_digest")
        if receipt is not None:
            if not isinstance(receipt, str) or HEX64_RE.fullmatch(receipt) is None:
                raise DgerGen4Error("MOH_RECEIPT_DIGEST_INVALID")
            body = dict(inner); body.pop("receipt_digest")
            if canonical_digest(body) != receipt:
                raise DgerGen4Error("MOH_RECEIPT_DIGEST_MISMATCH")
            digest = receipt
        else:
            digest = canonical_digest(inner)
        payload = inner.get("result")
        if payload is not None and not isinstance(payload, dict):
            raise DgerGen4Error("MOH_RESULT_INVALID")
        return MohObservation(c.gep_execution_id, state, None, digest, payload, evidence)

    def moh_execute(self, c):
        result, _, evidence = self._invoke(c, MOH_TOOL_ID, MOH_EXECUTE_OPERATION, "EFFECT", {"execution_id": c.gep_execution_id})
        return self._moh_observation(c, result, evidence)

    def moh_status(self, c):
        result, _, evidence = self._invoke(c, MOH_TOOL_ID, MOH_STATUS_OPERATION, "EFFECT", {"execution_id": c.gep_execution_id})
        return self._moh_observation(c, result, evidence)

    def ahc_note_in_doubt(self, c, moh_observation_digest):
        if HEX64_RE.fullmatch(moh_observation_digest) is None:
            raise DgerGen4Error("MOH_OBSERVATION_DIGEST_INVALID")
        args = _ahc_arguments(c); args["moh_observation_digest"] = moh_observation_digest
        result, context, evidence = self._invoke(c, AHC_TOOL_ID, AHC_NOTE_IN_DOUBT_OPERATION, "EFFECT", args)
        _validate_ahc(result, c, context, keys=_AHC_NOTE_KEYS, codes={"AHC_MOH_IN_DOUBT_NOTED"})
        if result.get("status") != "IN_DOUBT" or result.get("moh_observation_digest") != moh_observation_digest or not isinstance(result.get("state_revision"), int) or isinstance(result.get("state_revision"), bool) or result["state_revision"] < 1:
            raise DgerGen4Error("AHC_MOH_IN_DOUBT_RESULT_INVALID")
        return Ack(True, canonical_digest(result), evidence)

    def ahc_accept_terminal(self, c, terminal_digest, result_ref, result_sha256):
        if HEX64_RE.fullmatch(terminal_digest) is None or HEX64_RE.fullmatch(result_sha256) is None:
            raise DgerGen4Error("AHC_TERMINAL_RESULT_INVALID")
        args = _ahc_arguments(c); args.update({"terminal_digest": terminal_digest, "result_ref": result_ref, "result_sha256": result_sha256})
        result, context, evidence = self._invoke(c, AHC_TOOL_ID, AHC_ACCEPT_TERMINAL_OPERATION, "EFFECT", args)
        _validate_ahc(result, c, context, keys=_AHC_TERMINAL_KEYS, codes={"AHC_TERMINAL_EFFECT_ACCEPTED"})
        if result.get("status") != "SUCCEEDED" or result.get("terminal_digest") != terminal_digest or result.get("result_ref") != result_ref or result.get("result_sha256") != result_sha256 or result.get("terminal_acceptance") != "RECONCILIATION_COMPLETE" or not isinstance(result.get("state_revision"), int) or isinstance(result.get("state_revision"), bool) or result["state_revision"] < 1:
            raise DgerGen4Error("AHC_TERMINAL_RESULT_INVALID")
        return Ack(True, canonical_digest(result), evidence)

    def chm_publish_terminal(self, c, result_ref, result_sha256):
        if c.chm_handoff_id is None or HEX64_RE.fullmatch(result_sha256) is None:
            raise DgerGen4Error("CHM_TERMINAL_RESULT_INVALID")
        descriptor = {"result_ref": result_ref, "result_sha256": result_sha256}
        args = {"handoff_id": c.chm_handoff_id, "ahc_effect_id": c.ahc_effect_reservation_id, "gep_execution_id": c.gep_execution_id, "result": descriptor}
        result, context, evidence = self._invoke(c, CHM_TOOL_ID, CHM_PUBLISH_TERMINAL_OPERATION, "EFFECT", args)
        if set(result) != _CHM_PUBLISH_KEYS or result.get("ok") is not True or result.get("code") != "HANDOFF_FOUND":
            raise DgerGen4Error("CHM_TERMINAL_RESULT_INVALID")
        expected_ns = {"tenant_id": c.origin.tenant_id, "principal_id": c.origin.principal_id, "deployment_id": c.origin.deployment_id}
        if result.get("handoff_id") != c.chm_handoff_id or result.get("namespace_binding") != expected_ns or result.get("external_execution") != {"ahc_effect_id": c.ahc_effect_reservation_id, "gep_execution_id": c.gep_execution_id} or result.get("execution_authority") != "NOT_CHM" or result.get("authorizes_moh_execution") is not False or result.get("ahc_effect_truth") != "NOT_CHM" or result.get("gep_execution_admission") != "NOT_CHM" or result.get("status") != "TERMINAL_RESULT" or not isinstance(result.get("reused"), bool):
            raise DgerGen4Error("CHM_TERMINAL_RESULT_INVALID")
        terminal = _mapping(result.get("terminal_result"), "CHM_TERMINAL_RESULT_INVALID")
        if set(terminal) != _CHM_TERMINAL_KEYS:
            raise DgerGen4Error("CHM_TERMINAL_RESULT_INVALID")
        expected_digest = "sha256:" + sha256(canonical_file_bytes({"result": descriptor}))
        if terminal.get("schema") != "chm-terminal-transport-result/v1" or terminal.get("ahc_effect_id") != c.ahc_effect_reservation_id or terminal.get("gep_execution_id") != c.gep_execution_id or terminal.get("result_digest") != expected_digest or terminal.get("result") != descriptor or terminal.get("relay_service_id") != self.service.service_principal_id or terminal.get("relay_service_deployment_id") != self.service.service_deployment_id or terminal.get("relay_context_digest") != context.context_digest or terminal.get("relay_delegation_invocation_id") != context.delegation_invocation_id:
            raise DgerGen4Error("CHM_TERMINAL_RESULT_INVALID")
        return Ack(True, canonical_digest(result), evidence)


def compose_gen4_peers(*, moh_home: Path, service_identity: ServiceIdentity, invoker: AuthenticatedPeerInvoker) -> Gep14CorrelationPeers:
    base = Gen4RuntimePeers(moh_home=moh_home, service_identity=service_identity, invoker=invoker)
    return Gep14CorrelationPeers(base, InvokerCorrelationReader(invoker))
