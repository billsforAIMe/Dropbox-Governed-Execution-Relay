from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest

from dger.relay_v1 import (
    CHM_TOOL_ID, MOH_TOOL_ID, READY_SCHEMA, REQUEST_SCHEMA, Relay, canonical_bytes, canonical_digest,
    moh_closure_digest, payload_manifest, sha256, _safe_rel,
)
from fixture_gateway import (
    CHM_COMMIT, CHM_TREE, COMMIT, CONSUMER, CONSUMER_REPO, FakeGateway, MOH_COMMIT, MOH_TREE, REGISTRY, TREE, make_binding,
)
from fixture_package import canonical_file, handoff_for, rewrite_ready, write_package

class RelayV1TestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dger-v1-")
        self.base = Path(self.tmp.name)
        self.transport = self.base / "transport"
        self.state = self.base / "state"
        self.moh = self.base / "moh"
        self.gateway = FakeGateway()
        self.relay = Relay(self.transport, self.state, moh_home=self.moh, gateway=self.gateway, sleep=lambda _: None)

    def tearDown(self):
        self.tmp.cleanup()

    def state_for(self, eid):
        return json.loads((self.state / "executions" / f"{eid}.json").read_text())

    def status_for(self, eid):
        return json.loads((self.transport / "Runs" / eid / "status.json").read_text())
