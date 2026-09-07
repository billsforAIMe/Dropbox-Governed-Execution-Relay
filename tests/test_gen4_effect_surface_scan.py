from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from dger_execution_surface_scan import SEMANTIC_EXECUTE_ALLOWLIST, scan_execution_call_sites


class ExecutionSurfaceScannerTests(unittest.TestCase):
    def _scan(self, files: dict[str, str]):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel, content in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, "utf-8")
            return scan_execution_call_sites(root)

    def test_recursive_process_start_apis_and_aliases_are_detected(self):
        process, _ = self._scan({
            "src/dger/nested/rogue.py": (
                "import subprocess as sp\n"
                "from os import system as shell\n"
                "import os\n"
                "import asyncio\n"
                "from pty import spawn as pty_spawn\n"
                "sp.run(['x'])\n"
                "shell('x')\n"
                "os.execv('/bin/x', ['x'])\n"
                "os.spawnv(os.P_NOWAIT, '/bin/x', ['x'])\n"
                "asyncio.create_subprocess_exec('x')\n"
                "pty_spawn(['x'])\n"
            )
        })
        targets = {row[2] for row in process}
        self.assertIn("subprocess.run", targets)
        self.assertIn("os.system", targets)
        self.assertIn("os.execv", targets)
        self.assertIn("os.spawnv", targets)
        self.assertIn("asyncio.create_subprocess_exec", targets)
        self.assertIn("pty.spawn", targets)
        self.assertTrue(all(row[0] == "src/dger/nested/rogue.py" for row in process))

    def test_direct_process_start_in_runtime_adapter_is_detected(self):
        process, _ = self._scan({
            "src/dger/gen4_runtime_peers.py": "import subprocess\ndef bad():\n    subprocess.call(['x'])\n"
        })
        self.assertEqual(1, len(process))
        self.assertEqual("subprocess.call", process[0][2])

    def test_dynamic_or_explicit_execute_invoke_is_semantic_execution(self):
        _, semantic = self._scan({
            "src/dger/rogue.py": (
                "def dynamic(g, operation):\n"
                "    g.invoke('mac-operation-host', operation, {})\n"
                "def explicit(g):\n"
                "    g.invoke('mac-operation-host', 'execute', {})\n"
            )
        })
        self.assertEqual({"dynamic", "explicit"}, {row[1] for row in semantic})

    def test_statically_read_only_protected_invocation_is_not_execution(self):
        _, semantic = self._scan({
            "src/dger/read_only.py": (
                "def read(invoker, tool_id, operation, args, service):\n"
                "    return invoker.invoke(tool_id, operation, 'READ', args, service)\n"
            )
        })
        self.assertEqual([], semantic)

    def test_repository_has_no_direct_process_start_and_exact_semantic_allowlist(self):
        process, semantic = scan_execution_call_sites(ROOT)
        self.assertEqual([], process)
        self.assertEqual(
            SEMANTIC_EXECUTE_ALLOWLIST,
            {(path, qualname, target) for path, qualname, target, _ in semantic},
        )


if __name__ == "__main__":
    unittest.main()
