from __future__ import annotations
import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; STATE=Path("/Users/brettmacpro/ChatGPT/State/Tools/Dropbox Governed Execution Relay")
class T(unittest.TestCase):
 def test_profile(self):
  p=json.loads((ROOT/"deployment/god-profile.json").read_text()); self.assertEqual(p["repository_id"],"dger"); self.assertEqual(len(p["surface"]),8)
  self.assertEqual(p["runtime_accounting"]["runtime_ids"],["dger.launchagent"]); self.assertEqual(p["runtime_accounting"]["writer_ids"],["dger.gep-child"])
  for r in p["surface"]: self.assertNotIn("..",Path(r["runtime_path"]).parts)
 def test_pyrunway_adapter(self):
  s=(ROOT/"deployment/dger-god-adapter").read_text(); self.assertIn("/usr/local/bin/pyrunway --standalone",s); self.assertNotIn("/usr/bin/python",s); a=(ROOT/"deployment/dger_god_adapter.py").read_text(); self.assertIn("/usr/bin/env",a); self.assertIn("uv",a); self.assertIn("UV_OFFLINE",a); self.assertIn("--locked",a)
 def test_stable_launcher(self):
  s=(ROOT/"launcher/dropbox-governed-execution-relay").read_text(); self.assertIn('TARGET="$RUNTIME/scripts/dger.py"',s); self.assertIn('cd "$RUNTIME"',s); self.assertIn("/usr/bin/env",s); self.assertNotIn("delivered-identity.json",s); self.assertIn("/usr/local/bin/pyrunway",s); self.assertNotIn("--standalone",s)
 def test_plist(self):
  s=(ROOT/"launchagent/com.brettmacpro.chatgpt.dropbox-governed-execution-relay.plist").read_text(); self.assertIn(str(STATE/"runtime/current/launcher/dropbox-governed-execution-relay"),s)
 def test_health_binding(self):
  s=(ROOT/"src/dger/relay.py").read_text(); self.assertIn('"dger_commit": dger_sha',s); self.assertIn('"dger_tree": dger_tree',s)
 def test_scopes(self):
  s=(ROOT/"deployment/dger_god_adapter.py").read_text()
  for x in ("processes","launchd-user","launchd-system","launchd-nonstandard","writers","ownership-executable","ownership-cwd","ownership-symlink"): self.assertIn(x,s)
if __name__=="__main__": unittest.main()
