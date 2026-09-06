from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

suite = unittest.TestSuite()
for name in (
    "test_relay_v1_core", "test_relay_v1_safety", "test_relay_v1_safety_more",
    "test_relay_v1_transport_recovery", "test_review_corrections", "test_gtg_http", "test_gen4",
):
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))

result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise SystemExit(1)
subprocess.run([sys.executable, str(ROOT / "tools/validate_gen4_effect_surface_inventory.py")], check=True)
print("DGER_GEN4_ASSURANCE_PASS")
