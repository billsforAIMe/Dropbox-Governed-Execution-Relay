from __future__ import annotations

from copy import deepcopy
import unittest

from dger.gen4 import (
    AHC_EFFECT_READ_OPERATION,
    CHM_HANDOFF_READ_OPERATION,
    GEP_CORRELATION_OPERATION,
    AuthenticatedPeerRead,
    DgerGen4Error,
    Gep14CorrelationPeers,
    InvocationEvidence,
    REQUEST_SCHEMA,
    UnavailableGen4Peers,
    canonical_file_bytes,
    sha256,
)
from test_gen4 import service_identity

GEP_TOOL = "governed-execution-platform"
AHC_TOOL = "autonomous-handoff-coordinator"
CHM_TOOL = "common-handoff-manager"
EXECUTION_ID = "execution_" + "e" * 64
EFFECT_ID = "effect-" + "f" * 40
HANDOFF_ID = "hnd_" + "a" * 64
ADMISSION_SHA256 = "3" * 64
PAYLOAD_SHA256 = "4" * 64
GEP_REQUEST_DIGEST = "2" * 64
ORIGIN_CONTEXT_DIGEST = "sha256:" + "1" * 64
WORK_REVISION = 12
CLAIM_ID = "claim-001"
PROJECT = "Tools"


def request(handoff_id: str | None = HANDOFF_ID) -> dict:
    return {
        "schema": REQUEST_SCHEMA,
        "dger_request_id": "dger-001",
        "gep_execution_id": EXECUTION_ID,
        "ahc_effect_reservation_id": EFFECT_ID,
        "chm_handoff_id": handoff_id,
    }


def delegated_context(tool_id: str, operation: str, marker: str) -> dict:
    value = {
        "schema": "governed-delegated-service-context/v1",
        "issuer": "governed-tool-gateway",
        "tenant_id": "tenant-A",
        "principal_id": "principal-A",
        "deployment_id": "builder-deployment-A",
        "origin_actor_role": "BUILDER",
        "provisioned_fleet_epoch": 7,
        "origin_context_digest": ORIGIN_CONTEXT_DIGEST,
        "origin_invocation_id": "gtg_inv_" + "b" * 64,
        "service_role": "EXECUTION_RELAY",
        "service_id": "dger-service",
        "service_deployment_id": "dger-deployment-A",
        "delegation_invocation_id": "gtg_del_" + marker * 64,
        "authorized_operations": [f"tool:{tool_id}:{operation}"],
        "authorized_capability_classes": ["READ"],
        "project_binding": PROJECT,
    }
    value["context_digest"] = "sha256:" + sha256(canonical_file_bytes(value))
    return value


def evidence(tool_id: str, operation: str, sequence: int) -> InvocationEvidence:
    return InvocationEvidence(
        tool_id=tool_id,
        operation=operation,
        invocation_id=f"gtg_inv_{sequence:064x}",
        tool_identity=f"{100 + sequence:040x}",
        tool_tree=f"{200 + sequence:040x}",
        gtg_identity=f"{300 + sequence:040x}",
        registry_identity=f"{400 + sequence:040x}",
    )


def gep_result() -> dict:
    return {
        "ok": True,
        "code": "GEP_TRUSTED_CORRELATION_READ",
        "launch_capability": False,
        "origin": {
            "tenant_id": "tenant-A",
            "principal_id": "principal-A",
            "deployment_id": "builder-deployment-A",
            "fleet_epoch": 7,
            "originating_invocation_id": "gtg_inv_" + "b" * 64,
            "context_digest": "1" * 64,
        },
        "service_deployment_id": "dger-deployment-A",
        "ahc_execution_claim_id": CLAIM_ID,
        "ahc_effect_reservation_id": EFFECT_ID,
        "ahc_work_revision": str(WORK_REVISION),
        "gep_execution_id": EXECUTION_ID,
        "gep_request_digest": GEP_REQUEST_DIGEST,
        "gep_admission_sha256": ADMISSION_SHA256,
        "origin_envelope_sha256": "5" * 64,
        "trusted_binding_digest": "6" * 64,
        "result_binding": None,
    }


def ahc_result() -> dict:
    return {
        "ok": True,
        "code": "AHC_EFFECT_READ",
        "effect_id": EFFECT_ID,
        "execution_claim_id": CLAIM_ID,
        "effect_class": "EXTERNAL_EXECUTION",
        "status": "RESERVED",
        "workstream_id": "workstream-001",
        "workstream_revision": WORK_REVISION,
        "provisioned_fleet_epoch": 7,
        "origin_context_digest": ORIGIN_CONTEXT_DIGEST,
        "origin_invocation_id": "gtg_inv_" + "b" * 64,
        "gep_execution_id": EXECUTION_ID,
        "gep_request_digest": GEP_REQUEST_DIGEST,
        "reconciliation_mode": "INDEPENDENT",
        "terminal_evidence_digest": None,
        "replayed": False,
    }


def chm_result() -> dict:
    return {
        "ok": True,
        "code": "HANDOFF_FOUND",
        "handoff_id": HANDOFF_ID,
        "namespace_binding": {
            "tenant_id": "tenant-A",
            "principal_id": "principal-A",
            "deployment_id": "builder-deployment-A",
        },
        "project_binding": PROJECT,
        "external_execution": {
            "ahc_effect_id": EFFECT_ID,
            "gep_execution_id": EXECUTION_ID,
        },
        "terminal_result": None,
        "execution_authority": "NOT_CHM",
        "authorizes_moh_execution": False,
        "ahc_effect_truth": "NOT_CHM",
        "gep_execution_admission": "NOT_CHM",
    }


class Reader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.rows = {
            (GEP_TOOL, GEP_CORRELATION_OPERATION): AuthenticatedPeerRead(
                gep_result(), delegated_context(GEP_TOOL, GEP_CORRELATION_OPERATION, "c"),
                evidence(GEP_TOOL, GEP_CORRELATION_OPERATION, 1),
            ),
            (AHC_TOOL, AHC_EFFECT_READ_OPERATION): AuthenticatedPeerRead(
                ahc_result(), delegated_context(AHC_TOOL, AHC_EFFECT_READ_OPERATION, "d"),
                evidence(AHC_TOOL, AHC_EFFECT_READ_OPERATION, 2),
            ),
            (CHM_TOOL, CHM_HANDOFF_READ_OPERATION): AuthenticatedPeerRead(
                chm_result(), delegated_context(CHM_TOOL, CHM_HANDOFF_READ_OPERATION, "e"),
                evidence(CHM_TOOL, CHM_HANDOFF_READ_OPERATION, 3),
            ),
        }

    def invoke_read(self, tool_id, operation, arguments, service_identity):
        self.calls.append((tool_id, operation, dict(arguments)))
        return self.rows[(tool_id, operation)]


class Gep14CorrelationAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reader = Reader()
        self.adapter = Gep14CorrelationPeers(UnavailableGen4Peers(), self.reader)
        self.service = service_identity()

    def establish(self, handoff_id: str | None = HANDOFF_ID):
        return self.adapter.establish_correlation(
            request(handoff_id), ADMISSION_SHA256, PAYLOAD_SHA256, self.service
        )

    def test_exact_gep_ahc_chm_projection_establishes_correlation(self):
        correlation = self.establish()
        self.assertEqual(correlation.gep_execution_id, EXECUTION_ID)
        self.assertEqual(correlation.ahc_effect_reservation_id, EFFECT_ID)
        self.assertEqual(correlation.ahc_execution_claim_id, CLAIM_ID)
        self.assertEqual(correlation.ahc_work_revision, str(WORK_REVISION))
        self.assertEqual(correlation.gep_admission_sha256, ADMISSION_SHA256)
        self.assertEqual(correlation.chm_handoff_id, HANDOFF_ID)
        self.assertEqual(correlation.origin.context_digest, ORIGIN_CONTEXT_DIGEST)
        self.assertEqual(
            [(item.tool_id, item.operation) for item in correlation.provider_evidence],
            [
                (GEP_TOOL, GEP_CORRELATION_OPERATION),
                (AHC_TOOL, AHC_EFFECT_READ_OPERATION),
                (CHM_TOOL, CHM_HANDOFF_READ_OPERATION),
            ],
        )
        self.assertEqual(
            self.reader.calls,
            [
                (GEP_TOOL, GEP_CORRELATION_OPERATION, {"execution_id": EXECUTION_ID}),
                (
                    AHC_TOOL,
                    AHC_EFFECT_READ_OPERATION,
                    {
                        "execution_claim_id": CLAIM_ID,
                        "effect_id": EFFECT_ID,
                        "gep_execution_id": EXECUTION_ID,
                        "gep_request_digest": GEP_REQUEST_DIGEST,
                    },
                ),
                (CHM_TOOL, CHM_HANDOFF_READ_OPERATION, {"handoff_id": HANDOFF_ID}),
            ],
        )

    def test_no_handoff_uses_only_gep_and_ahc(self):
        correlation = self.establish(None)
        self.assertIsNone(correlation.chm_handoff_id)
        self.assertEqual(
            [(item.tool_id, item.operation) for item in correlation.provider_evidence],
            [(GEP_TOOL, GEP_CORRELATION_OPERATION), (AHC_TOOL, AHC_EFFECT_READ_OPERATION)],
        )
        self.assertEqual(len(self.reader.calls), 2)

    def test_gep_bare_origin_digest_must_equal_authenticated_context_suffix(self):
        row = self.reader.rows[(GEP_TOOL, GEP_CORRELATION_OPERATION)]
        changed = deepcopy(dict(row.result))
        changed["origin"]["context_digest"] = "9" * 64
        self.reader.rows[(GEP_TOOL, GEP_CORRELATION_OPERATION)] = AuthenticatedPeerRead(
            changed, row.delegated_context, row.invocation_evidence
        )
        with self.assertRaisesRegex(DgerGen4Error, "GEP_ORIGIN_CONTEXT_MISMATCH"):
            self.establish()

    def test_gep_admission_digest_mismatch_fails_before_ahc(self):
        row = self.reader.rows[(GEP_TOOL, GEP_CORRELATION_OPERATION)]
        changed = dict(row.result)
        changed["gep_admission_sha256"] = "9" * 64
        self.reader.rows[(GEP_TOOL, GEP_CORRELATION_OPERATION)] = AuthenticatedPeerRead(
            changed, row.delegated_context, row.invocation_evidence
        )
        with self.assertRaisesRegex(DgerGen4Error, "GEP_ADMISSION_MISMATCH"):
            self.establish()
        self.assertEqual(len(self.reader.calls), 1)

    def test_existing_gep_result_binding_fails_before_ahc(self):
        row = self.reader.rows[(GEP_TOOL, GEP_CORRELATION_OPERATION)]
        changed = dict(row.result)
        changed["result_binding"] = {
            "schema_version": "GEP_TRUSTED_RESULT_BINDING_V1",
            "execution_id": EXECUTION_ID,
            "request_digest": GEP_REQUEST_DIGEST,
            "status": "SUCCEEDED",
            "result_manifest_digest": "7" * 64,
            "operation_result_digest": "8" * 64,
            "execution_evidence_digest": "9" * 64,
        }
        self.reader.rows[(GEP_TOOL, GEP_CORRELATION_OPERATION)] = AuthenticatedPeerRead(
            changed, row.delegated_context, row.invocation_evidence
        )
        with self.assertRaisesRegex(DgerGen4Error, "GEP_RESULT_ALREADY_BOUND"):
            self.establish()
        self.assertEqual(len(self.reader.calls), 1)

    def test_ahc_work_revision_mismatch_fails_before_chm(self):
        row = self.reader.rows[(AHC_TOOL, AHC_EFFECT_READ_OPERATION)]
        changed = dict(row.result)
        changed["workstream_revision"] = WORK_REVISION + 1
        self.reader.rows[(AHC_TOOL, AHC_EFFECT_READ_OPERATION)] = AuthenticatedPeerRead(
            changed, row.delegated_context, row.invocation_evidence
        )
        with self.assertRaisesRegex(DgerGen4Error, "AHC_WORK_REVISION_MISMATCH"):
            self.establish()
        self.assertEqual(len(self.reader.calls), 2)

    def test_noncanonical_ahc_revision_type_is_rejected(self):
        row = self.reader.rows[(AHC_TOOL, AHC_EFFECT_READ_OPERATION)]
        changed = dict(row.result)
        changed["workstream_revision"] = str(WORK_REVISION)
        self.reader.rows[(AHC_TOOL, AHC_EFFECT_READ_OPERATION)] = AuthenticatedPeerRead(
            changed, row.delegated_context, row.invocation_evidence
        )
        with self.assertRaisesRegex(DgerGen4Error, "AHC_EFFECT_READ_RESULT_INVALID"):
            self.establish()

    def test_chm_cannot_claim_execution_authority(self):
        row = self.reader.rows[(CHM_TOOL, CHM_HANDOFF_READ_OPERATION)]
        changed = dict(row.result)
        changed["authorizes_moh_execution"] = True
        self.reader.rows[(CHM_TOOL, CHM_HANDOFF_READ_OPERATION)] = AuthenticatedPeerRead(
            changed, row.delegated_context, row.invocation_evidence
        )
        with self.assertRaisesRegex(DgerGen4Error, "CHM_AUTHORITY_CLAIM_INVALID"):
            self.establish()

    def test_wrong_authenticated_operation_evidence_is_rejected(self):
        row = self.reader.rows[(GEP_TOOL, GEP_CORRELATION_OPERATION)]
        wrong = InvocationEvidence(
            tool_id=GEP_TOOL,
            operation="execution_reconcile",
            invocation_id="gtg_inv_" + "8" * 64,
            tool_identity="1" * 40,
            tool_tree="2" * 40,
            gtg_identity="3" * 40,
            registry_identity="4" * 40,
        )
        self.reader.rows[(GEP_TOOL, GEP_CORRELATION_OPERATION)] = AuthenticatedPeerRead(
            row.result, row.delegated_context, wrong
        )
        with self.assertRaisesRegex(DgerGen4Error, "GTG_INVOCATION_OPERATION_MISMATCH"):
            self.establish()


if __name__ == "__main__":
    unittest.main()
