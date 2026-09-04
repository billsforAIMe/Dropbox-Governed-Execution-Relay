from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from dger.relay_v1 import (
    READY_SCHEMA, REQUEST_SCHEMA, Relay, canonical_bytes, canonical_digest, moh_closure_digest, payload_manifest, sha256,
)
from fixture_gateway import (
    CHM_TOOL_ID, COMMIT, CONSUMER, CONSUMER_REPO, FakeGateway, MOH_TOOL_ID, REGISTRY, TREE, make_binding,
)

def canonical_file(value):
    return canonical_bytes(value) + b"\n"

def handoff_for(eid: str) -> str:
    return "hnd_" + sha256(eid.encode())


def write_package(root: Path, eid: str, *, content: bytes = b"print('fixture')\n", ready: bool = True, handoff: str | None = None) -> Path:
    package = root / "Ingress" / eid
    payload = package / "payload"
    payload.mkdir(parents=True, exist_ok=True)
    contract = {
        "schema": "moh-operation-contract/v1",
        "operation_id": "platform.self_check",
        "adapter_kind": "governed_python",
        "entrypoint": "adapter.py",
        "launch_context": "BACKGROUND",
        "effect_class": "READ",
        "retry_policy": "NO_AUTOMATIC_RETRY",
        "result_schema": "platform.self_check.result/v1",
        "parameters_schema": "none/v1",
        "release": {"tool_id": CONSUMER, "repository_id": CONSUMER_REPO, "selector": "refs/heads/main", "commit": COMMIT, "tree": TREE},
    }
    (payload / "operation.json").write_bytes(canonical_file(contract))
    (payload / "adapter.py").write_bytes(content)
    entries, total, manifest_digest = payload_manifest(payload)
    body = {
        "schema": "moh-execution-envelope/v1",
        "execution_id": eid,
        "upstream_correlation_id": f"corr:{eid}",
        "tool_id": CONSUMER,
        "repository_id": CONSUMER_REPO,
        "authority_selector": "refs/heads/main",
        "authority_commit": COMMIT,
        "authority_tree": TREE,
        "operation_id": "platform.self_check",
        "operation_contract_digest": canonical_digest(contract),
        "closure_digest": moh_closure_digest(entries),
        "parameters": {},
        "parameters_digest": canonical_digest({}),
        "effect_class": "READ",
        "launch_context": "BACKGROUND",
        "retry_policy": "NO_AUTOMATIC_RETRY",
    }
    envelope = dict(body)
    envelope["request_digest"] = canonical_digest(body)
    envelope_raw = canonical_file(envelope)
    request = {
        "schema": REQUEST_SCHEMA,
        "execution_id": eid,
        "logical_handoff_id": handoff or handoff_for(eid),
        "dger_request_id": f"req:{eid}",
    }
    request_raw = canonical_file(request)
    (package / "request.json").write_bytes(request_raw)
    (package / "envelope.json").write_bytes(envelope_raw)
    if ready:
        marker = {
            "schema": READY_SCHEMA,
            "execution_id": eid,
            "request_sha256": sha256(request_raw),
            "request_size": len(request_raw),
            "envelope_sha256": sha256(envelope_raw),
            "envelope_size": len(envelope_raw),
            "payload_manifest_sha256": manifest_digest,
            "payload_total_bytes": total,
            "payload_file_count": len(entries),
        }
        (package / "READY.json").write_bytes(canonical_file(marker))
    return package


def rewrite_ready(package: Path) -> None:
    from dger.relay_v1 import payload_manifest
    request_raw = (package / "request.json").read_bytes()
    envelope_raw = (package / "envelope.json").read_bytes()
    entries, total, manifest_digest = payload_manifest(package / "payload")
    marker = {
        "schema": READY_SCHEMA,
        "execution_id": package.name,
        "request_sha256": sha256(request_raw), "request_size": len(request_raw),
        "envelope_sha256": sha256(envelope_raw), "envelope_size": len(envelope_raw),
        "payload_manifest_sha256": manifest_digest, "payload_total_bytes": total, "payload_file_count": len(entries),
    }
    (package / "READY.json").write_bytes(canonical_file(marker))
