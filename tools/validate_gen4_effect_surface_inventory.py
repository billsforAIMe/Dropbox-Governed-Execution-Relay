from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "GOVERNED_EFFECT_SURFACE_INVENTORY.json"

REQUIRED_IDS = {
    "prototype-r0-library", "gen3-cli", "gen3-library-relay", "gen3-moh-effect", "gen3-recovery",
    "gen3-launcher", "gen4-library-relay", "gen4-moh-staging", "gen4-moh-effect-port", "gen4-ahc-effect-port",
    "gen4-chm-history-port", "gen4-production-peer-adapter", "deployment-admin",
}
REQUIRED_PATHS = {
    "src/dger/relay.py", "scripts/dger.py", "src/dger/relay_v1.py", "src/dger/relay_moh_invoke.py",
    "src/dger/relay_moh.py", "launcher/dropbox-governed-execution-relay", "src/dger/gen4.py",
    "src/dger/gen4_contract.py", "src/dger/gen4_driver.py", "src/dger/gen4_effect.py",
    "deployment/dger_god_adapter.py",
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
    ):
        if token not in gen4: fail(f"PROVIDER_EVIDENCE_EFFECT_TOKEN_MISSING:{token}")

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

    staging = next((x for x in surfaces if x.get("id") == "gen4-moh-staging"), None)
    if not isinstance(staging, dict) or staging.get("class") != "GEN4_MOH_STAGING_PREPARATION":
        fail("STAGING_SURFACE_CLASS")
    if "LOCAL_MATERIALIZATION" not in str(staging.get("mechanical_guard", "")):
        fail("STAGING_SURFACE_GUARD")

    # Mechanically enumerate process-start/semantic execute primitives in DGER Python.
    findings: list[str] = []
    for path in sorted((ROOT / "src/dger").glob("*.py")):
        text = path.read_text("utf-8")
        if "subprocess.Popen" in text or '"execute"' in text or ".moh_execute(" in text:
            findings.append(path.relative_to(ROOT).as_posix())
    allowed = {"src/dger/relay_moh_invoke.py", "src/dger/gen4_effect.py"}
    unexpected = set(findings) - allowed
    if unexpected: fail("UNDECLARED_EXECUTION_PRIMITIVE:" + ",".join(sorted(unexpected)))
    declared_exec_paths = {x["path"] for x in surfaces if x["class"] in {"LEGACY_MOH_EXECUTION_EFFECT", "GEN4_MOH_EXECUTION_EFFECT"}}
    if not allowed <= declared_exec_paths: fail("EXECUTION_PRIMITIVE_NOT_INVENTORIED")

    print(json.dumps({"ok": True, "schema": value["schema"], "surface_count": len(surfaces), "execution_primitive_paths": sorted(findings)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
