from __future__ import annotations

from dataclasses import asdict, replace
import json
import tempfile
import unittest
from pathlib import Path

from dger.gen4 import AhcObservation, Gen4Relay, InvocationEvidence, MohObservation, StageReceipt, TrustedCorrelation, canonical_digest
from test_gen4 import FakePeers, package, service_identity


class WrongCorrelationOperationPeers(FakePeers):
    def _corr(self, request, admission_sha, payload_sha, service):
        current = super()._corr(request, admission_sha, payload_sha, service)
        evidence = list(current.provider_evidence)
        evidence[0] = replace(evidence[0], operation="wrong_gep_operation")
        body = {
            "origin": asdict(current.origin),
            "service_deployment_id": current.service_deployment_id,
            "ahc_execution_claim_id": current.ahc_execution_claim_id,
            "ahc_effect_reservation_id": current.ahc_effect_reservation_id,
            "ahc_work_revision": current.ahc_work_revision,
            "gep_execution_id": current.gep_execution_id,
            "gep_request_digest": current.gep_request_digest,
            "gep_admission_sha256": current.gep_admission_sha256,
            "payload_manifest_sha256": payload_sha,
            "chm_handoff_id": current.chm_handoff_id,
            "provider_evidence": [asdict(item) for item in evidence],
        }
        return replace(current, provider_evidence=tuple(evidence), correlation_digest=canonical_digest(body))


class WrongBeginOperationPeers(FakePeers):
    def ahc_begin(self, correlation):
        obs = super().ahc_begin(correlation)
        evidence = obs.invocation_evidence
        assert isinstance(evidence, InvocationEvidence)
        return replace(obs, invocation_evidence=replace(evidence, operation="effect_status"))


class WrongMohStatusOperationPeers(FakePeers):
    def moh_status(self, correlation):
        obs = super().moh_status(correlation)
        evidence = obs.invocation_evidence
        assert isinstance(evidence, InvocationEvidence)
        return replace(obs, invocation_evidence=replace(evidence, operation="execute"))


class WrongTerminalAckOperationPeers(FakePeers):
    def ahc_accept_terminal(self, correlation, terminal_digest, result_ref, result_sha256):
        ack = super().ahc_accept_terminal(correlation, terminal_digest, result_ref, result_sha256)
        evidence = ack.invocation_evidence
        assert isinstance(evidence, InvocationEvidence)
        return replace(ack, invocation_evidence=replace(evidence, operation="note_moh_in_doubt"))


class RemoteStageKindPeers(FakePeers):
    def stage_moh(self, correlation, frozen_stage, payload_manifest_sha256):
        receipt = super().stage_moh(correlation, frozen_stage, payload_manifest_sha256)
        return replace(receipt, stage_kind="REMOTE_SEMANTIC")


class ProviderOperationEvidenceTests(unittest.TestCase):
    def _run(self, peers: FakePeers):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        relay = Gen4Relay(root / "transport", root / "state", service_identity=service_identity(), peers=peers)
        relay.process_one(package(root / "transport"))
        state = json.loads((root / "state/gen4/executions/dger-001.json").read_text())
        return td, root, relay, state

    def test_correlation_same_tool_wrong_operation_fails_before_stage(self):
        peers = WrongCorrelationOperationPeers()
        td, _root, _relay, state = self._run(peers)
        try:
            self.assertEqual(state["phase"], "INGRESS_FROZEN")
            self.assertNotIn("stage", peers.calls)
            self.assertEqual(peers.execute_calls, 0)
        finally:
            td.cleanup()

    def test_ahc_begin_same_tool_wrong_operation_fails_before_moh_execute(self):
        peers = WrongBeginOperationPeers()
        td, _root, _relay, state = self._run(peers)
        try:
            self.assertEqual(state["phase"], "PRE_AHC_EXECUTE_WAL")
            self.assertEqual(peers.execute_calls, 0)
        finally:
            td.cleanup()

    def test_moh_status_same_tool_wrong_operation_cannot_authorize_execute(self):
        peers = WrongMohStatusOperationPeers()
        td, _root, _relay, state = self._run(peers)
        try:
            self.assertEqual(state["phase"], "AHC_IN_DOUBT")
            self.assertEqual(peers.execute_calls, 0)
        finally:
            td.cleanup()

    def test_terminal_ack_same_tool_wrong_operation_never_reexecutes(self):
        peers = WrongTerminalAckOperationPeers()
        td, _root, relay, state = self._run(peers)
        try:
            self.assertEqual(state["phase"], "AHC_TERMINAL_PENDING")
            starts = peers.process_starts
            relay.scan_once()
            self.assertEqual(peers.process_starts, starts)
            state2 = json.loads((_root / "state/gen4/executions/dger-001.json").read_text())
            self.assertEqual(state2["phase"], "AHC_TERMINAL_PENDING")
        finally:
            td.cleanup()

    def test_stage_receipt_cannot_claim_remote_semantic_staging(self):
        peers = RemoteStageKindPeers()
        td, _root, _relay, state = self._run(peers)
        try:
            self.assertEqual(state["phase"], "CORRELATED")
            self.assertEqual(peers.execute_calls, 0)
        finally:
            td.cleanup()

    def test_local_stage_kind_is_durable_on_success(self):
        peers = FakePeers()
        td, _root, _relay, state = self._run(peers)
        try:
            self.assertEqual(state["phase"], "DONE")
            self.assertEqual(state["moh_stage_receipt"]["stage_kind"], "LOCAL_MATERIALIZATION")
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
