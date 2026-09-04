from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dger.gtg_http import GTGHttpGateway
from dger.relay_v1 import Relay


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dropbox Governed Execution Relay")
    p.add_argument("--transport-root", type=Path, required=True)
    p.add_argument("--state-root", type=Path, required=True)
    p.add_argument("--moh-home", type=Path, required=True)
    p.add_argument("--gtg-endpoint", required=True)
    p.add_argument("--gtg-token-file", type=Path, required=True)
    p.add_argument("--allow-insecure-localhost-gtg", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    gateway = GTGHttpGateway(
        args.gtg_endpoint,
        args.gtg_token_file,
        allow_insecure_localhost=args.allow_insecure_localhost_gtg,
    )
    Relay(
        args.transport_root,
        args.state_root,
        moh_home=args.moh_home,
        gateway=gateway,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
