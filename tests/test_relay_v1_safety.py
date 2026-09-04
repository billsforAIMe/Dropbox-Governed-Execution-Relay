from relay_v1_fixture import *
from relay_v1_fixture import RelayV1TestBase, _safe_rel


class RelayV1SafetyTests(RelayV1TestBase):
    def test_11_failed_execution_does_not_poison_unrelated_success(self):
        self.gateway.failed_ids.add("fails")
        pf = write_package(self.transport, "fails")
        ps = write_package(self.transport, "succeeds")
        self.relay.process_one(pf); self.relay.process_one(ps)
        self.assertEqual(self.state_for("fails")["moh_terminal_state"], "FAILED")
        self.assertEqual(self.state_for("succeeds")["moh_terminal_state"], "SUCCEEDED")
        self.assertEqual(self.state_for("succeeds")["phase"], "DONE")

    def test_12_chm_failure_for_one_execution_does_not_block_others(self):
        bad, good = "chm-bad", "chm-good"
        self.gateway.fail_chm_once.add(handoff_for(bad))
        pb, pg = write_package(self.transport, bad), write_package(self.transport, good)
        self.relay.process_one(pb); self.relay.process_one(pg)
        self.assertEqual(self.state_for(bad)["phase"], "CHM_PENDING")
        self.assertEqual(self.state_for(good)["phase"], "DONE")
        self.assertEqual(self.gateway.execute_calls[bad], 1)
        self.assertEqual(self.gateway.execute_calls[good], 1)

    def test_13_in_doubt_never_publishes_or_resolves_chm(self):
        eid = "uncertain"
        self.gateway.in_doubt_ids.add(eid)
        p = write_package(self.transport, eid)
        self.relay.process_one(p); self.relay.process_one(p)
        self.assertEqual(self.state_for(eid)["phase"], "MOH_IN_DOUBT")
        self.assertNotIn(handoff_for(eid), self.gateway.chm_results)
        self.assertNotIn(handoff_for(eid), self.gateway.resolved)
        self.assertEqual(self.gateway.execute_calls[eid], 1)

    def test_14_result_is_bounded_reference_not_large_stdout(self):
        eid = "bounded"
        self.relay.process_one(write_package(self.transport, eid))
        result = json.loads((self.transport / "Runs" / eid / "result.json").read_text())
        self.assertNotIn("diagnostic bytes", json.dumps(result))
        self.assertEqual(result["moh_execution"]["stdout"]["total_bytes"], 10_000_000)
        self.assertEqual(result["moh_execution"]["stdout"]["evidence_ref"], "moh/evidence/stdout")
        chm = self.gateway.chm_results[handoff_for(eid)]
        self.assertEqual(chm["bounded_result_reference"], f"Runs/{eid}/result.json")
        self.assertNotIn("stdout", chm)

    def test_15_symlink_payload_is_rejected_before_acceptance(self):
        p = write_package(self.transport, "symlink")
        target = p / "outside.py"; target.write_text("outside")
        (p / "payload" / "link.py").symlink_to(target)
        rewrite_ready_failed = False
        try:
            rewrite_ready(p)
        except Exception:
            rewrite_ready_failed = True
        self.assertTrue(rewrite_ready_failed)
        self.relay.process_one(p)
        self.assertNotIn("symlink", self.gateway.execute_calls)

    def test_16_provider_advance_after_acceptance_pauses_without_using_new_binding(self):
        eid = "provider-advance"
        self.gateway.running_status_cycles[eid] = 2
        p = write_package(self.transport, eid)
        self.relay.process_one(p)
        self.assertEqual(self.gateway.execute_calls[eid], 1)
        original = self.gateway.bindings[(MOH_TOOL_ID, "*")]
        self.gateway.bindings[(MOH_TOOL_ID, "*")] = make_binding(MOH_TOOL_ID, "6" * 40, "7" * 40, "100")
        self.relay.process_one(p)
        self.assertEqual(self.gateway.status_calls.get(eid, 0), 0)
        self.assertEqual(self.state_for(eid)["phase"], "MOH_RECONCILE")
        self.gateway.bindings[(MOH_TOOL_ID, "*")] = original
        self.relay.process_one(p); self.relay.process_one(p)
        self.assertEqual(self.gateway.execute_calls[eid], 1)
        self.assertEqual(self.state_for(eid)["phase"], "DONE")
