from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

DGER_REPO = "billsforAIMe/Dropbox-Governed-Execution-Relay"
DGER_REPO_ID = "1351496555"
DGER_COMMIT = "73f736d8ad4c1f11bb8ee51ff7497c74c2f41622"
DGER_TREE = "bebbc449d3c1319e2876774eec8dfef05b174ad9"
GTG_REPO = "billsforAIMe/Governed-Tool-Gateway"
GTG_COMMIT = "9333e6a94ef434386b28c4e77bff63fad27e4b5d"
REGISTRY_REPO = "billsforAIMe/Tool-Registry"
GTG_URL = "http://127.0.0.1:8799/mcp"
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


def run(args: list[str], *, env: dict[str, str] | None = None,
        timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        args,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
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


def tools_bearer_token() -> str:
    security = find_executable(["/usr/bin/security"])
    cp = run([
        security,
        "find-generic-password",
        "-a", "Tools",
        "-s", "governed-tool-gateway:Tools",
        "-w",
    ], timeout=30, check=False)
    token = cp.stdout.rstrip("\n") if cp.returncode == 0 else ""
    require(len(token) >= 32 and "\n" not in token and "\r" not in token,
            "GTG_TOOLS_BEARER_UNAVAILABLE")
    return token


def gtg_call(token: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    request = {
        "jsonrpc": "2.0",
        "id": "dger-gen4-registry-reconcile",
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    raw = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        GTG_URL,
        data=raw,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call",
            "Mcp-Name": name,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[-1800:]
        raise RuntimeError(f"GTG_HTTP_ERROR:{exc.code}:{detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"GTG_REQUEST_FAILED:{type(exc).__name__}:{exc}") from exc
    require(isinstance(payload, dict) and payload.get("error") is None, "GTG_RPC_ERROR")
    rpc_result = payload.get("result")
    require(isinstance(rpc_result, dict), "GTG_RPC_RESULT_MISSING")
    structured = rpc_result.get("structuredContent")
    require(isinstance(structured, dict), "GTG_STRUCTURED_RESULT_MISSING")
    return structured


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
    require(len(found) == 1 and found[0]["tool_current_identity"] == DGER_COMMIT,
            "SELFTEST_RESULT_DISCOVERY")
    print("DGER_GEN4_REGISTRY_RECONCILE_SELFTEST=PASS")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    require(not sys.argv[1:], "UNEXPECTED_ARGUMENTS")

    gh = find_executable(["/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh"])
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

    token = tools_bearer_token()
    env_path = str(GITSTORAGE_RUNTIME.parent) + os.pathsep + os.environ.get("PATH", os.defpath)
    os.environ["PATH"] = env_path

    structured = gtg_call(
        token,
        "invoke_tool",
        {
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
    )
    require(structured.get("ok") is True,
            "GTG_REGISTRY_INVOCATION_FAILED:" + json.dumps(structured, sort_keys=True)[:1800])

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
