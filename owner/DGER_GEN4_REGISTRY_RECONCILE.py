from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any

DGER_REPO = "billsforAIMe/Dropbox-Governed-Execution-Relay"
DGER_REPO_ID = "1351496555"
DGER_COMMIT = "73f736d8ad4c1f11bb8ee51ff7497c74c2f41622"
DGER_TREE = "bebbc449d3c1319e2876774eec8dfef05b174ad9"
GTG_REPO = "billsforAIMe/Governed-Tool-Gateway"
GTG_COMMIT = "9333e6a94ef434386b28c4e77bff63fad27e4b5d"
REGISTRY_REPO = "billsforAIMe/Tool-Registry"
BOOTSTRAP = Path("/Users/brettmacpro/ChatGPT/State/Tools/Governed Tool Gateway/RUNTIME/bootstrap.json")
INVOCATIONS = Path("/Users/brettmacpro/ChatGPT/State/Tools/Governed Tool Gateway/INVOCATIONS")
GITSTORAGE_RUNTIME = Path("/Users/brettmacpro/ChatGPT/Installed/Tools/GitStorage/gitstorage")
GITSTORAGE_SHA256 = "1059071d24ffd90502b80197702ce38a1d14b855dcb42c597c99a073cffbe587"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def physical_executable(path: Path) -> str | None:
    try:
        resolved = path.resolve(strict=True)
        st = resolved.stat()
    except (FileNotFoundError, OSError, RuntimeError):
        return None
    if not stat.S_ISREG(st.st_mode) or not os.access(resolved, os.X_OK):
        return None
    return str(resolved)


def find_executable(candidates: list[str]) -> str:
    for raw in candidates:
        found = physical_executable(Path(raw))
        if found is not None:
            return found
    raise RuntimeError("EXECUTABLE_NOT_FOUND:" + ",".join(candidates))


def run(args: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None,
        timeout: int = 600, check: bool = True) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "args": args,
        "env": env,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": timeout,
        "check": False,
    }
    if input_text is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = input_text
    cp = subprocess.run(**kwargs)
    if check and cp.returncode != 0:
        raise RuntimeError(f"COMMAND_FAILED:{Path(args[0]).name}:{cp.returncode}:{cp.stderr[-1800:]}")
    return cp


def gh_json(gh: str, path: str) -> Any:
    cp = run([gh, "api", path], timeout=90)
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GH_NON_JSON:{path}") from exc


def gh_ref(gh: str, repo: str) -> str:
    obj = gh_json(gh, f"repos/{repo}/git/ref/heads/main")
    require(isinstance(obj, dict), f"GH_REF_NOT_OBJECT:{repo}")
    node = obj.get("object")
    require(isinstance(node, dict) and isinstance(node.get("sha"), str), f"GH_REF_SHA_MISSING:{repo}")
    return node["sha"]


def find_registry_results(value: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if value.get("schema") == "tool-registry-reconcile-result/v1":
            out.append(value)
        for child in value.values():
            find_registry_results(child, out)
    elif isinstance(value, list):
        for child in value:
            find_registry_results(child, out)


def load_tools_binding() -> str:
    require(BOOTSTRAP.is_file() and not BOOTSTRAP.is_symlink(), "GTG_BOOTSTRAP_UNAVAILABLE_OR_UNSAFE")
    obj = json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
    require(isinstance(obj, dict), "GTG_BOOTSTRAP_NOT_OBJECT")
    bindings = obj.get("transport_bindings")
    require(isinstance(bindings, dict), "GTG_TRANSPORT_BINDINGS_MISSING")
    matches = [key for key, project in bindings.items() if isinstance(key, str) and key and project == "Tools"]
    require(len(matches) == 1, f"GTG_TOOLS_BINDING_NOT_UNIQUE:{len(matches)}")
    return matches[0]


def self_test() -> None:
    sample = {
        "result": {
            "structuredContent": {
                "ok": True,
                "result": {
                    "schema": "tool-registry-reconcile-result/v1",
                    "disposition": "RECONCILED",
                    "tool_current_identity": DGER_COMMIT,
                    "registry_current_identity": "a" * 40,
                    "authoritative_identity": {"commit": DGER_COMMIT, "tree": DGER_TREE},
                    "semantic_access_class": "SUBSTRATE",
                    "authority_effect": "REGISTRY_ONLY",
                    "changed": True,
                },
            }
        }
    }
    found: list[dict[str, Any]] = []
    find_registry_results(sample, found)
    require(len(found) == 1 and found[0]["tool_current_identity"] == DGER_COMMIT, "SELFTEST_RESULT_DISCOVERY")
    print("DGER_GEN4_REGISTRY_RECONCILE_SELFTEST=PASS")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    require(not sys.argv[1:], "UNEXPECTED_ARGUMENTS")

    gh = find_executable(["/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh"])
    gtg = find_executable(["/usr/local/bin/gtg-mcp", "/opt/homebrew/bin/gtg-mcp"])
    gtg_self = find_executable(["/usr/local/bin/gtg-self-test", "/opt/homebrew/bin/gtg-self-test"])
    gs = physical_executable(GITSTORAGE_RUNTIME)
    require(gs is not None, "GITSTORAGE_REGISTERED_RUNTIME_MISSING_OR_UNSAFE")
    require(hashlib.sha256(Path(gs).read_bytes()).hexdigest() == GITSTORAGE_SHA256,
            "GITSTORAGE_REGISTERED_RUNTIME_SHA256_MISMATCH")

    require(gh_ref(gh, DGER_REPO) == DGER_COMMIT, "DGER_MAIN_NOT_EXACT_DELIVERED_GEN4")
    require(gh_ref(gh, GTG_REPO) == GTG_COMMIT, "GTG_MAIN_MOVED_FROM_INSTALLED_GEN28")
    dger_commit = gh_json(gh, f"repos/{DGER_REPO}/git/commits/{DGER_COMMIT}")
    require(isinstance(dger_commit, dict) and isinstance(dger_commit.get("tree"), dict)
            and dger_commit["tree"].get("sha") == DGER_TREE, "DGER_DELIVERED_TREE_MISMATCH")
    registry_before = gh_ref(gh, REGISTRY_REPO)
    print(f"registry_before={registry_before}")
    print("dger_delivery_identity=PASS")

    portability = run([gtg_self], timeout=60)
    pobj = json.loads(portability.stdout)
    require(isinstance(pobj, dict) and pobj.get("status") == "PASS", "GTG_SELF_TEST_FAILED")
    print("gtg_self_test=PASS")

    binding = load_tools_binding()
    env = os.environ.copy()
    env["PATH"] = str(GITSTORAGE_RUNTIME.parent) + os.pathsep + env.get("PATH", os.defpath)
    request = {
        "jsonrpc": "2.0",
        "id": "dger-gen4-registry-reconcile",
        "method": "tools/call",
        "params": {
            "name": "invoke_tool",
            "arguments": {
                "tool_id": "tool-registry",
                "operation": "reconcile_tool",
                "arguments": {
                    "tool_id": "dropbox-governed-execution-relay",
                    "repository_id": DGER_REPO_ID,
                    "selector": "refs/heads/main",
                    "delivered_commit": DGER_COMMIT,
                    "delivered_tree": DGER_TREE,
                },
            },
        },
    }
    cp = run([
        gtg,
        "--bootstrap", str(BOOTSTRAP),
        "--invocation-state-root", str(INVOCATIONS),
        "--stdio",
        "--binding", binding,
    ], env=env, input_text=json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n", timeout=900, check=False)
    require(cp.returncode == 0, f"GTG_STDIO_EXIT:{cp.returncode}:{cp.stderr[-1800:]}")
    lines = [line for line in cp.stdout.splitlines() if line.strip()]
    require(len(lines) == 1, f"GTG_STDIO_RESPONSE_COUNT:{len(lines)}")
    response = json.loads(lines[0])
    require(isinstance(response, dict) and response.get("error") is None, "GTG_RPC_ERROR")
    rpc_result = response.get("result")
    require(isinstance(rpc_result, dict), "GTG_RPC_RESULT_MISSING")
    structured = rpc_result.get("structuredContent")
    require(isinstance(structured, dict), "GTG_STRUCTURED_RESULT_MISSING")
    require(structured.get("ok") is True, "GTG_REGISTRY_INVOCATION_FAILED:" + json.dumps(structured, sort_keys=True)[:1800])

    results: list[dict[str, Any]] = []
    find_registry_results(structured, results)
    require(len(results) == 1, f"REGISTRY_RESULT_COUNT:{len(results)}")
    result = results[0]
    require(result.get("disposition") in {"RECONCILED", "ALREADY_CURRENT"},
            "REGISTRY_RECONCILIATION_NOT_TERMINAL_SUCCESS:" + json.dumps(result, sort_keys=True)[:1800])
    require(result.get("tool_current_identity") == DGER_COMMIT, "REGISTRY_TOOL_IDENTITY_MISMATCH")
    authority = result.get("authoritative_identity")
    require(isinstance(authority, dict) and authority.get("commit") == DGER_COMMIT
            and authority.get("tree") == DGER_TREE, "REGISTRY_AUTHORITATIVE_IDENTITY_MISMATCH")
    require(result.get("semantic_access_class") == "SUBSTRATE", "REGISTRY_SEMANTIC_CLASS_CHANGED")
    require(result.get("authority_effect") == "REGISTRY_ONLY", "REGISTRY_AUTHORITY_EFFECT_UNEXPECTED")
    registry_after = gh_ref(gh, REGISTRY_REPO)
    require(result.get("registry_current_identity") == registry_after, "REGISTRY_POSTREAD_MISMATCH")
    require(gh_ref(gh, DGER_REPO) == DGER_COMMIT, "DGER_MAIN_MOVED_DURING_REGISTRY_RECONCILE")

    safe = {
        "disposition": result.get("disposition"),
        "changed": result.get("changed"),
        "registry_before": registry_before,
        "registry_after": registry_after,
        "tool_current_identity": result.get("tool_current_identity"),
        "semantic_access_class": result.get("semantic_access_class"),
        "path_state": result.get("path_state"),
        "registry_publisher_backend": result.get("registry_publisher_backend"),
        "registry_publisher_fallback_reason": result.get("registry_publisher_fallback_reason"),
    }
    print("registry_reconcile_result=" + json.dumps(safe, sort_keys=True, separators=(",", ":")))
    print("DGER_GEN4_REGISTRY_RECONCILE=PASS")


if __name__ == "__main__":
    main()
