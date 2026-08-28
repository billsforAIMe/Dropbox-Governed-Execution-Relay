#!/usr/bin/env python3
from __future__ import annotations
import ctypes, errno, hashlib, json, os, re, signal, stat, struct, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
LABEL="com.brettmacpro.chatgpt.dropbox-governed-execution-relay"
RID="dger.launchagent"; WID="dger.gep-child"
STATE=Path("/Users/brettmacpro/ChatGPT/State/Tools/Dropbox Governed Execution Relay")
DGER_BARE=Path("/Users/brettmacpro/ChatGPT/Git/Tools/Dropbox Governed Execution Relay.git")
HEALTH_STALE_SECONDS=6
PLIST=Path("/Users/brettmacpro/Library/LaunchAgents/com.brettmacpro.chatgpt.dropbox-governed-execution-relay.plist")
LAUNCHER=STATE/"runtime/current/launcher/dropbox-governed-execution-relay"
LEGACY=Path("/usr/local/bin/dropbox-governed-execution-relay")
PROTOCOL="DGER_R0_V1"; GEP="aa755d8941f7b0d46343c7e6b0d36c5f4cc40c15"; OP="platform.self_check"
SCOPES=["launchd-nonstandard","launchd-system","launchd-user","ownership-cwd","ownership-executable","ownership-symlink","processes","writers"]
def run(a,timeout=15): return subprocess.run([str(x) for x in a],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
def loaded(domain):
    return run(["/bin/launchctl","print",f"{domain}/{LABEL}"]).returncode==0
def _ps_pids():
    p=run(["/bin/ps","-axo","pid=,uid="])
    if p.returncode: raise RuntimeError("ps pid/uid enumeration failed")
    out=[]; me=os.getuid()
    for line in p.stdout.decode("ascii","replace").splitlines():
        q=line.strip().split()
        if len(q)!=2: continue
        try: pid,uid=int(q[0]),int(q[1])
        except ValueError: continue
        if uid==me and pid!=os.getpid(): out.append((pid,uid))
    return out

def _launchctl_pid():
    p=run(["/bin/launchctl","print",f"gui/{os.getuid()}/{LABEL}"])
    if p.returncode: return None
    hits=sorted(set(re.findall(r"(?m)^\s*pid\s*=\s*([0-9]+)\s*$",p.stdout.decode("utf-8","replace"))))
    if len(hits)>1: raise RuntimeError("launchctl pid ambiguous")
    return int(hits[0]) if hits else None

def _lsof_names(pid, descriptor):
    p=run(["/usr/sbin/lsof","-a","-p",str(pid),"-d",descriptor,"-Fn"],5)
    if p.returncode not in (0,1): raise RuntimeError(f"lsof inspection failed:{pid}:{descriptor}")
    return [line[1:] for line in p.stdout.decode("utf-8","replace").splitlines() if line.startswith("n") and len(line)>1]

def _pid_exists(pid):
    p=run(["/bin/ps","-p",str(pid),"-o","pid="],5)
    return p.returncode==0 and any(x.strip()==str(pid) for x in p.stdout.decode("ascii","replace").splitlines())

def _argv_from_procargs(raw,pid):
    if len(raw)<4: raise RuntimeError(f"native argv truncated:{pid}")
    argc=struct.unpack("=i",raw[:4])[0]
    if argc<1 or argc>4096: raise RuntimeError(f"native argv argc invalid:{pid}:{argc}")
    i=4; end=raw.find(b"\0",i)
    if end<0: raise RuntimeError(f"native argv executable unterminated:{pid}")
    i=end+1
    while i<len(raw) and raw[i]==0: i+=1
    argv=[]
    for _ in range(argc):
        if i>=len(raw): raise RuntimeError(f"native argv truncated:{pid}")
        end=raw.find(b"\0",i)
        if end<0: raise RuntimeError(f"native argv unterminated:{pid}")
        argv.append(os.fsdecode(raw[i:end])); i=end+1
    if len(argv)!=argc or any(not isinstance(x,str) or not x for x in argv): raise RuntimeError(f"native argv malformed:{pid}")
    return argv

def _native_argv(pid):
    if sys.platform!="darwin": raise RuntimeError("native Darwin argv inspection unavailable")
    libc=ctypes.CDLL(None,use_errno=True); fn=libc.sysctl
    fn.argtypes=[ctypes.POINTER(ctypes.c_int),ctypes.c_uint,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.c_void_p,ctypes.c_size_t]
    fn.restype=ctypes.c_int
    mib=(ctypes.c_int*3)(1,49,int(pid))
    for attempt in range(2):
        size=ctypes.c_size_t(0); ctypes.set_errno(0)
        if fn(mib,3,None,ctypes.byref(size),None,0)!=0:
            err=ctypes.get_errno()
            if err in (errno.ESRCH,errno.EINVAL) and not _pid_exists(pid): raise ProcessLookupError(pid)
            raise RuntimeError(f"native argv size failed:{pid}:{err}")
        if size.value<4 or size.value>4*1024*1024: raise RuntimeError(f"native argv size invalid:{pid}:{size.value}")
        buf=ctypes.create_string_buffer(size.value); actual=ctypes.c_size_t(size.value); ctypes.set_errno(0)
        if fn(mib,3,buf,ctypes.byref(actual),None,0)==0:
            return _argv_from_procargs(buf.raw[:actual.value],pid)
        err=ctypes.get_errno()
        if err==errno.ENOMEM and attempt==0: continue
        if err in (errno.ESRCH,errno.EINVAL) and not _pid_exists(pid): raise ProcessLookupError(pid)
        raise RuntimeError(f"native argv read failed:{pid}:{err}")
    raise RuntimeError(f"native argv unstable:{pid}")

def _no_symlink_components(path):
    p=Path(path)
    if not p.is_absolute(): raise RuntimeError(f"ownership path not absolute:{p}")
    cur=Path("/")
    for part in p.parts[1:]:
        cur=cur/part
        try: st=cur.lstat()
        except FileNotFoundError: raise RuntimeError(f"ownership path missing:{cur}")
        if stat.S_ISLNK(st.st_mode): raise RuntimeError(f"ownership symlink boundary:{cur}")

def _physical_dir(path):
    p=Path(path); _no_symlink_components(p)
    if not p.is_dir(): raise RuntimeError(f"ownership directory unavailable:{p}")
    return p

def _physical_file(path):
    p=Path(path); _no_symlink_components(p)
    st=p.lstat()
    if not stat.S_ISREG(st.st_mode): raise RuntimeError(f"ownership file unavailable:{p}")
    return p

def cwd(pid):
    names=_lsof_names(pid,"cwd")
    if len(names)!=1: raise RuntimeError(f"cwd ownership ambiguous:{pid}:{names}")
    actual=Path(names[0]); _physical_dir(actual); return actual

def _physical_argv_paths(argv,pid):
    if not isinstance(argv,list) or not argv: raise RuntimeError(f"native argv empty:{pid}")
    out=[]
    for token in argv:
        if not isinstance(token,str): raise RuntimeError(f"native argv token invalid:{pid}")
        p=Path(token)
        if not p.is_absolute(): continue
        try:
            if p.exists() or p.is_symlink(): out.append(p)
        except OSError: continue
    return out

def _interpreter_owned(pid, expected_cwd):
    root=_physical_dir(Path(expected_cwd)); venv=_physical_dir(root/".venv"); bindir=_physical_dir(venv/"bin")
    candidates=[]
    for name in ("python","python3","python3.14"):
        p=bindir/name
        if p.exists() or p.is_symlink(): candidates.append(p)
    if not candidates: raise RuntimeError(f"project interpreter unavailable:{root}")
    txt=_lsof_names(pid,"txt"); matches=[]
    for observed in txt:
        op=Path(observed)
        for expected in candidates:
            try:
                if os.path.samefile(op,expected): matches.append((str(op),str(expected)))
            except (FileNotFoundError,OSError): pass
    if not matches: raise RuntimeError(f"process executable ownership mismatch:{pid}:{root}")
    return matches[0][0]

def _owned(pid, argv, expected_cwd, required_target):
    root=_physical_dir(expected_cwd); actual_cwd=cwd(pid)
    if not os.path.samefile(actual_cwd,root): raise RuntimeError(f"process cwd ownership mismatch:{pid}:{actual_cwd}:{root}")
    target=_physical_file(required_target); matched=[]
    for token_path in _physical_argv_paths(argv,pid):
        try:
            if os.path.samefile(token_path,target): matched.append(str(token_path))
        except (FileNotFoundError,OSError): pass
    if len(matched)!=1: raise RuntimeError(f"process target ownership mismatch:{pid}:{target}:{matched}")
    exe=_interpreter_owned(pid,root)
    return {"pid":pid,"argv":list(argv),"cwd":str(actual_cwd),"target":str(target),"executable":exe}

def _classify_argv(pid,argv,lpid):
    if not isinstance(argv,list) or not argv: raise RuntimeError(f"native argv empty:{pid}")
    rt_target=str(STATE/"runtime/current/scripts/dger.py"); marker=str(STATE/"attempts")+"/"; suffix="/gep-tree/scripts/governed_exec.py"; legacy=str(LEGACY)
    abs_tokens=[x for x in argv if isinstance(x,str) and x.startswith("/")]
    runtime=[x for x in abs_tokens if x==rt_target]; writers=[x for x in abs_tokens if x.startswith(marker) and x.endswith(suffix)]; legacy_hits=[x for x in abs_tokens if x==legacy]
    if runtime and (len(runtime)!=1 or lpid is None or pid!=lpid): raise RuntimeError(f"unowned DGER runtime process:{pid}")
    if len(writers)>1: raise RuntimeError(f"writer target ambiguous:{pid}")
    if legacy_hits: raise RuntimeError(f"legacy DGER runtime process active:{pid}")
    plausible=[x for x in abs_tokens if Path(x).name in ("dger.py","governed_exec.py","dropbox-governed-execution-relay")]
    recognized=set(runtime+writers+legacy_hits); unowned=[x for x in plausible if x not in recognized]
    if unowned: raise RuntimeError(f"plausible unowned DGER/GEP process:{pid}:{unowned}")
    return {"runtime_target":runtime[0] if runtime else None,"writer_target":writers[0] if writers else None}

def procs():
    rows=_ps_pids(); runtime=[]; writers=[]; lpid=_launchctl_pid(); rt=STATE/"runtime/current"; rt_target=rt/"scripts/dger.py"; rowmap={pid:uid for pid,uid in rows}
    for pid,_uid in rows:
        try: argv=_native_argv(pid)
        except ProcessLookupError: continue
        cls=_classify_argv(pid,argv,lpid)
        if cls["runtime_target"]: runtime.append(_owned(pid,argv,rt,rt_target))
        if cls["writer_target"]:
            raw_target=Path(cls["writer_target"]); _no_symlink_components(raw_target); target=_physical_file(raw_target); gep_tree=_physical_dir(target.parent.parent); attempts=_physical_dir(STATE/"attempts")
            try: target.relative_to(attempts)
            except ValueError: raise RuntimeError(f"writer target ownership mismatch:{pid}:{target}")
            writers.append(_owned(pid,argv,gep_tree,target))
    if lpid is not None and not runtime:
        if lpid not in rowmap: raise RuntimeError(f"launchctl pid absent from same-user pid set:{lpid}")
        try: argv=_native_argv(lpid)
        except ProcessLookupError as exc: raise RuntimeError(f"launchctl pid disappeared:{lpid}") from exc
        _classify_argv(lpid,argv,lpid); runtime=[_owned(lpid,argv,rt,rt_target)]
    if len(runtime)>1: raise RuntimeError("multiple owned DGER runtime processes")
    if len(writers)>1: raise RuntimeError("multiple owned DGER writer processes")
    return runtime,writers

def dup_files():
    expected=PLIST.resolve(strict=False); hits=[]
    for root in [Path("/Library/LaunchAgents"),Path("/Library/LaunchDaemons"),Path("/System/Library/LaunchAgents"),Path("/System/Library/LaunchDaemons"),Path.home()/"Library/LaunchAgents"]:
        p=root/f"{LABEL}.plist"
        if (p.exists() or p.is_symlink()) and p.resolve(strict=False)!=expected: hits.append(str(p))
    return hits
def discover():
    errors=[]; amb=[]
    if loaded("system"): amb.append("system-launchd-duplicate")
    amb += ["launchd-file:"+x for x in dup_files()]
    try:
        r,w=procs()
    except Exception as e:
        r=[]; w=[]; errors.append(str(e))
    user_loaded=loaded(f"gui/{os.getuid()}")
    return {"discovery_complete":not errors and not amb,"discovery_scopes":SCOPES,
            "discovered_runtime_ids":[RID],"discovered_writer_ids":[WID],
            "active_runtime_ids":[RID] if user_loaded or r else [],
            "active_writer_ids":[WID] if w else [],
            "runtime_process_ownership":r,"writer_process_ownership":w,
            "ambiguities":amb,"errors":errors}

def stop():
    run(["/bin/launchctl","bootout",f"gui/{os.getuid()}/{LABEL}"])
    r,w=procs()
    for item in w:
        try: os.kill(int(item["pid"]),signal.SIGTERM)
        except ProcessLookupError: pass
    end=time.time()+5
    while time.time()<end:
        r,w=procs()
        if not r and not w and not loaded(f"gui/{os.getuid()}"): return
        time.sleep(.1)
    raise RuntimeError("quiescence timeout")
def start():
    if loaded(f"gui/{os.getuid()}"): raise RuntimeError("already loaded")
    if not PLIST.is_file() or PLIST.is_symlink() or not LAUNCHER.is_file() or LAUNCHER.is_symlink(): raise RuntimeError("runtime files unavailable")
    rt=STATE/"runtime/current"
    if not rt.is_dir() or rt.is_symlink(): raise RuntimeError("runtime root unavailable")
    uenv=os.environ.copy(); uenv["UV_OFFLINE"]="1"; uenv["PATH"]="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
    up=subprocess.run(["/usr/bin/env","uv","sync","--locked"],cwd=rt,env=uenv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
    if up.returncode: raise RuntimeError("runtime environment provisioning failed")
    if run(["/bin/launchctl","bootstrap",f"gui/{os.getuid()}",str(PLIST)]).returncode: raise RuntimeError("bootstrap failed")
    if run(["/bin/launchctl","kickstart","-k",f"gui/{os.getuid()}/{LABEL}"]).returncode: raise RuntimeError("kickstart failed")
def dbroot():
    roots=[]; base=Path.home()/"Library/CloudStorage"
    if base.is_dir():
        for p in base.iterdir():
            m=p/"Software/NSP - Temporary Files"
            if p.is_dir() and not p.is_symlink() and m.is_dir() and not m.is_symlink(): roots.append(p.resolve())
    u=sorted({str(x) for x in roots})
    if len(u)!=1: raise RuntimeError("Dropbox root ambiguous")
    return Path(u[0])
def _surface_specs():
    rt=STATE/"runtime/current"
    return [
        (".python-version",rt/".python-version","0644"),
        ("pyproject.toml",rt/"pyproject.toml","0644"),
        ("uv.lock",rt/"uv.lock","0644"),
        ("scripts/dger.py",rt/"scripts/dger.py","0644"),
        ("src/dger/__init__.py",rt/"src/dger/__init__.py","0644"),
        ("src/dger/relay.py",rt/"src/dger/relay.py","0644"),
        ("launcher/dropbox-governed-execution-relay",rt/"launcher/dropbox-governed-execution-relay","0755"),
        ("launchagent/com.brettmacpro.chatgpt.dropbox-governed-execution-relay.plist",PLIST,"0644"),
    ]

def _surface_digest(rows):
    return hashlib.sha256((json.dumps(rows,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode()).hexdigest()

def _runtime_surface():
    rows=[]
    for source,path,mode in _surface_specs():
        _physical_file(path)
        st=path.lstat()
        if f"{stat.S_IMODE(st.st_mode):04o}"!=mode: raise RuntimeError(f"surface mode mismatch:{source}")
        data=path.read_bytes()
        rows.append({"source_path":source,"logical_path":source,"runtime_path":str(path),"mode":mode,"size":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    return _surface_digest(rows),rows

def _git_surface(commit):
    rows=[]
    for source,path,mode in _surface_specs():
        cp=run(["/usr/bin/git",f"--git-dir={DGER_BARE}","cat-file","blob",f"{commit}:{source}"])
        if cp.returncode: raise RuntimeError(f"candidate surface blob unavailable:{source}")
        m=run(["/usr/bin/git",f"--git-dir={DGER_BARE}","ls-tree",commit,"--",source])
        line=m.stdout.decode("utf-8","replace").strip()
        expected_git="100755" if mode=="0755" else "100644"
        if not line.startswith(expected_git+" blob "): raise RuntimeError(f"candidate surface mode mismatch:{source}:{line}")
        data=cp.stdout
        rows.append({"source_path":source,"logical_path":source,"runtime_path":str(path),"mode":mode,"size":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    return _surface_digest(rows),rows

def health():
    h=dbroot()/"Software/Dropbox Governed Execution Relay/V1/Control/health.json"
    try:
        _physical_file(h); st=h.lstat()
        if st.st_size>1024*1024: return None
        v=json.loads(h.read_text("utf-8"))
        return v if isinstance(v,dict) else None
    except Exception:
        return None

def _strict_sequence(h):
    if not isinstance(h,dict): return None
    v=h.get("sequence")
    return v if type(v) is int and v>=0 else None

def _utc_ts(v):
    if not isinstance(v,str) or not v.endswith("Z"): return None
    try:return datetime.strptime(v,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:return None

def _snapshot_valid(c,h,now_ts=None,expected_surface=None):
    if not isinstance(h,dict): return False
    now_ts=time.time() if now_ts is None else now_ts
    ts=_utc_ts(h.get("updated_at_utc"))
    if ts is None or ts>now_ts or now_ts-ts>HEALTH_STALE_SECONDS: return False
    if _strict_sequence(h) is None:return False
    expected={"schema_version":PROTOCOL,"protocol_version":PROTOCOL,"expected_interval_seconds":2,
              "qualified_gep_operation":OP,"qualified_gep_commit":GEP}
    if not all(h.get(k)==v for k,v in expected.items()): return False
    try:
        rt_sha,rt_rows=_runtime_surface()
        git_sha,git_rows=_git_surface(c["approved_commit"]) if expected_surface is None else expected_surface
    except Exception:return False
    if rt_sha!=git_sha or rt_rows!=git_rows:return False
    if h.get("dger_resident_surface_sha256")!=rt_sha:return False
    if h.get("dger_resident_surface")!=rt_rows:return False
    return True

def _pair_valid(first,second):
    a=_strict_sequence(first); b=_strict_sequence(second)
    if a is None or b is None or b<=a:return False
    t1=_utc_ts(first.get("updated_at_utc")); t2=_utc_ts(second.get("updated_at_utc"))
    return t1 is not None and t2 is not None and (t2-t1)>=2.0

def _progressing_health(c,baseline,expected_surface,health_fn=None,now_fn=None,monotonic_fn=None,sleep_fn=None):
    if type(baseline) is not int:return False
    health_fn=health if health_fn is None else health_fn
    now_fn=time.time if now_fn is None else now_fn
    monotonic_fn=time.monotonic if monotonic_fn is None else monotonic_fn
    sleep_fn=time.sleep if sleep_fn is None else sleep_fn
    deadline=monotonic_fn()+8.0; first=None
    while monotonic_fn()<deadline:
        h=health_fn(); seqv=_strict_sequence(h)
        if seqv is not None and seqv>baseline and _snapshot_valid(c,h,now_ts=now_fn(),expected_surface=expected_surface):
            first=h; break
        sleep_fn(.1)
    if first is None:return False
    not_before=monotonic_fn()+2.0
    sleep_fn(2.0)
    deadline=not_before+8.0
    while monotonic_fn()<deadline:
        if monotonic_fn()<not_before:
            sleep_fn(.1); continue
        h=health_fn()
        if _snapshot_valid(c,h,now_ts=now_fn(),expected_surface=expected_surface) and _pair_valid(first,h):return True
        sleep_fn(.1)
    return False

def seq():
    h=health(); v=_strict_sequence(h)
    return v if v is not None else -1

def state_path(c): return c.with_name("project_adapter_state.json")
def atomic_state(path, value):
    if path.is_symlink():
        raise RuntimeError("adapter state symlink")
    tmp = path.with_name("." + path.name + "." + str(os.getpid()) + ".tmp")
    if tmp.exists() or tmp.is_symlink():
        raise RuntimeError("adapter state temp collision")
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
def load_ctx(p):
    v=json.loads(p.read_text("utf-8")); exp={"runtime_ids":[RID],"writer_ids":[WID],"stop_required_ids":[RID],"leave_stopped_ids":[]}
    if v.get("schema_version")!=1 or v.get("project_id")!="dger-r0" or v.get("runtime_accounting")!=exp: raise ValueError("context mismatch")
    return v
def report(c,prior,healthy=None):
    d=discover()
    if not d["discovery_complete"]: raise RuntimeError(f"discovery incomplete:{d}")
    q=not d["active_runtime_ids"] and not d["active_writer_ids"]
    out={"nonce":c["nonce"],**d,"prior_active_runtime_ids":sorted(prior),"quiescent":q}
    if healthy is not None: out["healthy"]=bool(healthy)
    return out
def smoke(c,baseline):
    if not loaded(f"gui/{os.getuid()}"): return False
    try:
        r,w=procs()
        if len(r)!=1 or w: return False
        tr=run(["/usr/bin/git",f"--git-dir={DGER_BARE}","rev-parse",f"{c['approved_commit']}^{{tree}}"])
        if tr.returncode or tr.stdout.decode().strip()!=c.get("approved_tree"): return False
        expected_surface=_git_surface(c["approved_commit"])
    except Exception:return False
    return _progressing_health(c,baseline,expected_surface)

def emit(v,s,d,rc=0):
    print(json.dumps({"verb":v,"status":s,"details":d},sort_keys=True)); return rc
def main(a):
    v=a[1] if len(a)>1 else ""
    if len(a)!=4 or a[2]!="--context": return emit(v,"BLOCKED",{},70)
    p=Path(a[3])
    try:
        c=load_ctx(p)
        if c.get("verb")!=v: raise ValueError("verb mismatch")
        sp=state_path(p)
        if v=="quiesce":
            before=discover()
            if not before["discovery_complete"]: raise RuntimeError(f"initial discovery incomplete:{before}")
            prior=before["active_runtime_ids"]; baseline=seq()
            atomic_state(sp, {"run_id":c["run_id"],"prior":prior,"baseline":baseline})
            stop(); return emit(v,"PASS",report(c,prior))
        if sp.is_symlink() or not sp.is_file(): raise RuntimeError("adapter state unavailable")
        s=json.loads(sp.read_text("utf-8"))
        if s.get("run_id")!=c.get("run_id"): raise ValueError("state mismatch")
        prior=s["prior"]
        if v=="prove-quiescence": return emit(v,"PASS",report(c,prior))
        if v=="restart":
            expected=sorted(c.get("expected_restart_ids",[]))
            if expected not in ([],[RID]): raise RuntimeError("restart set mismatch")
            if expected:start()
            return emit(v,"PASS",{"nonce":c["nonce"],"restarted_runtime_ids":expected})
        if v=="runtime-smoke": return emit(v,"PASS",report(c,prior,smoke(c,int(s["baseline"]))))
        if v=="unquiesce": return emit(v,"PASS",{"nonce":c["nonce"]})
        raise ValueError("unsupported verb")
    except Exception as e:
        print(f"DGER_GOD_ADAPTER_BLOCKED:{e}",file=sys.stderr); return emit(v,"BLOCKED",{},70)
if __name__=="__main__": raise SystemExit(main(sys.argv))
