from __future__ import annotations

from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LocationIndependenceTests(unittest.TestCase):
    def test_portable_python_does_not_embed_owner_or_checkout_paths(self):
        for rel in ("src/dger/relay.py", "src/dger/relay_protocol.py", "src/dger/relay_state.py", "src/dger/relay_v1.py", "src/dger/gtg_http.py", "scripts/dger.py"):
            text = (ROOT / rel).read_text()
            self.assertNotIn("/Users/", text, rel)
            self.assertNotIn("/ChatGPT/Tools/Dropbox Governed Execution Relay", text, rel)
            self.assertNotIn("/ChatGPT/Git/Tools/Governed Execution Platform.git", text, rel)

    def test_mac_launcher_is_binding_boundary(self):
        text = (ROOT / "launcher/dropbox-governed-execution-relay").read_text()
        self.assertNotIn("/Users/brettmacpro", text)
        self.assertNotIn("ChatGPT/Git/Tools/Dropbox Governed Execution Relay.git", text)
        for flag in ("--transport-root", "--state-root", "--moh-home", "--gtg-endpoint", "--gtg-token-file"):
            self.assertIn(flag, text)
        self.assertIn('STATE="$HOME/ChatGPT/State/Tools/Dropbox Governed Execution Relay"', text)
        self.assertIn('BINDING="$STATE/runtime-binding.json"', text)
        self.assertIn('MARKER="$SOFTWARE/NSP - Temporary Files"', text)
        self.assertIn('DGER_GTG_BINDING_UNAVAILABLE', text)
        self.assertNotIn("--gep-bare", text)
        self.assertNotIn("--handoff-manager", text)

    def test_launchagent_invokes_god_managed_runtime_launcher(self):
        text = (ROOT / "launchagent/com.brettmacpro.chatgpt.dropbox-governed-execution-relay.plist").read_text()
        expected = "/Users/brettmacpro/ChatGPT/State/Tools/Dropbox Governed Execution Relay/runtime/current/launcher/dropbox-governed-execution-relay"
        self.assertIn(f"<string>{expected}</string>", text)

    def test_entrypoint_requires_every_external_binding(self):
        spec = importlib.util.spec_from_file_location("dger_entrypoint_test", ROOT / "scripts" / "dger.py")
        self.assertIsNotNone(spec); self.assertIsNotNone(spec.loader)
        entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)
        parser = entry.parser()
        with self.assertRaises(SystemExit): parser.parse_args([])
        args = parser.parse_args([
            "--transport-root", "/tmp/transport", "--state-root", "/tmp/state",
            "--moh-home", "/tmp/moh", "--gtg-endpoint", "https://gtg.invalid/mcp",
            "--gtg-token-file", "/tmp/token",
        ])
        self.assertEqual(Path("/tmp/state"), args.state_root)
        self.assertEqual(Path("/tmp/moh"), args.moh_home)


if __name__ == "__main__":
    unittest.main(verbosity=2)
