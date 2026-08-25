from pathlib import Path
import unittest

FIXED_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"

class LauncherEnvironmentTest(unittest.TestCase):
    def test_launcher_exports_common_governed_uv_path(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "launcher" / "dropbox-governed-execution-relay").read_text("utf-8")
        self.assertEqual(text.count("export PATH="), 1)
        self.assertIn(f"export PATH='{FIXED_PATH}'", text)
        self.assertLess(text.index("export PATH="), text.index("exec env PYRUNWAY_STRICT=1"))

if __name__ == "__main__":
    unittest.main()
