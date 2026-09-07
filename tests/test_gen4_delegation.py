from __future__ import annotations

from dataclasses import replace
import unittest

import dger.gen4_delegation as delegation
from dger.gen4_contract import ServiceIdentity
from dger.gen4_delegation import (
    DELEGATED_AUTHORIZATION_RULE,
    DELEGATED_SERVICE_CONTEXT_ISSUER,
    DELEGATED_SERVICE_CONTEXT_SCHEMA,
    EXECUTION_RELAY_ROLE,
    delegated_service_context_to_dict,
    parse_delegated_service_context,
    require_protected_service_match,
)
from dger.gen4_primitives import (
    DgerGen4Error, REQUEST_SCHEMA, SERVICE_IDENTITY_SCHEMA, _validate_request,
    canonical_digest, canonical_file_bytes, sha256,
)


def service_identity(deployment: str = "dger-deployment-A") -> ServiceIdentity:
    body = {
        "schema": SERVICE_IDENTITY_SCHEMA,
        "service_principal_id": "dger-service",
        "service_deployment_id": deployment,
        "actor_role": EXECUTION_RELAY_ROLE,
    }
    return ServiceIdentity(
        service_principal_id=body["service_principal_id"],
        service_deployment_id=deployment,
        actor_role=EXECUTION_RELAY_ROLE,
        identity_digest=canonical_digest(body),
    )


def valid_context() -> dict:
    value = {
        "schema": DELEGATED_SERVICE_CONTEXT_SCHEMA,
        "issuer": DELEGATED_SERVICE_CONTEXT_ISSUER,
        "tenant_id": "tenant-A",
        "principal_id": "principal-A",
        "deployment_id": "builder-deployment-A",
        "origin_actor_role": "BUILDER",
        "provisioned_fleet_epoch": 7,
        "origin_context_digest": "sha256:" + "1" * 64,
        "origin_invocation_id": "gtg_inv_" + "2" * 64,
        "service_role": EXECUTION_RELAY_ROLE,
        "service_id": "dger-service",
        "service_deployment_id": "dger-deployment-A",
        "delegation_invocation_id": "gtg_del_" + "3" * 64,
        "authorized_operations": [
            "tool:common-handoff-manager:handoff_read",
            "tool:common-handoff-manager:publish_terminal_result",
        ],
        "authorized_capability_classes": ["EFFECT", "READ"],
        "project_binding": "ai-me",
    }
    value["context_digest"] = "sha256:" + sha256(canonical_file_bytes(value))
    return value


class DelegatedServiceContextTests(unittest.TestCase):
    def test_exact_delivered_context_round_trips_without_role_impersonation(self):
        raw = valid_context()
        context = parse_delegated_service_context(raw)
        self.assertEqual(context.origin_actor_role, "BUILDER")
        self.assertEqual(context.service_role, "EXECUTION_RELAY")
        self.assertEqual(context.service_id, "dger-service")
        self.assertEqual(context.origin_invocation_id, "gtg_inv_" + "2" * 64)
        self.assertEqual(context.delegation_invocation_id, "gtg_del_" + "3" * 64)
        self.assertEqual(delegated_service_context_to_dict(context), raw)
        self.assertEqual(DELEGATED_AUTHORIZATION_RULE, "ORIGIN_INTERSECT_SERVICE_INTERSECT_TARGET_POLICY")

    def test_parsed_value_exposes_no_local_authorization_decision(self):
        context = parse_delegated_service_context(valid_context())
        self.assertEqual(
            context.authorized_operations,
            (
                "tool:common-handoff-manager:handoff_read",
                "tool:common-handoff-manager:publish_terminal_result",
            ),
        )
        self.assertFalse(hasattr(delegation, "authorize"))
        self.assertFalse(hasattr(delegation, "require_delegated_operation_claim"))

    def test_context_digest_binds_exact_logical_value_but_is_not_authentication(self):
        raw = valid_context()
        parse_delegated_service_context(raw)
        raw["tenant_id"] = "tenant-B"
        with self.assertRaisesRegex(DgerGen4Error, "DELEGATED_CONTEXT_DIGEST_MISMATCH"):
            parse_delegated_service_context(raw)

    def test_context_is_bound_to_protected_service_not_dropbox_identity(self):
        context = parse_delegated_service_context(valid_context())
        require_protected_service_match(context, service_identity())
        with self.assertRaisesRegex(DgerGen4Error, "WRONG_DGER_SERVICE_DEPLOYMENT"):
            require_protected_service_match(context, service_identity("other-dger"))
        wrong_service = replace(service_identity(), service_principal_id="other-service")
        with self.assertRaisesRegex(DgerGen4Error, "WRONG_DGER_SERVICE_ID"):
            require_protected_service_match(context, wrong_service)

    def test_exact_gtg_invocation_names_are_required(self):
        for field, bad in (
            ("origin_invocation_id", "inv_" + "2" * 32),
            ("delegation_invocation_id", "inv_" + "3" * 32),
            ("origin_context_digest", "1" * 64),
            ("context_digest", "4" * 64),
        ):
            with self.subTest(field=field):
                raw = valid_context(); raw[field] = bad
                with self.assertRaises(DgerGen4Error):
                    parse_delegated_service_context(raw)

    def test_context_is_closed_and_canonical_arrays_are_not_normalized(self):
        raw = valid_context(); raw["tenant_from_dropbox"] = "attacker"
        with self.assertRaisesRegex(DgerGen4Error, "DELEGATED_CONTEXT_INVALID"):
            parse_delegated_service_context(raw)
        raw = valid_context(); raw["authorized_operations"] = list(reversed(raw["authorized_operations"]))
        with self.assertRaisesRegex(DgerGen4Error, "DELEGATED_CONTEXT_OPERATIONS_INVALID"):
            parse_delegated_service_context(raw)
        raw = valid_context(); raw["authorized_capability_classes"] = ["READ", "READ"]
        with self.assertRaisesRegex(DgerGen4Error, "DELEGATED_CONTEXT_CAPABILITIES_INVALID"):
            parse_delegated_service_context(raw)

    def test_epoch_and_roles_fail_closed(self):
        for field, bad in (
            ("provisioned_fleet_epoch", 0),
            ("provisioned_fleet_epoch", True),
            ("origin_actor_role", "EXECUTION_RELAY"),
            ("service_role", "BUILDER"),
        ):
            with self.subTest(field=field):
                raw = valid_context(); raw[field] = bad
                with self.assertRaises(DgerGen4Error):
                    parse_delegated_service_context(raw)

    def test_dropbox_request_cannot_supply_gtg_actor_or_service_authority_fields(self):
        request = {
            "schema": REQUEST_SCHEMA,
            "dger_request_id": "dger-001",
            "gep_execution_id": "gep-001",
            "ahc_effect_reservation_id": "effect-001",
            "chm_handoff_id": "hnd-001",
        }
        attacker_fields = {
            "issuer": DELEGATED_SERVICE_CONTEXT_ISSUER,
            "tenant_id": "tenant-B",
            "principal_id": "principal-B",
            "deployment_id": "builder-B",
            "origin_actor_role": "BUILDER",
            "provisioned_fleet_epoch": 99,
            "origin_context_digest": "sha256:" + "a" * 64,
            "origin_invocation_id": "gtg_inv_" + "b" * 64,
            "service_role": EXECUTION_RELAY_ROLE,
            "service_id": "attacker-relay",
            "service_deployment_id": "attacker-deployment",
            "delegation_invocation_id": "gtg_del_" + "c" * 64,
            "authorized_operations": ["tool:mac-operation-host:execute"],
            "authorized_capability_classes": ["EFFECT"],
            "project_binding": "attacker-project",
            "context_digest": "sha256:" + "d" * 64,
        }
        for field, value in attacker_fields.items():
            with self.subTest(field=field):
                forged = dict(request); forged[field] = value
                with self.assertRaisesRegex(DgerGen4Error, "MALFORMED_REQUEST"):
                    _validate_request(forged, "dger-001")


if __name__ == "__main__":
    unittest.main()
