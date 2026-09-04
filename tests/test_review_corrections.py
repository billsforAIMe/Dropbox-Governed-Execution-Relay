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


def attestation(value, tool, operation):
    att = value.get("identity_attestation")
    evidence = value.get("evidence")
    if not isinstance(att, dict) or not isinstance(evidence, dict):
        raise DgerError("GTG_IDENTITY_ATTESTATION_REQUIRED")
    if evidence.get("tool_id") != tool or evidence.get("tool_identity") != att.get("tool_identity"):
        raise DgerError("GTG_INVOCATION_IDENTITY_MISMATCH")
    return {
        "tool_id": tool,
        "operation": operation,
        "invocation_id": value["invocation_id"],
        "tool_identity": att["tool_identity"],
        "tool_tree": att["tool_tree"],
        "gtg_identity": att["gtg_identity"],
        "registry_identity": evidence["registry_identity"],
    }


def response(eid: str, state: str) -> dict:
    return {"schema": "moh-status/v1", "execution_id": eid, "state": state}


def wrapped(eid: str, state: str, *, tool_identity: str = "1" * 40, tool_tree: str = "2" * 40) -> dict:
    return {
        "ok": True,
        "invocation_id": "inv_" + "1" * 32,
        "result": {
            "ok": state not in {"FAILED", "IN_DOUBT"},
            "state": state,
            "response_json": json.dumps(response(eid, state), sort_keys=True, separators=(",", ":")),
        },
        "identity_attestation": {
            "tool_identity": tool_identity,
            "tool_tree": tool_tree,
            "gtg_identity": "9" * 40,
        },
        "evidence": {
            "tool_id": "mac-operation-host",
            "tool_identity": tool_identity,
            "registry_identity": "3" * 40,
        },
    }


# Synthetic package shell so exact changed source files can be imported without
# reconstructing unchanged modules. Behaviors below come from changed source files;
# only unrelated dependencies are stubbed.
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
protocol._invocation_attestation = attestation
protocol.utc = lambda: "2026-09-04T00:00:00Z"
protocol.EXECUTION_ID_RE = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
protocol.PROTOCOL = "DGER_EXECUTION_V1"
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

    def _status(self, execution_id, status, **extra):
        self.statuses.append((execution_id, status, extra))

    def _publish_result(self, execution_id, record):
        self.published.append((execution_id, copy.deepcopy(record)))
        return "a" * 64, f"Runs/{execution_id}/result.json"


class KillAfterEffectGateway:
    def __init__(self):
        self.calls = []
        self.kill_execute_once = True

    def invoke(self, tool_id, operation, arguments):
        self.calls.append(operation)
        if operation == "execute" and self.kill_execute_once:
            self.kill_execute_once = False
            raise SystemExit("power loss after MOH accepted execute")
        return wrapped(arguments["execution_id"], "SUCCEEDED")


class SequenceGateway:
    def __init__(self):
        self.status_events = ["IN_DOUBT", RuntimeError("status transport lost"), "NOT_FOUND"]
        self.calls = []

    def invoke(self, tool_id, operation, arguments):
        self.calls.append(operation)
        if operation == "execute":
            raise AssertionError("execute must never be called after IN_DOUBT latch")
        event = self.status_events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return wrapped(arguments["execution_id"], event)


class InvocationAdvanceGateway:
    def __init__(self):
        self.effect_count = 0
        self.calls = []

    def invoke(self, tool_id, operation, arguments):
        self.calls.append(operation)
        if operation == "execute":
            self.effect_count += 1
        return wrapped(arguments["execution_id"], "SUCCEEDED", tool_identity="6" * 40, tool_tree="7" * 40)


class MissingAttestationGateway:
    def invoke(self, tool_id, operation, arguments):
        value = wrapped(arguments["execution_id"], "SUCCEEDED")
        value.pop("identity_attestation")
        return value


class ReviewCorrectionTests(unittest.TestCase):
    def setUp(self):
        STORE.clear()

    def base_state(self, eid="exec-1"):
        return {
            "execution_id": eid,
            "phase": "MOH_STAGE_COMPLETE",
            "moh_binding": {"tool_identity": "1" * 40, "tool_tree": "2" * 40},
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

        relay._reconcile_moh(durable)
        durable = load_state(relay.state, "exec-2")
        self.assertTrue(durable["moh_in_doubt_ever"])
        self.assertEqual(durable["phase"], "MOH_IN_DOUBT")

        relay._reconcile_moh(durable)
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

    def test_b04_invocation_time_provider_advance_is_attested_not_preblocked(self):
        gateway = InvocationAdvanceGateway()
        relay = Harness(gateway)
        state = self.base_state("exec-4")
        result = relay._invoke_moh(state, "execute")
        self.assertIsNotNone(result)
        self.assertEqual(gateway.effect_count, 1)
        durable = load_state(relay.state, "exec-4")
        self.assertEqual(durable["moh_binding"]["tool_identity"], "1" * 40)
        self.assertEqual(durable["moh_execute_attestation"]["tool_identity"], "6" * 40)
        self.assertEqual(durable["moh_execute_attestation"]["tool_tree"], "7" * 40)

    def test_success_without_attestation_is_reconcile_only(self):
        relay = Harness(MissingAttestationGateway())
        state = self.base_state("exec-5")
        result = relay._invoke_moh(state, "execute")
        self.assertIsNone(result)
        durable = load_state(relay.state, "exec-5")
        self.assertEqual(durable["phase"], "MOH_RECONCILE")
        self.assertTrue(durable["moh_execute_may_have_happened"])
        self.assertEqual(durable["last_moh_attestation_error"]["code"], "GTG_IDENTITY_ATTESTATION_REQUIRED")

    def test_http_adapter_requires_attestation_on_success(self):
        spec = importlib.util.spec_from_file_location("dger.gtg_http", SRC / "gtg_http.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        gateway = object.__new__(mod.GTGHttpGateway)
        valid = wrapped("exec-6", "SUCCEEDED")
        gateway._call = lambda *a, **k: copy.deepcopy(valid)
        returned = gateway.invoke("mac-operation-host", "execute", {"execution_id": "exec-6"})
        self.assertEqual(returned["identity_attestation"]["tool_identity"], "1" * 40)

        invalid = copy.deepcopy(valid)
        invalid.pop("identity_attestation")
        gateway._call = lambda *a, **k: copy.deepcopy(invalid)
        with self.assertRaisesRegex(mod.GTGHttpError, "GTG_IDENTITY_ATTESTATION_REQUIRED"):
            gateway.invoke("mac-operation-host", "execute", {"execution_id": "exec-6"})


if __name__ == "__main__":
    unittest.main(verbosity=2)