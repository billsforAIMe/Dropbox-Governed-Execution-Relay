from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from dger.gen4 import Gen4Relay, REQUEST_SCHEMA, canonical_file_bytes, make_ready_record, sha256
from dger.gen4_contract import InvocationEvidence
from dger.gen4_runtime_peers import (
    AHC_ACCEPT_TERMINAL_OPERATION, AHC_BEGIN_OPERATION, AHC_EFFECT_READ_OPERATION,
    AHC_NOTE_IN_DOUBT_OPERATION, AHC_STATUS_OPERATION, CHM_HANDOFF_READ_OPERATION,
    CHM_PUBLISH_TERMINAL_OPERATION, GEP_CORRELATION_OPERATION, MOH_EXECUTE_OPERATION,
    MOH_STATUS_OPERATION, AuthenticatedPeerInvocation, UnavailableAuthenticatedPeerInvoker,
    compose_gen4_peers,
)
from test_gen4 import service_identity

GEP = "governed-execution-platform"
AHC = "autonomous-handoff-coordinator"
CHM = "common-handoff-manager"
MOH = "mac-operation-host"
EXECUTION = "execution_" + "e" * 64
EFFECT = "effect-" + "f" * 40
HANDOFF = "hnd_" + "a" * 64
CLAIM = "claim-001"
REVISION = 12
REQUEST_DIGEST = "2" * 64
ORIGIN_DIGEST = "sha256:" + "1" * 64
ORIGIN_INVOCATION = "gtg_inv_" + "b" * 64
PROJECT = "Tools"


def delegated_context(tool: str, operation: str, authority_class: str, sequence: int) -> dict:
    value = {
        "schema": "governed-delegated-service-context/v1", "issuer": "governed-tool-gateway",
        "tenant_id": "tenant-A", "principal_id": "principal-A", "deployment_id": "builder-deployment-A",
        "origin_actor_role": "BUILDER", "provisioned_fleet_epoch": 7,
        "origin_context_digest": ORIGIN_DIGEST, "origin_invocation_id": ORIGIN_INVOCATION,
        "service_role": "EXECUTION_RELAY", "service_id": "dger-service",
        "service_deployment_id": "dger-deployment-A", "delegation_invocation_id": f"gtg_del_{sequence:064x}",
        "authorized_operations": [f"tool:{tool}:{operation}"],
        "authorized_capability_classes": [authority_class], "project_binding": PROJECT,
    }
    value["context_digest"] = "sha256:" + sha256(canonical_file_bytes(value))
    return value


def evidence(tool: str, operation: str, sequence: int) -> InvocationEvidence:
    return InvocationEvidence(tool, operation, f"gtg_inv_{sequence:064x}", f"{100 + sequence:040x}", f"{200 + sequence:040x}", f"{300 + sequence:040x}", f"{400 + sequence:040x}")


def ahc_projection(code: str, status: str, *, replayed: bool = False, terminal=None) -> dict:
    return {
        "ok": True, "code": code, "effect_id": EFFECT, "execution_claim_id": CLAIM,
        "effect_class": "EXTERNAL_EXECUTION", "status": status, "workstream_id": "workstream-001",
        "workstream_revision": REVISION, "provisioned_fleet_epoch": 7,
        "origin_context_digest": ORIGIN_DIGEST, "origin_invocation_id": ORIGIN_INVOCATION,
        "gep_execution_id": EXECUTION, "gep_request_digest": REQUEST_DIGEST,
        "reconciliation_mode": "INDEPENDENT", "terminal_evidence_digest": terminal, "replayed": replayed,
    }


class FakeProtectedInvoker:
    def __init__(self, admission_sha: str) -> None:
        self.admission_sha = admission_sha
        self.calls: list[tuple[str, str, str, dict]] = []
        self.sequence = 0
        self.execute_calls = 0
        self.fail_operation: str | None = None
        self.wrong_origin_operation: str | None = None
        self.bad_moh_ok = False
        self.ahc_status = "RESERVED"

    def invoke(self, tool_id, operation, authority_class, arguments, service_identity):
        self.sequence += 1
        self.calls.append((tool_id, operation, authority_class, dict(arguments)))
        if self.fail_operation == operation:
            raise RuntimeError("PROTECTED_RELAY_UNAVAILABLE")
        ctx = delegated_context(tool_id, operation, authority_class, self.sequence)
        if self.wrong_origin_operation == operation:
            ctx["deployment_id"] = "other-deployment"
            body = dict(ctx); body.pop("context_digest")
            ctx["context_digest"] = "sha256:" + sha256(canonical_file_bytes(body))
        result = self._result(tool_id, operation, arguments, ctx)
        return AuthenticatedPeerInvocation(result, ctx, evidence(tool_id, operation, self.sequence))

    def _result(self, tool_id, operation, arguments, context):
        if tool_id == GEP and operation == GEP_CORRELATION_OPERATION:
            return {
                "ok": True, "code": "GEP_TRUSTED_CORRELATION_READ", "launch_capability": False,
                "origin": {"tenant_id": "tenant-A", "principal_id": "principal-A", "deployment_id": "builder-deployment-A", "fleet_epoch": 7, "originating_invocation_id": ORIGIN_INVOCATION, "context_digest": "1" * 64},
                "service_deployment_id": "dger-deployment-A", "ahc_execution_claim_id": CLAIM,
                "ahc_effect_reservation_id": EFFECT, "ahc_work_revision": str(REVISION),
                "gep_execution_id": EXECUTION, "gep_request_digest": REQUEST_DIGEST,
                "gep_admission_sha256": self.admission_sha, "origin_envelope_sha256": "5" * 64,
                "trusted_binding_digest": "6" * 64, "result_binding": None,
            }
        if tool_id == AHC and operation == AHC_EFFECT_READ_OPERATION:
            return ahc_projection("AHC_EFFECT_READ", "RESERVED")
        if tool_id == CHM and operation == CHM_HANDOFF_READ_OPERATION:
            return {
                "ok": True, "code": "HANDOFF_FOUND", "handoff_id": HANDOFF,
                "namespace_binding": {"tenant_id": "tenant-A", "principal_id": "principal-A", "deployment_id": "builder-deployment-A"},
                "project_binding": PROJECT, "external_execution": {"ahc_effect_id": EFFECT, "gep_execution_id": EXECUTION},
                "terminal_result": None, "execution_authority": "NOT_CHM", "authorizes_moh_execution": False,
                "ahc_effect_truth": "NOT_CHM", "gep_execution_admission": "NOT_CHM",
            }
        if tool_id == AHC and operation == AHC_BEGIN_OPERATION:
            self.ahc_status = "IN_DOUBT"
            return ahc_projection("AHC_EFFECT_IN_DOUBT", "IN_DOUBT")
        if tool_id == AHC and operation == AHC_STATUS_OPERATION:
            return ahc_projection("AHC_EFFECT_STATUS", self.ahc_status)
        if tool_id == MOH and operation == MOH_STATUS_OPERATION:
            inner = {"schema": "moh-status/v1", "execution_id": EXECUTION, "state": "NOT_FOUND"}
            return {"ok": not self.bad_moh_ok, "state": "NOT_FOUND", "response_json": json.dumps(inner, sort_keys=True, separators=(",", ":"))}
        if tool_id == MOH and operation == MOH_EXECUTE_OPERATION:
            self.execute_calls += 1
            inner = {"schema": "moh-status/v1", "execution_id": EXECUTION, "state": "SUCCEEDED", "result": {"ok": True}}
            return {"ok": True, "state": "SUCCEEDED", "response_json": json.dumps(inner, sort_keys=True, separators=(",", ":"))}
        if tool_id == AHC and operation == AHC_NOTE_IN_DOUBT_OPERATION:
            out = ahc_projection("AHC_MOH_IN_DOUBT_NOTED", "IN_DOUBT")
            out.update({"moh_observation_digest": arguments["moh_observation_digest"], "state_revision": 13})
            return out
        if tool_id == AHC and operation == AHC_ACCEPT_TERMINAL_OPERATION:
            self.ahc_status = "SUCCEEDED"
            out = ahc_projection("AHC_TERMINAL_EFFECT_ACCEPTED", "SUCCEEDED", terminal="sha256:" + "9" * 64)
            out.update({"terminal_digest": arguments["terminal_digest"], "result_ref": arguments["result_ref"], "result_sha256": arguments["result_sha256"], "terminal_acceptance": "RECONCILIATION_COMPLETE", "state_revision": 14})
            return out
        if tool_id == CHM and operation == CHM_PUBLISH_TERMINAL_OPERATION:
            descriptor = dict(arguments["result"])
            terminal = {
                "schema": "chm-terminal-transport-result/v1", "ahc_effect_id": EFFECT, "gep_execution_id": EXECUTION,
                "result_digest": "sha256:" + sha256(canonical_file_bytes({"result": descriptor})), "result": descriptor,
                "relay_service_id": "dger-service", "relay_service_deployment_id": "dger-deployment-A",
                "relay_context_digest": context["context_digest"], "relay_delegation_invocation_id": context["delegation_invocation_id"],
            }
            return {
                "ok": True, "code": "HANDOFF_FOUND", "handoff_id": HANDOFF, "status": "TERMINAL_RESULT",
                "namespace_binding": {"tenant_id": "tenant-A", "principal_id": "principal-A", "deployment_id": "builder-deployment-A"},
                "project_binding": PROJECT, "target_role": "BUILDER", "review_episode_id": None,
                "external_execution": {"ahc_effect_id": EFFECT, "gep_execution_id": EXECUTION}, "terminal_result": terminal,
                "execution_authority": "NOT_CHM", "authorizes_moh_execution": False, "ahc_effect_truth": "NOT_CHM",
                "gep_execution_admission": "NOT_CHM", "reused": False,
            }
        raise AssertionError((tool_id, operation))


def make_package(transport: Path, admission: bytes) -> Path:
    rid = "dger-001"
    package = transport / "IngressV2" / rid
    payload = package / "payload"
    payload.mkdir(parents=True)
    (payload / "operation.json").write_bytes(b'{"operation":"fixed"}\n')
    (payload / "adapter.py").write_bytes(b"print('fixed')\n")
    request = {"schema": REQUEST_SCHEMA, "dger_request_id": rid, "gep_execution_id": EXECUTION, "ahc_effect_reservation_id": EFFECT, "chm_handoff_id": HANDOFF}
    request_raw = canonical_file_bytes(request)
    (package / "request.json").write_bytes(request_raw)
    (package / "admission.bin").write_bytes(admission)
    (package / "READY.json").write_bytes(canonical_file_bytes(make_ready_record(request_raw, admission, payload, rid)))
    return package


class Gen4RuntimePeerCompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.transport, self.state, self.moh = self.root / "transport", self.root / "state", self.root / "moh"
        self.admission = b'{"signed":"opaque-gen4-admission"}'
        self.service = service_identity()
        self.invoker = FakeProtectedInvoker(sha256(self.admission))
        self.peers = compose_gen4_peers(moh_home=self.moh, service_identity=self.service, invoker=self.invoker)
        self.relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers)
        self.package = make_package(self.transport, self.admission)

    def tearDown(self): self.tmp.cleanup()

    def test_full_composed_path_reaches_done_without_changing_activation(self):
        self.assertTrue(self.relay.process_one(self.package))
        self.assertEqual(self.relay._load_state("dger-001")["phase"], "DONE")
        self.assertEqual(self.invoker.execute_calls, 1)
        self.assertEqual((self.moh / "inbox" / EXECUTION / "envelope.json").read_bytes(), self.admission)
        self.assertEqual([(tool, op, cls) for tool, op, cls, _ in self.invoker.calls], [
            (GEP, GEP_CORRELATION_OPERATION, "READ"), (AHC, AHC_EFFECT_READ_OPERATION, "READ"),
            (CHM, CHM_HANDOFF_READ_OPERATION, "READ"), (AHC, AHC_BEGIN_OPERATION, "EFFECT"),
            (MOH, MOH_STATUS_OPERATION, "EFFECT"), (MOH, MOH_EXECUTE_OPERATION, "EFFECT"),
            (AHC, AHC_ACCEPT_TERMINAL_OPERATION, "EFFECT"), (CHM, CHM_PUBLISH_TERMINAL_OPERATION, "EFFECT"),
        ])

    def test_unavailable_protected_relay_fails_before_moh_materialization(self):
        peers = compose_gen4_peers(moh_home=self.moh, service_identity=self.service, invoker=UnavailableAuthenticatedPeerInvoker())
        relay = Gen4Relay(self.transport, self.state / "unavailable", service_identity=self.service, peers=peers)
        self.assertTrue(relay.process_one(self.package))
        self.assertEqual(relay._load_state("dger-001")["phase"], "INGRESS_FROZEN")
        self.assertFalse((self.moh / "inbox" / EXECUTION).exists())

    def test_wrong_origin_on_ahc_begin_response_is_reconciled_before_moh(self):
        self.invoker.wrong_origin_operation = AHC_BEGIN_OPERATION
        self.assertTrue(self.relay.process_one(self.package))
        self.assertEqual(self.relay._load_state("dger-001")["phase"], "DONE")
        self.assertEqual(self.invoker.execute_calls, 1)
        operations = [op for _, op, _, _ in self.invoker.calls]
        self.assertLess(operations.index(AHC_BEGIN_OPERATION), operations.index(AHC_STATUS_OPERATION))
        self.assertLess(operations.index(AHC_STATUS_OPERATION), operations.index(MOH_STATUS_OPERATION))

    def test_wrong_origin_on_correlation_read_fails_before_moh(self):
        self.invoker.wrong_origin_operation = GEP_CORRELATION_OPERATION
        self.assertTrue(self.relay.process_one(self.package))
        self.assertEqual(self.relay._load_state("dger-001")["phase"], "INGRESS_FROZEN")
        self.assertEqual(self.invoker.execute_calls, 0)
        self.assertFalse((self.moh / "inbox" / EXECUTION).exists())

    def test_moh_wrapper_truth_mismatch_blocks_execute(self):
        self.invoker.bad_moh_ok = True
        self.assertTrue(self.relay.process_one(self.package))
        self.assertEqual(self.relay._load_state("dger-001")["phase"], "AHC_IN_DOUBT")
        self.assertEqual(self.invoker.execute_calls, 0)

    def test_chm_failure_after_terminal_does_not_repeat_execute(self):
        self.invoker.fail_operation = CHM_PUBLISH_TERMINAL_OPERATION
        self.assertTrue(self.relay.process_one(self.package))
        self.assertEqual(self.relay._load_state("dger-001")["phase"], "CHM_PENDING")
        self.assertEqual(self.invoker.execute_calls, 1)
        self.relay.resume_one("dger-001")
        self.assertEqual(self.invoker.execute_calls, 1)

    def test_existing_conflicting_moh_stage_blocks_before_ahc(self):
        final = self.moh / "inbox" / EXECUTION
        (final / "payload").mkdir(parents=True)
        (final / "envelope.json").write_bytes(b"different")
        self.assertTrue(self.relay.process_one(self.package))
        self.assertEqual(self.relay._load_state("dger-001")["phase"], "CORRELATED")
        self.assertFalse(any(op == AHC_BEGIN_OPERATION for _, op, _, _ in self.invoker.calls))


if __name__ == "__main__": unittest.main()
