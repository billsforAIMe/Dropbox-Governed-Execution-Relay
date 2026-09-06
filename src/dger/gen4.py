from __future__ import annotations

from .gen4_primitives import *  # re-export stable source-contract helpers
from .gen4_contract import (
    Ack, AhcObservation, Gen4Peers, InvocationEvidence, MohObservation, ServiceIdentity, StageReceipt,
    TrustedCorrelation, TrustedOrigin, UnavailableGen4Peers, load_service_identity,
)
from .gen4_delegation import (
    DELEGATED_AUTHORIZATION_RULE, DELEGATED_SERVICE_CONTEXT_ISSUER,
    DELEGATED_SERVICE_CONTEXT_SCHEMA, EXECUTION_RELAY_ROLE, DelegatedServiceContext,
    delegated_service_context_to_dict, parse_delegated_service_context,
    require_protected_service_match,
)
from .gen4_state import Gen4StateMixin
from .gen4_effect import Gen4EffectMixin
from .gen4_driver import Gen4DriverMixin


class Gen4Relay(Gen4DriverMixin, Gen4EffectMixin, Gen4StateMixin):
    pass


__all__ = [
    "Ack", "AhcObservation", "DELEGATED_AUTHORIZATION_RULE", "DELEGATED_SERVICE_CONTEXT_ISSUER",
    "DELEGATED_SERVICE_CONTEXT_SCHEMA", "DgerGen4Error", "DelegatedServiceContext",
    "EXECUTION_RELAY_ROLE", "Gen4Peers", "Gen4Relay", "InvocationEvidence", "MohObservation",
    "REQUEST_SCHEMA", "READY_SCHEMA", "RESULT_SCHEMA", "SERVICE_IDENTITY_SCHEMA", "ServiceIdentity",
    "StageReceipt", "TrustedCorrelation", "TrustedOrigin", "UnavailableGen4Peers", "canonical_bytes",
    "canonical_digest", "canonical_file_bytes", "delegated_service_context_to_dict",
    "load_service_identity", "make_ready_record", "parse_delegated_service_context", "payload_manifest",
    "require_protected_service_match", "sha256",
]
