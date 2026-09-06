from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping

DGER_REPO = "billsforAIMe/Dropbox-Governed-Execution-Relay"
DGER_REPO_ID = "1351496555"
DGER_COMMIT = "73f736d8ad4c1f11bb8ee51ff7497c74c2f41622"
DGER_TREE = "bebbc449d3c1319e2876774eec8dfef05b174ad9"
REGISTRY_REPO = "billsforAIMe/Tool-Registry"
REGISTRY_REMOTE = "https://github.com/billsforAIMe/Tool-Registry.git"
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
        timeout: int = 900, check: bool = True) -> subprocess.CompletedProcess[str]:
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
        raise RuntimeError(f"COMMAND_FAILED:{Path(args[0]).name}:{cp.returncode}:{cp.stderr[-2400:]}")
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


def gh_token(gh: str) -> str:
    clean = dict(os.environ)
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "TOOL_REGISTRY_GITHUB_TOKEN",
                "TOOL_REGISTRY_GTG_HTTP_URL", "TOOL_REGISTRY_GTG_BEARER_TOKEN"):
        clean.pop(key, None)
    cp = run([gh, "auth", "token", "--hostname", "github.com"], env=clean, timeout=30, check=False)
    token = cp.stdout.strip() if cp.returncode == 0 else ""
    require(len(token) >= 20 and "\n" not in token and "\r" not in token,
            "GITHUB_PROVIDER_CREDENTIAL_UNAVAILABLE")
    return token


def git_authenticated_env(token: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "TOOL_REGISTRY_GTG_HTTP_URL", "TOOL_REGISTRY_GTG_BEARER_TOKEN"):
        env.pop(key, None)
    env["TOOL_REGISTRY_GITHUB_TOKEN"] = token
    basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
    env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {basic}"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["PATH"] = str(GITSTORAGE_RUNTIME.parent) + os.pathsep + "/usr/bin:/bin"
    return env


def gitstorage(gs: str, args: list[str], env: dict[str, str]) -> dict[str, Any]:
    cp = run([gs, *args], env=env, timeout=600, check=False)
    try:
        payload = json.loads(cp.stdout)
    except Exception as exc:
        raise RuntimeError(f"GITSTORAGE_NON_JSON:{args[0]}:{cp.stderr[-1600:]}") from exc
    require(cp.returncode == 0 and isinstance(payload, dict) and payload.get("ok") is True,
            "GITSTORAGE_FAILED:" + args[0] + ":" + json.dumps(payload, sort_keys=True)[:1800])
    return payload


def result_oid(payload: Mapping[str, Any]) -> str:
    result = payload.get("result")
    require(isinstance(result, dict), "GITSTORAGE_RESULT_NOT_OBJECT")
    oid = result.get("oid")
    require(isinstance(oid, str) and len(oid) in {40, 64}, "GITSTORAGE_RESULT_OID_MISSING")
    return oid


def self_test() -> None:
    require(DGER_COMMIT != DGER_TREE, "SELFTEST_IDENTITY_DISTINCT")
    sample = {"ok": True, "result": {"oid": "a" * 40}}
    require(result_oid(sample) == "a" * 40, "SELFTEST_GITSTORAGE_RESULT")
    basic = base64.b64encode(b"x-access-token:secret").decode("ascii")
    require(base64.b64decode(basic).decode("ascii") == "x-access-token:secret", "SELFTEST_AUTH_ENCODING")
    print("DGER_GEN4_REGISTRY_EXACT_MATERIALIZATION_SELFTEST=PASS")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    require(not sys.argv[1:], "UNEXPECTED_ARGUMENTS")

    gh = find_executable(["/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh"])
    gs = physical_executable(GITSTORAGE_RUNTIME)
    require(gs is not None, "GITSTORAGE_REGISTERED_RUNTIME_UNAVAILABLE_OR_UNSAFE")
    require(hashlib.sha256(Path(gs).read_bytes()).hexdigest() == GITSTORAGE_SHA256,
            "GITSTORAGE_REGISTERED_RUNTIME_SHA256_MISMATCH")

    require(gh_ref(gh, DGER_REPO) == DGER_COMMIT, "DGER_MAIN_NOT_EXACT_DELIVERED_GEN4")
    dger_commit = gh_json(gh, f"repos/{DGER_REPO}/git/commits/{DGER_COMMIT}")
    require(isinstance(dger_commit, dict) and isinstance(dger_commit.get("tree"), dict)
            and dger_commit["tree"].get("sha") == DGER_TREE, "DGER_DELIVERED_TREE_MISMATCH")
    registry_before = gh_ref(gh, REGISTRY_REPO)
    print(f"registry_before={registry_before}")
    print("dger_delivery_identity=PASS")

    token = gh_token(gh)
    child_env = git_authenticated_env(token)
    request = {
        "operation": "reconcile_tool",
        "arguments": {
            "tool_id": "dropbox-governed-execution-relay",
            "repository_id": DGER_REPO_ID,
            "selector": "refs/heads/main",
            "delivered_commit": DGER_COMMIT,
            "delivered_tree": DGER_TREE,
        },
    }

    with tempfile.TemporaryDirectory(prefix="dger-gen4-registry-exact-") as td:
        registry_root = Path(td) / "Tool-Registry"
        gitstorage(gs, ["clone", "--remote", REGISTRY_REMOTE, "--destination", str(registry_root)], child_env)
        head = result_oid(gitstorage(gs, ["resolve-ref", "--repo", str(registry_root), "--ref", "HEAD"], child_env))
        require(head == registry_before, f"REGISTRY_MATERIALIZATION_STALE:{head}:{registry_before}")
        service = registry_root / "tools/reconciliation_service_v3.py"
        require(service.is_file() and not service.is_symlink(), "REGISTRY_SERVICE_MISSING_FROM_EXACT_MATERIALIZATION")
        print("registry_exact_materialization=PASS")

        cp = run(
            [sys.executable, str(service)],
            env=child_env,
            input_text=json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n",
            timeout=1200,
            check=False,
        )
        require(cp.returncode == 0, f"REGISTRY_SERVICE_EXIT:{cp.returncode}:{cp.stderr[-2400:]}")
        lines = [line for line in cp.stdout.splitlines() if line.strip()]
        require(len(lines) == 1, f"REGISTRY_SERVICE_RESPONSE_COUNT:{len(lines)}:{cp.stderr[-1200:]}")
        result = json.loads(lines[0])

    require(isinstance(result, dict), "REGISTRY_RESULT_NOT_OBJECT")
    require(result.get("status") != "BLOCKED",
            "REGISTRY_RECONCILIATION_BLOCKED:" + json.dumps(result, sort_keys=True)[:2400])
    require(result.get("disposition") in {"RECONCILED", "ALREADY_CURRENT"},
            "REGISTRY_RECONCILIATION_NOT_TERMINAL_SUCCESS:" + json.dumps(result, sort_keys=True)[:2400])
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
    print("DGER_GEN4_REGISTRY_EXACT_MATERIALIZATION=PASS")


if __name__ == "__main__":
    main()
