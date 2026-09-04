from pathlib import Path
import tempfile
import unittest

from dger.phase1 import (
    ACKNOWLEDGED,
    CrashInjected,
    DELIVERY_REQUIRED,
    Phase1Relay,
    load_json,
)

ACTION = "a" * 64
EXECUTION = "execution_" + ("b" * 64)
HANDOFF = "execution_handoff_" + ("c" * 64)
DESCRIPTOR_DIGEST = "d" * 64
DESCRIPTOR = {
    "schema_version": "GEP_PHASE1_EXECUTION_DESCRIPTOR_V1",
    "execution_id": EXECUTION,
    "chm_handoff_id": HANDOFF,
    "v1_action_id": ACTION,
    "project_id": "ai-me",
    "operation_id": "platform.self_check",
    "operation_revision": "0" * 64,
    "parameters": {},
    "governed_target": {},
}
TERMINAL = {
    "execution_id": EXECUTION,
    "descriptor_digest": DESCRIPTOR_DIGEST,
    "status": "SUCCEEDED",
    "result_manifest_reference": f"{EXECUTION}/terminal.json",
    "result_manifest_digest": "e" * 64,
}


class FakeCHM:
    def __init__(self):
        self.slot = None
        self.terminal = None
        self.statuses = []

    def get_handoff(self, handoff_id):
        return {
            "handoff_id": HANDOFF,
            "execution_id": EXECUTION,
            "v1_action_id": ACTION,
            "execution_descriptor": DESCRIPTOR,
            "execution_descriptor_digest": DESCRIPTOR_DIGEST,
            "slot_allocation": self.slot,
            "terminal_result": self.terminal,
        }

    def active_capacity(self):
        return [] if self.slot is None else [{"task": EXECUTION, **self.slot}]

    def acquire_capacity(self, execution_id):
        self.slot = {"slot": "Execution1", "allocation_id": "allocation_" + ("f" * 32)}
        return self.slot

    def bind_capacity(self, handoff_id, execution_id, slot, allocation_id):
        self.slot = {"slot": slot, "allocation_id": allocation_id}
        return {}

    def capacity_status(self, slot, allocation_id, status):
        self.statuses.append(status)
        return {}

    def publish_terminal(self, handoff_id, proof):
        self.terminal = {
            "status": proof["status"],
            "result_manifest_reference": proof["result_manifest_reference"],
            "result_manifest_digest": proof["result_manifest_digest"],
            "descriptor_digest": proof["descriptor_digest"],
        }
        return {"terminal_result": self.terminal}


class FakeGEP:
    def __init__(self):
        self.started = False
        self.start_calls = 0

    def reconcile(self, descriptor):
        return TERMINAL if self.started else {"status": "NOT_STARTED", "execution_id": EXECUTION, "descriptor_digest": DESCRIPTOR_DIGEST}

    def start(self, descriptor):
        self.start_calls += 1
        self.started = True
        return TERMINAL


class FakeWake:
    def __init__(self):
        self.events = []

    def deliver(self, event):
        self.events.append(event)


class Phase1RelayTests(unittest.TestCase):
    def _run_crash(self, point):
        chm, gep, wake = FakeCHM(), FakeGEP(), FakeWake()
        seen = False

        def hook(current):
            nonlocal seen
            if current == point and not seen:
                seen = True
                raise CrashInjected(point)

        with tempfile.TemporaryDirectory() as td:
            relay = Phase1Relay(Path(td), chm, gep, wake, hook)
            with self.assertRaises(CrashInjected):
                relay.process(HANDOFF)
            relay.crash_hook = None
            relay.process(HANDOFF)
            self.assertLessEqual(gep.start_calls, 1)
            outbox = load_json(relay._outbox_path(EXECUTION))
            if chm.terminal is not None:
                self.assertIsNotNone(outbox)
                self.assertIn(outbox["phase"], {DELIVERY_REQUIRED, ACKNOWLEDGED})
            if outbox is not None:
                relay.deliver(EXECUTION)
                self.assertLessEqual(gep.start_calls, 1)

    def test_crash_matrix_never_second_launch_or_orphan_terminal(self):
        for point in (
            "after_request_receipt",
            "after_capacity_allocation",
            "before_gep_start_request",
            "after_gep_start_request",
            "after_gep_terminal_truth",
            "before_outbox_pending",
            "after_outbox_pending_before_chm_publication",
            "after_chm_publication_before_delivery_state",
            "during_wake",
            "after_wake_before_acknowledgment",
        ):
            with self.subTest(crash_point=point):
                self._run_crash(point)

    def test_uncertain_blocks_capacity_and_never_starts(self):
        class UncertainGEP(FakeGEP):
            def reconcile(self, descriptor):
                return {"status": "UNCERTAIN", "execution_id": EXECUTION, "descriptor_digest": DESCRIPTOR_DIGEST}

            def start(self, descriptor):
                raise AssertionError("start must not be called from UNCERTAIN recovery")

        with tempfile.TemporaryDirectory() as td:
            chm, wake = FakeCHM(), FakeWake()
            relay = Phase1Relay(Path(td), chm, UncertainGEP(), wake)
            self.assertEqual(relay.process(HANDOFF)["status"], "UNCERTAIN")
            self.assertIn("BLOCKED", chm.statuses)


if __name__ == "__main__":
    unittest.main()
