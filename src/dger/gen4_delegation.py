from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from .gen4_contract import ServiceIdentity
from .gen4_primitives import DgerGen4Error

DELEGATED_SERVICE_CONTEXT_SCHEMA = "governed-delegated-service-context/v1"
DELEGATED_SERVICE_CONTEXT_ISSUER = "governed-tool-gateway"
EXECUTION_RELAY_ROLE = "EXECUTION_RELAY"
DELEGATED_AUTHORIZATION_RULE = "ORIGIN_INTERSECT_SERVICE_INTERSECT_TARGET_POLICY"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ORIGIN_INVOCATION_RE = re.compile(r"^gtg_inv_[0-9a-f]{64}$")
_DELEGATION_INVOCATION_RE = re.compile(r"^gtg_del_[0-9a-f]{64}$")
_CONTEXT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPERATION_RE = re.compile(r"^tool:[a-z0-9][a-z0-9-]{0,63}:[a-z][a-z0-9_.:-]{0,127}$")
_ORIGIN_ROLES = frozenset({"BUILDER", "REVIEWER", "V1_SERVICE"})
_CAPABILITY_CLASSES = frozenset({"EFFECT", "READ"})

_EXPECTED_FIELDS = {
    "schema",
    "issuer",
    "tenant_id",
    "principal_id",
    "deployment_id",
    "origin_actor_role",
    "provisioned_fleet_epoch",
    "origin_context_digest",
    "origin_invocation_id",
    "service_role",
    "service_id",
    "service_deployment_id",
    "delegation_invocation_id",
    "authorized_operations",
    "authorized_capability_classes",
    "project_binding",
    "context_digest",
}


@dataclass(frozen=True)
class DelegatedServiceContext:
    """Closed GTG #94 delegated-service *value* contract.

    Construction validates the exact delivered logical record only. It never proves
    transport authentication, signature verification, GTC policy currentness, or
    authorization. Those remain GTG/GTC-owned runtime propositions.
    """

    schema: str
    issuer: str
    tenant_id: str
    principal_id: str
    deployment_id: str
    origin_actor_role: str
    provisioned_fleet_epoch: int
    origin_context_digest: str
    origin_invocation_id: str
    service_role: str
    service_id: str
    service_deployment_id: str
    delegation_invocation_id: str
    authorized_operations: tuple[str, ...]
    authorized_capability_classes: tuple[str, ...]
    project_binding: str | None
    context_digest: str


def _require_id(value: Any, code: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise DgerGen4Error(code)
    return value


def _require_canonical_string_list(
    value: Any,
    *,
    item_re: re.Pattern[str] | None,
    allowed: frozenset[str] | None,
    code: str,
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DgerGen4Error(code)
    if item_re is not None and any(item_re.fullmatch(item) is None for item in value):
        raise DgerGen4Error(code)
    if allowed is not None and any(item not in allowed for item in value):
        raise DgerGen4Error(code)
    # GTG #94 canonicalization requires unique lexicographically sorted
    # authorization arrays. DGER rejects rather than normalizes changed bytes.
    if value != sorted(set(value)):
        raise DgerGen4Error(code)
    return tuple(value)


def parse_delegated_service_context(value: Any) -> DelegatedServiceContext:
    """Parse the exact delivered GTG logical value without authenticating it."""
    if not isinstance(value, dict) or set(value) != _EXPECTED_FIELDS:
        raise DgerGen4Error("DELEGATED_CONTEXT_INVALID")
    if value.get("schema") != DELEGATED_SERVICE_CONTEXT_SCHEMA:
        raise DgerGen4Error("DELEGATED_CONTEXT_SCHEMA_INVALID")
    if value.get("issuer") != DELEGATED_SERVICE_CONTEXT_ISSUER:
        raise DgerGen4Error("DELEGATED_CONTEXT_ISSUER_INVALID")

    tenant_id = _require_id(value.get("tenant_id"), "DELEGATED_CONTEXT_TENANT_INVALID")
    principal_id = _require_id(value.get("principal_id"), "DELEGATED_CONTEXT_PRINCIPAL_INVALID")
    deployment_id = _require_id(value.get("deployment_id"), "DELEGATED_CONTEXT_DEPLOYMENT_INVALID")
    origin_actor_role = value.get("origin_actor_role")
    if origin_actor_role not in _ORIGIN_ROLES:
        raise DgerGen4Error("DELEGATED_CONTEXT_ORIGIN_ROLE_INVALID")

    epoch = value.get("provisioned_fleet_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
        raise DgerGen4Error("DELEGATED_CONTEXT_FLEET_EPOCH_INVALID")

    origin_context_digest = value.get("origin_context_digest")
    if not isinstance(origin_context_digest, str) or _CONTEXT_DIGEST_RE.fullmatch(origin_context_digest) is None:
        raise DgerGen4Error("DELEGATED_CONTEXT_ORIGIN_DIGEST_INVALID")
    origin_invocation_id = value.get("origin_invocation_id")
    if not isinstance(origin_invocation_id, str) or _ORIGIN_INVOCATION_RE.fullmatch(origin_invocation_id) is None:
        raise DgerGen4Error("DELEGATED_CONTEXT_ORIGIN_INVOCATION_INVALID")

    if value.get("service_role") != EXECUTION_RELAY_ROLE:
        raise DgerGen4Error("DELEGATED_CONTEXT_SERVICE_ROLE_INVALID")
    service_id = _require_id(value.get("service_id"), "DELEGATED_CONTEXT_SERVICE_ID_INVALID")
    service_deployment_id = _require_id(
        value.get("service_deployment_id"), "DELEGATED_CONTEXT_SERVICE_DEPLOYMENT_INVALID"
    )
    delegation_invocation_id = value.get("delegation_invocation_id")
    if not isinstance(delegation_invocation_id, str) or _DELEGATION_INVOCATION_RE.fullmatch(delegation_invocation_id) is None:
        raise DgerGen4Error("DELEGATED_CONTEXT_INVOCATION_INVALID")

    authorized_operations = _require_canonical_string_list(
        value.get("authorized_operations"),
        item_re=_OPERATION_RE,
        allowed=None,
        code="DELEGATED_CONTEXT_OPERATIONS_INVALID",
    )
    authorized_capability_classes = _require_canonical_string_list(
        value.get("authorized_capability_classes"),
        item_re=None,
        allowed=_CAPABILITY_CLASSES,
        code="DELEGATED_CONTEXT_CAPABILITIES_INVALID",
    )

    project_binding = value.get("project_binding")
    if project_binding is not None and (
        not isinstance(project_binding, str) or not (1 <= len(project_binding) <= 4096)
    ):
        raise DgerGen4Error("DELEGATED_CONTEXT_PROJECT_BINDING_INVALID")

    context_digest = value.get("context_digest")
    if not isinstance(context_digest, str) or _CONTEXT_DIGEST_RE.fullmatch(context_digest) is None:
        raise DgerGen4Error("DELEGATED_CONTEXT_DIGEST_INVALID")

    return DelegatedServiceContext(
        schema=DELEGATED_SERVICE_CONTEXT_SCHEMA,
        issuer=DELEGATED_SERVICE_CONTEXT_ISSUER,
        tenant_id=tenant_id,
        principal_id=principal_id,
        deployment_id=deployment_id,
        origin_actor_role=origin_actor_role,
        provisioned_fleet_epoch=epoch,
        origin_context_digest=origin_context_digest,
        origin_invocation_id=origin_invocation_id,
        service_role=EXECUTION_RELAY_ROLE,
        service_id=service_id,
        service_deployment_id=service_deployment_id,
        delegation_invocation_id=delegation_invocation_id,
        authorized_operations=authorized_operations,
        authorized_capability_classes=authorized_capability_classes,
        project_binding=project_binding,
        context_digest=context_digest,
    )


def delegated_service_context_to_dict(context: DelegatedServiceContext) -> dict[str, Any]:
    value = asdict(context)
    value["authorized_operations"] = list(context.authorized_operations)
    value["authorized_capability_classes"] = list(context.authorized_capability_classes)
    return value


def require_protected_service_match(context: DelegatedServiceContext, service: ServiceIdentity) -> None:
    """Bind a validated value to DGER protected service identity; still not authentication."""
    if service.actor_role != EXECUTION_RELAY_ROLE or context.service_role != EXECUTION_RELAY_ROLE:
        raise DgerGen4Error("SERVICE_ROLE_INVALID")
    if context.service_id != service.service_principal_id:
        raise DgerGen4Error("WRONG_DGER_SERVICE_ID")
    if context.service_deployment_id != service.service_deployment_id:
        raise DgerGen4Error("WRONG_DGER_SERVICE_DEPLOYMENT")


def require_delegated_operation_claim(
    context: DelegatedServiceContext,
    *,
    tool_id: str,
    operation: str,
    authority_class: str,
) -> None:
    """Check consistency with an already-authenticated GTG/GTC decision.

    This function MUST NOT be used to turn an unauthenticated serialized context into
    authority. GTG/GTC owns authentication and the origin ∩ EXECUTION_RELAY ∩ target
    policy decision; DGER merely refuses a peer call not named by that admitted result.
    """
    if authority_class not in _CAPABILITY_CLASSES:
        raise DgerGen4Error("DELEGATED_CONTEXT_CAPABILITY_INVALID")
    tool = _require_id(tool_id, "DELEGATED_CONTEXT_TOOL_INVALID")
    op = _require_id(operation, "DELEGATED_CONTEXT_OPERATION_INVALID")
    operation_id = f"tool:{tool}:{op}"
    if operation_id not in context.authorized_operations:
        raise DgerGen4Error("OPERATION_DENIED")
    if authority_class not in context.authorized_capability_classes:
        raise DgerGen4Error("OPERATION_DENIED")
