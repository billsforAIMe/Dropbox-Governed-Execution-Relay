from __future__ import annotations

from dataclasses import replace
import unittest

from dger.gen4 import DgerGen4Error
import dger.gen4_delegation as delegation
from dger.gen4_delegation import (
    DELEGATED_AUTHORIZATION_RULE,
    DELEGATED_SERVICE_CONTEXT_ISSUER,
    DELEGATED_SERVICE_CONTEXT_SCHEMA,
    EXECUTION_RELAY_ROLE,
    delegated_service_context_to_dict,
    parse_delegated_service_context,
    require_protected_service_match,
)
from test_gen4 import service_identity


def valid_context() -> dict:
    return {
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
            "tool:common-handoff-manager:handoff_attach_result",
            "tool:common-handoff-manager:handoff_get",
        ],
        "authorized_capability_classes": ["EFFECT", "READ"],
        "project_binding": "ai-me",
        "context_digest": "sha256:" + "4" * 64,
    }


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
                "tool:common-handoff-manager:handoff_attach_result",
                "tool:common-handoff-manager:handoff_get",
            ),
        )
        self.assertFalse(hasattr(delegation, "authorize"))
        self.assertFalse(hasattr(delegation, "require_delegated_operation_claim"))

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


if __name__ == "__main__":
    unittest.main()
