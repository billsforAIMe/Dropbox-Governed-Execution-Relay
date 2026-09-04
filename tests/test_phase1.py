from pathlib import Path
import tempfile
import threading
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
UNCERTAIN = {
    "execution_id": EXECUTION,
    "descriptor_digest": DESCRIPTOR_DIGEST,
    "status": "UNCERTAIN",
    "start_intent_reference": f"{EXECUTION}/start-intent.json",
    "start_intent_digest": "9" * 64,
}


class FakeCHM:
    def __init__(self):
        self.allocation = None
        self.bound = None
        self.capacity_state = None
        self.terminal = None
        self.uncertain = None
        self.statuses = []
        self.acquire_calls = 0
        self.allocations_created = 0
        self.lock = threading.Lock()

    def get_handoff(self, handoff_id):
        status = self.terminal["status"] if self.terminal is not None else ("UNCERTAIN" if self.uncertain is not None else ("CAPACITY_RESERVED" if self.bound else "PENDING"))
        return {
            "handoff_id": HANDOFF,
            "execution_id": EXECUTION,
            "v1_action_id": ACTION,
            "execution_descriptor": DESCRIPTOR,
            "execution_descriptor_digest": DESCRIPTOR_DIGEST,
            "status": status,
            "slot_allocation": self.bound,
            "uncertain_result": self.uncertain,
            "terminal_result": self.terminal,
        }

    def active_capacity(self):
        with self.lock:
            if self.allocation is None or self.capacity_state == "RELEASED":
                return []
            return [{"task": EXECUTION, "status": self.capacity_state, **self.allocation}]

    def acquire_capacity(self, execution_id):
        with self.lock:
            self.acquire_calls += 1
            if self.allocation is None or self.capacity_state == "RELEASED":
                self.allocation = {"slot": "Execution1", "allocation_id": "allocation_" + ("f" * 32)}
                self.capacity_state = "RESERVED"
                self.allocations_created += 1
                return {**self.allocation, "changed": True, "status": "RESERVED"}
            return {**self.allocation, "changed": False, "status": self.capacity_state}

    def bind_capacity(self, handoff_id, execution_id, slot, allocation_id):
        proposed = {"slot": slot, "allocation_id": allocation_id}
        with self.lock:
            if self.bound is not None and self.bound != proposed:
                raise AssertionError("conflicting logical slot bind")
            self.bound = proposed
        return {}

    def capacity_status(self, slot, allocation_id, status):
        with self.lock:
            self.assert_allocation(slot, allocation_id)
            allowed = {
                ("RESERVED", "RUNNING"),
                ("RUNNING", "BLOCKED"),
                ("RUNNING", "RELEASED"),
                ("BLOCKED", "RELEASED"),
            }
            if (self.capacity_state, status) not in allowed:
                raise AssertionError(f"invalid transition {self.capacity_state}->{status}")
            self.capacity_state = status
            self.statuses.append(status)
        return {"status": status}

    def assert_allocation(self, slot, allocation_id):
        if self.allocation != {"slot": slot, "allocation_id": allocation_id}:
            raise AssertionError("allocation mismatch")

    def publish_uncertain(self, handoff_id, proof):
        self.uncertain = {
            "status": "UNCERTAIN",
            "start_intent_reference": proof["start_intent_reference"],
            "start_intent_digest": proof["start_intent_digest"],
            "descriptor_digest": proof["descriptor_digest"],
            "classification": "CONSEQUENTIAL_START_MAY_HAVE_OCCURRED",
        }
        return {"status": "UNCERTAIN", "uncertain_result": self.uncertain, "terminal_result": None}

    def publish_terminal(self, handoff_id, proof):
        self.terminal = {
            "status": proof["status"],
            "result_manifest_reference": proof["result_manifest_reference"],
            "result_manifest_digest": proof["result_manifest_digest"],
            "descriptor_digest": proof["descriptor_digest"],
        }
        return {"status": proof["status"], "uncertain_result": self.uncertain, "terminal_result": self.terminal}


class FakeGEP:
    def __init__(self):
        self.started = False
        self.start_calls = 0
        self.lock = threading.Lock()

    def reconcile(self, descriptor):
        with self.lock:
            return TERMINAL if self.started else {"status": "NOT_STARTED", "execution_id": EXECUTION, "descriptor_digest": DESCRIPTOR_DIGEST}

    def start(self, descriptor):
        with self.lock:
            if not self.started:
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
            self.assertEqual(1, chm.allocations_created)
            outbox = load_json(relay._outbox_path(EXECUTION))
            if chm.terminal is not None:
                self.assertIsNotNone(outbox)
                self.assertIn(outbox["phase"], {DELIVERY_REQUIRED, ACKNOWLEDGED})
            if outbox is not None:
                relay.deliver(EXECUTION)
                self.assertLessEqual(gep.start_calls, 1)

    def test_crash_matrix_never_second_launch_or_second_allocation(self):
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

    def test_crash_after_acquire_before_bind_recovers_same_allocation(self):
        chm, gep, wake = FakeCHM(), FakeGEP(), FakeWake()
        with tempfile.TemporaryDirectory() as td:
            relay = Phase1Relay(Path(td), chm, gep, wake, lambda point: (_ for _ in ()).throw(CrashInjected(point)) if point == "after_capacity_allocation" else None)
            with self.assertRaises(CrashInjected):
                relay.process(HANDOFF)
            self.assertIsNone(chm.bound)
            first = dict(chm.allocation)
            relay.crash_hook = None
            relay.process(HANDOFF)
            self.assertEqual(first, chm.bound)
            self.assertEqual(1, chm.allocations_created)

    def test_concurrent_duplicate_relays_share_one_capacity_allocation(self):
        chm, gep, wake = FakeCHM(), FakeGEP(), FakeWake()
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            relays = [Phase1Relay(Path(a), chm, gep, wake), Phase1Relay(Path(b), chm, gep, wake)]
            barrier = threading.Barrier(2)
            errors = []

            def worker(relay):
                try:
                    barrier.wait()
                    relay._find_or_acquire_capacity(chm.get_handoff(HANDOFF))
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(relay,)) for relay in relays]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual([], errors)
            self.assertEqual(1, chm.allocations_created)
            self.assertEqual(chm.allocation, chm.bound)

    def test_uncertain_transitions_running_to_blocked_publishes_chm_and_never_starts(self):
        class UncertainGEP(FakeGEP):
            def reconcile(self, descriptor):
                return dict(UNCERTAIN)

            def start(self, descriptor):
                raise AssertionError("start must not be called from UNCERTAIN recovery")

        with tempfile.TemporaryDirectory() as td:
            chm, wake = FakeCHM(), FakeWake()
            relay = Phase1Relay(Path(td), chm, UncertainGEP(), wake)
            self.assertEqual(relay.process(HANDOFF)["status"], "UNCERTAIN")
            self.assertEqual(["RUNNING", "BLOCKED"], chm.statuses)
            self.assertEqual("BLOCKED", chm.capacity_state)
            self.assertIsNotNone(chm.uncertain)
            self.assertEqual(DESCRIPTOR_DIGEST, chm.uncertain["descriptor_digest"])


if __name__ == "__main__":
    unittest.main()
