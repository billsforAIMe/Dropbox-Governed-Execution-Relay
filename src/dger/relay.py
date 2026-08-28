from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import struct
import sys
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

PROTOCOL = "DGER_R0_V1"
REQUEST_SCHEMA = "DGER_R0_REQUEST_V1"
READY_SCHEMA = "DGER_R0_READY_V1"
QUALIFIED_GEP_SHA = "aa755d8941f7b0d46343c7e6b0d36c5f4cc40c15"
QUALIFIED_GEP_TREE = "26ebad2517b29eabf47110144e8534a07b62f015"
QUALIFIED_OPERATION = "platform.self_check"
QUALIFIED_PROJECT = "ai-me"
GEP_BARE = Path("/Users/brettmacpro/ChatGPT/Git/Tools/Governed Execution Platform.git")
DGER_BARE = Path("/Users/brettmacpro/ChatGPT/Git/Tools/Dropbox Governed Execution Relay.git")
PYRUNWAY = Path("/usr/local/bin/pyrunway")
CHM = Path("/usr/local/bin/handoff-manager")
CHM_SLOT = "Handoff100"
DEFAULT_STATE = Path("/Users/brettmacpro/ChatGPT/State/Tools/Dropbox Governed Execution Relay")
EXPECTED_INTERVAL_SECONDS = 2
HEALTH_STALE_SECONDS = 6
MAX_ATTEMPTS = 2
MAX_CAPTURE = 65536
REQUEST_RE = re.compile(r"r0-[0-9a-f]{32}")


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(canonical(value)); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass


def load_json_regular(path: Path) -> tuple[dict[str, Any], bytes]:
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValueError("UNSAFE_FILE_TYPE")
    data = path.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    return value, data


def resolve_dropbox_root() -> Path:
    base = Path.home() / "Library" / "CloudStorage"
    roots: list[Path] = []
    if base.is_dir():
        for provider in base.iterdir():
            marker = provider / "Software" / "NSP - Temporary Files"
            if marker.is_dir() and not provider.is_symlink() and not marker.is_symlink():
                roots.append(provider.resolve())
    unique = sorted({str(p) for p in roots})
    if len(unique) != 1:
        raise RuntimeError(f"DROPBOX_ROOT_AMBIGUOUS_OR_MISSING:{len(unique)}")
    return Path(unique[0])


def git_main_identity() -> tuple[str, str]:
    def g(*args: str) -> str:
        cp = subprocess.run(["/usr/bin/git", f"--git-dir={GEP_BARE}", *args], capture_output=True, text=True, timeout=15)
        if cp.returncode:
            raise RuntimeError("GEP_AUTHORITY_UNAVAILABLE")
        return cp.stdout.strip()
    sha = g("rev-parse", "refs/heads/main")
    return sha, g("rev-parse", f"{sha}^{{tree}}")


def resident_surface_identity() -> tuple[str, list[dict[str, Any]]]:
    runtime = DEFAULT_STATE / "runtime/current"
    specs = [
        (".python-version", ".python-version", runtime / ".python-version", 0o644),
        ("pyproject.toml", "pyproject.toml", runtime / "pyproject.toml", 0o644),
        ("uv.lock", "uv.lock", runtime / "uv.lock", 0o644),
        ("scripts/dger.py", "scripts/dger.py", runtime / "scripts/dger.py", 0o644),
        ("src/dger/__init__.py", "src/dger/__init__.py", runtime / "src/dger/__init__.py", 0o644),
        ("src/dger/relay.py", "src/dger/relay.py", runtime / "src/dger/relay.py", 0o644),
        ("launcher/dropbox-governed-execution-relay", "launcher/dropbox-governed-execution-relay", runtime / "launcher/dropbox-governed-execution-relay", 0o755),
        ("launchagent/com.brettmacpro.chatgpt.dropbox-governed-execution-relay.plist", "launchagent/com.brettmacpro.chatgpt.dropbox-governed-execution-relay.plist", Path.home() / "Library/LaunchAgents/com.brettmacpro.chatgpt.dropbox-governed-execution-relay.plist", 0o644),
    ]
    rows: list[dict[str, Any]] = []
    for source_path, logical_path, path, expected_mode in specs:
        if not path.is_absolute():
            raise RuntimeError(f"DGER_RESIDENT_SURFACE_NONABSOLUTE:{logical_path}")
        cur = Path("/")
        for part in path.parts[1:]:
            cur = cur / part
            try: cst = cur.lstat()
            except FileNotFoundError as exc: raise RuntimeError(f"DGER_RESIDENT_SURFACE_MISSING:{logical_path}:{cur}") from exc
            if stat.S_ISLNK(cst.st_mode):
                raise RuntimeError(f"DGER_RESIDENT_SURFACE_SYMLINK:{logical_path}:{cur}")
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode):
            raise RuntimeError(f"DGER_RESIDENT_SURFACE_UNSAFE:{logical_path}")
        observed_mode = stat.S_IMODE(st.st_mode)
        if observed_mode != expected_mode:
            raise RuntimeError(f"DGER_RESIDENT_SURFACE_MODE:{logical_path}:{observed_mode:04o}")
        data = path.read_bytes()
        rows.append({
            "source_path": source_path,
            "logical_path": logical_path,
            "runtime_path": str(path),
            "mode": f"{expected_mode:04o}",
            "size": len(data),
            "sha256": digest(data),
        })
    return digest(canonical(rows)), rows

def qualified() -> bool:
    try:
        return git_main_identity() == (QUALIFIED_GEP_SHA, QUALIFIED_GEP_TREE)
    except Exception:
        return False


def _run_chm(args: list[str], context: Path | None = None) -> dict[str, Any]:
    if not CHM.is_file() or not os.access(CHM, os.X_OK):
        raise RuntimeError("CHM_UNAVAILABLE")
    env = os.environ.copy()
    if context is not None:
        env["HANDOFF_MANAGER_CONTEXT_FILE"] = str(context)
    cp = subprocess.run([str(CHM), *args], capture_output=True, text=True, timeout=20, env=env)
    try:
        value = json.loads(cp.stdout)
    except Exception as exc:
        raise RuntimeError("CHM_INVALID_RESULT") from exc
    if not isinstance(value, dict) or cp.returncode not in (0, 2):
        raise RuntimeError("CHM_INVOCATION_FAILURE")
    return value


def _record_name(request_id: str) -> str:
    return f"DGER_R0_{request_id}"


def assign_slot(request_id: str) -> str:
    # R0 is deliberately single-worker, so one dedicated CHM lane is sufficient.
    # CHM assignment is idempotent for the same OPEN slot + immutable record, which
    # recovers the crash window after CHM assignment but before local phase persistence.
    value = _run_chm(["assign", CHM_SLOT, _record_name(request_id)])
    if value.get("ok") and value.get("code") == "HANDOFF_ASSIGNED":
        return CHM_SLOT
    code = value.get("code")
    if code == "INVALID_HANDOFF_RECORD":
        raise RuntimeError("CHM_RECORD_UNAVAILABLE")
    if code == "HANDOFF_CONFLICT":
        raise RuntimeError("CHM_DEDICATED_SLOT_BUSY")
    raise RuntimeError(f"CHM_ASSIGN_FAILED:{code}")


def context_file(state: Path, request_id: str, capability: str) -> Path:
    p = state / "contexts" / f"{request_id}.json"
    atomic_json(p, {"caller_id": f"dger-r0:{request_id}", "claim_capability": capability})
    os.chmod(p, 0o600)
    return p


def transition(slot: str, status: str, ctx: Path) -> dict[str, Any]:
    value = _run_chm(["status", slot, status], ctx)
    if value.get("ok"):
        return value
    # CHM returns the current target-slot lifecycle state on an invalid transition.
    # Treat an already-reached target state as successful recovery from the narrow
    # crash window after CHM commit but before DGER local phase persistence.
    if value.get("code") == "INVALID_HANDOFF_TRANSITION" and value.get("status") == status:
        return {**value, "ok": True, "recovered": True}
    raise RuntimeError(f"CHM_STATUS_FAILED:{value.get('code')}")


def claim_once(state: Path, request_id: str) -> Path:
    p = state / "claims" / f"{request_id}.claim"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return p
    with os.fdopen(fd, "wb") as fh:
        fh.write(canonical({"request_id": request_id, "claimed_at_utc": utc()})); fh.flush(); os.fsync(fh.fileno())
    return p


def _state_path(state: Path, request_id: str) -> Path:
    return state / "requests" / f"{request_id}.json"


def read_state(state: Path, request_id: str) -> dict[str, Any]:
    p = _state_path(state, request_id)
    if not p.exists():
        return {"request_id": request_id, "attempts": 0, "phase": "NEW"}
    return load_json_regular(p)[0]


def save_state(state: Path, request_id: str, value: dict[str, Any]) -> None:
    atomic_json(_state_path(state, request_id), value)


KERN_PROCARGS2 = 49


class _ProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32), ("pbi_status", ctypes.c_uint32), ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32), ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32), ("pbi_gid", ctypes.c_uint32), ("pbi_ruid", ctypes.c_uint32), ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32), ("pbi_svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16), ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32), ("pbi_pgid", ctypes.c_uint32), ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32), ("e_tpgid", ctypes.c_uint32), ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64), ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _libproc():
    if sys.platform != "darwin": raise RuntimeError("DARWIN_PROCESS_INSPECTION_REQUIRED")
    return ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)


def _native_pids() -> list[int]:
    lib=_libproc(); fn=lib.proc_listallpids; fn.argtypes=[ctypes.c_void_p,ctypes.c_int]; fn.restype=ctypes.c_int
    count=fn(None,0)
    if count<=0 or count>1_000_000: raise RuntimeError("PROC_LISTALLPIDS_COUNT_INVALID")
    arr=(ctypes.c_int*(count+64))(); got=fn(ctypes.cast(arr,ctypes.c_void_p),ctypes.sizeof(arr))
    if got<0: raise RuntimeError("PROC_LISTALLPIDS_FAILED")
    return sorted({int(arr[i]) for i in range(min(got,len(arr))) if int(arr[i])>1})


def _bsd_identity(pid:int)->dict[str,int]:
    lib=_libproc(); fn=lib.proc_pidinfo; fn.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_int]; fn.restype=ctypes.c_int
    info=_ProcBsdInfo(); ctypes.set_errno(0); got=fn(int(pid),3,0,ctypes.byref(info),ctypes.sizeof(info))
    if got!=ctypes.sizeof(info):
        err=ctypes.get_errno()
        if err in (errno.ESRCH,errno.EINVAL) or got==0: raise ProcessLookupError(pid)
        raise RuntimeError(f"PROC_PIDTBSDINFO_FAILED:{pid}:{got}:{err}")
    if int(info.pbi_pid)!=int(pid): raise RuntimeError(f"PROC_PIDTBSDINFO_PID_MISMATCH:{pid}:{info.pbi_pid}")
    return {"pid":int(info.pbi_pid),"ppid":int(info.pbi_ppid),"uid":int(info.pbi_uid),"start_sec":int(info.pbi_start_tvsec),"start_usec":int(info.pbi_start_tvusec)}


def _argv_from_procargs(raw:bytes,pid:int)->list[str]:
    if len(raw)<4: raise RuntimeError(f"NATIVE_ARGV_TRUNCATED:{pid}")
    argc=struct.unpack("=i",raw[:4])[0]
    if argc<1 or argc>4096: raise RuntimeError(f"NATIVE_ARGV_ARGC_INVALID:{pid}:{argc}")
    i=4; end=raw.find(b"\0",i)
    if end<0: raise RuntimeError(f"NATIVE_ARGV_EXEC_UNTERMINATED:{pid}")
    i=end+1
    while i<len(raw) and raw[i]==0: i+=1
    argv=[]
    for _ in range(argc):
        if i>=len(raw): raise RuntimeError(f"NATIVE_ARGV_TRUNCATED:{pid}")
        end=raw.find(b"\0",i)
        if end<0: raise RuntimeError(f"NATIVE_ARGV_UNTERMINATED:{pid}")
        argv.append(os.fsdecode(raw[i:end])); i=end+1
    if len(argv)!=argc or any(not isinstance(x,str) or not x for x in argv): raise RuntimeError(f"NATIVE_ARGV_MALFORMED:{pid}")
    return argv


def _native_argv(pid:int)->list[str]:
    if sys.platform!="darwin": raise RuntimeError("DARWIN_PROCESS_INSPECTION_REQUIRED")
    libc=ctypes.CDLL(None,use_errno=True); fn=libc.sysctl
    fn.argtypes=[ctypes.POINTER(ctypes.c_int),ctypes.c_uint,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.c_void_p,ctypes.c_size_t]; fn.restype=ctypes.c_int
    mib=(ctypes.c_int*3)(1,KERN_PROCARGS2,int(pid))
    for attempt in range(2):
        size=ctypes.c_size_t(0); ctypes.set_errno(0)
        if fn(mib,3,None,ctypes.byref(size),None,0)!=0:
            err=ctypes.get_errno()
            if err in (errno.ESRCH,errno.EINVAL): raise ProcessLookupError(pid)
            raise RuntimeError(f"NATIVE_ARGV_SIZE_FAILED:{pid}:{err}")
        if size.value<4 or size.value>4*1024*1024: raise RuntimeError(f"NATIVE_ARGV_SIZE_INVALID:{pid}:{size.value}")
        buf=ctypes.create_string_buffer(size.value); actual=ctypes.c_size_t(size.value); ctypes.set_errno(0)
        if fn(mib,3,buf,ctypes.byref(actual),None,0)==0: return _argv_from_procargs(buf.raw[:actual.value],pid)
        err=ctypes.get_errno()
        if err==errno.ENOMEM and attempt==0: continue
        if err in (errno.ESRCH,errno.EINVAL): raise ProcessLookupError(pid)
        raise RuntimeError(f"NATIVE_ARGV_READ_FAILED:{pid}:{err}")
    raise RuntimeError(f"NATIVE_ARGV_UNSTABLE:{pid}")


def _lsof_names(pid:int,descriptor:str)->list[str]:
    cp=subprocess.run(["/usr/sbin/lsof","-a","-p",str(pid),"-d",descriptor,"-Fn"],capture_output=True,timeout=5)
    if cp.returncode not in (0,1): raise RuntimeError(f"LSOF_INSPECTION_FAILED:{pid}:{descriptor}")
    return [line[1:] for line in cp.stdout.decode("utf-8","replace").splitlines() if line.startswith("n") and len(line)>1]


def _no_symlink_components(path:Path,allow_leaf_symlink:bool=False)->None:
    p=Path(path)
    if not p.is_absolute(): raise RuntimeError(f"PROCESS_PATH_NOT_ABSOLUTE:{p}")
    cur=Path("/"); parts=p.parts[1:]
    for idx,part in enumerate(parts):
        cur=cur/part
        try: st=cur.lstat()
        except FileNotFoundError as exc: raise RuntimeError(f"PROCESS_PATH_MISSING:{cur}") from exc
        if stat.S_ISLNK(st.st_mode) and not (allow_leaf_symlink and idx==len(parts)-1): raise RuntimeError(f"PROCESS_PATH_SYMLINK:{cur}")


def _expected_gep_target(target:str|Path)->tuple[Path,Path]:
    p=Path(target); _no_symlink_components(p)
    if not p.is_file() or p.name!="governed_exec.py" or p.parent.name!="scripts" or p.parent.parent.name!="gep-tree": raise RuntimeError(f"GEP_ATTEMPT_TARGET_INVALID:{p}")
    physical=p.resolve(strict=True)
    if p!=physical: raise RuntimeError(f"GEP_ATTEMPT_TARGET_NONCANONICAL:{p}")
    tree=p.parent.parent; _no_symlink_components(tree)
    if not tree.is_dir(): raise RuntimeError(f"GEP_ATTEMPT_TREE_INVALID:{tree}")
    return p,tree


def _samefile(a:Path,b:Path)->bool:
    try:return a.samefile(b)
    except Exception:return False


def _allowed_gep_executable(tree:Path,observed:Path)->bool:
    candidates=[PYRUNWAY,tree/".venv/bin/python",tree/".venv/bin/python3",tree/".venv/bin/python3.14"]
    for candidate in candidates:
        try:_no_symlink_components(candidate,allow_leaf_symlink=True)
        except RuntimeError:continue
        if candidate.exists() and _samefile(candidate,observed):return True
    return False


def _owned_attempt_process(pid:int,target:str|Path|None=None)->dict[str,Any]:
    before=_bsd_identity(pid)
    if before["uid"]!=os.getuid(): raise RuntimeError(f"GEP_ATTEMPT_WRONG_UID:{pid}:{before['uid']}")
    argv=_native_argv(pid)
    if len(argv)!=4 or argv[2:]!=["self-check",QUALIFIED_PROJECT]: raise RuntimeError(f"GEP_ATTEMPT_ARGV_OWNERSHIP:{pid}")
    argv_target=argv[1]
    if target is not None:
        target_path,tree=_expected_gep_target(target)
        if argv_target!=str(target_path): raise RuntimeError(f"GEP_ATTEMPT_ARGV_OWNERSHIP:{pid}")
    else:
        target_path,tree=_expected_gep_target(argv_target)
    expected=[str(target_path),"self-check",QUALIFIED_PROJECT]
    if argv[1:]!=expected: raise RuntimeError(f"GEP_ATTEMPT_ARGV_OWNERSHIP:{pid}")
    cwds=sorted(set(_lsof_names(pid,"cwd")))
    if len(cwds)!=1: raise RuntimeError(f"GEP_ATTEMPT_CWD_AMBIGUOUS:{pid}:{len(cwds)}")
    cwd=Path(cwds[0]); _no_symlink_components(cwd)
    if not cwd.is_dir() or not _samefile(cwd,tree): raise RuntimeError(f"GEP_ATTEMPT_CWD_OWNERSHIP:{pid}:{cwd}")
    txts=sorted(set(_lsof_names(pid,"txt")))
    if len(txts)!=1: raise RuntimeError(f"GEP_ATTEMPT_TXT_AMBIGUOUS:{pid}:{len(txts)}")
    txt=Path(txts[0]); _no_symlink_components(txt)
    if not txt.is_file() or not _allowed_gep_executable(tree,txt): raise RuntimeError(f"GEP_ATTEMPT_EXECUTABLE_OWNERSHIP:{pid}:{txt}")
    after=_bsd_identity(pid)
    if before!=after: raise RuntimeError(f"GEP_ATTEMPT_PID_REUSED_DURING_INSPECTION:{pid}")
    return {"pid":pid,"uid":before["uid"],"ppid":before["ppid"],"start_sec":before["start_sec"],"start_usec":before["start_usec"],"argv":argv,"cwd":str(cwd.resolve(strict=True)),"txt":str(txt.resolve(strict=True)),"target":str(target_path)}


def process_identity(pid:int)->str|None:
    try:return digest(canonical(_owned_attempt_process(pid,None)))
    except Exception:return None

def is_same_live_process(pid:Any,identity:Any)->bool:
    if not isinstance(pid,int) or pid<=1 or not isinstance(identity,str) or not re.fullmatch(r"[0-9a-f]{64}",identity):return False
    return process_identity(pid)==identity

def find_attempt_process(target:Any)->tuple[int,str]|None:
    if not isinstance(target,str) or not target:return None
    try:target_path,_tree=_expected_gep_target(target)
    except Exception:return None
    wanted=str(target_path); valid=[]; invalid=[]
    try:pids=_native_pids()
    except Exception as exc:raise RuntimeError("GEP_ATTEMPT_PID_ENUMERATION_FAILED") from exc
    for pid in pids:
        if pid==os.getpid():continue
        # Preliminary identity/argv are candidate filters only.  They are never trusted for
        # ownership; _owned_attempt_process takes a new proc_bsdinfo snapshot and re-reads argv.
        try:
            preliminary_info=_bsd_identity(pid)
            if preliminary_info["uid"]!=os.getuid():continue
            preliminary_argv=_native_argv(pid)
        except ProcessLookupError:continue
        except Exception:continue
        if wanted not in preliminary_argv:continue
        try:rec=_owned_attempt_process(pid,wanted)
        except Exception:invalid.append(pid);continue
        valid.append((pid,digest(canonical(rec))))
    if invalid:raise RuntimeError("UNOWNED_GEP_ATTEMPT_TARGET_PROCESS:"+",".join(str(x) for x in sorted(invalid)))
    if len(valid)>1:raise RuntimeError("MULTIPLE_GEP_ATTEMPT_PROCESSES")
    return valid[0] if valid else None

def reconstruct_gep(attempt_dir: Path) -> Path:
    tree = attempt_dir / "gep-tree"
    if tree.exists(): shutil.rmtree(tree)
    tree.mkdir(parents=True)
    archive = attempt_dir / "gep.tar"
    with archive.open("wb") as fh:
        cp = subprocess.run(["/usr/bin/git", f"--git-dir={GEP_BARE}", "archive", "--format=tar", QUALIFIED_GEP_SHA], stdout=fh, stderr=subprocess.PIPE)
    if cp.returncode:
        raise RuntimeError("GEP_ARCHIVE_FAILED")
    cp = subprocess.run(["/usr/bin/tar", "-xf", str(archive), "-C", str(tree)], capture_output=True)
    if cp.returncode:
        raise RuntimeError("GEP_ARCHIVE_EXTRACT_FAILED")
    physical = tree.resolve(strict=True)
    if physical.is_symlink() or not physical.is_dir():
        raise RuntimeError("GEP_RECONSTRUCTION_UNSAFE")
    return physical


def provision_gep(tree: Path) -> None:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("UV_UNAVAILABLE")
    env = os.environ.copy()
    env["UV_OFFLINE"] = "1"
    cp = subprocess.run([uv, "sync", "--locked"], cwd=tree, env=env, capture_output=True, text=True, timeout=120)
    if cp.returncode:
        raise RuntimeError(f"GEP_UV_SYNC_LOCKED_FAILED:{cp.returncode}")
    venv = tree / ".venv"
    if venv.is_symlink() or not venv.is_dir():
        raise RuntimeError("GEP_CANONICAL_ENVIRONMENT_MISSING")


def start_gep(state_root: Path, request_id: str, current: dict[str, Any]) -> dict[str, Any]:
    attempts = int(current.get("attempts", 0))
    if attempts >= MAX_ATTEMPTS:
        raise RuntimeError("RERUN_LIMIT_EXCEEDED")
    attempt = attempts + 1
    ad = state_root / "attempts" / request_id / f"attempt-{attempt}"
    ad.mkdir(parents=True, exist_ok=True)
    tree = reconstruct_gep(ad)
    provision_gep(tree)
    stdout_path, stderr_path = ad / "stdout.json", ad / "stderr.log"
    out, err = open(stdout_path, "wb"), open(stderr_path, "wb")
    env = os.environ.copy(); env["PYRUNWAY_STRICT"] = "1"; env["PYTHONDONTWRITEBYTECODE"] = "1"
    target = (tree / "scripts" / "governed_exec.py").resolve(strict=True)
    cmd = [str(PYRUNWAY), str(target), "self-check", QUALIFIED_PROJECT]
    current.update({"attempts": attempt, "phase": "GEP_STARTING", "attempt_dir": str(ad), "gep_target": str(target), "gep_launch_reserved_utc": utc()})
    current.pop("gep_pid", None); current.pop("gep_process_identity", None)
    save_state(state_root, request_id, current)
    try:
        proc = subprocess.Popen(cmd, cwd=tree, env=env, stdout=out, stderr=err, start_new_session=True)
    finally:
        out.close(); err.close()
    ident = None
    for _ in range(20):
        ident = process_identity(proc.pid)
        if ident: break
        time.sleep(0.05)
    if not ident:
        try: proc.terminate()
        except Exception: pass
        raise RuntimeError("GEP_CHILD_IDENTITY_UNAVAILABLE")
    current.update({"phase": "GEP_RUNNING", "gep_pid": proc.pid, "gep_process_identity": ident, "gep_started_utc": utc()})
    save_state(state_root, request_id, current)
    return current


def read_gep_terminal(current: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
    ad = Path(current["attempt_dir"]); so, se = ad / "stdout.json", ad / "stderr.log"
    stdout = so.read_text("utf-8", errors="replace")[:MAX_CAPTURE] if so.exists() else ""
    stderr = se.read_text("utf-8", errors="replace")[:MAX_CAPTURE] if se.exists() else ""
    try: value = json.loads(stdout)
    except Exception: return None, stdout, stderr
    return value if isinstance(value, dict) else None, stdout, stderr


def safe_output_dir(parent: Path, request_id: str) -> Path:
    if not REQUEST_RE.fullmatch(request_id):
        raise RuntimeError("INVALID_REQUEST_ID")
    if parent.is_symlink():
        raise RuntimeError("UNSAFE_OUTPUT_PARENT")
    p = parent / request_id
    if p.is_symlink():
        raise RuntimeError("UNSAFE_OUTPUT_PATH")
    p.mkdir(parents=True, exist_ok=True)
    if p.is_symlink() or p.resolve().parent != parent.resolve():
        raise RuntimeError("UNSAFE_OUTPUT_PATH")
    return p


class Relay:
    def __init__(self, root: Path, state_root: Path = DEFAULT_STATE, *, sleep=time.sleep):
        if root.is_symlink(): raise RuntimeError("UNSAFE_TRANSPORT_ROOT")
        if state_root.is_symlink(): raise RuntimeError("UNSAFE_RELAY_PATH")
        self.root = root.resolve(); self.state = state_root.resolve(); self.sleep = sleep
        self.ingress, self.runs, self.control = self.root / "Ingress", self.root / "Runs", self.root / "Control"
        self.sequence_file = self.state / "health-sequence"
        for p in (self.ingress, self.runs, self.control, self.state):
            if p.is_symlink(): raise RuntimeError("UNSAFE_RELAY_PATH")
            p.mkdir(parents=True, exist_ok=True)
            if p.is_symlink(): raise RuntimeError("UNSAFE_RELAY_PATH")
        self._mismatch: dict[str, tuple[int, int, float]] = {}

    def heartbeat(self, state="IDLE") -> None:
        try: seq = int(self.sequence_file.read_text().strip())
        except Exception: seq = 0
        seq += 1
        tmp = self.sequence_file.with_name(f".{self.sequence_file.name}.{os.getpid()}.tmp")
        tmp.write_text(str(seq)); os.replace(tmp, self.sequence_file)
        surface_sha, surface_rows = resident_surface_identity()
        atomic_json(self.control / "health.json", {
            "schema_version": PROTOCOL,
            "sequence": seq,
            "updated_at_utc": utc(),
            "relay_state": state,
            "protocol_version": PROTOCOL,
            "expected_interval_seconds": EXPECTED_INTERVAL_SECONDS,
            "qualified_gep_operation": QUALIFIED_OPERATION,
            "qualified_gep_commit": QUALIFIED_GEP_SHA,
            "dger_resident_surface_sha256": surface_sha,
            "dger_resident_surface": surface_rows,
        }, 0o644)

    def status(self, rid: str, state: str, **extra: Any) -> None:
        atomic_json(safe_output_dir(self.runs, rid) / "status.json", {"schema_version": PROTOCOL, "request_id": rid, "state": state, "updated_at_utc": utc(), **extra}, 0o644)

    def result(self, rid: str, outcome: str, classification: str, **extra: Any) -> None:
        p = safe_output_dir(self.runs, rid) / "result.json"
        if not p.exists():
            atomic_json(p, {"schema_version": PROTOCOL, "request_id": rid, "terminal": True, "outcome": outcome, "classification": classification, "completed_at_utc": utc(), **extra}, 0o644)

    def validate_package(self, d: Path) -> tuple[str, dict[str, Any]] | None:
        rid = d.name
        if not REQUEST_RE.fullmatch(rid) or d.is_symlink() or not d.is_dir(): return None
        ready, request = d / "READY.json", d / "request.json"
        if ready.is_symlink() or request.is_symlink():
            self.result(rid, "BLOCKED", "UNSAFE_PACKAGE_PATH"); return None
        if not ready.exists(): return None
        try: rv, _ = load_json_regular(ready)
        except Exception as exc: self.result(rid, "BLOCKED", "MALFORMED_READY", detail=str(exc)); return None
        if set(rv) != {"schema_version", "request_id", "request_sha256", "request_size"} or rv.get("schema_version") != READY_SCHEMA or rv.get("request_id") != rid:
            self.result(rid, "BLOCKED", "MALFORMED_READY"); return None
        if not request.exists(): return None
        try:
            names = {p.name for p in d.iterdir()}
        except OSError as exc:
            self.result(rid, "BLOCKED", "UNSAFE_PACKAGE_PATH", detail=str(exc)); return None
        if names != {"request.json", "READY.json"}:
            self.result(rid, "BLOCKED", "UNEXPECTED_PACKAGE_ENTRY"); return None
        try: qv, qb = load_json_regular(request)
        except Exception as exc: self.result(rid, "BLOCKED", "MALFORMED_REQUEST", detail=str(exc)); return None
        size, expected = rv.get("request_size"), rv.get("request_sha256")
        if not isinstance(size, int) or size < 1 or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            self.result(rid, "BLOCKED", "MALFORMED_READY"); return None
        if len(qb) != size or digest(qb) != expected:
            st = request.stat(); old = self._mismatch.get(rid); current = (st.st_size, st.st_mtime_ns, time.monotonic())
            if old and old[:2] == current[:2] and time.monotonic() - old[2] >= EXPECTED_INTERVAL_SECONDS:
                self.result(rid, "BLOCKED", "REQUEST_INTEGRITY_MISMATCH"); return None
            self._mismatch[rid] = current; return None
        if qb != canonical(qv): self.result(rid, "BLOCKED", "NONCANONICAL_REQUEST"); return None
        if set(qv) != {"schema_version", "request_id", "project_id", "operation_id"} or qv.get("schema_version") != REQUEST_SCHEMA or qv.get("request_id") != rid:
            self.result(rid, "BLOCKED", "MALFORMED_REQUEST"); return None
        if qv.get("project_id") != QUALIFIED_PROJECT or qv.get("operation_id") != QUALIFIED_OPERATION:
            self.result(rid, "BLOCKED", "OPERATION_NOT_ALLOWLISTED"); return None
        return rid, qv

    def _finish_chm(self, rid: str, current: dict[str, Any]) -> bool:
        slot, cap = current.get("chm_slot"), current.get("claim_capability")
        if not isinstance(slot, str) or not isinstance(cap, str): return True
        ctx = context_file(self.state, rid, cap)
        try: transition(slot, "CLOSED", ctx)
        except Exception as exc: self.status(rid, "RESULT_PUBLISHED_CHM_PENDING", detail=str(exc), chm_slot=slot); return False
        finally:
            try: ctx.unlink()
            except FileNotFoundError: pass
        current["phase"] = "DONE"; current["chm_closed_utc"] = utc(); save_state(self.state, rid, current); return True

    def process_one(self, d: Path) -> bool:
        rid = d.name; current = read_state(self.state, rid); result_path = self.runs / rid / "result.json"
        if result_path.exists():
            if current.get("phase") != "DONE": self._finish_chm(rid, current)
            return True
        if not self.validate_package(d): return False
        claim_once(self.state, rid)
        if not qualified(): self.result(rid, "BLOCKED", "CLASSIFICATION_VOID", qualified_gep_commit=QUALIFIED_GEP_SHA); return True
        if current.get("phase") == "NEW":
            try:
                slot = assign_slot(rid); cap = secrets.token_urlsafe(48)
                current.update({"chm_slot": slot, "claim_capability": cap, "phase": "CHM_ASSIGNED"}); save_state(self.state, rid, current)
            except Exception as exc:
                self.status(rid, "DEGRADED_CHM_UNAVAILABLE", detail=str(exc)); return False
        if current.get("phase") == "CHM_ASSIGNED":
            try:
                slot, cap = current["chm_slot"], current["claim_capability"]
                ctx = context_file(self.state, rid, cap)
                try: transition(slot, "STARTED", ctx)
                finally:
                    try: ctx.unlink()
                    except FileNotFoundError: pass
                current["phase"] = "CHM_STARTED"; current["chm_started_utc"] = utc(); save_state(self.state, rid, current)
                self.status(rid, "CHM_STARTED", chm_slot=slot, attempts=current.get("attempts", 0))
            except Exception as exc:
                self.status(rid, "DEGRADED_CHM_UNAVAILABLE", detail=str(exc)); return False
        if current.get("phase") == "GEP_STARTING":
            value, stdout, stderr = read_gep_terminal(current)
            if value is not None and value.get("operation_id") == QUALIFIED_OPERATION and value.get("project_id") == QUALIFIED_PROJECT and isinstance(value.get("run_id"), str):
                outcome = "SUCCESS" if value.get("overall_outcome") == "SUCCESS" else "FAILED"
                self.result(rid, outcome, "GEP_TERMINAL", gep_result=value, stdout=stdout, stderr=stderr, attempts=current.get("attempts"), chm_slot=current.get("chm_slot"))
                current["phase"] = "RESULT_PUBLISHED"; save_state(self.state, rid, current); self._finish_chm(rid, current); return True
            adopted = None
            for _ in range(20):
                adopted = find_attempt_process(current.get("gep_target"))
                if adopted: break
                self.sleep(0.05)
            if adopted:
                pid, ident = adopted
                current.update({"phase": "GEP_RUNNING", "gep_pid": pid, "gep_process_identity": ident, "gep_adopted_utc": utc()})
                save_state(self.state, rid, current)
                self.status(rid, "GEP_RUNNING", attempts=current.get("attempts"), chm_slot=current.get("chm_slot")); return True
            value, stdout, stderr = read_gep_terminal(current)
            if value is not None and value.get("operation_id") == QUALIFIED_OPERATION and value.get("project_id") == QUALIFIED_PROJECT and isinstance(value.get("run_id"), str):
                outcome = "SUCCESS" if value.get("overall_outcome") == "SUCCESS" else "FAILED"
                self.result(rid, outcome, "GEP_TERMINAL", gep_result=value, stdout=stdout, stderr=stderr, attempts=current.get("attempts"), chm_slot=current.get("chm_slot"))
                current["phase"] = "RESULT_PUBLISHED"; save_state(self.state, rid, current); self._finish_chm(rid, current); return True
            current["phase"] = "CHM_STARTED"; current.pop("gep_pid", None); current.pop("gep_process_identity", None); save_state(self.state, rid, current)
            if int(current.get("attempts", 0)) >= MAX_ATTEMPTS:
                self.result(rid, "BLOCKED", "RERUN_LIMIT_EXCEEDED", detail="GEP_STARTING reservation consumed without live or terminal child", attempts=current.get("attempts"), chm_slot=current.get("chm_slot")); current["phase"] = "RESULT_PUBLISHED"; save_state(self.state, rid, current); self._finish_chm(rid, current); return True
            self.status(rid, "GEP_INVOCATION_RETRY", detail="GEP_STARTING reservation consumed without live or terminal child", attempts=current.get("attempts"), chm_slot=current.get("chm_slot")); return True
        if current.get("phase") == "GEP_RUNNING":
            value, stdout, stderr = read_gep_terminal(current)
            if value is not None and value.get("operation_id") == QUALIFIED_OPERATION and value.get("project_id") == QUALIFIED_PROJECT and isinstance(value.get("run_id"), str):
                outcome = "SUCCESS" if value.get("overall_outcome") == "SUCCESS" else "FAILED"
                self.result(rid, outcome, "GEP_TERMINAL", gep_result=value, stdout=stdout, stderr=stderr, attempts=current.get("attempts"), chm_slot=current.get("chm_slot"))
                current["phase"] = "RESULT_PUBLISHED"; save_state(self.state, rid, current); self._finish_chm(rid, current); return True
            if is_same_live_process(current.get("gep_pid"), current.get("gep_process_identity")):
                self.status(rid, "GEP_RUNNING", attempts=current.get("attempts"), chm_slot=current.get("chm_slot")); return True
            current["phase"] = "CHM_STARTED"; current.pop("gep_pid", None); current.pop("gep_process_identity", None); save_state(self.state, rid, current)
        if current.get("phase") in {"CHM_STARTED", "CHM_ASSIGNED"}:
            if int(current.get("attempts", 0)) >= MAX_ATTEMPTS:
                self.result(rid, "BLOCKED", "RERUN_LIMIT_EXCEEDED", attempts=current.get("attempts"), chm_slot=current.get("chm_slot")); current["phase"] = "RESULT_PUBLISHED"; save_state(self.state, rid, current); self._finish_chm(rid, current); return True
            try:
                current = start_gep(self.state, rid, current); self.status(rid, "GEP_RUNNING", attempts=current.get("attempts"), chm_slot=current.get("chm_slot")); return True
            except Exception as exc:
                fresh = read_state(self.state, rid)
                if fresh.get("phase") == "GEP_STARTING":
                    current = fresh
                    self.status(rid, "GEP_START_RECOVERY_PENDING", detail=str(exc), attempts=current.get("attempts"), chm_slot=current.get("chm_slot")); return True
                current = fresh
                current["attempts"] = int(current.get("attempts", 0)) + 1; current["phase"] = "CHM_STARTED"; save_state(self.state, rid, current)
                if current["attempts"] >= MAX_ATTEMPTS:
                    self.result(rid, "BLOCKED", "RERUN_LIMIT_EXCEEDED", detail=str(exc), attempts=current["attempts"], chm_slot=current.get("chm_slot")); current["phase"] = "RESULT_PUBLISHED"; save_state(self.state, rid, current); self._finish_chm(rid, current)
                else: self.status(rid, "GEP_INVOCATION_RETRY", detail=str(exc), attempts=current["attempts"])
                return True
        return True

    def scan_once(self) -> None:
        self.heartbeat("SCANNING")
        dirs = []
        for p in self.ingress.iterdir():
            try:
                if p.is_dir() and not p.is_symlink(): dirs.append(p)
            except OSError: continue
        degraded = False
        for p in sorted(dirs, key=lambda x: x.name):
            try: self.process_one(p)
            except Exception: degraded = True
        self.heartbeat("DEGRADED_REQUEST" if degraded else "IDLE")

    def run(self) -> None:
        while True:
            try: self.scan_once()
            except Exception as exc: self.heartbeat("DEGRADED:" + type(exc).__name__)
            self.sleep(EXPECTED_INTERVAL_SECONDS)
