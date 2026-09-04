from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest

from dger.relay_v1 import (
    CHM_TOOL_ID,
    MOH_TOOL_ID,
    READY_SCHEMA,
    REQUEST_SCHEMA,
    Relay,
    canonical_bytes,
    canonical_digest,
    moh_closure_digest,
    payload_manifest,
    sha256,
    _safe_rel,
)

COMMIT = "a" * 40
TREE = "b" * 40
REGISTRY = "c" * 40
GTG_COMMIT = "9" * 40
CONSUMER = "fixture-consumer"
CONSUMER_REPO = "424242"
MOH_COMMIT = "d" * 40
MOH_TREE = "e" * 40
CHM_COMMIT = "1" * 40
CHM_TREE = "2" * 40


def canonical_file(value):
    return canonical_bytes(value) + b"\n"


def make_binding(tool_id: str, commit: str, tree: str, repo_id: str) -> dict:
    return {
        "authoritative_binding": {
            "provider": "github",
            "repository": f"fixture/{tool_id}",
            "repository_id": repo_id,
            "selector": "refs/heads/main",
            "registry_observed_ref": commit,
        },
        "delivered_binding": {
            "tool_identity": commit,
            "tool_tree": tree,
            "registry_identity": REGISTRY,
        },
    }


class FakeGatewayCore:
    def __init__(self):
        self.bindings = {
            (MOH_TOOL_ID, "*"): make_binding(MOH_TOOL_ID, MOH_COMMIT, MOH_TREE, "100"),
            (CHM_TOOL_ID, "*"): make_binding(CHM_TOOL_ID, CHM_COMMIT, CHM_TREE, "200"),
            (CONSUMER, "*"): make_binding(CONSUMER, COMMIT, TREE, CONSUMER_REPO),
        }
        self.moh: dict[str, dict] = {}
        self.execute_calls: dict[str, int] = {}
        self.status_calls: dict[str, int] = {}
        self.get_calls: dict[str, int] = {}
        self.attach_calls: dict[str, int] = {}
        self.resolve_calls: dict[str, int] = {}
        self.chm_results: dict[str, dict] = {}
        self.handoff_states: dict[str, str] = {}
        self.resolved: set[str] = set()
        self.lost_execute_once: set[str] = set()
        self.lost_attach_once: set[str] = set()
        self.fail_chm_once: set[str] = set()
        self.failed_ids: set[str] = set()
        self.in_doubt_ids: set[str] = set()
        self.running_status_cycles: dict[str, int] = {}
        self._lost_execute_done: set[str] = set()
        self._lost_attach_done: set[str] = set()
        self._fail_chm_done: set[str] = set()
        self.lock = threading.Lock()
        self.invocations = 0

    def doctor(self, tool_id: str, operation: str):
        binding = self.bindings[(tool_id, "*")]
        return {
            "schema": "gtg-doctor/v2",
            "ok": True,
            "tool_id": tool_id,
            "operation": operation,
            "callability_state": "READY",
            "authoritative_binding": dict(binding["authoritative_binding"]),
            "delivered_binding": dict(binding["delivered_binding"]),
            "registry_identity": REGISTRY,
            "reason": "ready",
        }

    def _inv(self, tool_id: str, result: dict) -> dict:
        with self.lock:
            self.invocations += 1
            inv = f"inv_{self.invocations:032x}"
        delivered = self.bindings[(tool_id, "*")]["delivered_binding"]
        return {
            "code": "INVOKE_TOOL_OK",
            "ok": True,
            "invocation_id": inv,
            "status": "completed",
            "result": result,
            "identity_attestation": {
                "tool_identity": delivered["tool_identity"],
                "tool_tree": delivered["tool_tree"],
                "gtg_identity": GTG_COMMIT,
            },
            "evidence": {
                "tool_id": tool_id,
                "tool_identity": delivered["tool_identity"],
                "registry_identity": delivered["registry_identity"],
            },
        }

    def _moh_response(self, execution_id: str, state: str) -> dict:
        base = {
            "schema": "moh-status/v1",
            "execution_id": execution_id,
            "state": state,
        }
        if state != "NOT_FOUND":
            base.update({
                "request_digest": "3" * 64,
                "operation_id": "platform.self_check",
                "result": {"schema": "platform.self_check.result/v1", "ok": state == "SUCCEEDED"} if state == "SUCCEEDED" else None,
                "result_digest": "4" * 64 if state == "SUCCEEDED" else None,
                "exit_status": 0 if state == "SUCCEEDED" else (1 if state == "FAILED" else None),
                "failure_code": "FIXTURE_FAILED" if state == "FAILED" else ("FIXTURE_IN_DOUBT" if state == "IN_DOUBT" else None),
                "stdout": {"digest": "5" * 64, "total_bytes": 10_000_000, "retained_bytes": 65536, "truncated": True, "evidence_ref": "moh/evidence/stdout"},
                "stderr": None,
                "termination": None,
            })
            base["receipt_digest"] = canonical_digest(base)
        return base