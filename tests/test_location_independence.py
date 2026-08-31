from __future__ import annotations

from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LocationIndependenceTests(unittest.TestCase):
    def test_portable_python_does_not_embed_owner_or_checkout_paths(self):
        for rel in ("src/dger/relay.py", "scripts/dger.py"):
            text = (ROOT / rel).read_text()
            self.assertNotIn("/Users/", text, rel)
            self.assertNotIn("/ChatGPT/Tools/Dropbox Governed Execution Relay", text, rel)
            self.assertNotIn("/ChatGPT/Git/Tools/Governed Execution Platform.git", text, rel)
            self.assertNotIn("/ChatGPT/State/Tools/Dropbox Governed Execution Relay", text, rel)

    def test_mac_launcher_is_binding_boundary(self):
        text = (ROOT / "launcher/dropbox-governed-execution-relay").read_text()
        self.assertNotIn("/Users/brettmacpro", text)
        for flag in (
            "--transport-root",
            "--state-root",
            "--gep-bare",
            "--pyrunway",
            "--handoff-manager",
        ):
            self.assertIn(flag, text)
        self.assertIn('STATE="$HOME/ChatGPT/State/Tools/Dropbox Governed Execution Relay"', text)
        self.assertIn('GEP_BARE="$HOME/ChatGPT/Git/Tools/Governed Execution Platform.git"', text)
        self.assertIn('MARKER="$SOFTWARE/NSP - Temporary Files"', text)
        self.assertIn('DROPBOX_ROOT_COUNT=$((DROPBOX_ROOT_COUNT + 1))', text)
        self.assertIn('DGER_DROPBOX_ROOT_AMBIGUOUS_OR_MISSING', text)

    def test_entrypoint_requires_every_external_binding(self):
        spec = importlib.util.spec_from_file_location("dger_entrypoint_test", ROOT / "scripts" / "dger.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        parser = entry.parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])
        args = parser.parse_args([
            "--transport-root", "/tmp/transport",
            "--state-root", "/tmp/state",
            "--gep-bare", "/tmp/gep.git",
            "--pyrunway", "/tmp/pyrunway",
            "--handoff-manager", "/tmp/handoff-manager",
        ])
        self.assertEqual(Path("/tmp/state"), args.state_root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
