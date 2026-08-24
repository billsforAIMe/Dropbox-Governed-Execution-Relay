from __future__ import annotations
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dger.relay import Relay, resolve_dropbox_root

def main() -> int:
    base = resolve_dropbox_root()
    software = base / "Software"
    if software.is_symlink(): raise RuntimeError("UNSAFE_SOFTWARE_ROOT")
    root = software / "Dropbox Governed Execution Relay" / "V1"
    if root.is_symlink(): raise RuntimeError("UNSAFE_TRANSPORT_ROOT")
    Relay(root).run()
    return 0
if __name__ == "__main__": raise SystemExit(main())
