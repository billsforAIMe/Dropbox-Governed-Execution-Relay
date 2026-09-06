from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dger.gen4 import (
    Ack, AhcObservation, DgerGen4Error, Gen4Relay, InvocationEvidence, MohObservation, REQUEST_SCHEMA,
    SERVICE_IDENTITY_SCHEMA, ServiceIdentity, StageReceipt, TrustedCorrelation,
    TrustedOrigin, UnavailableGen4Peers, canonical_digest, canonical_file_bytes,
    load_service_identity, make_ready_record, payload_manifest, sha256,
)
from dger.legacy_guard import LegacySurfaceRetired, assert_legacy_allowed


class Crash(BaseException):
    pass


def service_identity(deployment: str = "dger-deployment-A") -> ServiceIdentity:
    body = {
        "schema": SERVICE_IDENTITY_SCHEMA,
        "service_principal_id": "dger-service",
        "service_deployment_id": deployment,
        "actor_role": "EXECUTION_RELAY",
    }
    return ServiceIdentity(
        service_principal_id=body["service_principal_id"],
        service_deployment_id=deployment,
        actor_role="EXECUTION_RELAY",
        identity_digest=canonical_digest(body),
    )


def package(root: Path, rid: str = "dger-001", gep: str = "gep-001", effect: str = "effect-001", handoff: str | None = "hnd-001", admission: bytes = b"signed-admission-v1") -> Path:
    p = root / "IngressV2" / rid
    (p / "payload").mkdir(parents=True)
    (p / "payload" / "operation.json").write_bytes(b'{"operation":"fixed"}\n')
    (p / "payload" / "adapter.py").write_bytes(b"print('fixed')\n")
    req = {
        "schema": REQUEST_SCHEMA,
        "dger_request_id": rid,
        "gep_execution_id": gep,
        "ahc_effect_reservation_id": effect,
        "chm_handoff_id": handoff,
    }
    req_raw = canonical_file_bytes(req)
    (p / "request.json").write_bytes(req_raw)
    (p / "admission.bin").write_bytes(admission)
    ready = make_ready_record(req_raw, admission, p / "payload", rid)
    (p / "READY.json").write_bytes(canonical_file_bytes(ready))
    return p


class FakePeers:
    def __init__(self) -> None:
        self.origin = TrustedOrigin(
            tenant_id="tenant-A", principal_id="principal-A", deployment_id="builder-deployment-A",
            fleet_epoch=7, originating_invocation_id="inv-origin-001", context_digest="1" * 64,
        )
        self.service_deployment_override: str | None = None
        self.request_overrides: dict[str, str | None] = {}
        self.correlation_error: Exception | None = None
        self.stage_error: Exception | None = None
        self.begin_error_once: Exception | None = None
        self.begin_state = "IN_DOUBT"
        self.ahc_state = "IN_DOUBT"
        self.ahc_status_error: Exception | None = None
        self.moh_status_error: Exception | None = None
        self.execute_error_once: Exception | None = None
        self.ambiguous_execute_started = True
        self.ahc_terminal_error: Exception | None = None
        self.chm_error: Exception | None = None
        self.note_in_doubt_error: Exception | None = None
        self.status_queue: list[str] = ["NOT_FOUND"]
        self.execute_queue: list[str] = ["SUCCEEDED"]
        self.calls: list[str] = []
        self.execute_calls = 0
        self.process_starts = 0
        self.terminal_acks = 0
        self.chm_acks = 0
        self.note_acks = 0
        self.stage_admission: bytes | None = None
        self.provider_generation = 1
        self.invocation_sequence = 0
        self.omit_correlation_evidence = False
        self.omit_ahc_evidence = False
        self.omit_moh_evidence = False
        self.last_correlation: TrustedCorrelation | None = None

    def _evidence(self, tool_id: str, operation: str) -> InvocationEvidence:
        self.invocation_sequence += 1
        generation = self.provider_generation
        return InvocationEvidence(
            tool_id=tool_id,
            operation=operation,
            invocation_id=f"inv_{self.invocation_sequence:032x}",
            tool_identity=f"{generation:040x}",
            tool_tree=f"{1000 + generation:040x}",
            gtg_identity=f"{2000 + generation:040x}",
            registry_identity=f"{3000 + generation:040x}",
        )

    def _corr(self, request: dict, admission_sha: str, payload_sha: str, service: ServiceIdentity) -> TrustedCorrelation:
        values = {
            "gep_execution_id": request["gep_execution_id"],
            "ahc_effect_reservation_id": request["ahc_effect_reservation_id"],
            "chm_handoff_id": request.get("chm_handoff_id"),
        }
        values.update(self.request_overrides)
        service_dep = self.service_deployment_override or service.service_deployment_id
        evidence: tuple[InvocationEvidence, ...]
        if self.omit_correlation_evidence:
            evidence = ()
        else:
            items = [
                self._evidence("governed-execution-platform", "correlation_read"),
                self._evidence("autonomous-handoff-coordinator", "effect_read"),
            ]
            if values["chm_handoff_id"] is not None:
                items.append(self._evidence("common-handoff-manager", "handoff_read"))
            evidence = tuple(items)
        body = {
            "origin": asdict(self.origin),
            "service_deployment_id": service_dep,
            "ahc_execution_claim_id": "claim-001",
            "ahc_effect_reservation_id": values["ahc_effect_reservation_id"],
            "ahc_work_revision": "rev-001",
            "gep_execution_id": values["gep_execution_id"],
            "gep_request_digest": "2" * 64,
            "gep_admission_sha256": admission_sha,
            "payload_manifest_sha256": payload_sha,
            "chm_handoff_id": values["chm_handoff_id"],
            "provider_evidence": [asdict(item) for item in evidence],
        }
        return TrustedCorrelation(
            origin=self.origin,
            service_deployment_id=service_dep,
            ahc_execution_claim_id="claim-001",
            ahc_effect_reservation_id=str(values["ahc_effect_reservation_id"]),
            ahc_work_revision="rev-001",
            gep_execution_id=str(values["gep_execution_id"]),
            gep_request_digest="2" * 64,
            gep_admission_sha256=admission_sha,
            chm_handoff_id=values["chm_handoff_id"],
            correlation_digest=canonical_digest(body),
            provider_evidence=evidence,
        )

    def establish_correlation(self, request, admission_sha256, payload_manifest_sha256, service_identity):
        self.calls.append("correlate")
        if self.correlation_error:
            raise self.correlation_error
        c = self._corr(request, admission_sha256, payload_manifest_sha256, service_identity)
        self.last_correlation = c
        return c

    def stage_moh(self, correlation, frozen_stage, payload_manifest_sha256):
        self.calls.append("stage")
        if self.stage_error:
            raise self.stage_error
        admission = (frozen_stage / "admission.bin").read_bytes()
        self.stage_admission = admission
        _, _, manifest = payload_manifest(frozen_stage / "payload")
        if manifest != payload_manifest_sha256:
            raise RuntimeError("PAYLOAD_MISMATCH")
        return StageReceipt(
            gep_execution_id=correlation.gep_execution_id,
            admission_sha256=sha256(admission),
            payload_manifest_sha256=manifest,
            stage_digest=canonical_digest({"admission": sha256(admission), "payload": manifest}),
        )

    def ahc_begin(self, correlation):
        self.calls.append("ahc_begin")
        if self.begin_error_once:
            exc, self.begin_error_once = self.begin_error_once, None
            self.ahc_state = "IN_DOUBT"
            raise exc
        self.ahc_state = self.begin_state
        evidence = None if self.omit_ahc_evidence else self._evidence("autonomous-handoff-coordinator", "begin_effect")
        return AhcObservation(correlation.ahc_effect_reservation_id, correlation.gep_execution_id, self.begin_state, "3" * 64, evidence)

    def ahc_status(self, correlation):
        self.calls.append("ahc_status")
        if self.ahc_status_error:
            raise self.ahc_status_error
        evidence = None if self.omit_ahc_evidence else self._evidence("autonomous-handoff-coordinator", "effect_status")
        return AhcObservation(correlation.ahc_effect_reservation_id, correlation.gep_execution_id, self.ahc_state, "4" * 64, evidence)

    def moh_status(self, correlation):
        self.calls.append("moh_status")
        if self.moh_status_error:
            raise self.moh_status_error
        state = self.status_queue.pop(0) if len(self.status_queue) > 1 else self.status_queue[0]
        evidence = None if self.omit_moh_evidence else self._evidence("mac-operation-host", "status")
        return MohObservation(correlation.gep_execution_id, state, "moh-rec-001" if state != "NOT_FOUND" else None, "5" * 64, None, evidence)

    def moh_execute(self, correlation):
        self.calls.append("moh_execute")
        self.execute_calls += 1
        if self.execute_error_once:
            exc, self.execute_error_once = self.execute_error_once, None
            if self.ambiguous_execute_started:
                self.process_starts += 1
                if self.status_queue == ["NOT_FOUND"]:
                    self.status_queue = ["RUNNING", "SUCCEEDED"]
            raise exc
        state = self.execute_queue.pop(0) if len(self.execute_queue) > 1 else self.execute_queue[0]
        if state not in {"REJECTED_PRECONDITION", "REJECTED_DUPLICATE_MISMATCH", "NOT_FOUND", "ADMITTED", "IN_DOUBT"}:
            self.process_starts += 1
        evidence = None if self.omit_moh_evidence else self._evidence("mac-operation-host", "execute")
        return MohObservation(correlation.gep_execution_id, state, "moh-rec-001", "6" * 64, {"ok": state == "SUCCEEDED"} if state in {"SUCCEEDED", "FAILED"} else None, evidence)

    def ahc_note_in_doubt(self, correlation, moh):
        self.calls.append("ahc_note_in_doubt")
        if self.note_in_doubt_error:
            raise self.note_in_doubt_error
        self.note_acks += 1
        return Ack(True, "7" * 64, self._evidence("autonomous-handoff-coordinator", "note_moh_in_doubt"))

    def ahc_accept_terminal(self, correlation, terminal_digest, result_ref, result_sha256):
        self.calls.append("ahc_terminal")
        if self.ahc_terminal_error:
            raise self.ahc_terminal_error
        self.terminal_acks += 1
        return Ack(True, "8" * 64, self._evidence("autonomous-handoff-coordinator", "accept_terminal_effect"))

    def chm_publish_terminal(self, correlation, result_ref, result_sha256):
        self.calls.append("chm_terminal")
        if self.chm_error:
            raise self.chm_error
        self.chm_acks += 1
        return Ack(True, "9" * 64, self._evidence("common-handoff-manager", "publish_terminal_result"))


class Gen4Tests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.transport = self.root / "transport"
        self.state = self.root / "state"
        self.peers = FakePeers()
        self.service = service_identity()
        self.relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers)

    def tearDown(self): self.td.cleanup()

    def state_record(self, rid="dger-001"):
        return json.loads((self.state / "gen4/executions" / f"{rid}.json").read_text())

    def test_happy_path_orders_ahc_before_moh_and_chm_after_ahc(self):
        p = package(self.transport)
        self.assertTrue(self.relay.process_one(p))
        s = self.state_record()
        self.assertEqual(s["phase"], "DONE")
        self.assertLess(self.peers.calls.index("ahc_begin"), self.peers.calls.index("moh_execute"))
        self.assertLess(self.peers.calls.index("moh_execute"), self.peers.calls.index("ahc_terminal"))
        self.assertLess(self.peers.calls.index("ahc_terminal"), self.peers.calls.index("chm_terminal"))
        self.assertEqual(self.peers.process_starts, 1)
        self.assertEqual(self.peers.stage_admission, b"signed-admission-v1")
        providers = {item["tool_id"] for item in s["trusted_correlation"]["provider_evidence"]}
        self.assertEqual(providers, {"governed-execution-platform", "autonomous-handoff-coordinator", "common-handoff-manager"})
        result = json.loads((self.transport / "RunsV2/dger-001/result.json").read_text())
        self.assertEqual(result["moh_invocation_evidence"]["tool_id"], "mac-operation-host")

    def test_missing_correlation_provider_evidence_fails_closed(self):
        self.peers.omit_correlation_evidence = True
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.peers.execute_calls, 0)
        self.assertEqual(self.state_record()["phase"], "INGRESS_FROZEN")

    def test_missing_ahc_or_moh_provider_evidence_fails_before_effect_progress(self):
        self.peers.omit_ahc_evidence = True
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.peers.execute_calls, 0)
        self.assertEqual(self.state_record()["phase"], "PRE_AHC_EXECUTE_WAL")

    def test_unavailable_peer_contract_fails_closed_without_execute(self):
        relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=UnavailableGen4Peers())
        p = package(self.transport)
        relay.process_one(p)
        self.assertEqual(self.state_record()["phase"], "INGRESS_FROZEN")

    def test_transport_identity_or_execution_profile_fields_are_rejected(self):
        for field, value in (("tenant_id", "tenant-B"), ("principal_id", "principal-B"), ("deployment_id", "builder-B"), ("fleet_epoch", 99), ("argv", ["/bin/sh"]), ("cwd", "/tmp"), ("execution_profile", "caller-choice")):
            with self.subTest(field=field):
                td = tempfile.TemporaryDirectory(); root = Path(td.name); peers = FakePeers()
                p = package(root/"transport")
                req = json.loads((p/"request.json").read_text()); req[field] = value
                raw = canonical_file_bytes(req); (p/"request.json").write_bytes(raw)
                admission = (p/"admission.bin").read_bytes(); (p/"READY.json").write_bytes(canonical_file_bytes(make_ready_record(raw, admission, p/"payload", "dger-001")))
                Gen4Relay(root/"transport", root/"state", service_identity=self.service, peers=peers).process_one(p)
                self.assertEqual(peers.execute_calls, 0)
                td.cleanup()

    def test_crash_before_ingress_freeze_leaves_no_private_acceptance_and_retries_cleanly(self):
        p = package(self.transport)
        relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers, fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "before_ingress_freeze" else None)
        with self.assertRaises(Crash): relay.process_one(p)
        self.assertFalse((self.state/"gen4/executions/dger-001.json").exists())
        self.assertFalse((self.state/"gen4/frozen/dger-001").exists())
        Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers).process_one(p)
        self.assertEqual(self.state_record()["phase"], "DONE")
        self.assertEqual(self.peers.process_starts, 1)

    def test_changed_admission_after_ready_rejected_before_peer(self):
        p = package(self.transport)
        (p / "admission.bin").write_bytes(b"forged")
        self.assertTrue(self.relay.process_one(p))
        self.assertFalse((self.state / "gen4/executions/dger-001.json").exists())
        self.assertEqual(self.peers.calls, [])

    def test_altered_payload_after_ready_rejected_before_peer(self):
        p = package(self.transport)
        (p / "payload/adapter.py").write_text("changed\n")
        self.relay.process_one(p)
        self.assertFalse((self.state / "gen4/executions/dger-001.json").exists())
        self.assertEqual(self.peers.calls, [])

    def test_package_replayed_through_another_dger_deployment_fails_closed(self):
        p = package(self.transport)
        peers_b = FakePeers(); peers_b.service_deployment_override = "dger-deployment-A"
        service_b = service_identity("dger-deployment-B")
        relay_b = Gen4Relay(self.transport, self.state, service_identity=service_b, peers=peers_b)
        relay_b.process_one(p)
        self.assertEqual(peers_b.execute_calls, 0)
        self.assertEqual(json.loads((self.state/"gen4/executions/dger-001.json").read_text())["phase"], "INGRESS_FROZEN")

    def test_wrong_service_deployment_rejected(self):
        self.peers.service_deployment_override = "other-dger"
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.peers.execute_calls, 0)
        self.assertEqual(self.state_record()["phase"], "INGRESS_FROZEN")

    def test_gep_execution_mismatch_rejected(self):
        self.peers.request_overrides["gep_execution_id"] = "gep-other"
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.peers.execute_calls, 0)

    def test_copied_chm_handoff_mismatch_rejected(self):
        self.peers.request_overrides["chm_handoff_id"] = "hnd-other"
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.peers.execute_calls, 0)

    def test_stale_or_superseded_ahc_effect_fails_before_stage(self):
        self.peers.correlation_error = DgerGen4Error("AHC_EFFECT_STALE_OR_SUPERSEDED")
        self.relay.process_one(package(self.transport))
        self.assertNotIn("stage", self.peers.calls)
        self.assertNotIn("moh_execute", self.peers.calls)

    def test_foreign_tenant_principal_deployment_epoch_peer_rejections_never_execute(self):
        for code in ("WRONG_TENANT", "WRONG_PRINCIPAL", "WRONG_ORIGIN_DEPLOYMENT", "STALE_FLEET_EPOCH", "FUTURE_FLEET_EPOCH"):
            with self.subTest(code=code):
                td = tempfile.TemporaryDirectory(); root = Path(td.name); peers = FakePeers(); peers.correlation_error = DgerGen4Error(code)
                relay = Gen4Relay(root/"transport", root/"state", service_identity=self.service, peers=peers)
                relay.process_one(package(root/"transport"))
                self.assertEqual(peers.execute_calls, 0)
                td.cleanup()

    def test_same_gep_execution_changed_intent_conflicts(self):
        self.relay.process_one(package(self.transport, rid="dger-001", gep="gep-shared"))
        p2 = package(self.transport, rid="dger-002", gep="gep-shared", effect="effect-other")
        self.relay.process_one(p2)
        s2 = self.state_record("dger-002")
        self.assertEqual(s2["phase"], "INGRESS_FROZEN")
        self.assertEqual(self.peers.process_starts, 1)

    def test_exact_duplicate_is_idempotent(self):
        p = package(self.transport)
        self.relay.process_one(p)
        starts = self.peers.process_starts
        self.relay.process_one(p)
        self.assertEqual(self.peers.process_starts, starts)

    def test_changed_byte_duplicate_rejected(self):
        p = package(self.transport)
        relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers, fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "after_accept_state" else None)
        with self.assertRaises(Crash): relay.process_one(p)
        (p / "admission.bin").write_bytes(b"changed")
        req = (p / "request.json").read_bytes(); (p / "READY.json").write_bytes(canonical_file_bytes(make_ready_record(req, b"changed", p/"payload", "dger-001")))
        relay2 = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers)
        relay2.process_one(p)
        self.assertEqual(self.peers.process_starts, 0)

    def test_dropbox_deleted_after_acceptance_resumes_from_private_state(self):
        p = package(self.transport)
        relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers, fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "after_accept_state" else None)
        with self.assertRaises(Crash): relay.process_one(p)
        shutil.rmtree(p)
        Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers).scan_once()
        self.assertEqual(self.state_record()["phase"], "DONE")
        self.assertEqual(self.peers.process_starts, 1)

    def test_crash_after_ingress_freeze_before_state_resumes(self):
        p = package(self.transport)
        relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers, fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "after_ingress_freeze" else None)
        with self.assertRaises(Crash): relay.process_one(p)
        shutil.rmtree(p)
        Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers).scan_once()
        self.assertEqual(self.state_record()["phase"], "DONE")

    def _crash_resume(self, boundary: str):
        p = package(self.transport)
        relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers, fault=lambda n: (_ for _ in ()).throw(Crash()) if n == boundary else None)
        with self.assertRaises(Crash): relay.process_one(p)
        Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers).scan_once()
        return self.state_record()

    def test_crash_after_pre_ahc_wal_does_not_execute_before_begin(self):
        s = self._crash_resume("after_pre_ahc_wal")
        self.assertEqual(s["phase"], "DONE")
        self.assertLess(self.peers.calls.index("ahc_begin"), self.peers.calls.index("moh_execute"))
        self.assertEqual(self.peers.process_starts, 1)

    def test_lost_ahc_begin_response_reconciles_before_execute(self):
        self.peers.begin_error_once = TimeoutError("lost")
        self.relay.process_one(package(self.transport))
        s = self.state_record()
        self.assertEqual(s["phase"], "DONE")
        self.assertLess(self.peers.calls.index("ahc_status"), self.peers.calls.index("moh_execute"))
        self.assertEqual(self.peers.process_starts, 1)

    def test_crash_after_ahc_in_doubt_before_execute_is_status_first(self):
        self._crash_resume("after_ahc_in_doubt")
        i = self.peers.calls.index("ahc_begin")
        self.assertEqual(self.peers.calls[i+1], "moh_status")
        self.assertEqual(self.peers.process_starts, 1)

    def test_crash_after_moh_execute_wal_is_status_first_and_at_most_one_start(self):
        self._crash_resume("after_moh_execute_wal")
        self.assertEqual(self.peers.process_starts, 1)
        self.assertGreaterEqual(self.peers.calls.count("moh_status"), 2)

    def test_moh_admitted_status_is_safe_proof_then_single_execute(self):
        self.peers.status_queue = ["ADMITTED"]
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.state_record()["phase"], "DONE")
        self.assertEqual(self.peers.execute_calls, 1)
        self.assertEqual(self.peers.process_starts, 1)

    def test_lost_execute_response_reconciles_running_then_terminal_without_repeat(self):
        self.peers.execute_error_once = TimeoutError("lost execute response")
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.peers.process_starts, 1)
        self.assertEqual(self.peers.execute_calls, 1)
        self.relay.scan_once()
        self.relay.scan_once()
        self.assertEqual(self.state_record()["phase"], "DONE")
        self.assertEqual(self.peers.process_starts, 1)
        self.assertEqual(self.peers.execute_calls, 1)

    def test_lost_execute_with_proven_not_found_can_retry_same_id(self):
        self.peers.execute_error_once = TimeoutError("lost before MOH admission")
        self.peers.ambiguous_execute_started = False
        self.peers.status_queue = ["NOT_FOUND"]
        self.relay.process_one(package(self.transport))
        self.relay.scan_once()
        self.assertEqual(self.state_record()["phase"], "DONE")
        self.assertEqual(self.peers.execute_calls, 2)
        self.assertEqual(self.peers.process_starts, 1)

    def test_moh_in_doubt_latches_and_retries_ahc_report_without_execute(self):
        self.peers.execute_queue = ["IN_DOUBT"]
        self.peers.note_in_doubt_error = TimeoutError("AHC down")
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.state_record()["phase"], "MOH_IN_DOUBT_AHC_PENDING")
        execute_calls = self.peers.execute_calls
        self.peers.note_in_doubt_error = None
        self.relay.scan_once()
        self.assertEqual(self.state_record()["phase"], "MOH_IN_DOUBT")
        self.assertEqual(self.peers.execute_calls, execute_calls)
        self.assertTrue(self.state_record()["moh_in_doubt_ever"])
        self.assertEqual(self.state_record()["ahc_in_doubt_report_ack"]["invocation_evidence"]["tool_id"], "autonomous-handoff-coordinator")

    def test_ahc_unavailable_after_moh_terminal_never_reexecutes(self):
        self.peers.ahc_terminal_error = TimeoutError("AHC down")
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.state_record()["phase"], "AHC_TERMINAL_PENDING")
        starts = self.peers.process_starts
        self.peers.ahc_terminal_error = None
        self.relay.scan_once()
        self.assertEqual(self.state_record()["phase"], "DONE")
        self.assertEqual(self.peers.process_starts, starts)

    def test_chm_unavailable_after_moh_terminal_never_reexecutes(self):
        self.peers.chm_error = TimeoutError("CHM down")
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.state_record()["phase"], "CHM_PENDING")
        starts = self.peers.process_starts
        self.peers.chm_error = None
        self.relay.scan_once()
        self.assertEqual(self.state_record()["phase"], "DONE")
        self.assertEqual(self.peers.process_starts, starts)

    def test_result_publication_lost_response_replays_exactly(self):
        p = package(self.transport)
        relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers, fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "after_result_publication" else None)
        with self.assertRaises(Crash): relay.process_one(p)
        result_before = (self.transport/"RunsV2/dger-001/result.json").read_bytes()
        starts = self.peers.process_starts
        Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers).scan_once()
        self.assertEqual((self.transport/"RunsV2/dger-001/result.json").read_bytes(), result_before)
        self.assertEqual(self.peers.process_starts, starts)

    def test_result_conflict_fails_closed_without_reexecution(self):
        p = package(self.transport)
        relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers, fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "after_moh_terminal" else None)
        with self.assertRaises(Crash): relay.process_one(p)
        out = self.transport/"RunsV2/dger-001"; out.mkdir(parents=True, exist_ok=True); (out/"result.json").write_bytes(b"conflict\n")
        starts = self.peers.process_starts
        Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers).scan_once()
        self.assertEqual(self.state_record()["phase"], "RESULT_CONFLICT")
        self.assertEqual(self.peers.process_starts, starts)

    def test_provider_advancement_alone_does_not_reexecute(self):
        self.peers.ahc_terminal_error = TimeoutError("AHC provider unavailable")
        self.relay.process_one(package(self.transport))
        self.assertEqual(self.state_record()["phase"], "AHC_TERMINAL_PENDING")
        starts = self.peers.process_starts
        self.peers.ahc_terminal_error = None
        self.peers.provider_generation = 2
        self.relay.scan_once()
        s = self.state_record()
        self.assertEqual(s["phase"], "DONE")
        self.assertEqual(self.peers.process_starts, starts)
        self.assertEqual(s["ahc_terminal_ack"]["invocation_evidence"]["tool_identity"], f"{2:040x}")

    def test_incompatible_provider_rejection_never_reexecutes(self):
        self.peers.ahc_terminal_error = DgerGen4Error("PROVIDER_NOT_CURRENT_COMPATIBLE")
        self.relay.process_one(package(self.transport))
        starts = self.peers.process_starts
        self.relay.scan_once()
        self.assertEqual(self.state_record()["phase"], "AHC_TERMINAL_PENDING")
        self.assertEqual(self.peers.process_starts, starts)

    def test_peer_rejection_models_forged_changed_or_wrong_key_admission_without_start(self):
        for code in ("GEP_ADMISSION_SIGNATURE_INVALID", "GEP_ADMISSION_BODY_CHANGED", "GEP_ADMISSION_KEY_NOT_TRUSTED"):
            with self.subTest(code=code):
                td = tempfile.TemporaryDirectory(); root = Path(td.name); peers = FakePeers(); peers.execute_queue = ["REJECTED_PRECONDITION"]
                relay = Gen4Relay(root/"transport", root/"state", service_identity=self.service, peers=peers)
                relay.process_one(package(root/"transport", admission=(code+"-bytes").encode()))
                self.assertEqual(peers.process_starts, 0)
                self.assertEqual(json.loads((root/"state/gen4/executions/dger-001.json").read_text())["phase"], "DONE")
                td.cleanup()

    def test_service_identity_change_after_acceptance_fails_resume_closed(self):
        p = package(self.transport)
        relay = Gen4Relay(self.transport, self.state, service_identity=self.service, peers=self.peers, fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "after_correlation" else None)
        with self.assertRaises(Crash): relay.process_one(p)
        other = service_identity("dger-deployment-B")
        relay2 = Gen4Relay(self.transport, self.state, service_identity=other, peers=self.peers)
        relay2.scan_once()
        self.assertEqual(self.peers.execute_calls, 0)


class LegacyGuardTests(unittest.TestCase):

    def test_prototype_r0_direct_execution_surface_is_permanently_retired(self):
        from dger import relay as prototype
        self.assertNotIn("subprocess.Popen", (ROOT / "src/dger/relay.py").read_text("utf-8"))
        with self.assertRaises(prototype.RetiredPrototypeSurface):
            prototype.Relay(None, None)

    def test_gen3_runtime_contains_secure_activation_guard(self):
        text = (ROOT / "src/dger/relay_runtime.py").read_text("utf-8")
        self.assertIn("assert_legacy_allowed(state_root)", text)

    def test_service_identity_file_must_be_owner_only(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"service.json"
            body = {"schema":SERVICE_IDENTITY_SCHEMA,"service_principal_id":"dger-service","service_deployment_id":"dger-A","actor_role":"EXECUTION_RELAY"}
            body["identity_digest"] = canonical_digest(body)
            p.write_bytes(canonical_file_bytes(body)); p.chmod(0o644)
            with self.assertRaises(DgerGen4Error): load_service_identity(p)
            p.chmod(0o600)
            self.assertEqual(load_service_identity(p).service_deployment_id, "dger-A")

    def test_absent_activation_allows_preactivation_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            assert_legacy_allowed(Path(td))

    def test_valid_activation_retires_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); p = root/"gen4/ACTIVATED.json"; p.parent.mkdir(parents=True)
            value = {"schema":"dger-gen4-activation/v1","mode":"GEN4_REQUIRED","activation_id":"act-1","peer_tuple_digest":"a"*64,"service_identity_digest":"b"*64}
            p.write_bytes(canonical_file_bytes(value))
            with self.assertRaises(LegacySurfaceRetired): assert_legacy_allowed(root)

    def test_malformed_activation_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); p = root/"gen4/ACTIVATED.json"; p.parent.mkdir(parents=True); p.write_text("{}")
            with self.assertRaises(LegacySurfaceRetired): assert_legacy_allowed(root)


if __name__ == "__main__":
    unittest.main()
