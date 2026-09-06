from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dger.gen4 import (  # noqa: E402
    MAX_ADMISSION_BYTES, MAX_REQUEST_BYTES, REQUEST_SCHEMA, atomic_bytes, canonical_file_bytes,
    make_ready_record, read_regular,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Seal a deterministic DGER Gen4 transport package")
    p.add_argument("package", type=Path)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    package = args.package
    if package.is_symlink() or not package.is_dir():
        raise SystemExit("UNSAFE_PACKAGE")
    request_raw = read_regular(package / "request.json", MAX_REQUEST_BYTES)
    admission_raw = read_regular(package / "admission.bin", MAX_ADMISSION_BYTES)
    try:
        request = json.loads(request_raw)
    except Exception as exc:
        raise SystemExit("INVALID_REQUEST") from exc
    if not isinstance(request, dict) or request.get("schema") != REQUEST_SCHEMA:
        raise SystemExit("INVALID_REQUEST")
    request_id = request.get("dger_request_id")
    if not isinstance(request_id, str) or request_id != package.name:
        raise SystemExit("REQUEST_DIRECTORY_MISMATCH")
    ready = make_ready_record(request_raw, admission_raw, package / "payload", request_id)
    raw = canonical_file_bytes(ready)
    target = package / "READY.json"
    if target.exists():
        if read_regular(target, MAX_REQUEST_BYTES) != raw:
            raise SystemExit("READY_CONFLICT")
    else:
        atomic_bytes(target, raw, 0o644)
    if read_regular(target, MAX_REQUEST_BYTES) != raw:
        raise SystemExit("READY_READBACK_MISMATCH")
    print(json.dumps({"ok": True, "dger_request_id": request_id, "ready_sha256": __import__("hashlib").sha256(raw).hexdigest()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
