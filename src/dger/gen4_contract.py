from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any, Protocol

from .gen4_primitives import (
    DgerGen4Error, HEX64_RE, MAX_PEER_OBSERVATION_BYTES, MOH_ALL, SERVICE_IDENTITY_SCHEMA, TRUSTED_CORRELATION_SCHEMA, _json_object_no_duplicates, _safe_id,
    canonical_bytes, canonical_digest, read_protected_regular,
)

GEP_TOOL_ID = "governed-execution-platform"
AHC_TOOL_ID = "autonomous-handoff-coordinator"
MOH_TOOL_ID = "mac-operation-host"
CHM_TOOL_ID = "common-handoff-manager"
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_GTG_INVOCATION_ID_RE = re.compile(r"^gtg_inv_[0-9a-f]{64}$")
_GTG_DELEGATION_ID_RE = re.compile(r"^gtg_del_[0-9a-f]{64}$")
_GTG_CONTEXT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class InvocationEvidence:
    """Normalized exact GTG invocation-time provider identity evidence.

    The peer adapter may map only an exact delivered GTG/GTC attestation into this
    structure. DGER does not infer currentness or compatibility from caller data.
    """
    tool_id: str
    operation: str
    invocation_id: str
    tool_identity: str
    tool_tree: str
    gtg_identity: str
    registry_identity: str


@dataclass(frozen=True)
class ServiceIdentity:
    service_principal_id: str
    service_deployment_id: str
    actor_role: str
    identity_digest: str


@dataclass(frozen=True)
class TrustedOrigin:
    tenant_id: str
    principal_id: str
    deployment_id: str
    actor_role: str
    fleet_epoch: int
    originating_invocation_id: str
    context_digest: str


@dataclass(frozen=True)
class TrustedCorrelation:
    origin: TrustedOrigin
    service_principal_id: str
    service_deployment_id: str
    service_role: str
    delegation_invocation_id: str
    delegated_context_digest: str
    ahc_execution_claim_id: str
    ahc_effect_reservation_id: str
    ahc_work_revision: str
    gep_execution_id: str
    gep_request_digest: str
    gep_admission_sha256: str
    chm_handoff_id: str | None
    correlation_digest: str
    provider_evidence: tuple[InvocationEvidence, ...] = ()


@dataclass(frozen=True)
class StageReceipt:
    gep_execution_id: str
    admission_sha256: str
    payload_manifest_sha256: str
    stage_digest: str
    stage_kind: str = "LOCAL_MATERIALIZATION"


@dataclass(frozen=True)
class AhcObservation:
    effect_reservation_id: str
    gep_execution_id: str
    state: str
    observation_digest: str
    invocation_evidence: InvocationEvidence | dict[str, Any] | None = None


@dataclass(frozen=True)
class MohObservation:
    gep_execution_id: str
    state: str
    record_id: str | None
    evidence_digest: str
    result: dict[str, Any] | None = None
    invocation_evidence: InvocationEvidence | dict[str, Any] | None = None


@dataclass(frozen=True)
class Ack:
    ok: bool
    digest: str
    invocation_evidence: InvocationEvidence | dict[str, Any] | None = None


class Gen4Peers(Protocol):
    """Internal semantic port. Wire/auth translation belongs to exact delivered peer adapters.

    Implementations MUST invoke semantic peers under the protected DGER service
    credential and the exact GTG-authenticated delegated context. No method accepts
    identity from Dropbox as authority. Every successful semantic peer call MUST
    return exact invocation-time GTG provider identity evidence bound to the exact
    normalized operation DGER requested.

    ``establish_correlation`` may consume only delivered peer source contracts. The
    current authoritative GEP source does not expose the post-#94 trusted execution-
    binding/correlation operation DGER ultimately requires, so a production adapter
    must remain unavailable rather than inventing ``correlation_read`` or an alias.
    AHC's five DGER effect semantics, by contrast, are source-delivered and may be
    composed even while their runtime front door remains unavailable.

    ``stage_moh`` is deliberately different: in this source-ready pre-activation
    contract it is only local, non-effectful materialization of already authenticated
    immutable bytes into the MOH staging substrate. Its receipt MUST say
    ``LOCAL_MATERIALIZATION`` and it MUST NOT perform a semantic peer invocation or
    start a process. If a delivered peer tuple later requires remote/semantic staging,
    that adapter contract is changed input and must add exact invocation evidence
    under change-driven review rather than silently reusing this receipt.
    """

    def establish_correlation(
        self,
        request: dict[str, Any],
        admission_sha256: str,
        payload_manifest_sha256: str,
        service_identity: ServiceIdentity,
    ) -> TrustedCorrelation: ...
    def stage_moh(self, correlation: TrustedCorrelation, frozen_stage: Path, payload_manifest_sha256: str) -> StageReceipt: ...
    def ahc_begin(self, correlation: TrustedCorrelation) -> AhcObservation: ...
    def ahc_status(self, correlation: TrustedCorrelation) -> AhcObservation: ...
    def moh_execute(self, correlation: TrustedCorrelation) -> MohObservation: ...
    def moh_status(self, correlation: TrustedCorrelation) -> MohObservation: ...
    def ahc_note_in_doubt(self, correlation: TrustedCorrelation, moh_observation_digest: str) -> Ack: ...
    def ahc_accept_terminal(self, correlation: TrustedCorrelation, terminal_digest: str, result_ref: str, result_sha256: str) -> Ack: ...
    def chm_publish_terminal(self, correlation: TrustedCorrelation, result_ref: str, result_sha256: str) -> Ack: ...


class UnavailableGen4Peers:
    """Safe production placeholder until the exact peer tuple is delivered."""
    def _no(self, *_: Any, **__: Any) -> Any:
        raise DgerGen4Error("GEN4_PEER_CONTRACTS_UNAVAILABLE")
    establish_correlation = _no
    stage_moh = _no
    ahc_begin = _no
    ahc_status = _no
    moh_execute = _no
    moh_status = _no
    ahc_note_in_doubt = _no
    ahc_accept_terminal = _no
    chm_publish_terminal = _no


def _invocation_evidence_from_any(value: InvocationEvidence | dict[str, Any] | None) -> InvocationEvidence:
    if isinstance(value, InvocationEvidence):
        return value
    if not isinstance(value, dict):
        raise DgerGen4Error("GTG_INVOCATION_EVIDENCE_REQUIRED")
    expected = {"tool_id", "operation", "invocation_id", "tool_identity", "tool_tree", "gtg_identity", "registry_identity"}
    if set(value) != expected:
        raise DgerGen4Error("GTG_INVOCATION_EVIDENCE_INVALID")
    return InvocationEvidence(**{key: str(value[key]) for key in expected})


def _validate_invocation_evidence(
    value: InvocationEvidence | dict[str, Any] | None,
    *,
    expected_tool: str | None = None,
    expected_operation: str | None = None,
) -> InvocationEvidence:
    evidence = _invocation_evidence_from_any(value)
    _safe_id(evidence.tool_id, "GTG_INVOCATION_TOOL_INVALID")
    _safe_id(evidence.operation, "GTG_INVOCATION_OPERATION_INVALID")
    if expected_tool is not None and evidence.tool_id != expected_tool:
        raise DgerGen4Error("GTG_INVOCATION_TOOL_MISMATCH")
    if expected_operation is not None and evidence.operation != expected_operation:
        raise DgerGen4Error("GTG_INVOCATION_OPERATION_MISMATCH")
    if _GTG_INVOCATION_ID_RE.fullmatch(evidence.invocation_id) is None:
        raise DgerGen4Error("GTG_INVOCATION_ID_INVALID")
    for key in ("tool_identity", "tool_tree", "gtg_identity", "registry_identity"):
        if _HEX40_RE.fullmatch(getattr(evidence, key)) is None:
            raise DgerGen4Error("GTG_INVOCATION_IDENTITY_INVALID", key)
    return evidence


def _validate_ack(ack: Ack, expected_tool: str, expected_operation: str) -> InvocationEvidence:
    if not ack.ok or HEX64_RE.fullmatch(ack.digest) is None:
        raise DgerGen4Error("PEER_ACK_INVALID", expected_tool)
    return _validate_invocation_evidence(
        ack.invocation_evidence,
        expected_tool=expected_tool,
        expected_operation=expected_operation,
    )


def load_service_identity(path: Path) -> ServiceIdentity:
    value = _json_object_no_duplicates(read_protected_regular(path, 16_384))
    expected = {"schema", "service_principal_id", "service_deployment_id", "actor_role", "identity_digest"}
    if set(value) != expected or value.get("schema") != SERVICE_IDENTITY_SCHEMA:
        raise DgerGen4Error("SERVICE_IDENTITY_INVALID")
    principal = _safe_id(value.get("service_principal_id"), "SERVICE_IDENTITY_INVALID")
    deployment = _safe_id(value.get("service_deployment_id"), "SERVICE_IDENTITY_INVALID")
    if value.get("actor_role") != "EXECUTION_RELAY":
        raise DgerGen4Error("SERVICE_ROLE_INVALID")
    supplied = value.get("identity_digest")
    body = {k: value[k] for k in ("schema", "service_principal_id", "service_deployment_id", "actor_role")}
    if not isinstance(supplied, str) or supplied != canonical_digest(body):
        raise DgerGen4Error("SERVICE_IDENTITY_DIGEST_MISMATCH")
    return ServiceIdentity(principal, deployment, "EXECUTION_RELAY", supplied)


def _evidence_list(c: TrustedCorrelation) -> list[InvocationEvidence]:
    return [_validate_invocation_evidence(item) for item in c.provider_evidence]


def _correlation_to_dict(c: TrustedCorrelation) -> dict[str, Any]:
    return {
        "schema": TRUSTED_CORRELATION_SCHEMA,
        "origin": asdict(c.origin),
        "service_principal_id": c.service_principal_id,
        "service_deployment_id": c.service_deployment_id,
        "service_role": c.service_role,
        "delegation_invocation_id": c.delegation_invocation_id,
        "delegated_context_digest": c.delegated_context_digest,
        "ahc_execution_claim_id": c.ahc_execution_claim_id,
        "ahc_effect_reservation_id": c.ahc_effect_reservation_id,
        "ahc_work_revision": c.ahc_work_revision,
        "gep_execution_id": c.gep_execution_id,
        "gep_request_digest": c.gep_request_digest,
        "gep_admission_sha256": c.gep_admission_sha256,
        "chm_handoff_id": c.chm_handoff_id,
        "correlation_digest": c.correlation_digest,
        "provider_evidence": [asdict(item) for item in _evidence_list(c)],
    }


def _correlation_from_dict(value: dict[str, Any]) -> TrustedCorrelation:
    expected = {
        "schema", "origin", "service_principal_id", "service_deployment_id", "service_role",
        "delegation_invocation_id", "delegated_context_digest", "ahc_execution_claim_id",
        "ahc_effect_reservation_id", "ahc_work_revision", "gep_execution_id", "gep_request_digest",
        "gep_admission_sha256", "chm_handoff_id", "correlation_digest", "provider_evidence",
    }
    if set(value) != expected or value.get("schema") != TRUSTED_CORRELATION_SCHEMA or not isinstance(value.get("origin"), dict):
        raise DgerGen4Error("TRUSTED_CORRELATION_STATE_INVALID")
    o = value["origin"]
    origin_expected = {"tenant_id", "principal_id", "deployment_id", "actor_role", "fleet_epoch", "originating_invocation_id", "context_digest"}
    if set(o) != origin_expected:
        raise DgerGen4Error("TRUSTED_ORIGIN_STATE_INVALID")
    raw_evidence = value.get("provider_evidence")
    if not isinstance(raw_evidence, list):
        raise DgerGen4Error("TRUSTED_PROVIDER_EVIDENCE_STATE_INVALID")
    origin = TrustedOrigin(
        tenant_id=str(o["tenant_id"]), principal_id=str(o["principal_id"]), deployment_id=str(o["deployment_id"]),
        actor_role=str(o["actor_role"]), fleet_epoch=int(o["fleet_epoch"]),
        originating_invocation_id=str(o["originating_invocation_id"]), context_digest=str(o["context_digest"]),
    )
    return TrustedCorrelation(
        origin=origin,
        service_principal_id=str(value["service_principal_id"]),
        service_deployment_id=str(value["service_deployment_id"]),
        service_role=str(value["service_role"]),
        delegation_invocation_id=str(value["delegation_invocation_id"]),
        delegated_context_digest=str(value["delegated_context_digest"]),
        ahc_execution_claim_id=str(value["ahc_execution_claim_id"]),
        ahc_effect_reservation_id=str(value["ahc_effect_reservation_id"]),
        ahc_work_revision=str(value["ahc_work_revision"]),
        gep_execution_id=str(value["gep_execution_id"]),
        gep_request_digest=str(value["gep_request_digest"]),
        gep_admission_sha256=str(value["gep_admission_sha256"]),
        chm_handoff_id=value.get("chm_handoff_id"),
        correlation_digest=str(value["correlation_digest"]),
        provider_evidence=tuple(_invocation_evidence_from_any(item) for item in raw_evidence),
    )


def _validate_correlation(c: TrustedCorrelation, request: dict[str, Any], admission_sha256: str, payload_manifest_sha256: str, service: ServiceIdentity) -> None:
    # Trusted fields are produced by the authenticated peer adapter, never accepted
    # from transport. DGER proves only their internal consistency and correlation to
    # its immutable transport intent; it does not authenticate the serialized values.
    for value, code in (
        (c.origin.tenant_id, "TRUSTED_TENANT_INVALID"), (c.origin.principal_id, "TRUSTED_PRINCIPAL_INVALID"),
        (c.origin.deployment_id, "TRUSTED_ORIGIN_DEPLOYMENT_INVALID"),
        (c.service_principal_id, "TRUSTED_SERVICE_ID_INVALID"),
        (c.ahc_execution_claim_id, "TRUSTED_AHC_CLAIM_INVALID"), (c.ahc_effect_reservation_id, "TRUSTED_AHC_EFFECT_INVALID"),
        (c.ahc_work_revision, "TRUSTED_AHC_REVISION_INVALID"), (c.gep_execution_id, "TRUSTED_GEP_EXECUTION_INVALID"),
    ):
        _safe_id(value, code)
    # The delivered AHC DGER effect bridge is specifically an originating Builder
    # effect. Preserving this value is not impersonation: DGER remains the immediate
    # EXECUTION_RELAY service actor and never substitutes itself for the origin.
    if c.origin.actor_role != "BUILDER":
        raise DgerGen4Error("TRUSTED_ORIGIN_ROLE_INVALID")
    if _GTG_INVOCATION_ID_RE.fullmatch(c.origin.originating_invocation_id) is None:
        raise DgerGen4Error("TRUSTED_INVOCATION_INVALID")
    if c.origin.fleet_epoch < 1:
        raise DgerGen4Error("TRUSTED_FLEET_EPOCH_INVALID")
    if _GTG_CONTEXT_DIGEST_RE.fullmatch(c.origin.context_digest) is None:
        raise DgerGen4Error("TRUSTED_CONTEXT_DIGEST_INVALID")
    if c.service_role != "EXECUTION_RELAY" or service.actor_role != "EXECUTION_RELAY":
        raise DgerGen4Error("SERVICE_ROLE_INVALID")
    if c.service_principal_id != service.service_principal_id:
        raise DgerGen4Error("WRONG_DGER_SERVICE_ID")
    if c.service_deployment_id != service.service_deployment_id:
        raise DgerGen4Error("WRONG_DGER_SERVICE_DEPLOYMENT")
    if _GTG_DELEGATION_ID_RE.fullmatch(c.delegation_invocation_id) is None:
        raise DgerGen4Error("TRUSTED_DELEGATION_INVOCATION_INVALID")
    if _GTG_CONTEXT_DIGEST_RE.fullmatch(c.delegated_context_digest) is None:
        raise DgerGen4Error("TRUSTED_DELEGATED_CONTEXT_DIGEST_INVALID")
    for value, code in ((c.gep_request_digest, "TRUSTED_GEP_REQUEST_DIGEST_INVALID"), (c.gep_admission_sha256, "TRUSTED_ADMISSION_DIGEST_INVALID"), (c.correlation_digest, "TRUSTED_CORRELATION_DIGEST_INVALID")):
        if HEX64_RE.fullmatch(value) is None:
            raise DgerGen4Error(code)
    if c.gep_execution_id != request["gep_execution_id"]:
        raise DgerGen4Error("GEP_EXECUTION_MISMATCH")
    if c.ahc_effect_reservation_id != request["ahc_effect_reservation_id"]:
        raise DgerGen4Error("AHC_EFFECT_MISMATCH")
    if c.chm_handoff_id != request.get("chm_handoff_id"):
        raise DgerGen4Error("CHM_HANDOFF_CORRELATION_MISMATCH")
    if c.gep_admission_sha256 != admission_sha256:
        raise DgerGen4Error("GEP_ADMISSION_MISMATCH")

    evidence = _evidence_list(c)
    invocation_ids = [item.invocation_id for item in evidence]
    if len(invocation_ids) != len(set(invocation_ids)):
        raise DgerGen4Error("GTG_INVOCATION_EVIDENCE_DUPLICATE")
    # Require only exact source-delivered semantic operations. Authoritative GEP Gen13
    # has no post-#94 trusted correlation-read operation, so DGER deliberately does
    # not invent one here. That missing GEP source contract remains the narrow source
    # blocker for a production establish_correlation adapter.
    required_pairs = {(AHC_TOOL_ID, "effect_read")}
    if c.chm_handoff_id is not None:
        required_pairs.add((CHM_TOOL_ID, "handoff_get"))
    if {(item.tool_id, item.operation) for item in evidence} != required_pairs:
        raise DgerGen4Error("TRUSTED_CORRELATION_PROVIDER_SET_INVALID")

    expected_corr = canonical_digest({
        "origin": asdict(c.origin),
        "service_principal_id": c.service_principal_id,
        "service_deployment_id": c.service_deployment_id,
        "service_role": c.service_role,
        "delegation_invocation_id": c.delegation_invocation_id,
        "delegated_context_digest": c.delegated_context_digest,
        "ahc_execution_claim_id": c.ahc_execution_claim_id,
        "ahc_effect_reservation_id": c.ahc_effect_reservation_id,
        "ahc_work_revision": c.ahc_work_revision,
        "gep_execution_id": c.gep_execution_id,
        "gep_request_digest": c.gep_request_digest,
        "gep_admission_sha256": c.gep_admission_sha256,
        "payload_manifest_sha256": payload_manifest_sha256,
        "chm_handoff_id": c.chm_handoff_id,
        "provider_evidence": [asdict(item) for item in evidence],
    })
    if c.correlation_digest != expected_corr:
        raise DgerGen4Error("TRUSTED_CORRELATION_DIGEST_MISMATCH")


def _validate_ahc(obs: AhcObservation, c: TrustedCorrelation, expected_operation: str) -> None:
    if obs.effect_reservation_id != c.ahc_effect_reservation_id or obs.gep_execution_id != c.gep_execution_id:
        raise DgerGen4Error("AHC_OBSERVATION_CORRELATION_MISMATCH")
    if obs.state not in {"RESERVED", "IN_DOUBT", "SUCCEEDED", "FAILED"}:
        raise DgerGen4Error("AHC_OBSERVATION_STATE_INVALID")
    if HEX64_RE.fullmatch(obs.observation_digest) is None:
        raise DgerGen4Error("AHC_OBSERVATION_DIGEST_INVALID")
    _validate_invocation_evidence(
        obs.invocation_evidence,
        expected_tool=AHC_TOOL_ID,
        expected_operation=expected_operation,
    )


def _validate_moh(obs: MohObservation, c: TrustedCorrelation, expected_operation: str) -> None:
    if obs.gep_execution_id != c.gep_execution_id:
        raise DgerGen4Error("MOH_EXECUTION_MISMATCH")
    if obs.state not in MOH_ALL:
        raise DgerGen4Error("MOH_STATE_INVALID")
    if obs.record_id is not None:
        _safe_id(obs.record_id, "MOH_RECORD_ID_INVALID")
    if HEX64_RE.fullmatch(obs.evidence_digest) is None:
        raise DgerGen4Error("MOH_EVIDENCE_DIGEST_INVALID")
    _validate_invocation_evidence(
        obs.invocation_evidence,
        expected_tool=MOH_TOOL_ID,
        expected_operation=expected_operation,
    )
    raw = canonical_bytes(asdict(obs))
    if len(raw) > MAX_PEER_OBSERVATION_BYTES:
        raise DgerGen4Error("MOH_OBSERVATION_TOO_LARGE")
