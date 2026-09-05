from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "deployment/dger_god_adapter.py"
PROFILE_TEMPLATE = ROOT / "deployment/god_profile.template.json"

spec = importlib.util.spec_from_file_location("dger_god_adapter", ADAPTER_PATH)
assert spec and spec.loader
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        home = root / "Users/brettmacpro"
        state = home / "ChatGPT/State/Tools/Dropbox Governed Execution Relay"
        runtime = state / "runtime/current"
        live = home / "Library/LaunchAgents" / f"{adapter.LABEL}.plist"
        candidate_plist = runtime / "launchagent" / f"{adapter.LABEL}.plist"
        launcher = runtime / "launcher/dropbox-governed-execution-relay"
        moh = home / "ChatGPT/State/Tools/Mac Operation Host"
        for directory in (state, candidate_plist.parent, launcher.parent, live.parent, moh):
            directory.mkdir(parents=True, exist_ok=True)
        launcher.write_text("#!/bin/zsh\n", encoding="utf-8")
        launcher.chmod(0o755)
        candidate_plist.write_bytes(plistlib.dumps({
            "Label": adapter.LABEL,
            "ProgramArguments": [str(launcher)],
            "RunAtLoad": True,
            "KeepAlive": True,
        }))
        values = {
            "HOME": home,
            "STATE": state,
            "RUNTIME_ROOT": runtime,
            "LIVE_PLIST": live,
            "CANDIDATE_PLIST": candidate_plist,
            "CANDIDATE_LAUNCHER": launcher,
            "DELIVERED_IDENTITY": state / "delivered-identity.json",
            "RUNTIME_BINDING": state / "runtime-binding.json",
            "TOKEN_FILE": state / "credentials/gtg-tools.token",
            "MOH_HOME": moh,
            "UID": 501,
        }
        self.patchers = [mock.patch.object(adapter, key, value) for key, value in values.items()]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.td.cleanup()

    def context(self) -> dict:
        return {
            "schema_version": 1,
            "transaction": "runtime_only_deploy",
            "authority_effect": "NONE",
            "recovery_ownership": "RUNTIME_SURFACE_ONLY",
            "run_id": "test-run",
            "project_id": "dropbox-governed-execution-relay",
            "deployment_root": str(adapter.STATE),
            "state_root": str(adapter.STATE),
            "approved_commit": "a" * 40,
            "approved_tree": "b" * 40,
            "runtime_accounting": {
                "runtime_ids": [adapter.RUNTIME_ID],
                "writer_ids": [],
                "stop_required_ids": [adapter.RUNTIME_ID],
                "leave_stopped_ids": [],
            },
            "derived_surfaces": [],
            "verb": "restart",
            "nonce": "nonce",
            "expected_restart_ids": [adapter.RUNTIME_ID],
        }

    def test_adapter_has_no_pid_signal_path(self):
        raw = ADAPTER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("os.kill", raw)
        self.assertNotIn("/bin/kill", raw)
        self.assertNotIn("/usr/bin/kill", raw)
        self.assertIn('GOD_CONSUMER_ADAPTER_CONTRACT = "consumer-hardening/v1"', raw)
        self.assertIn('GOD_TERMINATION_SAFETY_CONTRACT = "incarnation-bound-or-fail-closed/v1"', raw)
        self.assertIn('["/bin/launchctl", "bootout", f"gui/{UID}/{LABEL}"]', raw)

    def test_candidate_config_is_exact_and_secret_is_not_evidence(self):
        context = self.context()
        with mock.patch.object(adapter, "_keychain_token", return_value="T" * 48):
            adapter._install_candidate_config(context)
        delivered = json.loads(adapter.DELIVERED_IDENTITY.read_text(encoding="utf-8"))
        binding = json.loads(adapter.RUNTIME_BINDING.read_text(encoding="utf-8"))
        self.assertEqual(delivered["candidate_sha"], "a" * 40)
        self.assertEqual(delivered["candidate_tree"], "b" * 40)
        self.assertEqual(binding["gtg_endpoint"], adapter.GTG_ENDPOINT)
        self.assertEqual(binding["moh_home"], str(adapter.MOH_HOME))
        self.assertEqual(adapter.TOKEN_FILE.stat().st_mode & 0o777, 0o600)
        snapshot = {
            "delivered_identity": adapter._snapshot(adapter.DELIVERED_IDENTITY),
            "runtime_binding": adapter._snapshot(adapter.RUNTIME_BINDING),
            "live_plist": adapter._snapshot(adapter.LIVE_PLIST),
        }
        self.assertNotIn("token", json.dumps(snapshot).lower())
        self.assertNotIn("T" * 32, json.dumps(snapshot))

    def test_rollback_restores_predecessor_config_and_plist(self):
        old_identity = b'{"candidate_sha":"' + (b"c" * 40) + b'"}\n'
        old_binding = b'{"old":true}\n'
        old_plist = plistlib.dumps({"Label": adapter.LABEL, "ProgramArguments": [str(adapter.OLD_LAUNCHER)]})
        adapter._atomic(adapter.DELIVERED_IDENTITY, old_identity, 0o600)
        adapter._atomic(adapter.RUNTIME_BINDING, old_binding, 0o600)
        adapter._atomic(adapter.LIVE_PLIST, old_plist, 0o644)
        state = {"snapshots": {
            "delivered_identity": adapter._snapshot(adapter.DELIVERED_IDENTITY),
            "runtime_binding": adapter._snapshot(adapter.RUNTIME_BINDING),
            "live_plist": adapter._snapshot(adapter.LIVE_PLIST),
        }}
        adapter._atomic(adapter.DELIVERED_IDENTITY, b'{"new":1}\n', 0o600)
        adapter._atomic(adapter.RUNTIME_BINDING, b'{"new":2}\n', 0o600)
        adapter._atomic(adapter.LIVE_PLIST, adapter.CANDIDATE_PLIST.read_bytes(), 0o644)
        adapter._restore_predecessor(state)
        self.assertEqual(adapter.DELIVERED_IDENTITY.read_bytes(), old_identity)
        self.assertEqual(adapter.RUNTIME_BINDING.read_bytes(), old_binding)
        self.assertEqual(adapter.LIVE_PLIST.read_bytes(), old_plist)

    def test_profile_template_is_closed_complete_and_single_substitution(self):
        raw = PROFILE_TEMPLATE.read_text(encoding="utf-8")
        self.assertEqual(raw.count("__ADAPTER_SHA256__"), 1)
        adapter_sha = hashlib.sha256(ADAPTER_PATH.read_bytes()).hexdigest()
        rendered = raw.replace("__ADAPTER_SHA256__", adapter_sha)
        self.assertNotIn("__", rendered)
        profile = json.loads(rendered)
        self.assertEqual(profile["repository_id"], "dropbox-governed-execution-relay")
        self.assertEqual(profile["adapter"]["sha256"], adapter_sha)
        self.assertEqual(profile["runtime_accounting"]["stop_required_ids"], [adapter.RUNTIME_ID])
        self.assertEqual(profile["derived_surfaces"], [])
        source_paths = {item["source_path"] for item in profile["surface"]}
        self.assertEqual(len(source_paths), 24)
        self.assertIn("GOVERNED_RELEASE.json", source_paths)
        self.assertIn("launcher/dropbox-governed-execution-relay", source_paths)
        self.assertIn("launchagent/com.brettmacpro.chatgpt.dropbox-governed-execution-relay.plist", source_paths)
        self.assertIn("scripts/dger.py", source_paths)
        expected_modules = {
            "__init__.py", "gtg_http.py", "relay.py", "relay_accept.py", "relay_chm.py", "relay_moh.py",
            "relay_moh_invoke.py", "relay_protocol.py", "relay_protocol_base.py", "relay_protocol_binding.py",
            "relay_protocol_fs.py", "relay_protocol_ingress.py", "relay_protocol_validate.py", "relay_runtime.py",
            "relay_state.py", "relay_state_ingress.py", "relay_state_result.py", "relay_state_stage.py",
            "relay_state_store.py", "relay_v1.py",
        }
        self.assertEqual({path.rsplit("/", 1)[-1] for path in source_paths if path.startswith("src/dger/")}, expected_modules)


if __name__ == "__main__":
    unittest.main()
