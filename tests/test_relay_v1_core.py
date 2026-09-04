from relay_v1_fixture import *
from relay_v1_fixture import RelayV1TestBase, _safe_rel


class RelayV1CoreTests(RelayV1TestBase):
    def test_01_several_sequential_independent_executions(self):
        ids = ["call-A", "call-B", "call-C"]
        for eid in ids:
            self.relay.process_one(write_package(self.transport, eid))
        self.assertEqual({eid: self.state_for(eid)["phase"] for eid in ids}, {eid: "DONE" for eid in ids})
        self.assertEqual({eid: self.gateway.execute_calls[eid] for eid in ids}, {eid: 1 for eid in ids})
        self.assertEqual(len(self.gateway.chm_results), 3)

    def test_02_overlapping_independent_arrivals_do_not_cross_contaminate(self):
        ids = [f"burst-{i}" for i in range(12)]
        packages = [write_package(self.transport, eid) for eid in ids]
        threads = [threading.Thread(target=self.relay.process_one, args=(p,)) for p in packages]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertTrue(all(self.state_for(eid)["phase"] == "DONE" for eid in ids))
        self.assertEqual(set(self.gateway.execute_calls), set(ids))
        for eid in ids:
            result = json.loads((self.transport / "Runs" / eid / "result.json").read_text())
            self.assertEqual(result["execution_id"], eid)
            self.assertEqual(result["logical_handoff_id"], handoff_for(eid))

    def test_03_repeated_identical_request_is_idempotent(self):
        p = write_package(self.transport, "repeat")
        self.relay.process_one(p); self.relay.process_one(p); self.relay.process_one(p)
        self.assertEqual(self.gateway.execute_calls["repeat"], 1)
        self.assertEqual(self.gateway.attach_calls[handoff_for("repeat")], 1)
        self.assertEqual(self.state_for("repeat")["phase"], "DONE")

    def test_04_same_execution_id_different_payload_fails_closed(self):
        p = write_package(self.transport, "conflict")
        self.relay.process_one(p)
        (p / "payload" / "adapter.py").write_bytes(b"print('different')\n")
        envelope = json.loads((p / "envelope.json").read_text())
        entries, _, _ = payload_manifest(p / "payload")
        envelope["closure_digest"] = moh_closure_digest(entries)
        body = dict(envelope); body.pop("request_digest")
        envelope["request_digest"] = canonical_digest(body)
        (p / "envelope.json").write_bytes(canonical_file(envelope))
        rewrite_ready(p)
        self.relay.process_one(p)
        self.assertEqual(self.status_for("conflict")["state"], "IDENTITY_INTENT_CONFLICT")
        self.assertEqual(self.gateway.execute_calls["conflict"], 1)

    def test_05_partial_ingress_never_executes(self):
        p = write_package(self.transport, "partial", ready=False)
        self.assertFalse(self.relay.process_one(p))
        self.assertNotIn("partial", self.gateway.execute_calls)
        self.assertFalse((self.state / "executions" / "partial.json").exists())

    def test_06_lost_execute_response_recovers_terminal_by_status_without_repeat(self):
        eid = "lost-execute"
        self.gateway.lost_execute_once.add(eid)
        p = write_package(self.transport, eid)
        self.relay.process_one(p)
        self.assertEqual(self.state_for(eid)["phase"], "MOH_RECONCILE")
        Relay(self.transport, self.state, moh_home=self.moh, gateway=self.gateway, sleep=lambda _: None).process_one(p)
        self.assertEqual(self.state_for(eid)["phase"], "DONE")
        self.assertEqual(self.gateway.execute_calls[eid], 1)
        self.assertGreaterEqual(self.gateway.status_calls[eid], 1)

    def test_07_repeated_status_while_running_never_reexecutes(self):
        eid = "running"
        self.gateway.running_status_cycles[eid] = 3
        p = write_package(self.transport, eid)
        for _ in range(5):
            self.relay.process_one(p)
        self.assertEqual(self.state_for(eid)["phase"], "DONE")
        self.assertEqual(self.gateway.execute_calls[eid], 1)
        self.assertGreaterEqual(self.gateway.status_calls[eid], 3)

    def test_08_restart_while_running_uses_status_only(self):
        eid = "restart-running"
        self.gateway.running_status_cycles[eid] = 2
        p = write_package(self.transport, eid)
        self.relay.process_one(p)
        self.assertEqual(self.state_for(eid)["phase"], "MOH_RECONCILE")
        new_relay = Relay(self.transport, self.state, moh_home=self.moh, gateway=self.gateway, sleep=lambda _: None)
        new_relay.process_one(p); new_relay.process_one(p)
        self.assertEqual(self.gateway.execute_calls[eid], 1)
        self.assertEqual(self.state_for(eid)["phase"], "DONE")

    def test_09_restart_after_terminal_before_chm_publication_does_not_rerun(self):
        eid = "chm-down"
        hid = handoff_for(eid)
        self.gateway.fail_chm_once.add(hid)
        p = write_package(self.transport, eid)
        self.relay.process_one(p)
        self.assertEqual(self.state_for(eid)["phase"], "CHM_PENDING")
        self.assertEqual(self.gateway.execute_calls[eid], 1)
        Relay(self.transport, self.state, moh_home=self.moh, gateway=self.gateway, sleep=lambda _: None).process_one(p)
        self.assertEqual(self.state_for(eid)["phase"], "DONE")
        self.assertEqual(self.gateway.execute_calls[eid], 1)

    def test_10_lost_chm_attach_response_replays_same_result_and_converges(self):
        eid = "lost-attach"
        hid = handoff_for(eid)
        self.gateway.lost_attach_once.add(hid)
        p = write_package(self.transport, eid)
        self.relay.process_one(p)
        self.assertEqual(self.state_for(eid)["phase"], "CHM_PENDING")
        first_result = dict(self.gateway.chm_results[hid])
        self.relay.process_one(p)
        self.assertEqual(self.state_for(eid)["phase"], "DONE")
        self.assertEqual(self.gateway.chm_results[hid], first_result)
        self.assertEqual(self.gateway.execute_calls[eid], 1)
        self.assertEqual(self.gateway.attach_calls[hid], 2)

