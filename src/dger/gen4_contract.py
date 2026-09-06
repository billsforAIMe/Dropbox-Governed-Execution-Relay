from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .gen4_primitives import (
    DgerGen4Error, HEX64_RE, MAX_PEER_OBSERVATION_BYTES, MOH_ALL, SERVICE_IDENTITY_SCHEMA, TRUSTED_CORRELATION_SCHEMA, _json_object_no_duplicates, _safe_id,
    canonical_bytes, canonical_digest, read_protected_regular,
)

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
    fleet_epoch: int
    originating_invocation_id: str
    context_digest: str


@dataclass(frozen=True)
class TrustedCorrelation:
    origin: TrustedOrigin
    service_deployment_id: str
    ahc_execution_claim_id: str
    ahc_effect_reservation_id: str
    ahc_work_revision: str
    gep_execution_id: str
    gep_request_digest: str
    gep_admission_sha256: str
    chm_handoff_id: str | None
    correlation_digest: str


@dataclass(frozen=True)
class StageReceipt:
    gep_execution_id: str
    admission_sha256: str
    payload_manifest_sha256: str
    stage_digest: str


@dataclass(frozen=True)
class AhcObservation:
    effect_reservation_id: str
    gep_execution_id: str
    state: str
    observation_digest: str


@dataclass(frozen=True)
class MohObservation:
    gep_execution_id: str
    state: str
    record_id: str | None
    evidence_digest: str
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class Ack:
    ok: bool
    digest: str


class Gen4Peers(Protocol):
    """Internal semantic port. Wire/auth translation belongs to the exact delivered peer adapter.

    Implementations MUST invoke peers under the protected DGER service credential/delegated
    context. No method accepts identity from Dropbox as authority. The production adapter is
    intentionally unavailable until GTG/GTC #94 and the exact AHC/GEP/CHM/MOH contracts ship.
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
    def ahc_note_in_doubt(self, correlation: TrustedCorrelation, moh: MohObservation) -> Ack: ...
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


def _correlation_to_dict(c: TrustedCorrelation) -> dict[str, Any]:
    return {
        "schema": TRUSTED_CORRELATION_SCHEMA,
        "origin": asdict(c.origin),
        "service_deployment_id": c.service_deployment_id,
        "ahc_execution_claim_id": c.ahc_execution_claim_id,
        "ahc_effect_reservation_id": c.ahc_effect_reservation_id,
        "ahc_work_revision": c.ahc_work_revision,
        "gep_execution_id": c.gep_execution_id,
        "gep_request_digest": c.gep_request_digest,
        "gep_admission_sha256": c.gep_admission_sha256,
        "chm_handoff_id": c.chm_handoff_id,
        "correlation_digest": c.correlation_digest,
    }


def _correlation_from_dict(value: dict[str, Any]) -> TrustedCorrelation:
    if value.get("schema") != TRUSTED_CORRELATION_SCHEMA or not isinstance(value.get("origin"), dict):
        raise DgerGen4Error("TRUSTED_CORRELATION_STATE_INVALID")
    o = value["origin"]
    origin = TrustedOrigin(
        tenant_id=str(o["tenant_id"]), principal_id=str(o["principal_id"]), deployment_id=str(o["deployment_id"]),
        fleet_epoch=int(o["fleet_epoch"]), originating_invocation_id=str(o["originating_invocation_id"]), context_digest=str(o["context_digest"]),
    )
    return TrustedCorrelation(
        origin=origin,
        service_deployment_id=str(value["service_deployment_id"]),
        ahc_execution_claim_id=str(value["ahc_execution_claim_id"]),
        ahc_effect_reservation_id=str(value["ahc_effect_reservation_id"]),
        ahc_work_revision=str(value["ahc_work_revision"]),
        gep_execution_id=str(value["gep_execution_id"]),
        gep_request_digest=str(value["gep_request_digest"]),
        gep_admission_sha256=str(value["gep_admission_sha256"]),
        chm_handoff_id=value.get("chm_handoff_id"),
        correlation_digest=str(value["correlation_digest"]),
    )


def _validate_correlation(c: TrustedCorrelation, request: dict[str, Any], admission_sha256: str, payload_manifest_sha256: str, service: ServiceIdentity) -> None:
    # Trusted fields are produced by the authenticated peer adapter, never accepted
    # from transport. DGER only proves that routing/correlation hints match that truth.
    for value, code in (
        (c.origin.tenant_id, "TRUSTED_TENANT_INVALID"), (c.origin.principal_id, "TRUSTED_PRINCIPAL_INVALID"),
        (c.origin.deployment_id, "TRUSTED_ORIGIN_DEPLOYMENT_INVALID"), (c.origin.originating_invocation_id, "TRUSTED_INVOCATION_INVALID"),
        (c.ahc_execution_claim_id, "TRUSTED_AHC_CLAIM_INVALID"), (c.ahc_effect_reservation_id, "TRUSTED_AHC_EFFECT_INVALID"),
        (c.ahc_work_revision, "TRUSTED_AHC_REVISION_INVALID"), (c.gep_execution_id, "TRUSTED_GEP_EXECUTION_INVALID"),
    ):
        _safe_id(value, code)
    if c.origin.fleet_epoch < 0:
        raise DgerGen4Error("TRUSTED_FLEET_EPOCH_INVALID")
    for value, code in ((c.origin.context_digest, "TRUSTED_CONTEXT_DIGEST_INVALID"), (c.gep_request_digest, "TRUSTED_GEP_REQUEST_DIGEST_INVALID"), (c.gep_admission_sha256, "TRUSTED_ADMISSION_DIGEST_INVALID"), (c.correlation_digest, "TRUSTED_CORRELATION_DIGEST_INVALID")):
        if HEX64_RE.fullmatch(value) is None:
            raise DgerGen4Error(code)
    if c.service_deployment_id != service.service_deployment_id:
        raise DgerGen4Error("WRONG_DGER_SERVICE_DEPLOYMENT")
    if c.gep_execution_id != request["gep_execution_id"]:
        raise DgerGen4Error("GEP_EXECUTION_MISMATCH")
    if c.ahc_effect_reservation_id != request["ahc_effect_reservation_id"]:
        raise DgerGen4Error("AHC_EFFECT_MISMATCH")
    if c.chm_handoff_id != request.get("chm_handoff_id"):
        raise DgerGen4Error("CHM_HANDOFF_CORRELATION_MISMATCH")
    if c.gep_admission_sha256 != admission_sha256:
        raise DgerGen4Error("GEP_ADMISSION_MISMATCH")
    # The exact peer adapter is responsible for proving payload closure against the
    # authenticated GEP admission. The normalized correlation digest binds that proof.
    expected_corr = canonical_digest({
        "origin": asdict(c.origin),
        "service_deployment_id": c.service_deployment_id,
        "ahc_execution_claim_id": c.ahc_execution_claim_id,
        "ahc_effect_reservation_id": c.ahc_effect_reservation_id,
        "ahc_work_revision": c.ahc_work_revision,
        "gep_execution_id": c.gep_execution_id,
        "gep_request_digest": c.gep_request_digest,
        "gep_admission_sha256": c.gep_admission_sha256,
        "payload_manifest_sha256": payload_manifest_sha256,
        "chm_handoff_id": c.chm_handoff_id,
    })
    if c.correlation_digest != expected_corr:
        raise DgerGen4Error("TRUSTED_CORRELATION_DIGEST_MISMATCH")


def _validate_ahc(obs: AhcObservation, c: TrustedCorrelation) -> None:
    if obs.effect_reservation_id != c.ahc_effect_reservation_id or obs.gep_execution_id != c.gep_execution_id:
        raise DgerGen4Error("AHC_OBSERVATION_CORRELATION_MISMATCH")
    if obs.state not in {"RESERVED", "IN_DOUBT", "SUCCEEDED", "FAILED"}:
        raise DgerGen4Error("AHC_OBSERVATION_STATE_INVALID")
    if HEX64_RE.fullmatch(obs.observation_digest) is None:
        raise DgerGen4Error("AHC_OBSERVATION_DIGEST_INVALID")


def _validate_moh(obs: MohObservation, c: TrustedCorrelation) -> None:
    if obs.gep_execution_id != c.gep_execution_id:
        raise DgerGen4Error("MOH_EXECUTION_MISMATCH")
    if obs.state not in MOH_ALL:
        raise DgerGen4Error("MOH_STATE_INVALID")
    if obs.record_id is not None:
        _safe_id(obs.record_id, "MOH_RECORD_ID_INVALID")
    if HEX64_RE.fullmatch(obs.evidence_digest) is None:
        raise DgerGen4Error("MOH_EVIDENCE_DIGEST_INVALID")
    raw = canonical_bytes(asdict(obs))
    if len(raw) > MAX_PEER_OBSERVATION_BYTES:
        raise DgerGen4Error("MOH_OBSERVATION_TOO_LARGE")
