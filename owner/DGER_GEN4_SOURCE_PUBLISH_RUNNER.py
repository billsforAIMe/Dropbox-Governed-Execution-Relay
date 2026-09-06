from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CARRIER = HERE / "DGER_GEN4_SOURCE_PUBLISH.py"
KNOWN_ROOTS = (
    Path("/usr/bin"),
    Path("/bin"),
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)
GITSTORAGE_RUNTIME = Path("/Users/brettmacpro/ChatGPT/Installed/Tools/GitStorage/gitstorage")
GITSTORAGE_SHA256 = "1059071d24ffd90502b80197702ce38a1d14b855dcb42c597c99a073cffbe587"


def physical_executable(path: Path) -> str | None:
    try:
        resolved = path.resolve(strict=True)
        st = resolved.stat()
    except (FileNotFoundError, OSError, RuntimeError):
        return None
    if not stat.S_ISREG(st.st_mode) or not os.access(resolved, os.X_OK):
        return None
    return str(resolved)


def exact_gitstorage_runtime() -> str:
    found = physical_executable(GITSTORAGE_RUNTIME)
    if found is None:
        raise RuntimeError("GITSTORAGE_REGISTERED_RUNTIME_MISSING_OR_UNSAFE")
    digest = hashlib.sha256(Path(found).read_bytes()).hexdigest()
    if digest != GITSTORAGE_SHA256:
        raise RuntimeError(f"GITSTORAGE_RUNTIME_SHA256_MISMATCH:{digest}")
    return found


def governed_find_exe(*names: str) -> str:
    if any(Path(name).name == "gitstorage" for name in names):
        return exact_gitstorage_runtime()
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


def corrected_run(args: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None,
                  timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, object] = {
        "args": args,
        "env": env,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": timeout,
        "check": False,
    }
    if input_text is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = input_text
    cp = subprocess.run(**kwargs)
    if check and cp.returncode != 0:
        raise RuntimeError(f"COMMAND_FAILED:{Path(args[0]).name}:{cp.returncode}:{cp.stderr[-800:]}")
    return cp


def load_carrier():
    if not CARRIER.is_file() or CARRIER.is_symlink():
        raise RuntimeError("CARRIER_MISSING_OR_UNSAFE")
    spec = importlib.util.spec_from_file_location("dger_gen4_source_publish_carrier", CARRIER)
    if spec is None or spec.loader is None:
        raise RuntimeError("CARRIER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enumerate_deploy_keys(module, gh: str) -> list[dict]:
    keys: list[dict] = []
    for page in range(1, 11):
        obj = module._runner_original_gh_json(
            gh, f"repos/{module.REPO}/keys?per_page=100&page={page}"
        )
        if not isinstance(obj, list):
            raise RuntimeError("DEPLOY_KEY_LIST_NOT_ARRAY")
        for item in obj:
            if not isinstance(item, dict):
                raise RuntimeError("DEPLOY_KEY_ITEM_NOT_OBJECT")
            keys.append(item)
        if len(obj) < 100:
            return keys
    raise RuntimeError("DEPLOY_KEY_ENUMERATION_UNBOUNDED")


def require_zero_write_deploy_keys(keys: list[dict]) -> None:
    standing = [
        item for item in keys
        if item.get("read_only") is False
    ]
    if standing:
        ids = [str(item.get("id", "UNKNOWN")) for item in standing]
        raise RuntimeError("STANDING_WRITE_DEPLOY_KEY:" + ",".join(ids))


def install_deploy_key_guard(module) -> None:
    original = module.gh_json
    module._runner_original_gh_json = original

    def guarded(gh: str, path: str, *extra: str):
        is_create = (
            path == f"repos/{module.REPO}/keys"
            and "-X" in extra
            and "POST" in extra
        )
        if is_create:
            require_zero_write_deploy_keys(enumerate_deploy_keys(module, gh))
            print("preexisting_write_deploy_keys=ZERO")
        return original(gh, path, *extra)

    module.gh_json = guarded


def verify_post_run_key_hygiene(module) -> None:
    gh = governed_find_exe("/opt/homebrew/bin/gh", "/usr/local/bin/gh", "gh")
    require_zero_write_deploy_keys(enumerate_deploy_keys(module, gh))
    print("postrun_write_deploy_keys=ZERO")


def self_test() -> None:
    resolved = governed_find_exe("/bin/sh")
    if not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeError("RUNNER_RESOLUTION_SELFTEST_FAILED")
    gs = governed_find_exe("/usr/local/bin/gitstorage", "/opt/homebrew/bin/gitstorage", "gitstorage")
    if gs != str(GITSTORAGE_RUNTIME.resolve(strict=True)):
        raise RuntimeError("GITSTORAGE_RUNTIME_RESOLUTION_SELFTEST_FAILED")
    probe = corrected_run(["/bin/cat"], input_text="runner-input-probe\n", timeout=10)
    if probe.stdout != "runner-input-probe\n":
        raise RuntimeError("INPUT_SUBPROCESS_SELFTEST_FAILED")
    require_zero_write_deploy_keys([{"id": 1, "read_only": True}])
    try:
        require_zero_write_deploy_keys([{"id": 2, "read_only": False}])
    except RuntimeError as exc:
        if not str(exc).startswith("STANDING_WRITE_DEPLOY_KEY:"):
            raise
    else:
        raise RuntimeError("DEPLOY_KEY_GUARD_SELFTEST_FAIL_OPEN")
    module = load_carrier()
    module.find_exe = governed_find_exe
    module.run = corrected_run
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
    module.run = corrected_run
    install_deploy_key_guard(module)
    saved = sys.argv[:]
    caught: BaseException | None = None
    try:
        sys.argv = [str(CARRIER)]
        module.main()
    except BaseException as exc:
        caught = exc
    finally:
        sys.argv = saved
        verify_post_run_key_hygiene(module)
    if caught is not None:
        raise caught


if __name__ == "__main__":
    main()
