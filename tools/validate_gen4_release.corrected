from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = "42543696c544d3bc287e65da78d07751db310e58"


def fail(code: str) -> None:
    raise SystemExit(f"DGER_GEN4_RELEASE_INVALID:{code}")


def main() -> int:
    release = json.loads((ROOT / "GOVERNED_RELEASE.json").read_text("utf-8"))
    if release.get("manifest_schema_major") != 1: fail("MANIFEST_SCHEMA")
    if release.get("authority_id") != "dropbox-governed-execution-relay" or release.get("tool_id") != "dropbox-governed-execution-relay": fail("TOOL_ID")
    if release.get("release_generation") != 4 or release.get("supersedes_generation") != 3: fail("GENERATION")
    if release.get("rolls_back_to_generation") is not None or release.get("withdrawn_generations") != []: fail("RELEASE_LINEAGE")
    selector = release.get("release_selector_contract")
    if not isinstance(selector, dict) or selector.get("selector") != "refs/heads/main" or selector.get("release_only") is not True or selector.get("ancestry_preserving_forward_cas") is not True or selector.get("delivered_objects_remain_reachable") is not True:
        fail("SELECTOR_CONTRACT")
    normative = release.get("normative_files")
    expected_normative = ["docs/PROTOCOL_V2.md", "GOVERNED_EFFECT_SURFACE_INVENTORY.json"]
    if normative != expected_normative or any(not (ROOT / rel).is_file() for rel in expected_normative): fail("NORMATIVE_COMPOSITION")
    runtime = release.get("runtime_compatibility")
    if not isinstance(runtime, dict) or runtime.get("policy") != "exact_or_explicit_immutable_tool_release_declaration" or runtime.get("compatible_runtime_commits") != [PREDECESSOR]:
        fail("PREACTIVATION_RUNTIME")
    note = runtime.get("note")
    if not isinstance(note, str) or "pre-activation" not in note or "separate governed act" not in note: fail("RUNTIME_NOTE")
    compatibility = release.get("governance_compatibility")
    if not isinstance(compatibility, dict) or compatibility.get("authority_id") != "software-governance": fail("SG_COMPATIBILITY")
    if compatibility.get("governance_contract_major_allowed") != [2] or compatibility.get("manifest_schema_major_allowed") != [1]: fail("SG_SCHEMA_COMPATIBILITY")
    generation = compatibility.get("release_generation")
    if not isinstance(generation, dict) or generation.get("min") != 11 or generation.get("max") is not None: fail("SG_GENERATION_COMPATIBILITY")

    protocol = (ROOT / "docs/PROTOCOL_V2.md").read_text("utf-8")
    profile = (ROOT / "PROJECT_GOVERNANCE_PROFILE.md").read_text("utf-8")
    binding = (ROOT / "GOVERNANCE_BINDING.md").read_text("utf-8")
    readme = (ROOT / "README.md").read_text("utf-8")
    for token in ("GEN4_PEER_CONTRACTS_UNAVAILABLE", "invocation-time", "PRE_AHC_EXECUTE_WAL", "ACTIVATED.json"):
        if token not in protocol: fail(f"PROTOCOL_TOKEN:{token}")
    for token in ("Generation 4", "EXECUTION_RELAY", "UnavailableGen4Peers", "Generation-3 runtime to remain installed"):
        if token not in profile: fail(f"PROFILE_TOKEN:{token}")
    for token in ("Generation 4", "Pre-activation", "Gen4 activation"):
        if token not in binding: fail(f"BINDING_TOKEN:{token}")
    if not readme.startswith("# Dropbox Governed Execution Relay — Generation 4 source release") or "Prototype R0" not in readme or "permanently retired" not in readme:
        fail("README_GENERATION")

    print(json.dumps({
        "ok": True,
        "schema": "dger-gen4-release-validation/v1",
        "release_generation": 4,
        "preactivation_runtime_commit": PREDECESSOR,
        "normative_files": expected_normative,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
