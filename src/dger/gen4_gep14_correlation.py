from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Mapping, Protocol

from .gen4_contract import (
    AHC_TOOL_ID,
    CHM_TOOL_ID,
    GEP_TOOL_ID,
    Ack,
    AhcObservation,
    Gen4Peers,
    InvocationEvidence,
    MohObservation,
    ServiceIdentity,
    StageReceipt,
    TrustedCorrelation,
    TrustedOrigin,
    _validate_correlation,
    _validate_invocation_evidence,
)
from .gen4_delegation import (
    DelegatedServiceContext,
    parse_delegated_service_context,
    require_protected_service_match,
)
from .gen4_primitives import DgerGen4Error, HEX64_RE, REQUEST_SCHEMA, _safe_id, canonical_digest

GEP_CORRELATION_OPERATION = "correlation_read"
AHC_EFFECT_READ_OPERATION = "effect_read"
CHM_HANDOFF_READ_OPERATION = "handoff_read"
_GEP_CORRELATION_CODE = "GEP_TRUSTED_CORRELATION_READ"
_AHC_EFFECT_READ_CODE = "AHC_EFFECT_READ"
_CHM_HANDOFF_READ_CODE = "HANDOFF_FOUND"
_EXECUTION_ID_RE = re.compile(r"^execution_[0-9a-f]{64}$")
_EFFECT_ID_RE = re.compile(r"^effect-[0-9a-f]{40}$")
_HANDOFF_ID_RE = re.compile(r"^hnd_[0-9a-f]{64}$")

_GEP_RESULT_KEYS = {
    "ok",
    "code",
    "launch_capability",
    "origin",
    "service_deployment_id",
    "ahc_execution_claim_id",
    "ahc_effect_reservation_id",
    "ahc_work_revision",
    "gep_execution_id",
    "gep_request_digest",
    "gep_admission_sha256",
    "origin_envelope_sha256",
    "trusted_binding_digest",
    "result_binding",
}
_GEP_ORIGIN_KEYS = {
    "tenant_id",
    "principal_id",
    "deployment_id",
    "fleet_epoch",
    "originating_invocation_id",
    "context_digest",
}
_AHC_RESULT_KEYS = {
    "ok",
    "code",
    "effect_id",
    "execution_claim_id",
    "effect_class",
    "status",
    "workstream_id",
    "workstream_revision",
    "provisioned_fleet_epoch",
    "origin_context_digest",
    "origin_invocation_id",
    "gep_execution_id",
    "gep_request_digest",
    "reconciliation_mode",
    "terminal_evidence_digest",
    "replayed",
}
_CHM_RESULT_KEYS = {
    "ok",
    "code",
    "handoff_id",
    "namespace_binding",
    "project_binding",
    "external_execution",
    "terminal_result",
    "execution_authority",
    "authorizes_moh_execution",
    "ahc_effect_truth",
    "gep_execution_admission",
}


@dataclass(frozen=True)
class AuthenticatedPeerRead:
    """One protected GTG/GTC-authenticated delegated READ result.

    ``delegated_context`` is still parsed and consistency-checked by DGER, but its
    authentication is owned by the injected reader. A caller/Dropbox value is never
    sufficient to construct a production result at this boundary.
    """

    result: Mapping[str, Any]
    delegated_context: Mapping[str, Any]
    invocation_evidence: InvocationEvidence | dict[str, Any]


class AuthenticatedCorrelationReader(Protocol):
    """Protected semantic READ port used only by Gen4 correlation establishment.

    Implementations MUST authenticate the DGER EXECUTION_RELAY service and the exact
    non-transferable GTG delegated origin context before invoking the named peer.
    They MUST reject caller-selected identity/context and return exact invocation-time
    provider identity evidence for the operation actually invoked.
    """

    def invoke_read(
        self,
        tool_id: str,
        operation: str,
        arguments: Mapping[str, Any],
        service_identity: ServiceIdentity,
    ) -> AuthenticatedPeerRead: ...


def _require_mapping(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DgerGen4Error(code)
    return dict(value)


def _same_origin_service(a: DelegatedServiceContext, b: DelegatedServiceContext) -> bool:
    fields = (
        "tenant_id",
        "principal_id",
        "deployment_id",
        "origin_actor_role",
        "provisioned_fleet_epoch",
        "origin_context_digest",
        "origin_invocation_id",
        "service_role",
        "service_id",
        "service_deployment_id",
        "project_binding",
    )
    return all(getattr(a, field) == getattr(b, field) for field in fields)


class Gep14CorrelationPeers:
    """Gen4 peer wrapper that supplies only the GEP Gen14 correlation proposition.

    All non-correlation methods are delegated byte-for-byte/argument-for-argument to
    ``base_peers``. This class therefore cannot alter AHC begin/reconcile/terminal,
    MOH stage/execute/status, or CHM terminal semantics or DGER's durable ordering.
    """

    def __init__(self, base_peers: Gen4Peers, reader: AuthenticatedCorrelationReader) -> None:
        self._base = base_peers
        self._reader = reader

    def _read(
        self,
        tool_id: str,
        operation: str,
        arguments: Mapping[str, Any],
        service: ServiceIdentity,
    ) -> tuple[dict[str, Any], DelegatedServiceContext, InvocationEvidence]:
        observed = self._reader.invoke_read(tool_id, operation, dict(arguments), service)
        if not isinstance(observed, AuthenticatedPeerRead):
            raise DgerGen4Error("AUTHENTICATED_PEER_READ_INVALID")
        context = parse_delegated_service_context(
            _require_mapping(observed.delegated_context, "DELEGATED_CONTEXT_INVALID")
        )
        require_protected_service_match(context, service)
        if "READ" not in context.authorized_capability_classes:
            raise DgerGen4Error("DELEGATED_CONTEXT_READ_NOT_AUTHORIZED")
        exact_operation = f"tool:{tool_id}:{operation}"
        if exact_operation not in context.authorized_operations:
            raise DgerGen4Error("DELEGATED_CONTEXT_OPERATION_NOT_AUTHORIZED", exact_operation)
        evidence = _validate_invocation_evidence(
            observed.invocation_evidence,
            expected_tool=tool_id,
            expected_operation=operation,
        )
        result = _require_mapping(observed.result, "PEER_READ_RESULT_INVALID")
        if result.get("ok") is not True:
            detail = result.get("code") if isinstance(result.get("code"), str) else ""
            raise DgerGen4Error("PEER_READ_FAILED", detail)
        return result, context, evidence

    @staticmethod
    def _validate_request_inputs(
        request: Mapping[str, Any], admission_sha256: str, payload_manifest_sha256: str
    ) -> tuple[str, str, str | None]:
        expected = {
            "schema",
            "dger_request_id",
            "gep_execution_id",
            "ahc_effect_reservation_id",
            "chm_handoff_id",
        }
        if set(request) != expected or request.get("schema") != REQUEST_SCHEMA:
            raise DgerGen4Error("MALFORMED_REQUEST")
        _safe_id(request.get("dger_request_id"), "INVALID_DGER_REQUEST_ID")
        gep_execution_id = request.get("gep_execution_id")
        effect_id = request.get("ahc_effect_reservation_id")
        handoff_id = request.get("chm_handoff_id")
        if not isinstance(gep_execution_id, str) or _EXECUTION_ID_RE.fullmatch(gep_execution_id) is None:
            raise DgerGen4Error("INVALID_GEP_EXECUTION_ID")
        if not isinstance(effect_id, str) or _EFFECT_ID_RE.fullmatch(effect_id) is None:
            raise DgerGen4Error("INVALID_AHC_EFFECT_ID")
        if handoff_id is not None and (
            not isinstance(handoff_id, str) or _HANDOFF_ID_RE.fullmatch(handoff_id) is None
        ):
            raise DgerGen4Error("INVALID_CHM_HANDOFF_ID")
        if HEX64_RE.fullmatch(admission_sha256) is None:
            raise DgerGen4Error("GEP_ADMISSION_DIGEST_INVALID")
        if HEX64_RE.fullmatch(payload_manifest_sha256) is None:
            raise DgerGen4Error("PAYLOAD_MANIFEST_DIGEST_INVALID")
        return gep_execution_id, effect_id, handoff_id

    @staticmethod
    def _validate_gep(
        result: dict[str, Any],
        context: DelegatedServiceContext,
        service: ServiceIdentity,
        gep_execution_id: str,
        effect_id: str,
        admission_sha256: str,
    ) -> tuple[TrustedOrigin, str, str, str]:
        if set(result) != _GEP_RESULT_KEYS:
            raise DgerGen4Error("GEP_CORRELATION_RESULT_INVALID")
        if result.get("code") != _GEP_CORRELATION_CODE or result.get("launch_capability") is not False:
            raise DgerGen4Error("GEP_CORRELATION_RESULT_INVALID")
        origin = _require_mapping(result.get("origin"), "GEP_CORRELATION_ORIGIN_INVALID")
        if set(origin) != _GEP_ORIGIN_KEYS:
            raise DgerGen4Error("GEP_CORRELATION_ORIGIN_INVALID")
        # GEP Gen14 intentionally projects origin context_digest as bare 64-hex via
        # context_digest_hex(). The authenticated delegated context remains the
        # authoritative prefixed value DGER persists.
        expected_origin = {
            "tenant_id": context.tenant_id,
            "principal_id": context.principal_id,
            "deployment_id": context.deployment_id,
            "fleet_epoch": context.provisioned_fleet_epoch,
            "originating_invocation_id": context.origin_invocation_id,
            "context_digest": context.origin_context_digest.split(":", 1)[1],
        }
        if origin != expected_origin:
            raise DgerGen4Error("GEP_ORIGIN_CONTEXT_MISMATCH")
        if result.get("service_deployment_id") != service.service_deployment_id:
            raise DgerGen4Error("GEP_SERVICE_DEPLOYMENT_MISMATCH")
        if result.get("gep_execution_id") != gep_execution_id:
            raise DgerGen4Error("GEP_EXECUTION_MISMATCH")
        if result.get("ahc_effect_reservation_id") != effect_id:
            raise DgerGen4Error("AHC_EFFECT_MISMATCH")
        if result.get("gep_admission_sha256") != admission_sha256:
            raise DgerGen4Error("GEP_ADMISSION_MISMATCH")
        request_digest = result.get("gep_request_digest")
        admission_digest = result.get("gep_admission_sha256")
        origin_envelope = result.get("origin_envelope_sha256")
        trusted_binding = result.get("trusted_binding_digest")
        for value, code in (
            (request_digest, "TRUSTED_GEP_REQUEST_DIGEST_INVALID"),
            (admission_digest, "TRUSTED_ADMISSION_DIGEST_INVALID"),
            (origin_envelope, "GEP_ORIGIN_ENVELOPE_DIGEST_INVALID"),
            (trusted_binding, "GEP_TRUSTED_BINDING_DIGEST_INVALID"),
        ):
            if not isinstance(value, str) or HEX64_RE.fullmatch(value) is None:
                raise DgerGen4Error(code)
        claim_id = _safe_id(result.get("ahc_execution_claim_id"), "TRUSTED_AHC_CLAIM_INVALID")
        work_revision = _safe_id(result.get("ahc_work_revision"), "TRUSTED_AHC_REVISION_INVALID")
        trusted_origin = TrustedOrigin(
            tenant_id=context.tenant_id,
            principal_id=context.principal_id,
            deployment_id=context.deployment_id,
            actor_role=context.origin_actor_role,
            fleet_epoch=context.provisioned_fleet_epoch,
            originating_invocation_id=context.origin_invocation_id,
            context_digest=context.origin_context_digest,
        )
        return trusted_origin, claim_id, work_revision, request_digest

    @staticmethod
    def _validate_ahc_read(
        result: dict[str, Any],
        context: DelegatedServiceContext,
        gep_context: DelegatedServiceContext,
        *,
        claim_id: str,
        effect_id: str,
        work_revision: str,
        gep_execution_id: str,
        gep_request_digest: str,
    ) -> None:
        if not _same_origin_service(context, gep_context):
            raise DgerGen4Error("AHC_ORIGIN_CONTEXT_MISMATCH")
        if set(result) != _AHC_RESULT_KEYS or result.get("code") != _AHC_EFFECT_READ_CODE:
            raise DgerGen4Error("AHC_EFFECT_READ_RESULT_INVALID")
        if result.get("status") != "RESERVED" or result.get("reconciliation_mode") != "INDEPENDENT":
            raise DgerGen4Error("AHC_EFFECT_STALE_OR_SUPERSEDED")
        checks = (
            (result.get("effect_id"), effect_id, "AHC_EFFECT_MISMATCH"),
            (result.get("execution_claim_id"), claim_id, "AHC_CLAIM_MISMATCH"),
            (str(result.get("workstream_revision")), work_revision, "AHC_WORK_REVISION_MISMATCH"),
            (result.get("provisioned_fleet_epoch"), gep_context.provisioned_fleet_epoch, "AHC_FLEET_EPOCH_MISMATCH"),
            (result.get("origin_context_digest"), gep_context.origin_context_digest, "AHC_ORIGIN_CONTEXT_MISMATCH"),
            (result.get("origin_invocation_id"), gep_context.origin_invocation_id, "AHC_ORIGIN_CONTEXT_MISMATCH"),
            (result.get("gep_execution_id"), gep_execution_id, "GEP_EXECUTION_MISMATCH"),
            (result.get("gep_request_digest"), gep_request_digest, "GEP_REQUEST_DIGEST_MISMATCH"),
        )
        for observed, expected, code in checks:
            if observed != expected:
                raise DgerGen4Error(code)

    @staticmethod
    def _validate_chm_read(
        result: dict[str, Any],
        context: DelegatedServiceContext,
        gep_context: DelegatedServiceContext,
        *,
        handoff_id: str,
        effect_id: str,
        gep_execution_id: str,
    ) -> None:
        if not _same_origin_service(context, gep_context):
            raise DgerGen4Error("CHM_ORIGIN_CONTEXT_MISMATCH")
        if set(result) != _CHM_RESULT_KEYS or result.get("code") != _CHM_HANDOFF_READ_CODE:
            raise DgerGen4Error("CHM_HANDOFF_READ_RESULT_INVALID")
        namespace = result.get("namespace_binding")
        expected_namespace = {
            "tenant_id": gep_context.tenant_id,
            "principal_id": gep_context.principal_id,
            "deployment_id": gep_context.deployment_id,
        }
        if namespace != expected_namespace or result.get("project_binding") != gep_context.project_binding:
            raise DgerGen4Error("CHM_ORIGIN_CONTEXT_MISMATCH")
        if result.get("handoff_id") != handoff_id:
            raise DgerGen4Error("CHM_HANDOFF_CORRELATION_MISMATCH")
        external = result.get("external_execution")
        if external != {"ahc_effect_id": effect_id, "gep_execution_id": gep_execution_id}:
            raise DgerGen4Error("CHM_EXTERNAL_EXECUTION_MISMATCH")
        if (
            result.get("execution_authority") != "NOT_CHM"
            or result.get("authorizes_moh_execution") is not False
            or result.get("ahc_effect_truth") != "NOT_CHM"
            or result.get("gep_execution_admission") != "NOT_CHM"
        ):
            raise DgerGen4Error("CHM_AUTHORITY_CLAIM_INVALID")

    def establish_correlation(
        self,
        request: dict[str, Any],
        admission_sha256: str,
        payload_manifest_sha256: str,
        service_identity: ServiceIdentity,
    ) -> TrustedCorrelation:
        if service_identity.actor_role != "EXECUTION_RELAY":
            raise DgerGen4Error("SERVICE_ROLE_INVALID")
        gep_execution_id, effect_id, handoff_id = self._validate_request_inputs(
            request, admission_sha256, payload_manifest_sha256
        )
        gep_result, gep_context, gep_evidence = self._read(
            GEP_TOOL_ID,
            GEP_CORRELATION_OPERATION,
            {"execution_id": gep_execution_id},
            service_identity,
        )
        origin, claim_id, work_revision, gep_request_digest = self._validate_gep(
            gep_result,
            gep_context,
            service_identity,
            gep_execution_id,
            effect_id,
            admission_sha256,
        )
        if origin.actor_role != "BUILDER":
            raise DgerGen4Error("TRUSTED_ORIGIN_ROLE_INVALID")

        ahc_result, ahc_context, ahc_evidence = self._read(
            AHC_TOOL_ID,
            AHC_EFFECT_READ_OPERATION,
            {
                "execution_claim_id": claim_id,
                "effect_id": effect_id,
                "gep_execution_id": gep_execution_id,
                "gep_request_digest": gep_request_digest,
            },
            service_identity,
        )
        self._validate_ahc_read(
            ahc_result,
            ahc_context,
            gep_context,
            claim_id=claim_id,
            effect_id=effect_id,
            work_revision=work_revision,
            gep_execution_id=gep_execution_id,
            gep_request_digest=gep_request_digest,
        )

        provider_evidence: list[InvocationEvidence] = [gep_evidence, ahc_evidence]
        if handoff_id is not None:
            chm_result, chm_context, chm_evidence = self._read(
                CHM_TOOL_ID,
                CHM_HANDOFF_READ_OPERATION,
                {"handoff_id": handoff_id},
                service_identity,
            )
            self._validate_chm_read(
                chm_result,
                chm_context,
                gep_context,
                handoff_id=handoff_id,
                effect_id=effect_id,
                gep_execution_id=gep_execution_id,
            )
            provider_evidence.append(chm_evidence)

        body = {
            "origin": asdict(origin),
            "service_principal_id": service_identity.service_principal_id,
            "service_deployment_id": service_identity.service_deployment_id,
            "service_role": service_identity.actor_role,
            "delegation_invocation_id": gep_context.delegation_invocation_id,
            "delegated_context_digest": gep_context.context_digest,
            "ahc_execution_claim_id": claim_id,
            "ahc_effect_reservation_id": effect_id,
            "ahc_work_revision": work_revision,
            "gep_execution_id": gep_execution_id,
            "gep_request_digest": gep_request_digest,
            "gep_admission_sha256": admission_sha256,
            "payload_manifest_sha256": payload_manifest_sha256,
            "chm_handoff_id": handoff_id,
            "provider_evidence": [asdict(item) for item in provider_evidence],
        }
        correlation = TrustedCorrelation(
            origin=origin,
            service_principal_id=service_identity.service_principal_id,
            service_deployment_id=service_identity.service_deployment_id,
            service_role=service_identity.actor_role,
            delegation_invocation_id=gep_context.delegation_invocation_id,
            delegated_context_digest=gep_context.context_digest,
            ahc_execution_claim_id=claim_id,
            ahc_effect_reservation_id=effect_id,
            ahc_work_revision=work_revision,
            gep_execution_id=gep_execution_id,
            gep_request_digest=gep_request_digest,
            gep_admission_sha256=admission_sha256,
            chm_handoff_id=handoff_id,
            correlation_digest=canonical_digest(body),
            provider_evidence=tuple(provider_evidence),
        )
        _validate_correlation(
            correlation,
            request,
            admission_sha256,
            payload_manifest_sha256,
            service_identity,
        )
        return correlation

    def stage_moh(
        self, correlation: TrustedCorrelation, frozen_stage: Any, payload_manifest_sha256: str
    ) -> StageReceipt:
        return self._base.stage_moh(correlation, frozen_stage, payload_manifest_sha256)

    def ahc_begin(self, correlation: TrustedCorrelation) -> AhcObservation:
        return self._base.ahc_begin(correlation)

    def ahc_status(self, correlation: TrustedCorrelation) -> AhcObservation:
        return self._base.ahc_status(correlation)

    def moh_execute(self, correlation: TrustedCorrelation) -> MohObservation:
        return self._base.moh_execute(correlation)

    def moh_status(self, correlation: TrustedCorrelation) -> MohObservation:
        return self._base.moh_status(correlation)

    def ahc_note_in_doubt(self, correlation: TrustedCorrelation, moh_observation_digest: str) -> Ack:
        return self._base.ahc_note_in_doubt(correlation, moh_observation_digest)

    def ahc_accept_terminal(
        self,
        correlation: TrustedCorrelation,
        terminal_digest: str,
        result_ref: str,
        result_sha256: str,
    ) -> Ack:
        return self._base.ahc_accept_terminal(correlation, terminal_digest, result_ref, result_sha256)

    def chm_publish_terminal(
        self, correlation: TrustedCorrelation, result_ref: str, result_sha256: str
    ) -> Ack:
        return self._base.chm_publish_terminal(correlation, result_ref, result_sha256)
