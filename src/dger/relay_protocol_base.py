from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
from datetime import datetime, timezone
from typing import Any, Protocol

PROTOCOL = "DGER_EXECUTION_V1"
REQUEST_SCHEMA = "dger-execution-request/v1"
READY_SCHEMA = "dger-ready/v1"
PAYLOAD_MANIFEST_SCHEMA = "dger-payload-manifest/v1"
CHM_RESULT_SCHEMA = "dger-chm-completion/v1"
MOH_ENVELOPE_SCHEMA = "moh-execution-envelope/v1"
MOH_CLOSURE_SCHEMA = "moh-closure-manifest/v1"

MOH_TOOL_ID = "mac-operation-host"
CHM_TOOL_ID = "common-handoff-manager"
REQUIRED_CHM_OPERATIONS = ("handoff_get", "handoff_attach_result", "handoff_resolve")

MAX_ENVELOPE_BYTES = 32_768
MAX_REQUEST_BYTES = 32_768
MAX_FILES = 64
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_PATH_BYTES = 240
MAX_MOH_RESPONSE_BYTES = 256 * 1024
MAX_RESULT_RECORD_BYTES = 512 * 1024
EXPECTED_INTERVAL_SECONDS = 2

EXECUTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HANDOFF_ID_RE = re.compile(r"^hnd_[0-9a-f]{64}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

MOH_TERMINAL_PUBLISHABLE = {"SUCCEEDED", "FAILED", "REJECTED_PRECONDITION", "REJECTED_DUPLICATE_MISMATCH"}
MOH_UNRESOLVED = {"IN_DOUBT"}
MOH_NONTERMINAL = {"NOT_FOUND", "ADMITTED", "START_INTENT_COMMITTED", "RUNNING"}


class DgerError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


class SemanticGateway(Protocol):
    def doctor(self, tool_id: str, operation: str) -> dict[str, Any]: ...
    def invoke(self, tool_id: str, operation: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def invoke_frozen(
        self,
        tool_id: str,
        operation: str,
        arguments: dict[str, Any],
        frozen_binding: dict[str, Any],
    ) -> dict[str, Any]: ...
    def get_invocation(self, invocation_id: str) -> dict[str, Any]: ...


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_file_bytes(value: Any) -> bytes:
    return canonical_bytes(value) + b"\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: Any) -> str:
    return sha256(canonical_bytes(value))
