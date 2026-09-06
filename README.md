# Dropbox Governed Execution Relay — Generation 4 source release

DGER is the governed immutable-transport and reconciliation relay for asynchronous Mac execution. Generation 4 composes DGER with the fixed-dispatcher architecture while keeping execution admission, lifecycle entitlement, host process truth, handoff history, and transport authority separate.

Generation-4 **source publication and secure runtime activation are separate**. The exact delivered Generation-3 runtime may remain installed before cutover. Production Gen4 peer operations remain fail-closed until the exact current-compatible GTG/GTC, AHC, GEP, CHM, and MOH contracts are delivered and bound.

## Authority and boundary model

- **DGER Git:** software authority for DGER source only.
- **GTG/GTC:** authenticated delegated service context, operation authorization, provider currentness/compatibility, exact dispatch, and invocation-time identity attestation.
- **AHC:** consequential-effect lifecycle/entitlement authority and causal Builder wake authority.
- **GEP:** execution-admission authority and owner of the signed MOH admission/execution correlation.
- **MOH:** sole Mac process-start and terminal host-truth authority; preserves `NO BLIND REPEAT`.
- **CHM:** optional tenant-bound correlation/result/history only; never execution entitlement.
- **DGER:** immutable transport intake, protected reconciliation State, AHC-before-MOH ordering, bounded terminal publication, and exact provider-evidence retention.
- **Dropbox:** transport only; never software, trust, lifecycle, or execution authority.

The immediate service actor is `EXECUTION_RELAY`. Origin tenant/principal/deployment/fleet epoch is obtained only through authenticated peer truth. Caller/Dropbox material cannot establish identity, role, entitlement, execution profile, shell, executable, interpreter, argv, cwd, environment, PATH, trust key, handler, result channel, or retry policy.

## Immutable V2 ingress

The transport-neutral V2 package contains:

```text
<dger_request_id>/
  request.json
  admission.bin
  payload/**
  READY.json
```

`request.json` carries only DGER/GEP/AHC/optional-CHM correlation identifiers. `admission.bin` is the exact opaque GEP-signed MOH admission; DGER preserves it unchanged. `READY.json` binds exact request/admission bytes and deterministic payload closure. `tools/build_gen4_ingress.py` seals this package but grants no execution authority.

Once READY is accepted, DGER freezes exact material into private State with positive readback. Recovery no longer depends on continued Dropbox package presence. Same-ID changed-byte reuse or conflicting GEP execution intent fails closed.

## AHC-before-MOH execution ordering

For every Generation-4 execution DGER enforces:

```text
private ingress freeze
→ authenticated trusted correlation
→ exact MOH staging
→ PRE_AHC_EXECUTE_WAL
→ AHC begin
→ exact AHC IN_DOUBT
→ MOH status proof
→ MOH execute-call WAL
→ MOH execute/status reconciliation
→ durable MOH terminal truth
→ AHC terminal acceptance
→ optional CHM result/history publication
```

A lost AHC-begin response is reconciled through AHC status. Any ambiguous MOH execute response restarts through MOH status, not another blind execute. Only a fresh exact `NOT_FOUND`/`ADMITTED` observation can permit a same-GEP-execution retry. Once MOH reports `IN_DOUBT`, DGER permanently removes execute permission for that execution and retries only AHC in-doubt reporting.

AHC or CHM unavailability after MOH terminal truth cannot cause re-execution.

## Invocation-time provider identity

Every successful Generation-4 semantic peer call must carry exact GTG invocation-time evidence containing the invocation ID, Tool commit/tree, GTG identity, and Registry identity. DGER retains this evidence in trusted correlation, AHC/MOH observations, AHC/CHM acknowledgements, and the bounded terminal result where applicable.

Provider advancement alone never authorizes host execution. The exact peer adapter must reject a provider that is not current-compatible; DGER records whichever exact compatible provider actually serviced each successful call.

## Compatibility and anti-bypass

Generation-3 production remains valid only before protected Gen4 activation. Once `gen4/ACTIVATED.json` exists in installed DGER State, Generation-3 runtime construction fails closed; malformed/unsafe marker bytes also fail closed.

The older Prototype R0 direct-GEP process-start module is permanently retired in Generation-4 source and exposes no execution-capable compatibility shim.

`GOVERNED_EFFECT_SURFACE_INVENTORY.json` and `tools/validate_gen4_effect_surface_inventory.py` inventory the process-start/effect/admin/recovery/compatibility surfaces and detect unclassified DGER Python execution primitives.

## Current pre-activation peer boundary

`Gen4Peers` is an internal normalization/test port, not a caller authority surface. `UnavailableGen4Peers` is the source-published production placeholder and fails all Gen4 peer operations with `GEN4_PEER_CONTRACTS_UNAVAILABLE` until the exact delivered peer tuple exists.

DGER does not invent local substitutes for pending GTG actor-context, AHC effect, GEP signed-admission, CHM tenant-correlation, or MOH signed-admission contracts.

## Protocol and deployment

See `docs/PROTOCOL_V2.md` for the Generation-4 source contract and `docs/PROTOCOL_V1.md` for the delivered Generation-3 compatibility protocol.

Actual Gen4 activation requires protected DGER service credential/identity provisioning, exact peer currentness/callability, Mac deployment qualification, cross-namespace/service replay falsification, crash/recovery qualification, Registry discovery verification, rollback evidence, and protected activation-State creation. Until then, the existing Generation-3 installed runtime may remain selected under the explicit runtime compatibility declaration in `GOVERNED_RELEASE.json`.
