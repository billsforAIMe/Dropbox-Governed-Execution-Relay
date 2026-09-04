from relay_v1_fixture import *
from relay_v1_fixture import RelayV1TestBase, _safe_rel


class RelayV1SafetyMoreTests(RelayV1TestBase):
    def test_17_same_handoff_conflicting_terminal_result_fails_closed(self):
        hid = handoff_for("shared")
        p1 = write_package(self.transport, "shared-A", handoff=hid)
        p2 = write_package(self.transport, "shared-B", handoff=hid)
        # Both executions can pass CHM preflight while the same handoff is STARTED.
        # The first terminal publication wins; the second exact-but-different result
        # must fail closed at CHM rather than overwrite durable history.
        self.relay._accept_new(p1, "shared-A")
        self.relay._accept_new(p2, "shared-B")
        self.relay.process_one(p1); self.relay.process_one(p2)
        self.assertEqual(self.state_for("shared-A")["phase"], "DONE")
        self.assertEqual(self.state_for("shared-B")["phase"], "CHM_RESULT_CONFLICT")
        self.assertEqual(self.gateway.execute_calls["shared-B"], 1)

    def test_18_partial_moh_stage_never_triggers_execute(self):
        eid = "partial-moh"
        p = write_package(self.transport, eid)
        final = self.moh / "inbox" / eid
        final.mkdir(parents=True)
        (final / "envelope.json").write_text("{}")
        self.relay.process_one(p)
        self.assertNotIn(eid, self.gateway.execute_calls)
        self.assertEqual(self.status_for(eid)["state"], "MOH_RECONCILIATION_BLOCKED")
        self.assertEqual(self.status_for(eid)["code"], "PAYLOAD_MISSING_OR_UNSAFE")

    def test_19_path_traversal_components_fail_closed(self):
        for value in ("../escape", "/absolute", "a/../../b", "a/../b"):
            with self.assertRaises(Exception):
                _safe_rel(value)

    def test_20_stage_substitution_before_first_execute_fails_closed(self):
        eid = "stage-substitution"
        p = write_package(self.transport, eid)
        # Stop after acceptance and exact MOH materialization by calling those bounded pieces.
        state = self.relay._accept_new(p, eid)
        from dger.relay_v1 import materialize_moh_stage
        materialize_moh_stage(Path(state["frozen_stage"]), self.moh / "inbox", eid, state["frozen_stage_digest"])
        state["phase"] = "MOH_STAGE_COMPLETE"
        from dger.relay_v1 import save_state
        save_state(self.state, eid, state)
        (self.moh / "inbox" / eid / "envelope.json").write_text("{}")
        self.relay.process_one(p)
        self.assertNotIn(eid, self.gateway.execute_calls)
        self.assertEqual(self.status_for(eid)["state"], "MOH_RECONCILIATION_BLOCKED")
        self.assertEqual(self.status_for(eid)["code"], "MOH_STAGE_SUBSTITUTED")

    def test_21_non_started_chm_handoff_rejected_before_moh_stage_or_execute(self):
        eid = "chm-not-started"
        package = write_package(self.transport, eid)
        hid = handoff_for(eid)
        self.gateway.handoff_states[hid] = "OPEN"
        self.assertTrue(self.relay.process_one(package))
        status = json.loads((self.transport / "Runs" / eid / "status.json").read_text())
        self.assertEqual(status["state"], "REJECTED")
        self.assertEqual(status["code"], "CHM_HANDOFF_NOT_EXECUTION_READY")
        self.assertNotIn(eid, self.gateway.execute_calls)
        self.assertFalse((self.moh / "inbox" / eid).exists())


def _test_prior_in_doubt_then_not_found_never_reexecutes(self):
    eid = "in-doubt-then-not-found"
    package = write_package(self.transport, eid)
    self.gateway.in_doubt_ids.add(eid)
    self.assertTrue(self.relay.process_one(package))
    self.assertEqual(self.status_for(eid)["state"], "MOH_IN_DOUBT")
    execute_count = self.gateway.execute_calls.get(eid, 0)
    # Simulate later loss/corruption of host lookup state after DGER already saw IN_DOUBT.
    self.gateway.in_doubt_ids.discard(eid)
    self.gateway.moh[eid] = self.gateway._moh_response(eid, "NOT_FOUND")
    self.assertTrue(self.relay.process_one(package))
    self.assertEqual(self.status_for(eid)["state"], "MOH_IN_DOUBT")
    self.assertEqual(execute_count, self.gateway.execute_calls.get(eid, 0))

RelayV1SafetyMoreTests.test_22_prior_in_doubt_then_not_found_never_reexecutes = _test_prior_in_doubt_then_not_found_never_reexecutes
