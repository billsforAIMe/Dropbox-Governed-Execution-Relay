from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import uuid
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class GTGHttpError(RuntimeError):
    pass


MAX_GTG_RESPONSE_BYTES = 1024 * 1024
MAX_TOKEN_BYTES = 4096


def _read_secret(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise GTGHttpError("GTG_TOKEN_FILE_UNSAFE") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise GTGHttpError("GTG_TOKEN_FILE_UNSAFE")
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise GTGHttpError("GTG_TOKEN_FILE_PERMISSIONS")
        if st.st_size > MAX_TOKEN_BYTES:
            raise GTGHttpError("GTG_TOKEN_FILE_TOO_LARGE")
        raw = os.read(fd, MAX_TOKEN_BYTES + 1)
        if len(raw) != st.st_size:
            raise GTGHttpError("GTG_TOKEN_FILE_CHANGED")
    finally:
        os.close(fd)
    try:
        value = raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise GTGHttpError("GTG_TOKEN_INVALID") from exc
    if len(value) < 32:
        raise GTGHttpError("GTG_TOKEN_INVALID")
    return value


class GTGHttpGateway:
    """Transport-only adapter to GTG's permanent universal semantic surface."""

    def __init__(self, endpoint: str, token_file: Path, *, allow_insecure_localhost: bool = False, timeout: float = 30.0) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise GTGHttpError("GTG_ENDPOINT_INVALID")
        if parsed.scheme != "https":
            local = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
            if not (allow_insecure_localhost and local):
                raise GTGHttpError("GTG_ENDPOINT_REQUIRES_HTTPS")
        self.endpoint = endpoint
        self._token = _read_secret(token_file)
        self.timeout = timeout

    def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
                "_meta": {"io.modelcontextprotocol/clientInfo": {"name": "dger", "version": "1.0"}},
            },
        }, separators=(",", ":")).encode("utf-8")
        req = Request(self.endpoint, data=body, method="POST", headers={
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call",
            "Mcp-Name": name,
        })
        try:
            with urlopen(req, timeout=self.timeout) as response:
                raw = response.read(MAX_GTG_RESPONSE_BYTES + 1)
        except Exception as exc:
            raise GTGHttpError("GTG_TRANSPORT_FAILURE") from exc
        if len(raw) > MAX_GTG_RESPONSE_BYTES:
            raise GTGHttpError("GTG_RESPONSE_TOO_LARGE")
        try:
            payload = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GTGHttpError("GTG_INVALID_RESPONSE") from exc
        if not isinstance(payload, dict) or payload.get("id") != request_id:
            raise GTGHttpError("GTG_INVALID_RESPONSE")
        if "error" in payload:
            raise GTGHttpError("GTG_RPC_ERROR")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise GTGHttpError("GTG_INVALID_RESULT")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str):
                parsed_text = json.loads(text)
                if isinstance(parsed_text, dict):
                    return parsed_text
        raise GTGHttpError("GTG_RESULT_UNSTRUCTURED")

    def doctor(self, tool_id: str, operation: str) -> dict[str, Any]:
        return self._call("doctor", {"environment": "current", "tool_id": tool_id, "operation": operation})

    def invoke(self, tool_id: str, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._call("invoke_tool", {"tool_id": tool_id, "operation": operation, "arguments": arguments})

    def get_invocation(self, invocation_id: str) -> dict[str, Any]:
        return self._call("get_invocation", {"invocation_id": invocation_id})
