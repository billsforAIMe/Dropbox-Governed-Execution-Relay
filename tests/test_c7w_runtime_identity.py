from __future__ import annotations
import copy
import importlib.util
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
adapter_spec=importlib.util.spec_from_file_location("dger_god_adapter_c7w",ROOT/"deployment/dger_god_adapter.py")
if adapter_spec is None or adapter_spec.loader is None: raise RuntimeError("adapter spec unavailable")
adapter=importlib.util.module_from_spec(adapter_spec); adapter_spec.loader.exec_module(adapter)
relay_spec=importlib.util.spec_from_file_location("dger_relay_c7w",ROOT/"src/dger/relay.py")
if relay_spec is None or relay_spec.loader is None: raise RuntimeError("relay spec unavailable")
relay=importlib.util.module_from_spec(relay_spec); relay_spec.loader.exec_module(relay)
canonical=relay.canonical; digest=relay.digest
PROD_STATE=Path("/Users/brettmacpro/ChatGPT/State/Tools/Dropbox Governed Execution Relay")
r0_spec=importlib.util.spec_from_file_location("dger_test_r0_c7p_helper",ROOT/"tests/test_r0.py")
if r0_spec is None or r0_spec.loader is None: raise RuntimeError("test_r0 helper spec unavailable")
r0_helper=importlib.util.module_from_spec(r0_spec); r0_spec.loader.exec_module(r0_helper)
publish=r0_helper.publish

class C7WIdentityTests(unittest.TestCase):
    def rows(self): return [{"source_path":"a","logical_path":"a","runtime_path":"/r/a","mode":"0644","size":1,"sha256":"0"*64}]
    def good_health(self,seq=2,ts="2026-08-28T00:00:01Z"):
        return {"schema_version":adapter.PROTOCOL,"protocol_version":adapter.PROTOCOL,"expected_interval_seconds":2,"qualified_gep_operation":adapter.OP,"qualified_gep_commit":adapter.GEP,"sequence":seq,"updated_at_utc":ts,"dger_resident_surface_sha256":"x","dger_resident_surface":[]}
    def test_surface_digest_stable_and_sensitive(self):
        a=self.rows(); self.assertEqual(adapter._surface_digest(a),adapter._surface_digest(copy.deepcopy(a)))
        for key,value in (("sha256","1"*64),("mode","0755"),("runtime_path","/other/a")):
            b=copy.deepcopy(a); b[0][key]=value; self.assertNotEqual(adapter._surface_digest(a),adapter._surface_digest(b))
    def test_sequence_is_strict_integral_not_bool_string_or_float(self):
        self.assertEqual(adapter._strict_sequence({"sequence":2}),2)
        for bad in (True,"2",2.0,-1,None): self.assertIsNone(adapter._strict_sequence({"sequence":bad}))
    def test_pair_requires_strict_sequence_and_time(self):
        a={"sequence":4,"updated_at_utc":"2026-08-28T00:00:00Z"}; b={"sequence":5,"updated_at_utc":"2026-08-28T00:00:02Z"}
        self.assertTrue(adapter._pair_valid(a,b)); self.assertFalse(adapter._pair_valid(a,{**b,"sequence":4})); self.assertFalse(adapter._pair_valid(a,{**b,"sequence":True})); self.assertFalse(adapter._pair_valid(a,{**b,"updated_at_utc":a["updated_at_utc"]})); self.assertFalse(adapter._pair_valid(a,{**b,"updated_at_utc":"2026-08-28T00:00:01Z"}))
    def test_snapshot_time_and_surface_fail_closed(self):
        c={"approved_commit":"a"*40}; h=self.good_health(); now=adapter._utc_ts("2026-08-28T00:00:02Z")
        self.assertIsNotNone(now)
        with mock.patch.object(adapter,"_runtime_surface",return_value=("x",[])):
            self.assertTrue(adapter._snapshot_valid(c,h,now_ts=now,expected_surface=("x",[]))); self.assertFalse(adapter._snapshot_valid(c,{**h,"updated_at_utc":"bad"},now_ts=now,expected_surface=("x",[]))); self.assertFalse(adapter._snapshot_valid(c,{**h,"updated_at_utc":"2026-08-28T00:00:20Z"},now_ts=now,expected_surface=("x",[]))); self.assertFalse(adapter._snapshot_valid(c,{**h,"updated_at_utc":"2026-08-27T23:59:00Z"},now_ts=now,expected_surface=("x",[]))); self.assertFalse(adapter._snapshot_valid(c,{**h,"dger_resident_surface_sha256":"wrong"},now_ts=now,expected_surface=("x",[])))
    def test_progressing_health_positive_and_nonprogressing(self):
        c={"approved_commit":"a"*40}; one=self.good_health(2,"2026-08-28T00:00:00Z"); two=self.good_health(3,"2026-08-28T00:00:02Z"); now=adapter._utc_ts("2026-08-28T00:00:03Z")
        self.assertIsNotNone(now)
        class Clock:
            def __init__(self): self.t=0.0
            def mono(self): return self.t
            def sleep(self,seconds): self.t+=seconds
        clock=Clock()
        with mock.patch.object(adapter,"_runtime_surface",return_value=("x",[])):
            health_values=iter([one,two])
            self.assertTrue(adapter._progressing_health(c,1,("x",[]),health_fn=lambda: next(health_values),now_fn=lambda: now,monotonic_fn=clock.mono,sleep_fn=clock.sleep))
        clock=Clock()
        with mock.patch.object(adapter,"_runtime_surface",return_value=("x",[])):
            self.assertFalse(adapter._progressing_health(c,1,("x",[]),health_fn=lambda: one,now_fn=lambda: now,monotonic_fn=clock.mono,sleep_fn=clock.sleep))
    def test_relay_canonical_surface_hash_is_deterministic(self): self.assertEqual(digest(canonical(self.rows())),adapter._surface_digest(self.rows()))
    def test_adoption_doc_epoch2_authority(self):
        s=(ROOT/"docs/GOD_ADOPTION.md").read_text("utf-8")
        self.assertIn("binding epoch 2",s); self.assertIn("29efe52c22a882d433d33c6710d63111f56ceb73a6592a2779310e5d34df9e4c",s); self.assertIn("e53851c9e0976436518271329705730f5199e9bc819ac88cc8f0f829e2b4eeff",s); self.assertIn("cf305ce10143fb2a4f7cbcbf24b1500d441b0a0e",s); self.assertIn("non-operative",s); self.assertIn("does not remain in force",s)
    def test_launchctl_pid_parser_and_lsof_parser(self):
        cp=mock.Mock(returncode=0,stdout=b" pid = 123\n",stderr=b"")
        with mock.patch.object(adapter,"run",return_value=cp): self.assertEqual(adapter._launchctl_pid(),123)
        cp2=mock.Mock(returncode=0,stdout=b"p123\nn/tmp/a\n",stderr=b"")
        with mock.patch.object(adapter,"run",return_value=cp2): self.assertEqual(adapter._lsof_names(123,"cwd"),["/tmp/a"])
    def test_native_argv_parser_preserves_exact_space_path(self):
        target=str(PROD_STATE/"runtime/current/scripts/dger.py"); argv=["/opt/homebrew/bin/python3",target,"--flag"]
        raw=struct.pack("=i",len(argv))+b"/opt/homebrew/bin/python3\0\0"+b"\0".join(x.encode() for x in argv)+b"\0ENV=x\0"
        self.assertEqual(adapter._argv_from_procargs(raw,77),argv); self.assertEqual(adapter._argv_from_procargs(raw,77)[1],target)
    def test_native_argv_parser_rejects_malformed(self):
        for raw in (b"",struct.pack("=i",0)+b"x\0",struct.pack("=i",2)+b"x\0\0a\0"):
            with self.assertRaises(RuntimeError): adapter._argv_from_procargs(raw,77)
    def test_native_argv_current_process_on_darwin(self):
        self.assertEqual(sys.platform,"darwin"); argv=adapter._native_argv(os.getpid()); self.assertTrue(argv); self.assertTrue(all(isinstance(x,str) and x for x in argv)); info=adapter._bsd_identity(os.getpid()); self.assertEqual(info["pid"],os.getpid()); self.assertEqual(info["uid"],os.getuid()); self.assertGreater(info["start_sec"],0)
    def test_production_space_runtime_and_writer_classification(self):
        rt=str(PROD_STATE/"runtime/current/scripts/dger.py"); writer=str(PROD_STATE/"attempts/r0-00000000000000000000000000000001/attempt-1/gep-tree/scripts/governed_exec.py")
        with mock.patch.object(adapter,"STATE",PROD_STATE):
            self.assertEqual(adapter._classify_argv(101,["/python",rt],101)["runtime_target"],rt); self.assertEqual(adapter._classify_argv(102,["/python",writer,"self-check","ai-me"],101)["writer_target"],writer)
    def test_production_space_duplicate_writer_fails(self):
        w1=str(PROD_STATE/"attempts/a/gep-tree/scripts/governed_exec.py"); w2=str(PROD_STATE/"attempts/b/gep-tree/scripts/governed_exec.py")
        with mock.patch.object(adapter,"STATE",PROD_STATE), mock.patch.object(adapter,"_ps_pids",return_value=[(201,os.getuid()),(202,os.getuid())]), mock.patch.object(adapter,"_launchctl_pid",return_value=None), mock.patch.object(adapter,"_native_argv",side_effect=lambda p:["/python",w1 if p==201 else w2,"self-check","ai-me"]), mock.patch.object(adapter,"_no_symlink_components"), mock.patch.object(adapter,"_physical_file",side_effect=lambda p:Path(p)), mock.patch.object(adapter,"_physical_dir",side_effect=lambda p:Path(p)), mock.patch.object(adapter,"_owned",side_effect=lambda p,c,t,r,l:{"pid":p}):
            with self.assertRaisesRegex(RuntimeError,"multiple owned DGER writer"): adapter.procs()
    def test_production_space_unowned_and_legacy_fail(self):
        with mock.patch.object(adapter,"STATE",PROD_STATE):
            with self.assertRaisesRegex(RuntimeError,"plausible unowned"): adapter._classify_argv(1,["/python","/tmp/dger.py"],None)
            with self.assertRaisesRegex(RuntimeError,"legacy DGER"): adapter._classify_argv(1,[str(adapter.LEGACY)],None)
    def test_production_space_wrong_target_fails(self):
        wrong=str(PROD_STATE/"runtime/current/scripts/not-dger.py"); plausible=str(PROD_STATE/"other/dger.py")
        with mock.patch.object(adapter,"STATE",PROD_STATE):
            self.assertIsNone(adapter._classify_argv(3,["/python",wrong],None)["runtime_target"])
            with self.assertRaisesRegex(RuntimeError,"plausible unowned"): adapter._classify_argv(3,["/python",plausible],None)
    def test_owned_process_valid_wrong_cwd_wrong_executable_and_symlink_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="DGER Adapter state space ",dir="/private/tmp") as td:
            root=Path(td); state=root/"Dropbox Governed Execution Relay"; rt=state/"runtime/current"; target=rt/"scripts/dger.py"; target.parent.mkdir(parents=True); target.write_text("x"); (rt/".venv/bin").mkdir(parents=True); py=rt/".venv/bin/python"; py.write_text("x")
            def names(pid,desc): return [str(rt)] if desc=="cwd" else [str(py)]
            info={"pid":9,"ppid":1,"uid":os.getuid(),"start_sec":10,"start_usec":20}
            with mock.patch.object(adapter,"STATE",state),mock.patch.object(adapter,"_bsd_identity",side_effect=[info,dict(info)]),mock.patch.object(adapter,"_native_argv",return_value=[str(py),str(target)]),mock.patch.object(adapter,"_lsof_names",side_effect=names): self.assertEqual(adapter._owned(9,rt,target,"runtime",9)["target"],str(target))
            other=root/"other"; other.mkdir()
            def badcwd(pid,desc): return [str(other)] if desc=="cwd" else [str(py)]
            with mock.patch.object(adapter,"STATE",state),mock.patch.object(adapter,"_bsd_identity",return_value=info),mock.patch.object(adapter,"_native_argv",return_value=[str(py),str(target)]),mock.patch.object(adapter,"_lsof_names",side_effect=badcwd):
                with self.assertRaisesRegex(RuntimeError,"cwd ownership"): adapter._owned(9,rt,target,"runtime",9)
            badexe=root/"python"; badexe.write_text("x")
            def badtxt(pid,desc): return [str(rt)] if desc=="cwd" else [str(badexe)]
            with mock.patch.object(adapter,"STATE",state),mock.patch.object(adapter,"_bsd_identity",return_value=info),mock.patch.object(adapter,"_native_argv",return_value=[str(py),str(target)]),mock.patch.object(adapter,"_lsof_names",side_effect=badtxt):
                with self.assertRaisesRegex(RuntimeError,"executable ownership"): adapter._owned(9,rt,target,"runtime",9)
            link=root/"link"; link.symlink_to(rt,target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError,"symlink"): adapter._physical_dir(link)
    def test_missing_lsof_and_ambiguous_cwd_fail(self):
        with mock.patch.object(adapter,"_lsof_names",return_value=[]):
            with self.assertRaisesRegex(RuntimeError,"cwd ownership ambiguous"): adapter.cwd(1)
        with mock.patch.object(adapter,"_lsof_names",return_value=["/a","/b"]):
            with self.assertRaisesRegex(RuntimeError,"cwd ownership ambiguous"): adapter.cwd(1)
    def test_launchctl_pid_must_be_same_user_and_exact_target(self):
        with mock.patch.object(adapter,"STATE",PROD_STATE), mock.patch.object(adapter,"_ps_pids",return_value=[]), mock.patch.object(adapter,"_launchctl_pid",return_value=400):
            with self.assertRaisesRegex(RuntimeError,"same-user pid set"): adapter.procs()
        rt=str(PROD_STATE/"runtime/current/scripts/dger.py")
        with mock.patch.object(adapter,"STATE",PROD_STATE):
            with self.assertRaisesRegex(RuntimeError,"unowned DGER runtime"): adapter._classify_argv(401,["/python",rt],400)

    def _relay_attempt_fixture(self, root):
        tree=root/"attempts"/"r0-00000000000000000000000000000001"/"attempt-1"/"gep-tree"; (tree/"scripts").mkdir(parents=True); target=tree/"scripts/governed_exec.py"; target.write_text("x")
        (tree/".venv/bin").mkdir(parents=True); py=tree/".venv/bin/python"; py.write_text("x")
        return tree.resolve(),target.resolve(),py.resolve()
    def test_relay_native_procargs_parser_preserves_production_space_target(self):
        target=str(PROD_STATE/"attempts/r0-00000000000000000000000000000001/attempt-1/gep-tree/scripts/governed_exec.py"); argv=["/opt/homebrew/bin/python3",target,"self-check",relay.QUALIFIED_PROJECT]
        raw=struct.pack("=i",len(argv))+b"/opt/homebrew/bin/python3\0\0"+b"\0".join(x.encode() for x in argv)+b"\0ENV=x\0"; self.assertEqual(relay._argv_from_procargs(raw,88),argv)
    def test_relay_native_bsd_identity_and_pid_enumeration_current_process(self):
        self.assertEqual(sys.platform,"darwin"); info=relay._bsd_identity(os.getpid()); self.assertEqual(info["pid"],os.getpid()); self.assertEqual(info["uid"],os.getuid()); self.assertGreater(info["start_sec"],0); self.assertIn(os.getpid(),relay._native_pids())
    def test_relay_owned_attempt_process_positive_and_pid_reuse(self):
        with tempfile.TemporaryDirectory(prefix="DGER Relay space ",dir="/private/tmp") as td:
            tree,target,py=self._relay_attempt_fixture(Path(td)); info={"pid":901,"ppid":1,"uid":os.getuid(),"start_sec":10,"start_usec":20}; argv=[str(py),str(target),"self-check",relay.QUALIFIED_PROJECT]
            def names(pid,desc):return [str(tree)] if desc=="cwd" else [str(py)]
            with mock.patch.object(relay,"_bsd_identity",side_effect=[info,dict(info)]),mock.patch.object(relay,"_native_argv",return_value=argv),mock.patch.object(relay,"_lsof_names",side_effect=names): rec=relay._owned_attempt_process(901,str(target)); self.assertEqual(rec["target"],str(target))
            with mock.patch.object(relay,"_bsd_identity",side_effect=[info,{**info,"start_usec":21}]),mock.patch.object(relay,"_native_argv",return_value=argv),mock.patch.object(relay,"_lsof_names",side_effect=names):
                with self.assertRaisesRegex(RuntimeError,"PID_REUSED"):relay._owned_attempt_process(901,str(target))
    def test_relay_find_attempt_process_rejects_target_as_unrelated_argument(self):
        with tempfile.TemporaryDirectory(prefix="DGER Relay space ",dir="/private/tmp") as td:
            tree,target,py=self._relay_attempt_fixture(Path(td)); info={"pid":902,"ppid":1,"uid":os.getuid(),"start_sec":10,"start_usec":20}
            with mock.patch.object(relay,"_native_pids",return_value=[902]),mock.patch.object(relay,"_bsd_identity",return_value=info),mock.patch.object(relay,"_native_argv",return_value=[str(py),"-c","print(1)",str(target)]):
                with self.assertRaisesRegex(RuntimeError,"UNOWNED_GEP_ATTEMPT_TARGET_PROCESS"):relay.find_attempt_process(str(target))
    def test_relay_find_attempt_process_ignores_prefix_wrong_target(self):
        with tempfile.TemporaryDirectory(prefix="DGER Relay space ",dir="/private/tmp") as td:
            tree,target,py=self._relay_attempt_fixture(Path(td)); info={"pid":903,"ppid":1,"uid":os.getuid(),"start_sec":10,"start_usec":20}
            with mock.patch.object(relay,"_native_pids",return_value=[903]),mock.patch.object(relay,"_bsd_identity",return_value=info),mock.patch.object(relay,"_native_argv",return_value=[str(py),str(target)+".wrong","self-check",relay.QUALIFIED_PROJECT]):self.assertIsNone(relay.find_attempt_process(str(target)))
    def test_relay_find_attempt_process_duplicate_exact_owned_fails(self):
        with tempfile.TemporaryDirectory(prefix="DGER Relay space ",dir="/private/tmp") as td:
            tree,target,py=self._relay_attempt_fixture(Path(td)); info=lambda p:{"pid":p,"ppid":1,"uid":os.getuid(),"start_sec":10,"start_usec":p}; argv=[str(py),str(target),"self-check",relay.QUALIFIED_PROJECT]
            with mock.patch.object(relay,"_native_pids",return_value=[904,905]),mock.patch.object(relay,"_bsd_identity",side_effect=lambda p:info(p)),mock.patch.object(relay,"_native_argv",return_value=argv),mock.patch.object(relay,"_owned_attempt_process",side_effect=lambda p,t:{"pid":p,"uid":os.getuid(),"ppid":1,"start_sec":10,"start_usec":p,"argv":argv,"cwd":str(tree),"txt":str(py),"target":str(target)}):
                with self.assertRaisesRegex(RuntimeError,"MULTIPLE_GEP_ATTEMPT_PROCESSES"):relay.find_attempt_process(str(target))
    def test_relay_find_attempt_process_ownership_negatives_fail(self):
        with tempfile.TemporaryDirectory(prefix="DGER Relay space ",dir="/private/tmp") as td:
            root=Path(td); tree,target,py=self._relay_attempt_fixture(root); info={"pid":906,"ppid":1,"uid":os.getuid(),"start_sec":10,"start_usec":20}; argv=[str(py),str(target),"self-check",relay.QUALIFIED_PROJECT]; other=root/"other"; other.mkdir(); bad=root/"badpython"; bad.write_text("x")
            def run_find(names):
                with mock.patch.object(relay,"_native_pids",return_value=[906]),mock.patch.object(relay,"_bsd_identity",side_effect=[info,info,info]),mock.patch.object(relay,"_native_argv",return_value=argv),mock.patch.object(relay,"_lsof_names",side_effect=names):
                    with self.assertRaisesRegex(RuntimeError,"UNOWNED_GEP_ATTEMPT_TARGET_PROCESS"):relay.find_attempt_process(str(target))
            def badcwd(pid,desc):return [str(other)] if desc=="cwd" else [str(py)]
            run_find(badcwd)
            def badtxt(pid,desc):return [str(tree)] if desc=="cwd" else [str(bad)]
            run_find(badtxt)
            # PID reuse during ownership proof must also fail through the real discovery path.
            def names(pid,desc):return [str(tree)] if desc=="cwd" else [str(py)]
            with mock.patch.object(relay,"_native_pids",return_value=[906]),mock.patch.object(relay,"_bsd_identity",side_effect=[info,info,{**info,"start_usec":21}]),mock.patch.object(relay,"_native_argv",return_value=argv),mock.patch.object(relay,"_lsof_names",side_effect=names):
                with self.assertRaisesRegex(RuntimeError,"UNOWNED_GEP_ATTEMPT_TARGET_PROCESS"):relay.find_attempt_process(str(target))
            link=root/"link"; link.symlink_to(tree,target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError,"SYMLINK"):relay._expected_gep_target(link/"scripts/governed_exec.py")
    def test_relay_process_identity_rejects_pid_reuse_and_wrong_uid(self):
        with tempfile.TemporaryDirectory(prefix="DGER Relay space ",dir="/private/tmp") as td:
            tree,target,py=self._relay_attempt_fixture(Path(td)); argv=[str(py),str(target),"self-check",relay.QUALIFIED_PROJECT]; base={"pid":907,"ppid":1,"uid":os.getuid(),"start_sec":10,"start_usec":20}; names=lambda pid,desc:[str(tree)] if desc=="cwd" else [str(py)]
            with mock.patch.object(relay,"_native_argv",return_value=argv),mock.patch.object(relay,"_bsd_identity",side_effect=[base,base]),mock.patch.object(relay,"_lsof_names",side_effect=names):ident=relay.process_identity(907)
            self.assertRegex(ident or "",r"^[0-9a-f]{64}$")
            with mock.patch.object(relay,"_native_argv",return_value=argv),mock.patch.object(relay,"_bsd_identity",side_effect=[{**base,"start_usec":21},{**base,"start_usec":21}]),mock.patch.object(relay,"_lsof_names",side_effect=names):self.assertFalse(relay.is_same_live_process(907,ident))
            with mock.patch.object(relay,"_native_pids",return_value=[907]),mock.patch.object(relay,"_bsd_identity",return_value={**base,"uid":os.getuid()+1}),mock.patch.object(relay,"_native_argv",return_value=argv):self.assertIsNone(relay.find_attempt_process(str(target)))
    def test_relay_prefilter_argv_pid_reuse_before_guard_fails_real_find_and_process_one(self):
        with tempfile.TemporaryDirectory(prefix="DGER Relay PID reuse space ",dir="/private/tmp") as td:
            root=Path(td); tree,target,py=self._relay_attempt_fixture(root)
            old={"pid":908,"ppid":1,"uid":os.getuid(),"start_sec":10,"start_usec":20}
            replacement={"pid":908,"ppid":1,"uid":os.getuid(),"start_sec":11,"start_usec":1}
            old_argv=[str(py),str(target),"self-check",relay.QUALIFIED_PROJECT]
            replacement_argv=[str(py),"-c","print('replacement')"]
            names=lambda pid,desc:[str(tree)] if desc=="cwd" else [str(py)]
            # The preliminary filter sees the old process.  The guarded proof begins on the
            # replacement incarnation and MUST re-read argv, rejecting it despite same UID/cwd/TXT.
            with mock.patch.object(relay,"_native_pids",return_value=[908]),mock.patch.object(relay,"_native_argv",side_effect=[old_argv,replacement_argv]),mock.patch.object(relay,"_bsd_identity",side_effect=[old,replacement]),mock.patch.object(relay,"_lsof_names",side_effect=names):
                with self.assertRaisesRegex(RuntimeError,"UNOWNED_GEP_ATTEMPT_TARGET_PROCESS"):relay.find_attempt_process(str(target))
            rid="r0-00000000000000000000000000000063"; transport=root/"transport"; state=root/"state"; rr=relay.Relay(transport,state,sleep=lambda _:None); d=publish(transport,rid)
            ad=state/"attempts"/rid/"attempt-1"; rt=ad/"gep-tree"; shutil.copytree(tree,rt); target2=(rt/"scripts/governed_exec.py").resolve(); py2=(rt/".venv/bin/python").resolve()
            cur={"request_id":rid,"attempts":1,"phase":"GEP_STARTING","attempt_dir":str(ad),"gep_target":str(target2),"chm_slot":relay.CHM_SLOT}; relay.save_state(state,rid,cur)
            old_argv2=[str(py2),str(target2),"self-check",relay.QUALIFIED_PROJECT]; replacement_argv2=[str(py2),"-c","print('replacement')"]
            names2=lambda pid,desc:[str(rt.resolve())] if desc=="cwd" else [str(py2)]
            with mock.patch.object(relay,"qualified",return_value=True),mock.patch.object(relay,"read_gep_terminal",return_value=(None,"","")),mock.patch.object(relay,"_native_pids",return_value=[908]),mock.patch.object(relay,"_native_argv",side_effect=[old_argv2,replacement_argv2]),mock.patch.object(relay,"_bsd_identity",side_effect=[old,replacement]),mock.patch.object(relay,"_lsof_names",side_effect=names2),mock.patch.object(relay,"start_gep") as start:
                with self.assertRaisesRegex(RuntimeError,"UNOWNED_GEP_ATTEMPT_TARGET_PROCESS"):rr.process_one(d)
                start.assert_not_called()
            saved=relay.read_state(state,rid); self.assertEqual("GEP_STARTING",saved["phase"]); self.assertNotIn("gep_pid",saved); self.assertNotIn("gep_process_identity",saved)
    def test_relay_process_identity_argv_is_inside_guarded_interval(self):
        with tempfile.TemporaryDirectory(prefix="DGER Relay process identity ",dir="/private/tmp") as td:
            tree,target,py=self._relay_attempt_fixture(Path(td)); before={"pid":909,"ppid":1,"uid":os.getuid(),"start_sec":20,"start_usec":2}; after={**before,"start_usec":3}; argv=[str(py),str(target),"self-check",relay.QUALIFIED_PROJECT]; names=lambda pid,desc:[str(tree)] if desc=="cwd" else [str(py)]
            events=[]
            def bsd(pid): events.append("bsd"); return before if events.count("bsd")==1 else after
            def nav(pid): events.append("argv"); return argv
            with mock.patch.object(relay,"_bsd_identity",side_effect=bsd),mock.patch.object(relay,"_native_argv",side_effect=nav),mock.patch.object(relay,"_lsof_names",side_effect=names):self.assertIsNone(relay.process_identity(909))
            self.assertEqual(events[:2],["bsd","argv"])
    def test_relay_source_has_no_rendered_command_discovery_or_fingerprint(self):
        text=(ROOT/"src/dger/relay.py").read_text("utf-8"); self.assertNotIn("pid=,command=",text); self.assertNotIn('"command="',text); self.assertNotIn("physical not in parts[1]",text); self.assertIn("proc_pidinfo",text); self.assertIn("proc_listallpids",text); self.assertIn("KERN_PROCARGS2",text)

    def test_adoption_doc_exact_guarded_recovery_contract(self):
        s=(ROOT/"docs/GOD_ADOPTION.md").read_text("utf-8")
        self.assertIn("first native `proc_bsdinfo` identity",s); self.assertIn("second native `proc_bsdinfo` identity must equal the first exactly",s)
        self.assertIn("Preliminary argv/classification is filter-only",s); self.assertIn("Rendered `ps command=` text",s); self.assertIn("target containment is **never sufficient ownership proof**",s)
        self.assertNotIn("adopts only a live process whose command contains",s); self.assertIn("exact argv suffix",s); self.assertIn("never sends a PID-only signal",s); self.assertIn("blocks quiescence",s)
    def test_adapter_prefilter_pid_reuse_blocks_procs_and_stop_no_signal(self):
        with tempfile.TemporaryDirectory(prefix="DGER Adapter PID reuse space ",dir="/private/tmp") as td:
            root=Path(td); state=root/"Dropbox Governed Execution Relay"; tree=state/"attempts/r0-00000000000000000000000000000077/attempt-1/gep-tree"; (tree/"scripts").mkdir(parents=True); target=tree/"scripts/governed_exec.py"; target.write_text("x"); (tree/".venv/bin").mkdir(parents=True); py=tree/".venv/bin/python"; py.write_text("x"); (state/"attempts").mkdir(parents=True,exist_ok=True)
            pid=777; old_argv=[str(py),str(target),"self-check","ai-me"]; replacement_argv=[str(py),str(target),"other-operation","ai-me"]
            replacement={"pid":pid,"ppid":1,"uid":os.getuid(),"start_sec":22,"start_usec":1}
            names=lambda p,d:[str(tree)] if d=="cwd" else [str(py)]
            with mock.patch.object(adapter,"STATE",state),mock.patch.object(adapter,"_ps_pids",return_value=[(pid,os.getuid())]),mock.patch.object(adapter,"_launchctl_pid",return_value=None),mock.patch.object(adapter,"_native_argv",side_effect=[old_argv,replacement_argv]),mock.patch.object(adapter,"_bsd_identity",return_value=replacement),mock.patch.object(adapter,"_lsof_names",side_effect=names):
                with self.assertRaisesRegex(RuntimeError,"writer argv operation mismatch"): adapter.procs()
            boot=mock.Mock(returncode=0,stdout=b"",stderr=b"")
            with mock.patch.object(adapter,"STATE",state),mock.patch.object(adapter,"run",return_value=boot),mock.patch.object(adapter,"_ps_pids",return_value=[(pid,os.getuid())]),mock.patch.object(adapter,"_launchctl_pid",return_value=None),mock.patch.object(adapter,"_native_argv",side_effect=[old_argv,replacement_argv]),mock.patch.object(adapter,"_bsd_identity",return_value=replacement),mock.patch.object(adapter,"_lsof_names",side_effect=names),mock.patch.object(adapter.os,"kill") as kill:
                with self.assertRaisesRegex(RuntimeError,"writer argv operation mismatch"): adapter.stop()
                kill.assert_not_called()
            # Even a fully guarded live writer is a quiescence blocker; stop never PID-signals it.
            old={"pid":pid,"ppid":1,"uid":os.getuid(),"start_sec":21,"start_usec":9,"argv":old_argv,"cwd":str(tree),"target":str(target),"executable":str(py),"role":"writer"}
            with mock.patch.object(adapter,"run",return_value=boot),mock.patch.object(adapter,"procs",return_value=([],[old])),mock.patch.object(adapter.os,"kill") as kill:
                with self.assertRaisesRegex(RuntimeError,"PID-only termination forbidden"): adapter.stop()
                kill.assert_not_called()

    def test_adapter_exact_writer_role_wrong_missing_extra_rejected_procs_and_stop(self):
        with tempfile.TemporaryDirectory(prefix="DGER Adapter writer role space ",dir="/private/tmp") as td:
            root=Path(td); state=root/"Dropbox Governed Execution Relay"; tree=state/"attempts/r0-00000000000000000000000000000078/attempt-1/gep-tree"; (tree/"scripts").mkdir(parents=True); target=tree/"scripts/governed_exec.py"; target.write_text("x"); (tree/".venv/bin").mkdir(parents=True); py=tree/".venv/bin/python"; py.write_text("x"); (state/"attempts").mkdir(parents=True,exist_ok=True)
            pid=778; info={"pid":pid,"ppid":1,"uid":os.getuid(),"start_sec":30,"start_usec":4}; names=lambda p,d:[str(tree)] if d=="cwd" else [str(py)]
            good=[str(py),str(target),"self-check","ai-me"]
            bads=([str(py),str(target)],[str(py),str(target),"other","ai-me"],[str(py),str(target),"self-check","other"],[str(py),str(target),"self-check","ai-me","extra"])
            with mock.patch.object(adapter,"STATE",state),mock.patch.object(adapter,"_bsd_identity",side_effect=[info,dict(info)]),mock.patch.object(adapter,"_native_argv",return_value=good),mock.patch.object(adapter,"_lsof_names",side_effect=names):
                rec=adapter._owned(pid,tree,target,"writer",None); self.assertEqual(rec["argv"][-3:],[str(target),"self-check","ai-me"])
            for bad in bads:
                with self.subTest(argv=bad), mock.patch.object(adapter,"STATE",state),mock.patch.object(adapter,"_bsd_identity",return_value=info),mock.patch.object(adapter,"_native_argv",return_value=bad),mock.patch.object(adapter,"_lsof_names",side_effect=names):
                    with self.assertRaisesRegex(RuntimeError,"writer argv operation mismatch|role/target/operation ownership"): adapter._owned(pid,tree,target,"writer",None)
                with self.subTest(procs=bad), mock.patch.object(adapter,"STATE",state),mock.patch.object(adapter,"_ps_pids",return_value=[(pid,os.getuid())]),mock.patch.object(adapter,"_launchctl_pid",return_value=None),mock.patch.object(adapter,"_native_argv",return_value=bad),mock.patch.object(adapter,"_bsd_identity",return_value=info),mock.patch.object(adapter,"_lsof_names",side_effect=names):
                    with self.assertRaisesRegex(RuntimeError,"writer argv operation mismatch"): adapter.procs()
                boot=mock.Mock(returncode=0,stdout=b"",stderr=b"")
                with self.subTest(stop=bad), mock.patch.object(adapter,"STATE",state),mock.patch.object(adapter,"run",return_value=boot),mock.patch.object(adapter,"_ps_pids",return_value=[(pid,os.getuid())]),mock.patch.object(adapter,"_launchctl_pid",return_value=None),mock.patch.object(adapter,"_native_argv",return_value=bad),mock.patch.object(adapter,"_bsd_identity",return_value=info),mock.patch.object(adapter,"_lsof_names",side_effect=names),mock.patch.object(adapter.os,"kill") as kill:
                    with self.assertRaisesRegex(RuntimeError,"writer argv operation mismatch"): adapter.stop()
                    kill.assert_not_called()

    def test_adapter_stop_forbids_pid_signal_dispatch_and_live_writer_blocks_quiescence(self):
        source=(ROOT/"deployment/dger_god_adapter.py").read_text("utf-8")
        stop_src=source[source.index("def stop():"):source.index("def start():")]
        self.assertNotIn("os.kill",stop_src); self.assertNotIn("SIGTERM",stop_src); self.assertIn("PID-only termination forbidden",stop_src)
        writer={"pid":779,"uid":os.getuid(),"ppid":1,"start_sec":31,"start_usec":5,"argv":["/python","/x/governed_exec.py","self-check","ai-me"],"cwd":"/x","target":"/x/governed_exec.py","executable":"/python","role":"writer"}
        boot=mock.Mock(returncode=0,stdout=b"",stderr=b"")
        with mock.patch.object(adapter,"run",return_value=boot),mock.patch.object(adapter,"procs",return_value=([],[writer])),mock.patch.object(adapter.os,"kill") as kill:
            with self.assertRaisesRegex(RuntimeError,"PID-only termination forbidden"): adapter.stop()
            kill.assert_not_called()

    def test_adapter_procargs_preserves_legitimate_empty_argument_without_weakening_role(self):
        def raw(argv):
            return struct.pack("=i",len(argv))+b"/usr/bin/python\0\0"+b"\0".join(x.encode("utf-8") for x in argv)+b"\0"
        argv=["/usr/bin/python","","tail"]
        self.assertEqual(adapter._argv_from_procargs(raw(argv),881),argv)
        with mock.patch.object(adapter,"_ps_pids",return_value=[(881,os.getuid())]), mock.patch.object(adapter,"_launchctl_pid",return_value=None), mock.patch.object(adapter,"_native_argv",return_value=argv):
            self.assertEqual(adapter.procs(),([],[]))
        target=str(PROD_STATE/"attempts/r0-00000000000000000000000000000081/attempt-1/gep-tree/scripts/governed_exec.py")
        self.assertTrue(adapter._writer_role_argv(["/python","",target,"self-check","ai-me"],target))
        for bad in (["/python",target,"self-check","","ai-me"],["/python",target,"self-check","ai-me",""]):
            self.assertFalse(adapter._writer_role_argv(bad,target))
        with self.assertRaisesRegex(RuntimeError,"truncated"):
            adapter._argv_from_procargs(struct.pack("=i",2)+b"/x\0\0/x\0",882)

    def test_relay_procargs_preserves_legitimate_empty_argument_and_exact_writer_suffix(self):
        def raw(argv):
            return struct.pack("=i",len(argv))+b"/usr/bin/python\0\0"+b"\0".join(x.encode("utf-8") for x in argv)+b"\0"
        argv=["/usr/bin/python","","tail"]
        self.assertEqual(relay._argv_from_procargs(raw(argv),883),argv)
        with self.assertRaisesRegex(RuntimeError,"NATIVE_ARGV_TRUNCATED"):
            relay._argv_from_procargs(struct.pack("=i",2)+b"/x\0\0/x\0",884)
        with tempfile.TemporaryDirectory(prefix="DGER Relay empty argv role ",dir="/private/tmp") as td:
            tree,target,py=self._relay_attempt_fixture(Path(td))
            good=[str(py),"",str(target),"self-check",relay.QUALIFIED_PROJECT]
            # The relay ownership primitive is stricter than the adapter and requires exactly four argv entries.
            info={"pid":885,"ppid":1,"uid":os.getuid(),"start_sec":40,"start_usec":6}; names=lambda p,d:[str(tree)] if d=="cwd" else [str(py)]
            with mock.patch.object(relay,"_bsd_identity",return_value=info), mock.patch.object(relay,"_native_argv",return_value=good), mock.patch.object(relay,"_lsof_names",side_effect=names):
                with self.assertRaisesRegex(RuntimeError,"GEP_ATTEMPT_ARGV_OWNERSHIP"):
                    relay._owned_attempt_process(885,target)


    def test_adapter_dbroot_selects_canonical_dropbox_when_other_provider_has_marker(self):
        with tempfile.TemporaryDirectory(prefix="DGER C7AC adapter dbroot ",dir="/private/tmp") as td:
            home=Path(td); drop=home/"Library/CloudStorage/Dropbox"; (drop/"Software/NSP - Temporary Files").mkdir(parents=True); (home/"Library/CloudStorage/GoogleDrive-test/Software/NSP - Temporary Files").mkdir(parents=True)
            with mock.patch.object(Path,"home",return_value=home): self.assertEqual(adapter.dbroot(),drop.resolve())

    def test_adapter_dbroot_rejects_missing_or_symlinked_canonical_dropbox(self):
        with tempfile.TemporaryDirectory(prefix="DGER C7AC adapter dbroot reject ",dir="/private/tmp") as td:
            home=Path(td); base=home/"Library/CloudStorage"; (base/"GoogleDrive-test/Software/NSP - Temporary Files").mkdir(parents=True)
            with mock.patch.object(Path,"home",return_value=home):
                with self.assertRaisesRegex(RuntimeError,"Dropbox root unavailable"): adapter.dbroot()
            real=home/"real-dropbox"; (real/"Software/NSP - Temporary Files").mkdir(parents=True); os.symlink(real,base/"Dropbox",target_is_directory=True)
            with mock.patch.object(Path,"home",return_value=home):
                with self.assertRaisesRegex(RuntimeError,"Dropbox root unavailable"): adapter.dbroot()

    def test_relay_dropbox_root_selects_canonical_dropbox_when_other_provider_has_marker(self):
        with tempfile.TemporaryDirectory(prefix="DGER C7AC relay dbroot ",dir="/private/tmp") as td:
            home=Path(td); drop=home/"Library/CloudStorage/Dropbox"; (drop/"Software/NSP - Temporary Files").mkdir(parents=True); (home/"Library/CloudStorage/GoogleDrive-test/Software/NSP - Temporary Files").mkdir(parents=True)
            with mock.patch.object(Path,"home",return_value=home): self.assertEqual(relay.resolve_dropbox_root(),drop.resolve())

    def test_relay_dropbox_root_rejects_missing_or_symlinked_canonical_dropbox(self):
        with tempfile.TemporaryDirectory(prefix="DGER C7AC relay dbroot reject ",dir="/private/tmp") as td:
            home=Path(td); base=home/"Library/CloudStorage"; (base/"GoogleDrive-test/Software/NSP - Temporary Files").mkdir(parents=True)
            with mock.patch.object(Path,"home",return_value=home):
                with self.assertRaisesRegex(RuntimeError,"DROPBOX_ROOT_UNAVAILABLE"): relay.resolve_dropbox_root()
            real=home/"real-dropbox"; (real/"Software/NSP - Temporary Files").mkdir(parents=True); os.symlink(real,base/"Dropbox",target_is_directory=True)
            with mock.patch.object(Path,"home",return_value=home):
                with self.assertRaisesRegex(RuntimeError,"DROPBOX_ROOT_UNAVAILABLE"): relay.resolve_dropbox_root()

if __name__=="__main__": unittest.main()
