from __future__ import annotations

from pathlib import Path
from typing import Any

from .gen4_primitives import DgerGen4Error, ID_RE, MAX_ERROR_BYTES, PROTOCOL, atomic_json, utc

class Gen4DriverMixin:
    def _advance(self, state: dict[str, Any]) -> None:
        # Bounded one-transition loop: each iteration advances at most one durable
        # phase or performs one peer call, then reloads exact durable State.
        rid = state["dger_request_id"]
        for _ in range(24):
            state = self._load_state(rid) or state
            phase = state["phase"]
            before_error_generation = int(state.get("error_generation", 0))
            if phase in {"DONE", "RESULT_CONFLICT", "CHM_RESULT_CONFLICT", "MOH_IN_DOUBT"}:
                return
            if phase == "INGRESS_FROZEN": self._correlate(state)
            elif phase == "CORRELATED": self._stage(state)
            elif phase == "MOH_STAGED": self._write_pre_ahc_wal(state)
            elif phase == "PRE_AHC_EXECUTE_WAL": self._begin_ahc(state)
            elif phase == "AHC_BEGIN_RECONCILE": self._reconcile_ahc_begin(state)
            elif phase == "AHC_IN_DOUBT":
                if state.get("pre_execute_status_required") is not False:
                    self._status_before_execute(state)
                else:
                    self._execute_moh(state)
            elif phase == "MOH_RECONCILE": self._reconcile_moh(state)
            elif phase == "MOH_IN_DOUBT_AHC_PENDING": self._report_moh_in_doubt(state)
            elif phase == "MOH_TERMINAL": self._publish_terminal(state)
            elif phase == "AHC_TERMINAL_PENDING": self._accept_ahc_terminal(state)
            elif phase == "CHM_PENDING": self._publish_chm(state)
            else: raise DgerGen4Error("UNKNOWN_PHASE", str(phase))
            new_state = self._load_state(rid) or state
            # A blocked peer call records an error without moving the phase. Stop so
            # scan cadence, not a tight loop, controls retry.
            if new_state["phase"] == phase and int(new_state.get("error_generation", 0)) > before_error_generation:
                return
        raise DgerGen4Error("ADVANCE_TRANSITION_LIMIT")

    def process_one(self, package: Path) -> bool:
        request_id = package.name
        if ID_RE.fullmatch(request_id) is None or package.is_symlink() or not package.is_dir() or not (package / "READY.json").exists():
            return False
        with self._lock(request_id):
            current = self._load_state(request_id)
            try:
                self._freeze(package, request_id)
                current = self._accept_frozen(request_id)
                self._advance(current)
            except DgerGen4Error as exc:
                current = self._load_state(request_id)
                if current is not None:
                    self._record_error(current, "process_one", exc); self._save_state(request_id, current)
                self._status(request_id, "REJECTED", code=exc.code, detail=exc.detail[:MAX_ERROR_BYTES])
            return True

    def resume_one(self, request_id: str) -> bool:
        if ID_RE.fullmatch(request_id) is None:
            return False
        with self._lock(request_id):
            current = self._load_state(request_id)
            if current is None:
                if not self._frozen_dir(request_id).exists():
                    return False
                current = self._accept_frozen(request_id)
            self._advance(current)
            return True

    def scan_once(self) -> None:
        degraded = False
        packages: list[Path] = []
        for path in self.ingress.iterdir():
            try:
                if path.is_dir() and not path.is_symlink(): packages.append(path)
            except OSError: degraded = True
        for package in sorted(packages, key=lambda p: p.name):
            try: self.process_one(package)
            except Exception: degraded = True
        ids: set[str] = set()
        for root in (self.state / "frozen", self.state / "executions"):
            for path in root.iterdir():
                name = path.stem if root.name == "executions" else path.name
                if ID_RE.fullmatch(name): ids.add(name)
        for request_id in sorted(ids):
            try: self.resume_one(request_id)
            except Exception: degraded = True
        atomic_json(self.control / "gen4-health.json", {
            "schema": PROTOCOL,
            "relay_state": "DEGRADED" if degraded else "IDLE",
            "accepted_request_count": len(ids),
            "updated_at_utc": utc(),
        }, 0o644)
