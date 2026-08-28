from __future__ import annotations
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
adapter_spec=importlib.util.spec_from_file_location("dger_god_adapter_c7i",ROOT/"deployment/dger_god_adapter.py")
if adapter_spec is None or adapter_spec.loader is None: raise RuntimeError("adapter spec unavailable")
adapter=importlib.util.module_from_spec(adapter_spec); adapter_spec.loader.exec_module(adapter)
relay_spec=importlib.util.spec_from_file_location("dger_relay_c7i",ROOT/"src/dger/relay.py")
if relay_spec is None or relay_spec.loader is None: raise RuntimeError("relay spec unavailable")
relay=importlib.util.module_from_spec(relay_spec); relay_spec.loader.exec_module(relay)
canonical=relay.canonical; digest=relay.digest

class C7IIdentityTests(unittest.TestCase):
    def rows(self):
        return [{"source_path":"a","logical_path":"a","runtime_path":"/r/a","mode":"0644","size":1,"sha256":"0"*64}]
    def good_health(self,seq=2,ts="2026-08-28T00:00:01Z"):
        return {"schema_version":adapter.PROTOCOL,"protocol_version":adapter.PROTOCOL,
          "expected_interval_seconds":2,"qualified_gep_operation":adapter.OP,"qualified_gep_commit":adapter.GEP,
          "sequence":seq,"updated_at_utc":ts,"dger_resident_surface_sha256":"x","dger_resident_surface":[]}
    def test_surface_digest_stable_and_sensitive(self):
        a=self.rows(); self.assertEqual(adapter._surface_digest(a),adapter._surface_digest(copy.deepcopy(a)))
        for key,value in (("sha256","1"*64),("mode","0755"),("runtime_path","/other/a")):
            b=copy.deepcopy(a); b[0][key]=value; self.assertNotEqual(adapter._surface_digest(a),adapter._surface_digest(b))
    def test_sequence_is_strict_integral_not_bool_string_or_float(self):
        self.assertEqual(adapter._strict_sequence({"sequence":2}),2)
        for bad in (True,"2",2.0,-1,None): self.assertIsNone(adapter._strict_sequence({"sequence":bad}))
    def test_pair_requires_strict_sequence_and_time(self):
        a={"sequence":4,"updated_at_utc":"2026-08-28T00:00:00Z"}; b={"sequence":5,"updated_at_utc":"2026-08-28T00:00:02Z"}
        self.assertTrue(adapter._pair_valid(a,b)); self.assertFalse(adapter._pair_valid(a,{**b,"sequence":4}))
        self.assertFalse(adapter._pair_valid(a,{**b,"sequence":True})); self.assertFalse(adapter._pair_valid(a,{**b,"updated_at_utc":a["updated_at_utc"]}))
        self.assertFalse(adapter._pair_valid(a,{**b,"updated_at_utc":"2026-08-28T00:00:01Z"}))
    def test_snapshot_time_and_surface_fail_closed(self):
        c={"approved_commit":"a"*40}; h=self.good_health()
        with mock.patch.object(adapter,"_runtime_surface",return_value=("x",[])), mock.patch.object(adapter,"_git_surface",return_value=("x",[])):
            self.assertTrue(adapter._snapshot_valid(c,h,now_ts=1787875202))
            self.assertFalse(adapter._snapshot_valid(c,h,now_ts=1787875210))
            self.assertFalse(adapter._snapshot_valid(c,{**h,"updated_at_utc":"malformed"},now_ts=1787875202))
            self.assertFalse(adapter._snapshot_valid(c,{**h,"updated_at_utc":"2026-08-28T00:00:03Z"},now_ts=1787875202))
            self.assertFalse(adapter._snapshot_valid(c,{**h,"sequence":True},now_ts=1787875202))
            self.assertFalse(adapter._snapshot_valid(c,{**h,"dger_resident_surface_sha256":"y"},now_ts=1787875202))
    def test_progressing_health_positive_and_nonprogressing(self):
        c={"approved_commit":"a"*40}; first=self.good_health(2,"2026-08-28T00:00:01Z"); second=self.good_health(3,"2026-08-28T00:00:03Z")
        clock=[0.0]
        def mono(): clock[0]+=0.05; return clock[0]
        def sleep(_): pass
        vals=iter([first,second])
        with mock.patch.object(adapter,"_runtime_surface",return_value=("x",[])):
            self.assertTrue(adapter._progressing_health(c,1,("x",[]),health_fn=lambda:next(vals,second),now_fn=lambda:1787875204,monotonic_fn=mono,sleep_fn=sleep))
        clock=[0.0]; vals=iter([first]*300)
        with mock.patch.object(adapter,"_runtime_surface",return_value=("x",[])):
            self.assertFalse(adapter._progressing_health(c,1,("x",[]),health_fn=lambda:next(vals,first),now_fn=lambda:1787875204,monotonic_fn=mono,sleep_fn=sleep))
    def test_launchctl_pid_parser_and_lsof_parser(self):
        fake=mock.Mock(returncode=0,stdout=b"state = running\n\tpid = 1234\n",stderr=b"")
        with mock.patch.object(adapter,"run",return_value=fake): self.assertEqual(adapter._launchctl_pid(),1234)
        fake=mock.Mock(returncode=0,stdout=b"p123\nfcwd\nn/tmp/x\n",stderr=b"")
        with mock.patch.object(adapter,"run",return_value=fake): self.assertEqual(adapter._lsof_names(123,"cwd"),["/tmp/x"])
    def _proc_tree(self,root):
        state=root/"state"; rt=state/"runtime/current"; (rt/"scripts").mkdir(parents=True); (rt/".venv/bin").mkdir(parents=True)
        target=rt/"scripts/dger.py"; target.write_text("x"); py=rt/".venv/bin/python"; py.write_text("x")
        return state,rt,target,py
    def test_owned_process_valid_wrong_cwd_wrong_executable_and_symlink(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as td:
            root=Path(td); state,rt,target,py=self._proc_tree(root); cmd=f"{py} {target}"
            def names(pid,desc): return [str(rt)] if desc=="cwd" else [str(py)]
            with mock.patch.object(adapter,"_lsof_names",side_effect=names): self.assertEqual(adapter._owned(10,cmd,rt,target)["target"],str(target))
            wrong=root/"wrong"; wrong.mkdir()
            with mock.patch.object(adapter,"_lsof_names",side_effect=lambda p,d:[str(wrong)] if d=="cwd" else [str(py)]):
                with self.assertRaises(RuntimeError): adapter._owned(10,cmd,rt,target)
            other=root/"other"; other.write_text("x")
            with mock.patch.object(adapter,"_lsof_names",side_effect=lambda p,d:[str(rt)] if d=="cwd" else [str(other)]):
                with self.assertRaises(RuntimeError): adapter._owned(10,cmd,rt,target)
            link=root/"link"; link.symlink_to(rt,target_is_directory=True)
            with self.assertRaises(RuntimeError): adapter._physical_dir(link)
    def test_missing_lsof_and_ambiguous_cwd_fail(self):
        bad=mock.Mock(returncode=2,stdout=b"",stderr=b"")
        with mock.patch.object(adapter,"run",return_value=bad):
            with self.assertRaises(RuntimeError): adapter._lsof_names(1,"cwd")
        with mock.patch.object(adapter,"_lsof_names",return_value=["/a","/b"]):
            with self.assertRaises(RuntimeError): adapter.cwd(1)
    def test_unrelated_text_is_not_classified_and_duplicate_writers_fail(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as td:
            root=Path(td); state=root/"state"; (state/"attempts").mkdir(parents=True)
            with mock.patch.object(adapter,"STATE",state), mock.patch.object(adapter,"_launchctl_pid",return_value=None), mock.patch.object(adapter,"_ps_rows",return_value=[(1,"/bin/echo --note=/fake/runtime/current/scripts/dger.py")]):
                self.assertEqual(adapter.procs(),([],[]))
            writers=[]
            for n,pid in (("a",10),("b",11)):
                gt=state/f"attempts/{n}/gep-tree"; (gt/"scripts").mkdir(parents=True); (gt/".venv/bin").mkdir(parents=True)
                t=gt/"scripts/governed_exec.py"; t.write_text("x"); py=gt/".venv/bin/python"; py.write_text("x"); writers.append((pid,f"{py} {t}",gt,py))
            rows=[(pid,cmd) for pid,cmd,_,_ in writers]
            def lsof(pid,desc):
                rec=next(x for x in writers if x[0]==pid); return [str(rec[2])] if desc=="cwd" else [str(rec[3])]
            with mock.patch.object(adapter,"STATE",state), mock.patch.object(adapter,"_launchctl_pid",return_value=None), mock.patch.object(adapter,"_ps_rows",return_value=rows), mock.patch.object(adapter,"_lsof_names",side_effect=lsof):
                with self.assertRaisesRegex(RuntimeError,"multiple owned DGER writer"): adapter.procs()
    def test_valid_runtime_and_writer_procs_and_plausible_unowned_fail(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as td:
            root=Path(td); state,rt,target,py=self._proc_tree(root)
            runtime_cmd=f"{py} {target}"
            def runtime_lsof(pid,desc): return [str(rt)] if desc=="cwd" else [str(py)]
            with mock.patch.object(adapter,"STATE",state), mock.patch.object(adapter,"_launchctl_pid",return_value=10), mock.patch.object(adapter,"_ps_rows",return_value=[(10,runtime_cmd)]), mock.patch.object(adapter,"_lsof_names",side_effect=runtime_lsof):
                r,w=adapter.procs(); self.assertEqual(len(r),1); self.assertEqual(w,[])
            gt=state/"attempts/one/gep-tree"; (gt/"scripts").mkdir(parents=True); (gt/".venv/bin").mkdir(parents=True)
            wt=gt/"scripts/governed_exec.py"; wt.write_text("x"); wpy=gt/".venv/bin/python"; wpy.write_text("x"); wcmd=f"{wpy} {wt}"
            def writer_lsof(pid,desc): return [str(gt)] if desc=="cwd" else [str(wpy)]
            with mock.patch.object(adapter,"STATE",state), mock.patch.object(adapter,"_launchctl_pid",return_value=None), mock.patch.object(adapter,"_ps_rows",return_value=[(11,wcmd)]), mock.patch.object(adapter,"_lsof_names",side_effect=writer_lsof):
                r,w=adapter.procs(); self.assertEqual(r,[]); self.assertEqual(len(w),1)
            fake=root/"other/dger.py"; fake.parent.mkdir(); fake.write_text("x")
            with mock.patch.object(adapter,"STATE",state), mock.patch.object(adapter,"_launchctl_pid",return_value=None), mock.patch.object(adapter,"_ps_rows",return_value=[(12,f"/bin/python {fake}")]):
                with self.assertRaisesRegex(RuntimeError,"plausible unowned"): adapter.procs()
    def test_writer_symlink_boundary_and_wrong_target_fail(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as td:
            root=Path(td); state=root/"state"; attempts=state/"attempts"; attempts.mkdir(parents=True)
            real=root/"real-gep"; (real/"scripts").mkdir(parents=True); (real/".venv/bin").mkdir(parents=True)
            target=real/"scripts/governed_exec.py"; target.write_text("x"); py=real/".venv/bin/python"; py.write_text("x")
            link=attempts/"x"; link.mkdir(); (link/"gep-tree").symlink_to(real,target_is_directory=True)
            badtarget=link/"gep-tree/scripts/governed_exec.py"
            with mock.patch.object(adapter,"STATE",state), mock.patch.object(adapter,"_launchctl_pid",return_value=None), mock.patch.object(adapter,"_ps_rows",return_value=[(20,f"{py} {badtarget}")]):
                with self.assertRaisesRegex(RuntimeError,"symlink"): adapter.procs()
            state2,rt,rt_target,rt_py=self._proc_tree(root/"two"); other=root/"two/state/runtime/current/scripts/not-dger.py"; other.write_text("x")
            def names(pid,desc): return [str(rt)] if desc=="cwd" else [str(rt_py)]
            with mock.patch.object(adapter,"_lsof_names",side_effect=names):
                with self.assertRaises(RuntimeError): adapter._owned(21,f"{rt_py} {other}",rt,rt_target)
    def test_relay_canonical_surface_hash_is_deterministic(self):
        rows=self.rows(); self.assertEqual(digest(canonical(rows)),adapter._surface_digest(rows))

if __name__=="__main__": unittest.main()
