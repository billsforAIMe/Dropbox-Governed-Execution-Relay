from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dger.relay import EXPECTED_INTERVAL_SECONDS, Relay, atomic_json
from dger.phase1 import Phase1Relay
from dger.phase1_runtime import CHMCLI, DropboxWake, GEPCLI, Phase1Transport


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dropbox Governed Execution Relay")
    p.add_argument("--transport-root", type=Path, required=True)
    p.add_argument("--state-root", type=Path, required=True)
    p.add_argument("--gep-bare", type=Path, required=True)
    p.add_argument("--pyrunway", type=Path, required=True)
    p.add_argument("--handoff-manager", type=Path, required=True)
    p.add_argument("--phase1-gep-launcher", type=Path)
    p.add_argument("--phase1-principal-git-identity")
    return p


def _phase1_context(state_root: Path) -> Path:
    root = state_root / "phase1"
    if root.exists() and root.is_symlink():
        raise RuntimeError("DGER_PHASE1_CONTEXT_ROOT_UNSAFE")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "chm-context.json"
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("DGER_PHASE1_CONTEXT_UNSAFE")
        os.chmod(path, 0o600)
        try:
            value = json.loads(path.read_text("utf-8"))
        except Exception as exc:
            raise RuntimeError("DGER_PHASE1_CONTEXT_INVALID") from exc
        if (
            not isinstance(value, dict)
            or value.get("caller_id") != "dger-phase1"
            or not isinstance(value.get("claim_capability"), str)
            or len(value["claim_capability"]) < 32
        ):
            raise RuntimeError("DGER_PHASE1_CONTEXT_INVALID")
        return path
    atomic_json(path, {"caller_id": "dger-phase1", "claim_capability": secrets.token_urlsafe(48)})
    os.chmod(path, 0o600)
    return path


def _phase1(args) -> Phase1Transport | None:
    values = (args.phase1_gep_launcher, args.phase1_principal_git_identity)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise RuntimeError("DGER_PHASE1_BINDING_INCOMPLETE")
    context = _phase1_context(args.state_root)
    chm = CHMCLI(args.handoff_manager, args.phase1_principal_git_identity, context)
    gep = GEPCLI(args.phase1_gep_launcher)
    phase1_root = args.transport_root / "Phase1"
    wake = DropboxWake(phase1_root / "Wakes")
    relay = Phase1Relay(args.state_root / "phase1" / "relay", chm, gep, wake)
    return Phase1Transport(phase1_root, relay)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    r0 = Relay(
        args.transport_root,
        args.state_root,
        gep_bare=args.gep_bare,
        pyrunway=args.pyrunway,
        chm=args.handoff_manager,
    )
    phase1 = _phase1(args)
    if phase1 is None:
        r0.run()
        return 0
    while True:
        degraded = False
        try:
            r0.scan_once()
        except Exception:
            degraded = True
        try:
            phase1.scan_once()
        except Exception:
            degraded = True
        if degraded:
            try:
                r0.heartbeat("DEGRADED_PHASE1_OR_R0")
            except Exception:
                pass
        time.sleep(EXPECTED_INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
