from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "deployment/dger_god_adapter.py"
PROFILE_PATH = ROOT / "PROJECT_GOVERNANCE_PROFILE.md"
BINDING_PATH = ROOT / "GOVERNANCE_BINDING.md"

spec = importlib.util.spec_from_file_location("dger_god_adapter_crash", ADAPTER_PATH)
assert spec and spec.loader
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class SimulatedCrash(BaseException):
    pass


class RollbackCrashTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name).resolve()
        home = root / "Users/brettmacpro"
        state = home / "AI/State/Tools/Dropbox Governed Execution Relay"
        runtime = state / "runtime/current"
        live = home / "Library/LaunchAgents" / f"{adapter.LABEL}.plist"
        candidate_plist = runtime / "launchagent" / f"{adapter.LABEL}.plist"
        launcher = runtime / "launcher/dropbox-governed-execution-relay"
        script = runtime / "scripts/dger.py"
        moh = home / "ChatGPT/State/Tools/Mac Operation Host"
        old_launcher = root / "usr/local/bin/dropbox-governed-execution-relay"
        for directory in (
            state,
            candidate_plist.parent,
            launcher.parent,
            script.parent,
            live.parent,
            moh,
            old_launcher.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        launcher.write_text("#!/bin/zsh\n", encoding="utf-8")
        launcher.chmod(0o755)
        script.write_text("print('dger')\n", encoding="utf-8")
        old_launcher.write_text("#!/bin/zsh\n", encoding="utf-8")
        old_launcher.chmod(0o755)
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
            "CANDIDATE_SCRIPT": script,
            "OLD_LAUNCHER": old_launcher,
            "DELIVERED_IDENTITY": state / "delivered-identity.json",
            "RUNTIME_BINDING": state / "runtime-binding.json",
            "TOKEN_FILE": state / "credentials/gtg-tools.token",
            "MOH_HOME": moh,
            "UID": 501,
        }
        self.patchers = [mock.patch.object(adapter, key, value) for key, value in values.items()]
        for patcher in self.patchers:
            patcher.start()
        self.context_path = root / "context.json"
        self.state_path = adapter._state_path(self.context_path)
        self.old_identity = b'{"candidate_sha":"' + (b"c" * 40) + b'"}\n'
        self.old_binding = b'{"old":true}\n'
        self.old_token = b"old-token-material\n"
        self.old_plist = plistlib.dumps({
            "Label": adapter.LABEL,
            "ProgramArguments": [str(adapter.OLD_LAUNCHER)],
        })
        adapter._atomic(adapter.DELIVERED_IDENTITY, self.old_identity, 0o600)
        adapter._atomic(adapter.RUNTIME_BINDING, self.old_binding, 0o600)
        adapter._atomic(adapter.TOKEN_FILE, self.old_token, 0o600)
        adapter._atomic(adapter.LIVE_PLIST, self.old_plist, 0o644)

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.td.cleanup()

    def _context(self, verb: str) -> dict:
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
            "verb": verb,
            "nonce": "nonce",
            "expected_restart_ids": [],
        }

    def _write_context(self, verb: str) -> None:
        self.context_path.write_text(json.dumps(self._context(verb)), encoding="utf-8")

    @staticmethod
    def _discovery() -> dict:
        return {
            "discovery_complete": True,
            "discovery_scopes": list(adapter.REQUIRED_DISCOVERY_SCOPES),
            "discovered_runtime_ids": [],
            "discovered_writer_ids": [],
            "active_runtime_ids": [],
            "active_writer_ids": [],
            "ambiguities": [],
            "errors": [],
        }

    def _quiesce(self) -> int:
        self._write_context("quiesce")
        with (
            mock.patch.object(adapter, "project_discover", return_value=self._discovery()),
            mock.patch.object(adapter, "_stop_service", return_value=None),
        ):
            return adapter.main(["adapter", "quiesce", "--context", str(self.context_path)])

    def _prime_snapshots(self) -> None:
        self.assertEqual(self._quiesce(), 0)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertFalse(state["candidate_config_may_have_changed"])
        self.assertFalse(state["restart_applied"])
        self.assertFalse(state["rollback_config_restored"])

    def _assert_predecessor_restored(self) -> None:
        self.assertEqual(adapter.DELIVERED_IDENTITY.read_bytes(), self.old_identity)
        self.assertEqual(adapter.RUNTIME_BINDING.read_bytes(), self.old_binding)
        self.assertEqual(adapter.TOKEN_FILE.read_bytes(), self.old_token)
        self.assertEqual(adapter.TOKEN_FILE.stat().st_mode & 0o777, 0o600)
        self.assertEqual(adapter.LIVE_PLIST.read_bytes(), self.old_plist)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertFalse(state["candidate_config_may_have_changed"])
        self.assertFalse(state["restart_applied"])
        self.assertTrue(state["rollback_config_restored"])

    def _crash_after_atomic_target_then_recover(self, target: Path) -> None:
        self._prime_snapshots()
        self._write_context("restart")
        original_atomic = adapter._atomic

        def crashing_atomic(path: Path, data: bytes, mode: int) -> None:
            original_atomic(path, data, mode)
            if path == target:
                raise SimulatedCrash(f"after {path.name}")

        with (
            mock.patch.object(adapter, "_keychain_token", return_value="N" * 48),
            mock.patch.object(adapter, "_atomic", side_effect=crashing_atomic),
        ):
            with self.assertRaises(SimulatedCrash):
                adapter.main(["adapter", "restart", "--context", str(self.context_path)])

        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertTrue(state["candidate_config_may_have_changed"])
        self.assertFalse(state["restart_applied"])
        self.assertFalse(state["rollback_config_restored"])
        self.assertEqual(self._quiesce(), 0)
        self._assert_predecessor_restored()

    def test_crash_after_token_replacement_recovers_via_quiesce(self):
        self._crash_after_atomic_target_then_recover(adapter.TOKEN_FILE)

    def test_crash_after_delivered_identity_replacement_recovers_via_quiesce(self):
        self._crash_after_atomic_target_then_recover(adapter.DELIVERED_IDENTITY)

    def test_crash_after_runtime_binding_replacement_recovers_via_quiesce(self):
        self._crash_after_atomic_target_then_recover(adapter.RUNTIME_BINDING)

    def test_crash_after_live_plist_replacement_recovers_via_quiesce(self):
        self._crash_after_atomic_target_then_recover(adapter.LIVE_PLIST)

    def test_crash_before_post_install_state_write_recovers_via_quiesce(self):
        self._prime_snapshots()
        self._write_context("restart")
        original_write_state = adapter._write_adapter_state
        calls = 0

        def crashing_state_write(path: Path, value: dict) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise SimulatedCrash("before post-install state write")
            original_write_state(path, value)

        with (
            mock.patch.object(adapter, "_keychain_token", return_value="N" * 48),
            mock.patch.object(adapter, "_write_adapter_state", side_effect=crashing_state_write),
        ):
            with self.assertRaises(SimulatedCrash):
                adapter.main(["adapter", "restart", "--context", str(self.context_path)])

        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertTrue(state["candidate_config_may_have_changed"])
        self.assertFalse(state["restart_applied"])
        self.assertFalse(state["rollback_config_restored"])
        self.assertNotEqual(adapter.TOKEN_FILE.read_bytes(), self.old_token)
        self.assertNotEqual(adapter.LIVE_PLIST.read_bytes(), self.old_plist)
        self.assertEqual(self._quiesce(), 0)
        self._assert_predecessor_restored()

    def test_crash_during_restore_keeps_latch_until_full_restore_is_durable(self):
        self._prime_snapshots()
        self._write_context("restart")
        with mock.patch.object(adapter, "_keychain_token", return_value="N" * 48):
            self.assertEqual(adapter.main(["adapter", "restart", "--context", str(self.context_path)]), 0)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertTrue(state["candidate_config_may_have_changed"])
        self.assertTrue(state["restart_applied"])

        original_atomic = adapter._atomic
        crashed = False

        def crash_during_restore(path: Path, data: bytes, mode: int) -> None:
            nonlocal crashed
            original_atomic(path, data, mode)
            if path == adapter.DELIVERED_IDENTITY and not crashed:
                crashed = True
                raise SimulatedCrash("during predecessor restore")

        self._write_context("quiesce")
        with (
            mock.patch.object(adapter, "project_discover", return_value=self._discovery()),
            mock.patch.object(adapter, "_stop_service", return_value=None),
            mock.patch.object(adapter, "_atomic", side_effect=crash_during_restore),
        ):
            with self.assertRaises(SimulatedCrash):
                adapter.main(["adapter", "quiesce", "--context", str(self.context_path)])

        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertTrue(state["candidate_config_may_have_changed"])
        self.assertTrue(state["restart_applied"])
        self.assertFalse(state["rollback_config_restored"])
        self.assertEqual(self._quiesce(), 0)
        self._assert_predecessor_restored()


class StateLocusTests(unittest.TestCase):
    def test_authoritative_state_locus_is_unambiguous(self):
        production_state = "/Users/brettmacpro/AI/State/Tools/Dropbox Governed Execution Relay"
        profile = PROFILE_PATH.read_text(encoding="utf-8")
        binding = BINDING_PATH.read_text(encoding="utf-8")
        adapter_source = ADAPTER_PATH.read_text(encoding="utf-8")
        self.assertIn(production_state, profile)
        self.assertIn(production_state, binding)
        self.assertIn('STATE = HOME / "AI/State/Tools/Dropbox Governed Execution Relay"', adapter_source)
        self.assertNotIn("/Users/brettmacpro/ChatGPT/State/Tools/Dropbox Governed Execution Relay", profile)


if __name__ == "__main__":
    unittest.main()
