from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import sys

HERE = Path(__file__).resolve().parent
CARRIER = HERE / "DGER_GEN4_SOURCE_PUBLISH.py"
KNOWN_ROOTS = (
    Path("/usr/bin"),
    Path("/bin"),
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


def physical_executable(path: Path) -> str | None:
    try:
        resolved = path.resolve(strict=True)
        st = resolved.stat()
    except (FileNotFoundError, OSError, RuntimeError):
        return None
    if not stat.S_ISREG(st.st_mode) or not os.access(resolved, os.X_OK):
        return None
    return str(resolved)


def governed_find_exe(*names: str) -> str:
    for name in names:
        candidates: list[Path]
        if "/" in name:
            candidates = [Path(name)]
        else:
            candidates = [root / name for root in KNOWN_ROOTS]
        for candidate in candidates:
            found = physical_executable(candidate)
            if found is not None:
                return found
    raise RuntimeError("EXECUTABLE_NOT_FOUND:" + ",".join(names))


def load_carrier():
    if not CARRIER.is_file() or CARRIER.is_symlink():
        raise RuntimeError("CARRIER_MISSING_OR_UNSAFE")
    spec = importlib.util.spec_from_file_location("dger_gen4_source_publish_carrier", CARRIER)
    if spec is None or spec.loader is None:
        raise RuntimeError("CARRIER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def self_test() -> None:
    resolved = governed_find_exe("/bin/sh")
    if not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeError("RUNNER_RESOLUTION_SELFTEST_FAILED")
    module = load_carrier()
    module.find_exe = governed_find_exe
    saved = sys.argv[:]
    try:
        sys.argv = [str(CARRIER), "--self-test"]
        module.main()
    finally:
        sys.argv = saved
    print("DGER_GEN4_SOURCE_PUBLISH_RUNNER_SELFTEST=PASS")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    if sys.argv[1:]:
        raise RuntimeError("UNEXPECTED_ARGUMENTS")
    module = load_carrier()
    module.find_exe = governed_find_exe
    saved = sys.argv[:]
    try:
        sys.argv = [str(CARRIER)]
        module.main()
    finally:
        sys.argv = saved


if __name__ == "__main__":
    main()
