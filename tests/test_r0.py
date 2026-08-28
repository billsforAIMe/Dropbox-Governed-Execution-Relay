from __future__ import annotations
import hashlib, json
from pathlib import Path
import os, sys, tempfile, unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from dger import relay

def request(rid): return {"schema_version":relay.REQUEST_SCHEMA,"request_id":rid,"project_id":relay.QUALIFIED_PROJECT,"operation_id":relay.QUALIFIED_OPERATION}
def publish(root:Path,rid:str,value=None):
    d=root/"Ingress"/rid; d.mkdir(parents=True,exist_ok=True)
    q=relay.canonical(value or request(rid)); h=hashlib.sha256(q).hexdigest()
    (d/"request.json").write_bytes(q)
    (d/"READY.json").write_bytes(relay.canonical({"schema_version":relay.READY_SCHEMA,"request_id":rid,"request_sha256":h,"request_size":len(q)}))
    return d

class R0Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name)/"transport"; self.state=Path(self.t.name)/"state"; self.r=relay.Relay(self.root,self.state,sleep=lambda _:None)
    def tearDown(self): self.t.cleanup()
    def rid(self,n=1): return f"r0-{n:032x}"
    def test_single_operation_fixed(self):
        self.assertEqual("platform.self_check",relay.QUALIFIED_OPERATION); self.assertEqual("ai-me",relay.QUALIFIED_PROJECT); self.assertEqual(2,relay.MAX_ATTEMPTS); self.assertEqual("Handoff100",relay.CHM_SLOT)
    def test_ready_before_request_waits(self):
        rid=self.rid(); d=self.root/"Ingress"/rid; d.mkdir(parents=True); q=relay.canonical(request(rid)); (d/"READY.json").write_bytes(relay.canonical({"schema_version":relay.READY_SCHEMA,"request_id":rid,"request_sha256":hashlib.sha256(q).hexdigest(),"request_size":len(q)})); self.assertIsNone(self.r.validate_package(d)); (d/"request.json").write_bytes(q); self.assertEqual(rid,self.r.validate_package(d)[0])
    def test_unknown_operation_blocks(self):
        rid=self.rid(); v=request(rid); v["operation_id"]="other"; d=publish(self.root,rid,v); self.assertIsNone(self.r.validate_package(d)); self.assertEqual("OPERATION_NOT_ALLOWLISTED",json.loads((self.root/"Runs"/rid/"result.json").read_text())["classification"])
    def test_noncanonical_request_blocks(self):
        rid=self.rid(); d=self.root/"Ingress"/rid; d.mkdir(parents=True); q=json.dumps(request(rid),indent=2).encode(); (d/"request.json").write_bytes(q); (d/"READY.json").write_bytes(relay.canonical({"schema_version":relay.READY_SCHEMA,"request_id":rid,"request_sha256":hashlib.sha256(q).hexdigest(),"request_size":len(q)})); self.assertIsNone(self.r.validate_package(d)); self.assertEqual("NONCANONICAL_REQUEST",json.loads((self.root/"Runs"/rid/"result.json").read_text())["classification"])
    def test_two_queued_sorted(self):
        publish(self.root,self.rid(2)); publish(self.root,self.rid(1)); seen=[]
        with mock.patch.object(relay,"resident_surface_identity",return_value=("0"*64,[])), mock.patch.object(self.r,"process_one",side_effect=lambda p: seen.append(p.name) or True): self.r.scan_once()
        self.assertEqual([self.rid(1),self.rid(2)],seen)
    def test_o_excl_claim_idempotent(self):
        rid=self.rid(); a=relay.claim_once(self.state,rid); b=relay.claim_once(self.state,rid); self.assertEqual(a,b); self.assertEqual(rid,json.loads(a.read_text())["request_id"])
    def test_dedicated_chm_slot_assignment(self):
        rid=self.rid(); value={"ok":True,"code":"HANDOFF_ASSIGNED","slot":relay.CHM_SLOT,"changed":False}
        with mock.patch.object(relay,"_run_chm",return_value=value) as run: self.assertEqual(relay.CHM_SLOT,relay.assign_slot(rid))
        run.assert_called_once_with(["assign",relay.CHM_SLOT,f"DGER_R0_{rid}"])
    def test_no_global_active_dependency(self):
        self.assertFalse(hasattr(relay,"_active")); self.assertFalse(hasattr(relay,"find_existing_route"))
    def test_dedicated_slot_busy_fails_closed(self):
        rid=self.rid(); value={"ok":False,"code":"HANDOFF_CONFLICT","status":"STARTED"}
        with mock.patch.object(relay,"_run_chm",return_value=value):
            with self.assertRaisesRegex(RuntimeError,"CHM_DEDICATED_SLOT_BUSY"): relay.assign_slot(rid)
    def test_chm_unavailable_no_gep(self):
        rid=self.rid(); d=publish(self.root,rid)
        with mock.patch.object(relay,"qualified",return_value=True), mock.patch.object(relay,"assign_slot",side_effect=RuntimeError("down")), mock.patch.object(relay,"start_gep") as start: self.r.process_one(d); start.assert_not_called()
        self.assertEqual("DEGRADED_CHM_UNAVAILABLE",json.loads((self.root/"Runs"/rid/"status.json").read_text())["state"])
    def test_classification_void_before_chm(self):
        rid=self.rid(); d=publish(self.root,rid)
        with mock.patch.object(relay,"qualified",return_value=False), mock.patch.object(relay,"assign_slot") as assign: self.r.process_one(d); assign.assert_not_called()
        self.assertEqual("CLASSIFICATION_VOID",json.loads((self.root/"Runs"/rid/"result.json").read_text())["classification"])
    def test_started_recovery_is_target_local(self):
        rid=self.rid(); d=publish(self.root,rid); cur={"request_id":rid,"attempts":0,"phase":"CHM_ASSIGNED","chm_slot":relay.CHM_SLOT,"claim_capability":"secret"}; relay.save_state(self.state,rid,cur)
        with mock.patch.object(relay,"qualified",return_value=True), mock.patch.object(relay,"transition",return_value={"ok":True,"recovered":True}) as trans, mock.patch.object(relay,"start_gep",side_effect=lambda state,rid,c: c): self.r.process_one(d)
        self.assertEqual("STARTED",trans.call_args.args[1]); self.assertEqual(relay.CHM_SLOT,trans.call_args.args[0])
    def test_transition_recovers_already_started(self):
        ctx=self.state/"ctx"; ctx.write_text("{}")
        value={"ok":False,"code":"INVALID_HANDOFF_TRANSITION","status":"STARTED"}
        with mock.patch.object(relay,"_run_chm",return_value=value): result=relay.transition(relay.CHM_SLOT,"STARTED",ctx)
        self.assertTrue(result["ok"]); self.assertTrue(result["recovered"])
    def test_transition_recovers_already_closed(self):
        ctx=self.state/"ctx2"; ctx.write_text("{}")
        value={"ok":False,"code":"INVALID_HANDOFF_TRANSITION","status":"CLOSED"}
        with mock.patch.object(relay,"_run_chm",return_value=value): result=relay.transition(relay.CHM_SLOT,"CLOSED",ctx)
        self.assertTrue(result["ok"]); self.assertTrue(result["recovered"])
    def test_transition_wrong_current_state_fails_closed(self):
        ctx=self.state/"ctx3"; ctx.write_text("{}")
        value={"ok":False,"code":"INVALID_HANDOFF_TRANSITION","status":"OPEN"}
        with mock.patch.object(relay,"_run_chm",return_value=value):
            with self.assertRaisesRegex(RuntimeError,"CHM_STATUS_FAILED"): relay.transition(relay.CHM_SLOT,"CLOSED",ctx)
    def test_live_orphan_not_relaunched(self):
        rid=self.rid(); d=publish(self.root,rid); cur={"request_id":rid,"attempts":1,"phase":"GEP_RUNNING","gep_pid":321,"gep_process_identity":"abc","attempt_dir":str(self.state/"attempt")}; relay.save_state(self.state,rid,cur)
        with mock.patch.object(relay,"qualified",return_value=True), mock.patch.object(relay,"read_gep_terminal",return_value=(None,"","")), mock.patch.object(relay,"is_same_live_process",return_value=True), mock.patch.object(relay,"start_gep") as start: self.r.process_one(d); start.assert_not_called()
    def test_attempt_cap_no_third_start(self):
        rid=self.rid(); d=publish(self.root,rid); cur={"request_id":rid,"attempts":2,"phase":"CHM_STARTED"}; relay.save_state(self.state,rid,cur)
        with mock.patch.object(relay,"qualified",return_value=True), mock.patch.object(relay,"start_gep") as start, mock.patch.object(self.r,"_finish_chm",return_value=True): self.r.process_one(d); start.assert_not_called()
        self.assertEqual("RERUN_LIMIT_EXCEEDED",json.loads((self.root/"Runs"/rid/"result.json").read_text())["classification"])
    def test_provision_gep_locked_canonical_environment(self):
        tree=Path(self.t.name)/"gep"; tree.mkdir(); (tree/".venv").mkdir()
        completed=mock.Mock(returncode=0,stdout="",stderr="")
        with mock.patch.object(relay.shutil,"which",return_value="/usr/local/bin/uv"), mock.patch.object(relay.subprocess,"run",return_value=completed) as run:
            relay.provision_gep(tree)
        args,kwargs=run.call_args
        self.assertEqual(["/usr/local/bin/uv","sync","--locked"],args[0])
        self.assertEqual(tree,kwargs["cwd"]); self.assertEqual("1",kwargs["env"]["UV_OFFLINE"])
    def test_start_gep_uses_strict_canonical_pyrunway(self):
        rid=self.rid(); tree=Path(self.t.name)/"gep-run"; (tree/"scripts").mkdir(parents=True); target=tree/"scripts"/"governed_exec.py"; target.write_text("pass\n")
        proc=mock.Mock(pid=4321)
        cur={"request_id":rid,"attempts":0,"phase":"CHM_STARTED"}
        with mock.patch.object(relay,"reconstruct_gep",return_value=tree.resolve()), mock.patch.object(relay,"provision_gep") as provision, mock.patch.object(relay.subprocess,"Popen",return_value=proc) as popen, mock.patch.object(relay,"process_identity",return_value="proc-id"):
            result=relay.start_gep(self.state,rid,cur)
        provision.assert_called_once_with(tree.resolve())
        args,kwargs=popen.call_args; cmd=args[0]
        self.assertEqual(str(relay.PYRUNWAY),cmd[0]); self.assertNotIn("--standalone",cmd); self.assertEqual(str(target.resolve()),cmd[1]); self.assertEqual(["self-check",relay.QUALIFIED_PROJECT],cmd[2:])
        self.assertEqual("1",kwargs["env"]["PYRUNWAY_STRICT"]); self.assertEqual(tree.resolve(),kwargs["cwd"]); self.assertTrue(kwargs["start_new_session"]); self.assertEqual(1,result["attempts"])
    def test_terminal_result_write_once(self):
        rid=self.rid(); self.r.result(rid,"SUCCESS","ONE"); self.r.result(rid,"BLOCKED","TWO"); self.assertEqual("ONE",json.loads((self.root/"Runs"/rid/"result.json").read_text())["classification"])
    def test_health_sequence_monotonic(self):
        with mock.patch.object(relay,"resident_surface_identity",return_value=("0"*64,[])):
            self.r.heartbeat(); a=json.loads((self.root/"Control"/"health.json").read_text())["sequence"]; self.r.heartbeat(); b=json.loads((self.root/"Control"/"health.json").read_text())["sequence"]; self.assertGreater(b,a)

    def test_state_root_symlink_rejected_before_resolve(self):
        target=Path(self.t.name)/"real-state"; target.mkdir(); link=Path(self.t.name)/"state-link"; link.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,"UNSAFE_RELAY_PATH"): relay.Relay(Path(self.t.name)/"transport2",link,sleep=lambda _:None)
    def test_launch_reservation_persisted_before_child_identity(self):
        rid=self.rid(40); ad=self.state/"fake-attempt"; tree=ad/"gep-tree"; (tree/"scripts").mkdir(parents=True); (tree/"scripts"/"governed_exec.py").write_text("# fake\n")
        cur={"request_id":rid,"attempts":0,"phase":"CHM_STARTED"}; relay.save_state(self.state,rid,cur)
        fake=mock.Mock(pid=4321)
        with mock.patch.object(relay,"reconstruct_gep",return_value=tree), mock.patch.object(relay,"provision_gep"), mock.patch.object(relay.subprocess,"Popen",return_value=fake) as popen, mock.patch.object(relay,"process_identity",side_effect=SystemExit("simulated relay crash after Popen")):
            with self.assertRaises(SystemExit): relay.start_gep(self.state,rid,cur)
        saved=relay.read_state(self.state,rid)
        self.assertEqual("GEP_STARTING",saved["phase"]); self.assertEqual(1,saved["attempts"]); self.assertTrue(saved["gep_target"].endswith("/scripts/governed_exec.py")); popen.assert_called_once()
    def test_starting_crash_window_adopts_without_relaunch(self):
        rid=self.rid(41); d=publish(self.root,rid); ad=self.state/"attempts"/rid/"attempt-1"; tree=ad/"gep-tree"; target=tree/"scripts"/"governed_exec.py"; target.parent.mkdir(parents=True); target.write_text("# fake\n"); (tree/".venv/bin").mkdir(parents=True); py=tree/".venv/bin/python"; py.write_text("x")
        cur={"request_id":rid,"attempts":1,"phase":"GEP_STARTING","attempt_dir":str(ad),"gep_target":str(target.resolve()),"chm_slot":relay.CHM_SLOT}; relay.save_state(self.state,rid,cur)
        info={"pid":4321,"ppid":1,"uid":os.getuid(),"start_sec":10,"start_usec":20}; argv=[str(py.resolve()),str(target.resolve()),"self-check",relay.QUALIFIED_PROJECT]
        def names(pid,desc):return [str(tree.resolve())] if desc=="cwd" else [str(py.resolve())]
        with mock.patch.object(relay,"qualified",return_value=True),mock.patch.object(relay,"read_gep_terminal",return_value=(None,"","")),mock.patch.object(relay,"_native_pids",return_value=[4321]),mock.patch.object(relay,"_bsd_identity",return_value=info),mock.patch.object(relay,"_native_argv",return_value=argv),mock.patch.object(relay,"_lsof_names",side_effect=names),mock.patch.object(relay,"start_gep") as start:
            self.r.process_one(d); start.assert_not_called()
        saved=relay.read_state(self.state,rid); self.assertEqual("GEP_RUNNING",saved["phase"]); self.assertEqual(1,saved["attempts"]); self.assertEqual(4321,saved["gep_pid"]); self.assertRegex(saved["gep_process_identity"],r"^[0-9a-f]{64}$")
    def test_second_starting_reservation_cannot_launch_third_attempt(self):
        rid=self.rid(42); d=publish(self.root,rid); ad=self.state/"attempts"/rid/"attempt-2"; target=ad/"gep-tree"/"scripts"/"governed_exec.py"; target.parent.mkdir(parents=True); target.write_text("# fake\n")
        cur={"request_id":rid,"attempts":2,"phase":"GEP_STARTING","attempt_dir":str(ad),"gep_target":str(target),"chm_slot":relay.CHM_SLOT}; relay.save_state(self.state,rid,cur)
        with mock.patch.object(relay,"qualified",return_value=True), mock.patch.object(relay,"read_gep_terminal",return_value=(None,"","")), mock.patch.object(relay,"find_attempt_process",return_value=None), mock.patch.object(relay,"start_gep") as start, mock.patch.object(self.r,"_finish_chm",return_value=True):
            self.r.process_one(d); start.assert_not_called()
        result=json.loads((self.root/"Runs"/rid/"result.json").read_text()); self.assertEqual("RERUN_LIMIT_EXCEEDED",result["classification"]); self.assertEqual(2,result["attempts"])

if __name__=="__main__": unittest.main(verbosity=2)
