from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dger.relay import Relay


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dropbox Governed Execution Relay R0")
    p.add_argument("--transport-root", type=Path, required=True)
    p.add_argument("--state-root", type=Path, required=True)
    p.add_argument("--gep-bare", type=Path, required=True)
    p.add_argument("--pyrunway", type=Path, required=True)
    p.add_argument("--handoff-manager", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    Relay(
        args.transport_root,
        args.state_root,
        gep_bare=args.gep_bare,
        pyrunway=args.pyrunway,
        chm=args.handoff_manager,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
