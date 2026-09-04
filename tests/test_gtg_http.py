from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dger.gtg_http import GTGHttpError, GTGHttpGateway, MAX_GTG_RESPONSE_BYTES


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class GTGHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.token = self.root / "token"
        self.token.write_text("x" * 64)
        os.chmod(self.token, 0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def test_token_symlink_rejected(self):
        link = self.root / "link"
        link.symlink_to(self.token)
        with self.assertRaisesRegex(GTGHttpError, "GTG_TOKEN_FILE_UNSAFE"):
            GTGHttpGateway("https://gtg.invalid/mcp", link)

    def test_oversized_response_rejected_before_json_parse(self):
        gateway = GTGHttpGateway("https://gtg.invalid/mcp", self.token)
        with patch("dger.gtg_http.urlopen", return_value=_Response(b"x" * (MAX_GTG_RESPONSE_BYTES + 1))):
            with self.assertRaisesRegex(GTGHttpError, "GTG_RESPONSE_TOO_LARGE"):
                gateway.doctor("tool", "operation")

    def test_structured_response_round_trip(self):
        gateway = GTGHttpGateway("https://gtg.invalid/mcp", self.token)
        def response_for(request, timeout):
            body = json.loads(request.data)
            payload = json.dumps({
                "jsonrpc": "2.0", "id": body["id"],
                "result": {"structuredContent": {"ok": True, "value": 1}},
            }).encode()
            return _Response(payload)
        with patch("dger.gtg_http.urlopen", side_effect=response_for):
            self.assertEqual({"ok": True, "value": 1}, gateway.doctor("tool", "operation"))

    def test_invoke_requires_exact_success_attestation(self):
        gateway = GTGHttpGateway("https://gtg.invalid/mcp", self.token)
        def response_for(request, timeout):
            body = json.loads(request.data)
            tool_id = body["params"]["arguments"]["tool_id"]
            result = {
                "code": "INVOKE_TOOL_OK",
                "ok": True,
                "invocation_id": "inv_" + "1" * 32,
                "status": "completed",
                "result": {"ok": True},
                "identity_attestation": {
                    "tool_identity": "1" * 40,
                    "tool_tree": "2" * 40,
                    "gtg_identity": "3" * 40,
                },
                "evidence": {
                    "tool_id": tool_id,
                    "tool_identity": "1" * 40,
                    "registry_identity": "4" * 40,
                },
            }
            payload = json.dumps({
                "jsonrpc": "2.0", "id": body["id"],
                "result": {"structuredContent": result},
            }).encode()
            return _Response(payload)
        with patch("dger.gtg_http.urlopen", side_effect=response_for):
            value = gateway.invoke("mac-operation-host", "status", {"execution_id": "e"})
            self.assertEqual(value["identity_attestation"]["tool_identity"], "1" * 40)

        def missing_for(request, timeout):
            body = json.loads(request.data)
            result = {
                "code": "INVOKE_TOOL_OK",
                "ok": True,
                "invocation_id": "inv_" + "2" * 32,
                "status": "completed",
                "result": {"ok": True},
                "evidence": {
                    "tool_id": "mac-operation-host",
                    "tool_identity": "1" * 40,
                    "registry_identity": "4" * 40,
                },
            }
            payload = json.dumps({
                "jsonrpc": "2.0", "id": body["id"],
                "result": {"structuredContent": result},
            }).encode()
            return _Response(payload)
        with patch("dger.gtg_http.urlopen", side_effect=missing_for):
            with self.assertRaisesRegex(GTGHttpError, "GTG_IDENTITY_ATTESTATION_REQUIRED"):
                gateway.invoke("mac-operation-host", "status", {"execution_id": "e"})


if __name__ == "__main__":
    unittest.main(verbosity=2)