#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
import time

GOD_CONSUMER_ADAPTER_CONTRACT = "consumer-hardening/v1"
GOD_TERMINATION_SAFETY_CONTRACT = "incarnation-bound-or-fail-closed/v1"

HOME = Path("/Users/brettmacpro")
UID = 501
LABEL = "com.brettmacpro.chatgpt.dropbox-governed-execution-relay"
RUNTIME_ID = f"launchd:{LABEL}"
STATE = HOME / "ChatGPT/State/Tools/Dropbox Governed Execution Relay"
RUNTIME_ROOT = STATE / "runtime/current"
LIVE_PLIST = HOME / "Library/LaunchAgents" / f"{LABEL}.plist"
CANDIDATE_PLIST = RUNTIME_ROOT / "launchagent" / f"{LABEL}.plist"
CANDIDATE_LAUNCHER = RUNTIME_ROOT / "launcher/dropbox-governed-execution-relay"
OLD_LAUNCHER = Path("/usr/local/bin/dropbox-governed-execution-relay")
DELIVERED_IDENTITY = STATE / "delivered-identity.json"
RUNTIME_BINDING = STATE / "runtime-binding.json"
TOKEN_FILE = STATE / "credentials/gtg-tools.token"
MOH_HOME = HOME / "ChatGPT/State/Tools/Mac Operation Host"
GTG_ENDPOINT = "http://127.0.0.1:8799/mcp"
GTG_HOST = "127.0.0.1"
GTG_PORT = 8799
KEYCHAIN_ACCOUNT = "Tools"
KEYCHAIN_SERVICE = "governed-tool-gateway:Tools"
MAX_SNAPSHOT_BYTES = 128 * 1024
REQUIRED_DISCOVERY_SCOPES = [
    "launchd-nonstandard", "launchd-system", "launchd-user",
    "ownership-cwd", "ownership-executable", "ownership-symlink", "ownership-argv",
    "processes", "writers",
]
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _safe_env() -> dict[str, str]:
    return {
        "HOME": str(HOME),
        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def _run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_safe_env(),
        timeout=timeout,
        check=False,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plain_file(path: Path) -> bool:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(st.st_mode) and not path.is_symlink()


def _plain_dir(path: Path) -> bool:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(st.st_mode) and not path.is_symlink()


def _require_safe_parent_chain(path: Path) -> None:
    current = path.parent
    while True:
        if current.exists():
            st = current.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                raise RuntimeError(f"unsafe path component: {current}")
        if current == current.parent:
            break
        current = current.parent


def _atomic(path: Path, data: bytes, mode: int) -> None:
    _require_safe_parent_chain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _require_safe_parent_chain(path)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise RuntimeError(f"unsafe destination: {path}")
    tmp = path.with_name(f".{path.name}.dger-god-{os.getpid()}.tmp")
    if tmp.exists() or tmp.is_symlink():
        raise RuntimeError(f"temporary collision: {tmp}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _json_atomic(path: Path, value: object, mode: int = 0o600) -> None:
    _atomic(path, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8"), mode)


def _snapshot(path: Path) -> dict[str, object]:
    if not path.exists() and not path.is_symlink():
        return {"status": "MISSING"}
    if not _plain_file(path):
        raise RuntimeError(f"snapshot target unsafe: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise RuntimeError(f"snapshot target too large: {path}")
    return {
        "status": "PRESENT",
        "mode": stat.S_IMODE(path.stat().st_mode),
        "sha256": _sha256(raw),
        "base64": base64.b64encode(raw).decode("ascii"),
    }


def _restore(path: Path, snapshot: dict[str, object]) -> None:
    status_value = snapshot.get("status")
    if status_value == "MISSING":
        if path.exists() or path.is_symlink():
            if not _plain_file(path):
                raise RuntimeError(f"rollback target unsafe: {path}")
            path.unlink()
        return
    if status_value != "PRESENT":
        raise RuntimeError("invalid rollback snapshot status")
    encoded = snapshot.get("base64")
    expected_sha = snapshot.get("sha256")
    mode = snapshot.get("mode")
    if not isinstance(encoded, str) or not isinstance(expected_sha, str) or not isinstance(mode, int):
        raise RuntimeError("invalid rollback snapshot")
    raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    if len(raw) > MAX_SNAPSHOT_BYTES or _sha256(raw) != expected_sha:
        raise RuntimeError("rollback snapshot integrity mismatch")
    _atomic(path, raw, mode)


def _state_path(context_path: Path) -> Path:
    return context_path.with_name("dger_adapter_state.json")


def _load_context(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid GOD adapter context path")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid GOD adapter context")
    if value.get("project_id") != "dropbox-governed-execution-relay":
        raise ValueError("unexpected GOD project_id")
    if value.get("deployment_root") != str(STATE) or value.get("state_root") != str(STATE):
        raise ValueError("unexpected GOD DGER roots")
    commit = value.get("approved_commit")
    tree = value.get("approved_tree")
    if not isinstance(commit, str) or HEX40.fullmatch(commit) is None:
        raise ValueError("invalid approved commit")
    if not isinstance(tree, str) or HEX40.fullmatch(tree) is None:
        raise ValueError("invalid approved tree")
    return value


def _write_adapter_state(path: Path, value: dict) -> None:
    _json_atomic(path, value, 0o600)


def _load_adapter_state(path: Path, run_id: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("adapter state missing")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("run_id") != run_id:
        raise ValueError("adapter state run mismatch")
    return value


def _plist_identity(path: Path) -> tuple[bool, list[str]]:
    if not path.exists() and not path.is_symlink():
        return False, []
    if not _plain_file(path):
        return False, [f"unsafe launchd plist: {path}"]
    try:
        value = plistlib.loads(path.read_bytes())
    except Exception:
        return False, [f"unparseable launchd plist: {path}"]
    if not isinstance(value, dict) or value.get("Label") != LABEL:
        return False, [f"unexpected launchd label: {path}"]
    argv = value.get("ProgramArguments")
    if argv not in ([str(CANDIDATE_LAUNCHER)], [str(OLD_LAUNCHER)]):
        return False, [f"unexpected DGER launchd argv: {path}"]
    return True, []


def _launchd_loaded(domain: str) -> tuple[bool, str]:
    cp = _run(["/bin/launchctl", "print", f"{domain}/{LABEL}"])
    if cp.returncode == 0:
        return True, cp.stdout
    return False, cp.stderr


def _process_rows() -> tuple[list[tuple[int, int, str]], list[str]]:
    cp = _run(["/bin/ps", "-axo", "pid=,uid=,command="], timeout=20)
    if cp.returncode != 0:
        return [], ["process inventory unavailable"]
    rows: list[tuple[int, int, str]] = []
    errors: list[str] = []
    markers = ("dropbox-governed-execution-relay", str(STATE / "runtime/"))
    accepted_script = re.compile(re.escape(str(STATE / "runtime/")) + r"(?:current|[0-9a-f]{40})/scripts/dger\.py(?:\s|$)")
    for line in cp.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0]); uid = int(parts[1])
        except ValueError:
            continue
        command = parts[2]
        if not any(marker in command for marker in markers):
            continue
        accepted = accepted_script.search(command) is not None or command == str(OLD_LAUNCHER) or str(CANDIDATE_LAUNCHER) in command
        if uid != UID or not accepted:
            errors.append(f"ambiguous DGER-like process pid={pid}")
            continue
        rows.append((pid, uid, command))
    return rows, errors


def _observe_cwd(pids: list[int]) -> list[str]:
    errors: list[str] = []
    lsof = Path("/usr/sbin/lsof")
    if not _plain_file(lsof) or not os.access(lsof, os.X_OK):
        return ["lsof unavailable for ownership-cwd discovery"] if pids else []
    for pid in pids:
        cp = _run([str(lsof), "-a", "-p", str(pid), "-d", "cwd", "-Fn"], timeout=10)
        if cp.returncode != 0 or not any(line.startswith("n/") for line in cp.stdout.splitlines()):
            errors.append(f"cwd observation unavailable pid={pid}")
    return errors


def project_discover(context: dict) -> dict:
    errors: list[str] = []
    ambiguities: list[str] = []
    if os.geteuid() != UID or Path.home() != HOME:
        errors.append("DGER adapter must run as brettmacpro uid 501")
    plist_owned, plist_errors = _plist_identity(LIVE_PLIST)
    ambiguities.extend(plist_errors)
    gui_loaded, _ = _launchd_loaded(f"gui/{UID}")
    system_loaded, _ = _launchd_loaded("system")
    user_loaded, _ = _launchd_loaded(f"user/{UID}")
    if system_loaded or user_loaded:
        ambiguities.append("DGER launchd label present outside governed gui domain")
    rows, process_errors = _process_rows()
    ambiguities.extend(process_errors)
    pids = [pid for pid, _uid, _cmd in rows]
    ambiguities.extend(_observe_cwd(pids))
    if rows and not gui_loaded:
        ambiguities.append("DGER process exists without governed launchd service")
    discovered = [RUNTIME_ID] if (plist_owned or gui_loaded or rows) else []
    active = [RUNTIME_ID] if (gui_loaded or rows) else []
    return {
        "discovery_complete": not errors and not ambiguities,
        "discovery_scopes": list(REQUIRED_DISCOVERY_SCOPES),
        "discovered_runtime_ids": discovered,
        "discovered_writer_ids": [],
        "active_runtime_ids": active,
        "active_writer_ids": [],
        "ambiguities": ambiguities,
        "errors": errors,
    }


def _stop_service() -> None:
    loaded, _ = _launchd_loaded(f"gui/{UID}")
    if loaded:
        cp = _run(["/bin/launchctl", "bootout", f"gui/{UID}/{LABEL}"], timeout=30)
        if cp.returncode != 0:
            raise RuntimeError("launchd bootout failed")
    deadline = time.time() + 15
    while time.time() < deadline:
        loaded, _ = _launchd_loaded(f"gui/{UID}")
        rows, row_errors = _process_rows()
        if row_errors:
            raise RuntimeError("ambiguous DGER process during quiesce")
        if not loaded and not rows:
            return
        time.sleep(0.2)
    raise RuntimeError("DGER launchd service did not quiesce")


def _keychain_token() -> str:
    cp = _run(["/usr/bin/security", "find-generic-password", "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE, "-w"], timeout=15)
    if cp.returncode != 0:
        raise RuntimeError("GTG Tools keychain credential unavailable")
    token = cp.stdout.rstrip("\n")
    if len(token) < 32 or len(token.encode("utf-8")) > 4096:
        raise RuntimeError("GTG Tools credential invalid")
    return token


def _install_token_file() -> None:
    token = _keychain_token().encode("utf-8") + b"\n"
    if TOKEN_FILE.exists() or TOKEN_FILE.is_symlink():
        if not _plain_file(TOKEN_FILE):
            raise RuntimeError("DGER GTG token file unsafe")
        if stat.S_IMODE(TOKEN_FILE.stat().st_mode) & 0o077:
            raise RuntimeError("DGER GTG token file permissions too broad")
        if TOKEN_FILE.read_bytes() == token:
            return
    _atomic(TOKEN_FILE, token, 0o600)


def _candidate_plist_bytes() -> bytes:
    if not _plain_file(CANDIDATE_PLIST):
        raise RuntimeError("candidate DGER LaunchAgent template unavailable")
    raw = CANDIDATE_PLIST.read_bytes()
    try:
        value = plistlib.loads(raw)
    except Exception as exc:
        raise RuntimeError("candidate DGER LaunchAgent invalid") from exc
    if not isinstance(value, dict) or value.get("Label") != LABEL or value.get("ProgramArguments") != [str(CANDIDATE_LAUNCHER)]:
        raise RuntimeError("candidate DGER LaunchAgent identity mismatch")
    return raw


def _install_candidate_config(context: dict) -> None:
    if not _plain_dir(RUNTIME_ROOT) or not _plain_file(CANDIDATE_LAUNCHER):
        raise RuntimeError("candidate DGER runtime unavailable")
    if not _plain_dir(MOH_HOME):
        raise RuntimeError("MOH home unavailable")
    _install_token_file()
    delivered = {
        "schema_version": 1,
        "runtime_root": str(RUNTIME_ROOT),
        "candidate_sha": context["approved_commit"],
        "candidate_tree": context["approved_tree"],
    }
    binding = {
        "schema_version": 1,
        "moh_home": str(MOH_HOME),
        "gtg_endpoint": GTG_ENDPOINT,
        "gtg_token_file": str(TOKEN_FILE),
        "allow_insecure_localhost_gtg": True,
    }
    _json_atomic(DELIVERED_IDENTITY, delivered, 0o600)
    _json_atomic(RUNTIME_BINDING, binding, 0o600)
    _atomic(LIVE_PLIST, _candidate_plist_bytes(), 0o644)


def _candidate_config_ok(context: dict) -> bool:
    try:
        if not _plain_file(DELIVERED_IDENTITY) or not _plain_file(RUNTIME_BINDING):
            return False
        delivered = json.loads(DELIVERED_IDENTITY.read_text(encoding="utf-8"))
        binding = json.loads(RUNTIME_BINDING.read_text(encoding="utf-8"))
        if delivered != {"schema_version": 1, "runtime_root": str(RUNTIME_ROOT), "candidate_sha": context["approved_commit"], "candidate_tree": context["approved_tree"]}:
            return False
        if binding != {"schema_version": 1, "moh_home": str(MOH_HOME), "gtg_endpoint": GTG_ENDPOINT, "gtg_token_file": str(TOKEN_FILE), "allow_insecure_localhost_gtg": True}:
            return False
        if not _plain_file(TOKEN_FILE) or stat.S_IMODE(TOKEN_FILE.stat().st_mode) & 0o077:
            return False
        if TOKEN_FILE.read_text(encoding="utf-8").strip() != _keychain_token():
            return False
        if not _plain_file(LIVE_PLIST) or LIVE_PLIST.read_bytes() != _candidate_plist_bytes():
            return False
        return True
    except Exception:
        return False


def _gtg_ping() -> bool:
    try:
        token = _keychain_token()
        body = json.dumps({"jsonrpc": "2.0", "id": "dger-god-smoke", "method": "ping", "params": {}}).encode("utf-8")
        conn = http.client.HTTPConnection(GTG_HOST, GTG_PORT, timeout=5)
        try:
            conn.request("POST", "/mcp", body=body, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "ping"})
            response = conn.getresponse()
            raw = response.read(65536)
        finally:
            conn.close()
        if response.status != 200:
            return False
        value = json.loads(raw.decode("utf-8"))
        return isinstance(value, dict) and value.get("id") == "dger-god-smoke" and value.get("result") == {}
    except Exception:
        return False


def _restore_predecessor(state: dict) -> None:
    snapshots = state.get("snapshots")
    if not isinstance(snapshots, dict):
        raise RuntimeError("adapter predecessor snapshots unavailable")
    for key, path in (("delivered_identity", DELIVERED_IDENTITY), ("runtime_binding", RUNTIME_BINDING), ("live_plist", LIVE_PLIST)):
        snap = snapshots.get(key)
        if not isinstance(snap, dict):
            raise RuntimeError(f"adapter predecessor snapshot unavailable: {key}")
        _restore(path, snap)


def _report(context: dict, prior_active: list[str], *, healthy: bool | None = None) -> dict:
    observed = project_discover(context)
    details = {
        "nonce": context["nonce"],
        **observed,
        "prior_active_runtime_ids": sorted(prior_active),
        "quiescent": not observed["active_runtime_ids"] and not observed["active_writer_ids"],
    }
    if healthy is not None:
        details["healthy"] = healthy
    return details


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError(f"{label} must be list[str]")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} duplicates")
    return list(value)


def emit(verb: str, status_value: str, details: dict, rc: int = 0) -> int:
    print(json.dumps({"verb": verb, "status": status_value, "details": details}, sort_keys=True))
    return rc


def main(argv: list[str]) -> int:
    verb = argv[1] if len(argv) > 1 else ""
    if len(argv) != 4 or argv[2] != "--context":
        return emit(verb, "BLOCKED", {}, 70)
    context_path = Path(argv[3])
    try:
        context = _load_context(context_path)
        if context.get("verb") != verb:
            raise ValueError("verb/context mismatch")
        accounting = context.get("runtime_accounting")
        if accounting != {"runtime_ids": [RUNTIME_ID], "writer_ids": [], "stop_required_ids": [RUNTIME_ID], "leave_stopped_ids": []}:
            raise ValueError("unexpected DGER runtime accounting")
        state_path = _state_path(context_path)
        run_id = context.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id missing")

        if verb == "quiesce":
            before = project_discover(context)
            prior = list(before["active_runtime_ids"])
            if not state_path.exists():
                state = {
                    "schema_version": 1,
                    "run_id": run_id,
                    "prior_active_runtime_ids": prior,
                    "restart_applied": False,
                    "snapshots": {
                        "delivered_identity": _snapshot(DELIVERED_IDENTITY),
                        "runtime_binding": _snapshot(RUNTIME_BINDING),
                        "live_plist": _snapshot(LIVE_PLIST),
                    },
                }
                _write_adapter_state(state_path, state)
            else:
                state = _load_adapter_state(state_path, run_id)
                prior = _string_list(state.get("prior_active_runtime_ids"), "prior_active_runtime_ids")
            _stop_service()
            state = _load_adapter_state(state_path, run_id)
            if state.get("restart_applied") is True:
                _restore_predecessor(state)
                state["restart_applied"] = False
                state["rollback_config_restored"] = True
                _write_adapter_state(state_path, state)
            return emit(verb, "PASS", _report(context, prior))

        state = _load_adapter_state(state_path, run_id)
        prior = _string_list(state.get("prior_active_runtime_ids"), "prior_active_runtime_ids")
        if verb == "prove-quiescence":
            return emit(verb, "PASS", _report(context, prior))
        if verb == "prepare-offline":
            if context.get("derived_surfaces"):
                raise ValueError("DGER has no derived surfaces")
            return emit(verb, "PASS", {"nonce": context["nonce"]})
        if verb == "restart":
            expected = _string_list(context.get("expected_restart_ids"), "expected_restart_ids")
            if expected not in ([], [RUNTIME_ID]):
                raise ValueError("unexpected restart set")
            try:
                _install_candidate_config(context)
            except Exception:
                _restore_predecessor(state)
                raise
            state["restart_applied"] = True
            _write_adapter_state(state_path, state)
            if expected:
                cp = _run(["/bin/launchctl", "bootstrap", f"gui/{UID}", str(LIVE_PLIST)], timeout=30)
                if cp.returncode != 0:
                    raise RuntimeError("launchd bootstrap failed")
                deadline = time.time() + 20
                while time.time() < deadline:
                    discovered = project_discover(context)
                    if discovered["active_runtime_ids"] == [RUNTIME_ID] and not discovered["ambiguities"] and not discovered["errors"]:
                        rows, row_errors = _process_rows()
                        if rows and not row_errors:
                            break
                    time.sleep(0.25)
                else:
                    raise RuntimeError("DGER did not become healthy enough for smoke")
            return emit(verb, "PASS", {"nonce": context["nonce"], "restarted_runtime_ids": expected})
        if verb == "runtime-smoke":
            expected = _string_list(context.get("expected_restart_ids"), "expected_restart_ids")
            observed = project_discover(context)
            process_rows, process_errors = _process_rows()
            healthy = not process_errors and _candidate_config_ok(context) and _gtg_ping() and _plain_dir(MOH_HOME) and (bool(process_rows) if expected else not observed["active_runtime_ids"])
            return emit(verb, "PASS", _report(context, prior, healthy=healthy))
        if verb == "unquiesce":
            return emit(verb, "PASS", {"nonce": context["nonce"]})
        raise ValueError("unsupported verb")
    except Exception as exc:
        print(f"DGER_GOD_ADAPTER_BLOCKED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return emit(verb, "BLOCKED", {}, 70)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
