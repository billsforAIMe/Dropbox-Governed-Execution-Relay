from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

suite = unittest.TestSuite()
for name in ("test_relay_v1_core", "test_relay_v1_safety", "test_relay_v1_safety_more", "test_relay_v1_transport_recovery", "test_gtg_http"):
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))

class ChangedLocationTests(unittest.TestCase):
    def test_changed_portable_python_has_no_owner_checkout_paths(self):
        for rel in (
            "src/dger/relay_protocol.py", "src/dger/relay_protocol_base.py", "src/dger/relay_protocol_fs.py",
            "src/dger/relay_protocol_validate.py", "src/dger/relay_protocol_ingress.py", "src/dger/relay_protocol_binding.py", "src/dger/relay_state.py", "src/dger/relay_state_ingress.py", "src/dger/relay_state_store.py",
            "src/dger/relay_state_stage.py", "src/dger/relay_state_result.py", "src/dger/relay_v1.py", "src/dger/relay_runtime.py",
            "src/dger/relay_accept.py", "src/dger/relay_moh.py", "src/dger/relay_moh_invoke.py", "src/dger/relay_chm.py",
            "src/dger/gtg_http.py", "scripts/dger.py",
        ):
            text = (ROOT / rel).read_text()
            self.assertNotIn("/Users/", text, rel)
            self.assertNotIn("/ChatGPT/Tools/Dropbox Governed Execution Relay", text, rel)
            self.assertNotIn("/ChatGPT/Git/Tools/Governed Execution Platform.git", text, rel)

suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ChangedLocationTests))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
