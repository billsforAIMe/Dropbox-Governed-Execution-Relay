from __future__ import annotations

from fixture_gateway_core import (
    CHM_COMMIT, CHM_TOOL_ID, CHM_TREE, COMMIT, CONSUMER, CONSUMER_REPO, MOH_COMMIT, MOH_TOOL_ID, MOH_TREE,
    REGISTRY, TREE, FakeGatewayCore, canonical_file, make_binding,
)
from fixture_gateway_ops import FakeGatewayOpsMixin

class FakeGateway(FakeGatewayCore, FakeGatewayOpsMixin):
    pass
