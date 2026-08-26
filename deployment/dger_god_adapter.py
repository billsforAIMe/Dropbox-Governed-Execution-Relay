#!/usr/bin/env python3
from __future__ import annotations
import json, os, signal, subprocess, sys, time
from pathlib import Path
LABEL="com.brettmacpro.chatgpt.dropbox-governed-execution-relay"
RID="dger.launchagent"; WID="dger.gep-child"
STATE=Path("/Users/brettmacpro/ChatGPT/State/Tools/Dropbox Governed Execution Relay")
PLIST=Path("/Users/brettmacpro/Library/LaunchAgents/com.brettmacpro.chatgpt.dropbox-governed-execution-relay.plist")
LAUNCHER=STATE/"runtime/current/launcher/dropbox-governed-execution-relay"
LEGACY=Path("/usr/local/bin/dropbox-governed-execution-relay")
PROTOCOL="DGER_R0_V1"; GEP="aa755d8941f7b0d46343c7e6b0d36c5f4cc40c15"; OP="platform.self_check"
SCOPES=["launchd-nonstandard","launchd-system","launchd-user","ownership-cwd","ownership-executable","ownership-symlink","processes","writers"]
def run(a,timeout=15): return subprocess.run([str(x) for x in a],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
def loaded(domain):
    return run(["/bin/launchctl","print",f"{domain}/{LABEL}"]).returncode==0
def procs():
    p=run(["/bin/ps","-axo","pid=,command="])
    if p.returncode: raise RuntimeError("ps failed")
    r=[]; w=[]; a=str(STATE/"attempts")+"/"; g="/gep-tree/scripts/governed_exec.py"; n=str(STATE/"runtime/current"); l=str(LEGACY)
    for line in p.stdout.decode("utf-8","replace").splitlines():
        q=line.strip().split(None,1)
        if len(q)!=2: continue
        try: pid=int(q[0])
        except: continue
        if pid==os.getpid(): continue
        cmd=q[1]
        if a in cmd and g in cmd: w.append((pid,cmd))
        if (n in cmd or l in cmd) and a not in cmd: r.append((pid,cmd))
    return r,w
def cwd(pid):
    p=run(["/usr/sbin/lsof","-a","-p",str(pid),"-d","cwd","-Fn"],5)
    if p.returncode not in (0,1): raise RuntimeError(f"cwd inspection failed:{pid}")
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
        for pid,_ in r+w: cwd(pid)
    except Exception as e: r=[]; w=[]; errors.append(str(e))
    return {"discovery_complete":not errors and not amb,"discovery_scopes":SCOPES,
            "discovered_runtime_ids":[RID],"discovered_writer_ids":[WID],
            "active_runtime_ids":[RID] if loaded(f"gui/{os.getuid()}") or r else [],
            "active_writer_ids":[WID] if w else [],"ambiguities":amb,"errors":errors}
def stop():
    run(["/bin/launchctl","bootout",f"gui/{os.getuid()}/{LABEL}"])
    r,w=procs()
    for pid,_ in r+w:
        try: os.kill(pid,signal.SIGTERM)
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
    up=subprocess.run(["/usr/local/bin/uv","sync","--locked"],cwd=rt,env=uenv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
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
def health():
    h=dbroot()/"Software/Dropbox Governed Execution Relay/V1/Control/health.json"
    if h.is_symlink() or not h.is_file(): return None
    try:return json.loads(h.read_text("utf-8"))
    except:return None
def seq():
    h=health()
    try:return int(h.get("sequence",-1)) if h else -1
    except:return -1
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
    h=health()
    if not h or not loaded(f"gui/{os.getuid()}"): return False
    try:
        if int(h["sequence"])<=baseline:return False
    except:return False
    e={"schema_version":PROTOCOL,"protocol_version":PROTOCOL,"expected_interval_seconds":2,
       "qualified_gep_operation":OP,"qualified_gep_commit":GEP,
       "dger_commit":c["approved_commit"],"dger_tree":c["approved_tree"]}
    return all(h.get(k)==v for k,v in e.items())
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
