from __future__ import annotations

import json
import os
from pathlib import Path
import stat

ACTIVATION_SCHEMA = "dger-gen4-activation/v1"
ACTIVATION_MODE = "GEN4_REQUIRED"


class LegacySurfaceRetired(RuntimeError):
    pass


def _read_activation(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise LegacySurfaceRetired("GEN4_ACTIVATION_STATE_UNREADABLE") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > 16_384 or stat.S_IMODE(st.st_mode) & 0o022:
            raise LegacySurfaceRetired("GEN4_ACTIVATION_STATE_UNSAFE")
        raw = os.read(fd, st.st_size + 1)
        if len(raw) != st.st_size:
            raise LegacySurfaceRetired("GEN4_ACTIVATION_STATE_CHANGED")
    finally:
        os.close(fd)
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except Exception as exc:
        raise LegacySurfaceRetired("GEN4_ACTIVATION_STATE_INVALID") from exc
    if not isinstance(value, dict):
        raise LegacySurfaceRetired("GEN4_ACTIVATION_STATE_INVALID")
    return value


def assert_legacy_allowed(state_root: Path) -> None:
    """Fail closed once secure Gen4 activation State exists.

    The marker is installed deployment State, never Dropbox input. Its presence retires
    every legacy process-start-capable relay path; malformed marker bytes also fail closed.
    """
    marker = state_root / "gen4" / "ACTIVATED.json"
    if not marker.exists():
        return
    value = _read_activation(marker)
    expected = {"schema", "mode", "activation_id", "peer_tuple_digest", "service_identity_digest"}
    if set(value) != expected or value.get("schema") != ACTIVATION_SCHEMA or value.get("mode") != ACTIVATION_MODE:
        raise LegacySurfaceRetired("GEN4_ACTIVATION_STATE_INVALID")
    for key in ("activation_id", "peer_tuple_digest", "service_identity_digest"):
        item = value.get(key)
        if not isinstance(item, str) or not item:
            raise LegacySurfaceRetired("GEN4_ACTIVATION_STATE_INVALID")
    raise LegacySurfaceRetired("GEN3_SURFACE_RETIRED")
