from __future__ import annotations

from dataclasses import asdict, replace
import json
import tempfile
import unittest
from pathlib import Path

from dger.gen4 import Gen4Relay, canonical_digest
from test_gen4 import FakePeers, package, service_identity


class OrdinaryLifecycleCorrelationPeers(FakePeers):
    """Model the stale pre-relay CHM lifecycle-read evidence."""

    def _corr(self, request, admission_sha, payload_sha, service):
        current = super()._corr(request, admission_sha, payload_sha, service)
        evidence = list(current.provider_evidence)
        evidence[-1] = replace(evidence[-1], operation="handoff_get")
        body = {
            "origin": asdict(current.origin),
            "service_principal_id": current.service_principal_id,
            "service_deployment_id": current.service_deployment_id,
            "service_role": current.service_role,
            "delegation_invocation_id": current.delegation_invocation_id,
            "delegated_context_digest": current.delegated_context_digest,
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
        return replace(
            current,
            provider_evidence=tuple(evidence),
            correlation_digest=canonical_digest(body),
        )


class OrdinaryLifecycleTerminalPeers(FakePeers):
    """Model the stale ordinary CHM lifecycle-result operation."""

    def chm_publish_terminal(self, correlation, result_ref, result_sha256):
        ack = super().chm_publish_terminal(correlation, result_ref, result_sha256)
        evidence = ack.invocation_evidence
        assert evidence is not None
        return replace(ack, invocation_evidence=replace(evidence, operation="handoff_attach_result"))


class ChmRelayContractTests(unittest.TestCase):
    def _run(self, peers: FakePeers):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        relay = Gen4Relay(
            root / "transport",
            root / "state",
            service_identity=service_identity(),
            peers=peers,
        )
        relay.process_one(package(root / "transport"))
        state = json.loads((root / "state/gen4/executions/dger-001.json").read_text())
        return td, root, relay, state

    def test_ordinary_handoff_get_cannot_satisfy_execution_relay_correlation(self):
        peers = OrdinaryLifecycleCorrelationPeers()
        td, _root, _relay, state = self._run(peers)
        try:
            self.assertEqual(state["phase"], "INGRESS_FROZEN")
            self.assertNotIn("stage", peers.calls)
            self.assertEqual(peers.execute_calls, 0)
        finally:
            td.cleanup()

    def test_ordinary_attach_result_cannot_satisfy_relay_terminal_publication(self):
        peers = OrdinaryLifecycleTerminalPeers()
        td, _root, _relay, state = self._run(peers)
        try:
            self.assertEqual(state["phase"], "CHM_RESULT_CONFLICT")
            self.assertEqual(peers.execute_calls, 1)
            self.assertEqual(peers.process_starts, 1)
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
