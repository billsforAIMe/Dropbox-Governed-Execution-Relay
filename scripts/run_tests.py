from __future__ import annotations
import unittest
from pathlib import Path
r=Path(__file__).resolve().parents[1]
s=unittest.defaultTestLoader.discover(str(r/"tests"),pattern="test*.py")
x=unittest.TextTestRunner(verbosity=2).run(s)
raise SystemExit(0 if x.wasSuccessful() else 1)
