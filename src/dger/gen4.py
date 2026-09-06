from __future__ import annotations

from .gen4_primitives import *  # re-export stable source-contract helpers
from .gen4_contract import (
    Ack, AhcObservation, Gen4Peers, InvocationEvidence, MohObservation, ServiceIdentity, StageReceipt,
    TrustedCorrelation, TrustedOrigin, UnavailableGen4Peers, load_service_identity,
)
from .gen4_state import Gen4StateMixin
from .gen4_effect import Gen4EffectMixin
from .gen4_driver import Gen4DriverMixin


class Gen4Relay(Gen4DriverMixin, Gen4EffectMixin, Gen4StateMixin):
    pass


__all__ = [
    "Ack", "AhcObservation", "DgerGen4Error", "Gen4Peers", "Gen4Relay", "InvocationEvidence",
    "MohObservation", "REQUEST_SCHEMA", "READY_SCHEMA", "RESULT_SCHEMA", "SERVICE_IDENTITY_SCHEMA",
    "ServiceIdentity", "StageReceipt", "TrustedCorrelation", "TrustedOrigin", "UnavailableGen4Peers",
    "canonical_bytes", "canonical_digest", "canonical_file_bytes", "load_service_identity",
    "make_ready_record", "payload_manifest", "sha256",
]
