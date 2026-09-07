from __future__ import annotations

import ast
import json
from pathlib import Path

from dger_execution_surface_scan import SEMANTIC_EXECUTE_ALLOWLIST, scan_execution_call_sites

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "GOVERNED_EFFECT_SURFACE_INVENTORY.json"

REQUIRED_IDS = {
    "prototype-r0-library", "gen3-cli", "gen3-library-relay", "gen3-moh-effect", "gen3-recovery",
    "gen3-launcher", "gen4-library-relay", "gen4-moh-staging", "gen4-moh-effect-port",
    "gen4-gep14-execution-delegation", "gen4-ahc-effect-port", "gen4-chm-history-port",
    "gen4-production-peer-adapter", "deployment-admin",
}
REQUIRED_PATHS = {
    "src/dger/relay.py", "scripts/dger.py", "src/dger/relay_v1.py", "src/dger/relay_moh_invoke.py",
    "src/dger/relay_moh.py", "launcher/dropbox-governed-execution-relay",
    "src/dger/gen4_contract.py", "src/dger/gen4_driver.py", "src/dger/gen4_effect.py",
    "src/dger/gen4_gep14_correlation.py", "src/dger/gen4_runtime_peers.py", "deployment/dger_god_adapter.py",
}


def fail(msg: str) -> None:
    raise SystemExit(f"EFFECT_SURFACE_INVENTORY_INVALID:{msg}")


def function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
    return out


def main() -> int:
    value = json.loads(INV.read_text("utf-8"))
    if value.get("schema") != "governed-effect-surface-inventory/v1" or value.get("tool_id") != "dropbox-governed-execution-relay":
        fail("HEADER")
    surfaces = value.get("surfaces")
    if not isinstance(surfaces, list): fail("SURFACES")
    ids = [x.get("id") for x in surfaces if isinstance(x, dict)]
    if len(ids) != len(set(ids)) or set(ids) != REQUIRED_IDS: fail("DECLARED_SET")
    paths = {x.get("path") for x in surfaces if isinstance(x, dict)}
    if not REQUIRED_PATHS <= paths: fail("REQUIRED_PATHS")
    for rel in REQUIRED_PATHS:
        if not (ROOT / rel).is_file(): fail(f"MISSING:{rel}")

    prototype = (ROOT / "src/dger/relay.py").read_text("utf-8")
    if "DGER_PROTOTYPE_R0_RETIRED" not in prototype or "subprocess.Popen" in prototype:
        fail("PROTOTYPE_NOT_RETIRED")
    runtime = (ROOT / "src/dger/relay_runtime.py").read_text("utf-8")
    if "assert_legacy_allowed(state_root)" not in runtime:
        fail("GEN3_ACTIVATION_GUARD_MISSING")
    guard = (ROOT / "src/dger/legacy_guard.py").read_text("utf-8")
    if "ACTIVATED.json" not in guard or "GEN3_SURFACE_RETIRED" not in guard:
        fail("LEGACY_RETIREMENT_PREDICATE_MISSING")

    gen4_path = ROOT / "src/dger/gen4_effect.py"
    gen4 = gen4_path.read_text("utf-8")
    gen4_functions = function_names(gen4_path)
    for fn in {"_stage", "_write_pre_ahc_wal", "_begin_ahc", "_status_before_execute", "_execute_moh", "_reconcile_moh", "_accept_ahc_terminal", "_publish_chm"}:
        if fn not in gen4_functions: fail(f"GEN4_FUNCTION_MISSING:{fn}")
    ordering_tokens = [
        'receipt.stage_kind != "LOCAL_MATERIALIZATION"',
        'state["phase"] = "PRE_AHC_EXECUTE_WAL"',
        'obs = self.peers.ahc_begin(c)',
        '_validate_ahc(obs, c, "begin_effect")',
        'obs = self.peers.moh_status(c)',
        '_validate_moh(obs, c, "status")',
        'state["moh_execute_call_may_have_happened"] = True',
        'obs = self.peers.moh_execute(c)',
        'self._handle_moh(state, obs, "execute")',
    ]
    for token in ordering_tokens:
        if token not in gen4: fail(f"GEN4_ORDERING_TOKEN_MISSING:{token}")
    for token in (
        '_validate_ack(ack, AHC_TOOL_ID, "note_moh_in_doubt")',
        '_validate_ack(ack, AHC_TOOL_ID, "accept_terminal_effect")',
        '_validate_ack(ack, CHM_TOOL_ID, "publish_terminal_result")',
        '"moh_invocation_evidence"',
        'state["moh_execute_response_invalid"] = True',
        'state["moh_in_doubt_source"] = "INVALID_EXECUTE_RESPONSE"',
        'state["moh_in_doubt_ever"] = True',
    ):
        if token not in gen4: fail(f"PROVIDER_OR_NOREPEAT_TOKEN_MISSING:{token}")

    contract = (ROOT / "src/dger/gen4_contract.py").read_text("utf-8")
    if "GEN4_PEER_CONTRACTS_UNAVAILABLE" not in contract: fail("PRODUCTION_FAIL_CLOSED_MISSING")
    if "chm_publish_terminal" not in contract or "ahc_accept_terminal" not in contract:
        fail("TERMINAL_PORTS_MISSING")
    for token in (
        "class InvocationEvidence", "provider_evidence", "tool_identity", "tool_tree", "gtg_identity",
        "registry_identity", "expected_operation", "GTG_INVOCATION_OPERATION_MISMATCH",
        "TRUSTED_CORRELATION_PROVIDER_SET_INVALID", 'stage_kind: str = "LOCAL_MATERIALIZATION"',
    ):
        if token not in contract: fail(f"PROVIDER_EVIDENCE_CONTRACT_TOKEN_MISSING:{token}")

    adapter_path = ROOT / "src/dger/gen4_runtime_peers.py"
    adapter = adapter_path.read_text("utf-8")
    adapter_functions = function_names(adapter_path)
    for fn in {
        "stage_moh", "ahc_begin", "ahc_status", "moh_execute", "moh_status",
        "ahc_note_in_doubt", "ahc_accept_terminal", "chm_publish_terminal",
    }:
        if fn not in adapter_functions: fail(f"RUNTIME_PEER_FUNCTION_MISSING:{fn}")
    for token in (
        "class UnavailableAuthenticatedPeerInvoker",
        'DgerGen4Error("GEN4_PROTECTED_GTG_RELAY_UNAVAILABLE")',
        'DgerGen4Error("DELEGATED_CONTEXT_OPERATION_NOT_AUTHORIZED")',
        'DgerGen4Error("DELEGATED_CONTEXT_CAPABILITY_NOT_AUTHORIZED")',
        "expected_operation=operation",
        'DgerGen4Error("MOH_WRAPPER_OK_MISMATCH")',
        'DgerGen4Error("MOH_STAGE_CONFLICT")',
        'DgerGen4Error("GEP_ADMISSION_MISMATCH")',
        "return Gep14CorrelationPeers(base, InvokerCorrelationReader(invoker))",
    ):
        if token not in adapter: fail(f"RUNTIME_PEER_GUARD_MISSING:{token}")

    staging = next((x for x in surfaces if x.get("id") == "gen4-moh-staging"), None)
    if not isinstance(staging, dict) or staging.get("class") != "GEN4_MOH_STAGING_PREPARATION":
        fail("STAGING_SURFACE_CLASS")
    if "LOCAL_MATERIALIZATION" not in str(staging.get("mechanical_guard", "")):
        fail("STAGING_SURFACE_GUARD")
    execution = next((x for x in surfaces if x.get("id") == "gen4-moh-effect-port"), None)
    if not isinstance(execution, dict) or "INVALID_EXECUTE_RESPONSE" not in str(execution.get("mechanical_guard", "")):
        fail("EXECUTE_INVALID_RESPONSE_GUARD")
    production = next((x for x in surfaces if x.get("id") == "gen4-production-peer-adapter"), None)
    if (
        not isinstance(production, dict)
        or production.get("path") != "src/dger/gen4_runtime_peers.py"
        or production.get("class") != "PRODUCTION_PEER_ADAPTER"
        or "FAIL_CLOSED" not in str(production.get("post_gen4_status", ""))
        or "EXECUTION_RELAY" not in str(production.get("mechanical_guard", ""))
    ):
        fail("PRODUCTION_PEER_SURFACE_INVALID")

    try:
        process_calls, semantic_calls = scan_execution_call_sites(ROOT)
    except (OSError, SyntaxError, ValueError) as exc:
        fail("EXECUTION_SURFACE_SCAN_FAILED:" + str(exc))
    if process_calls:
        rendered = ";".join(f"{p}:{q}:{t}:{n}" for p, q, t, n in process_calls)
        fail("DIRECT_PROCESS_START_FORBIDDEN:" + rendered)
    semantic_set = {(p, q, t) for p, q, t, _ in semantic_calls}
    unexpected = semantic_set - SEMANTIC_EXECUTE_ALLOWLIST
    missing = SEMANTIC_EXECUTE_ALLOWLIST - semantic_set
    if unexpected:
        fail("UNDECLARED_SEMANTIC_EXECUTION:" + ";".join(":".join(x) for x in sorted(unexpected)))
    if missing:
        fail("EXPECTED_SEMANTIC_EXECUTION_MISSING:" + ";".join(":".join(x) for x in sorted(missing)))
    declared_exec_paths = {
        x["path"] for x in surfaces
        if x["class"] in {"LEGACY_MOH_EXECUTION_EFFECT", "GEN4_MOH_EXECUTION_EFFECT", "PRODUCTION_PEER_ADAPTER"}
    }
    expected_declared = {p for p, _, _ in SEMANTIC_EXECUTE_ALLOWLIST}
    if not expected_declared <= declared_exec_paths:
        fail("EXECUTION_PRIMITIVE_NOT_INVENTORIED")

    print(json.dumps({
        "ok": True,
        "schema": value["schema"],
        "surface_count": len(surfaces),
        "process_start_call_sites": process_calls,
        "semantic_execution_call_sites": semantic_calls,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
