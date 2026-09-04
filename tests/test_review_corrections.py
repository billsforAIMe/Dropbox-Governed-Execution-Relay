from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "dger"

class DgerError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail

STORE: dict[str, dict] = {}

def save_state(_root, execution_id, state):
    STORE[execution_id] = copy.deepcopy(state)

def load_state(_root, execution_id):
    value = STORE.get(execution_id)
    return copy.deepcopy(value) if value is not None else None

def unwrap(value, _tool, _operation):
    inv = value.get("invocation_id") if isinstance(value.get("invocation_id"), str) else None
    if value.get("ok") is True and isinstance(value.get("result"), dict):
        return value["result"], inv
    return None, inv

def response(eid: str, state: str) -> dict:
    return {"schema": "moh-status/v1", "execution_id": eid, "state": state}

def wrapped(eid: str, state: str) -> dict:
    return {
        "ok": True,
        "invocation_id": "inv_" + "1" * 32,
        "result": {
            "ok": state not in {"FAILED", "IN_DOUBT"},
            "state": state,
            "response_json": json.dumps(response(eid, state), sort_keys=True, separators=(",", ":")),
        },
    }

# Synthetic package shell so the exact changed source files can be imported without
# reconstructing unchanged modules. Every behavior exercised below comes from the
# changed source files themselves; only unrelated dependencies are stubbed.
pkg = types.ModuleType("dger")
pkg.__path__ = [str(SRC)]
sys.modules["dger"] = pkg

protocol = types.ModuleType("dger.relay_protocol")
for name in (
    "CHM_TOOL_ID", "EXECUTION_ID_RE", "EXPECTED_INTERVAL_SECONDS", "MAX_ENVELOPE_BYTES",
    "MAX_MOH_RESPONSE_BYTES", "MAX_REQUEST_BYTES", "MAX_RESULT_RECORD_BYTES", "MOH_TOOL_ID",
    "PROTOCOL", "READY_SCHEMA", "REQUEST_SCHEMA", "REQUIRED_CHM_OPERATIONS",
):
    setattr(protocol, name, None)
protocol.CHM_TOOL_ID = "common-handoff-manager"
protocol.MOH_TOOL_ID = "mac-operation-host"
protocol.MAX_MOH_RESPONSE_BYTES = 1024 * 1024
protocol.MOH_TERMINAL_PUBLISHABLE = {"SUCCEEDED", "FAILED", "REJECTED_PRECONDITION", "REJECTED_DUPLICATE_MISMATCH"}
protocol.MOH_UNRESOLVED = {"IN_DOUBT"}
protocol.DgerError = DgerError
protocol.SemanticGateway = object
protocol._json_object_no_duplicates = lambda raw: json.loads(raw.decode("utf-8"))
protocol.utc = lambda: "2026-09-04T00:00:00Z"
protocol.EXECUTION_ID_RE = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
protocol.PROTOCOL = "DGER_EXECUTION_V1"
# Unused imported names for these focused paths.
for name in (
    "_intent_digest", "_safe_rel", "_validate_consumer_binding", "_validate_ready", "_validate_request",
    "atomic_bytes", "atomic_json", "canonical_bytes", "canonical_digest", "canonical_file_bytes",
    "moh_closure_digest", "payload_manifest", "read_json_regular", "read_regular", "resolve_tool_binding",
    "sha256", "validate_moh_envelope",
):
    setattr(protocol, name, lambda *a, **k: None)
sys.modules["dger.relay_protocol"] = protocol

state_mod = types.ModuleType("dger.relay_state")
state_mod.save_state = save_state
state_mod.load_state = load_state
state_mod._unwrap_gtg_result = unwrap
state_mod._validate_moh_response = lambda r, eid: r["state"] if r.get("execution_id") == eid else (_ for _ in ()).throw(DgerError("BAD_ID"))
state_mod._result_record = lambda state, response, ref: {"execution_id": state["execution_id"], "state": response["state"], "ref": ref}
state_mod._chm_result = lambda *a, **k: {}
state_mod._safe_execution_dir = lambda *a, **k: Path("/tmp")
state_mod._stage_digest = lambda *a, **k: "stage"
state_mod.freeze_ingress = lambda *a, **k: None
state_mod.materialize_moh_stage = lambda *a, **k: None
for n in ("_chm_result", "_safe_execution_dir", "freeze_ingress"):
    pass
sys.modules["dger.relay_state"] = state_mod

runtime_mod = types.ModuleType("dger.relay_runtime")
runtime_mod.RelayRuntimeMixin = type("RelayRuntimeMixin", (), {})
sys.modules["dger.relay_runtime"] = runtime_mod
accept_mod = types.ModuleType("dger.relay_accept")
accept_mod.RelayAcceptMixin = type("RelayAcceptMixin", (), {})
sys.modules["dger.relay_accept"] = accept_mod
chm_mod = types.ModuleType("dger.relay_chm")
class StubChmMixin:
    def _publish_chm(self, state):
        self.chm_publications = getattr(self, "chm_publications", 0) + 1
        state["phase"] = "DONE"
        save_state(self.state, state["execution_id"], state)
chm_mod.RelayChmMixin = StubChmMixin
sys.modules["dger.relay_chm"] = chm_mod

def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, SRC / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

invoke_mod = load("dger.relay_moh_invoke", "relay_moh_invoke.py")
moh_mod = load("dger.relay_moh", "relay_moh.py")
v1_mod = load("dger.relay_v1", "relay_v1.py")

class Harness(moh_mod.RelayMohMixin):
    def __init__(self, gateway):
        self.gateway = gateway
        self.state = Path("/state")
        self.moh_home = Path("/moh")
        self.statuses = []
        self.published = []

    def _verify_frozen_binding(self, state, key, tool_id, operation):
        return None

    def _status(self, execution_id, status, **extra):
        self.statuses.append((execution_id, status, extra))

    def _publish_result(self, execution_id, record):
        self.published.append((execution_id, copy.deepcopy(record)))
        return "a" * 64, f"Runs/{execution_id}/result.json"

class KillAfterEffectGateway:
    def __init__(self):
        self.calls = []
        self.kill_execute_once = True

    def invoke_frozen(self, tool_id, operation, arguments, expected_binding):
        self.calls.append(operation)
        if operation == "execute" and self.kill_execute_once:
            self.kill_execute_once = False
            # Simulate process termination after the external effect reached its owner.
            raise SystemExit("power loss after MOH accepted execute")
        if operation == "status":
            return wrapped(arguments["execution_id"], "SUCCEEDED")
        return wrapped(arguments["execution_id"], "SUCCEEDED")

class SequenceGateway:
    def __init__(self):
        self.status_events = ["IN_DOUBT", RuntimeError("status transport lost"), "NOT_FOUND"]
        self.calls = []

    def invoke_frozen(self, tool_id, operation, arguments, expected_binding):
        self.calls.append(operation)
        if operation == "execute":
            raise AssertionError("execute must never be called after IN_DOUBT latch")
        event = self.status_events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return wrapped(arguments["execution_id"], event)

class FrozenRaceGateway:
    def __init__(self):
        self.effect_count = 0
        self.calls = []

    def invoke_frozen(self, tool_id, operation, arguments, expected_binding):
        self.calls.append((operation, copy.deepcopy(expected_binding)))
        # Represents an atomic GTG CAS mismatch after Doctor preflight but before effect.
        return {"ok": False, "code": "EXPECTED_BINDING_MISMATCH", "status": "rejected"}

class ReviewCorrectionTests(unittest.TestCase):
    def setUp(self):
        STORE.clear()

    def base_state(self, eid="exec-1"):
        return {
            "execution_id": eid,
            "phase": "MOH_STAGE_COMPLETE",
            "moh_binding": {"tool_identity": "1" * 40},
            "moh_execute_calls": 0,
            "moh_status_calls": 0,
            "envelope": {},
            "dger_request_id": "req",
            "logical_handoff_id": "hnd_" + "1" * 64,
        }

    def test_b01_execute_write_ahead_survives_process_death(self):
        gateway = KillAfterEffectGateway()
        relay = Harness(gateway)
        state = self.base_state()
        with self.assertRaises(SystemExit):
            relay._invoke_moh(state, "execute")
        durable = load_state(relay.state, state["execution_id"])
        self.assertEqual(durable["phase"], "MOH_RECONCILE")
        self.assertTrue(durable["moh_execute_may_have_happened"])
        self.assertEqual(durable["moh_execute_calls"], 1)

        # Restart from durable State: reconciliation asks status first; it does not execute again.
        relay2 = Harness(gateway)
        relay2._reconcile_moh(durable)
        self.assertEqual(gateway.calls, ["execute", "status"])
        self.assertEqual(load_state(relay2.state, state["execution_id"])["phase"], "CHM_PENDING")

    def test_b02_in_doubt_latch_survives_status_ambiguity_then_not_found(self):
        gateway = SequenceGateway()
        relay = Harness(gateway)
        state = self.base_state("exec-2")
        state["phase"] = "MOH_RECONCILE"

        relay._reconcile_moh(state)
        durable = load_state(relay.state, "exec-2")
        self.assertTrue(durable["moh_in_doubt_ever"])
        self.assertEqual(durable["phase"], "MOH_IN_DOUBT")

        relay._reconcile_moh(durable)  # transport ambiguity
        durable = load_state(relay.state, "exec-2")
        self.assertTrue(durable["moh_in_doubt_ever"])
        self.assertEqual(durable["phase"], "MOH_IN_DOUBT")

        relay._reconcile_moh(durable)  # later NOT_FOUND
        durable = load_state(relay.state, "exec-2")
        self.assertEqual(durable["phase"], "MOH_IN_DOUBT")
        self.assertEqual(gateway.calls, ["status", "status", "status"])

    def test_b03_raw_moh_terminal_phase_is_resumable(self):
        relay = object.__new__(v1_mod.Relay)
        relay.state = Path("/state")
        relay.chm_publications = 0
        relay.statuses = []
        relay._status = lambda *a, **k: relay.statuses.append((a, k))
        published = []
        relay._publish_result = lambda eid, record: (published.append((eid, record)) or ("b" * 64, f"Runs/{eid}/result.json"))

        state = self.base_state("exec-3")
        terminal = response("exec-3", "SUCCEEDED")
        state.update({
            "phase": "MOH_TERMINAL",
            "moh_terminal_state": "SUCCEEDED",
            "moh_terminal_response": terminal,
            "moh_terminal_at_utc": "2026-09-04T00:00:00Z",
        })
        save_state(relay.state, "exec-3", state)
        relay._advance_locked("exec-3", load_state(relay.state, "exec-3"))
        self.assertEqual(len(published), 1)
        self.assertEqual(relay.chm_publications, 1)
        self.assertEqual(load_state(relay.state, "exec-3")["phase"], "DONE")

    def test_b04_exact_binding_rejection_prevents_effect_after_preflight_race(self):
        gateway = FrozenRaceGateway()
        relay = Harness(gateway)
        state = self.base_state("exec-4")
        result = relay._invoke_moh(state, "execute")
        self.assertIsNone(result)
        self.assertEqual(gateway.effect_count, 0)
        self.assertEqual(load_state(relay.state, "exec-4")["phase"], "MOH_RECONCILE")
        self.assertEqual(gateway.calls[0][0], "execute")
        self.assertEqual(gateway.calls[0][1], state["moh_binding"])

    def test_http_adapter_blocks_until_authoritative_gtg_cas_exists(self):
        spec = importlib.util.spec_from_file_location("dger.gtg_http", SRC / "gtg_http.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        gateway = object.__new__(mod.GTGHttpGateway)
        gateway._call = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network call must not occur"))
        binding = {
            "authoritative_binding": {"repository_id": "123", "selector": "refs/heads/main"},
            "tool_identity": "1" * 40,
            "tool_tree": "2" * 40,
            "registry_identity": "3" * 40,
        }
        with self.assertRaisesRegex(mod.GTGHttpError, "GTG_ATOMIC_BINDING_CAS_UNAVAILABLE"):
            gateway.invoke_frozen("mac-operation-host", "execute", {"execution_id": "exec-4"}, binding)


if __name__ == "__main__":
    unittest.main(verbosity=2)
