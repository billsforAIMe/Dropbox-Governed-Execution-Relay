# DGER Execution Relay Protocol V2 — Generation 4 source contract

## Status

This is the Generation 4 **source-ready, pre-activation** contract for Dropbox Governed Execution Relay (DGER). It composes DGER with the fixed-dispatcher external-effect architecture without inventing peer-owned trust semantics.

Generation 4 source publication and secure runtime activation are separate. Until the exact delivered GTG/GTC delegated-service actor context, AHC effect bridge, GEP-signed MOH admission/reconciliation contract, CHM tenant-bound correlation contract, and MOH signed-admission consumer contract are all current and callable, DGER's production Gen4 peer adapter is intentionally unavailable and returns `GEN4_PEER_CONTRACTS_UNAVAILABLE`.

DGER remains transport and reconciliation infrastructure. It is not Builder/Reviewer authority, AHC lifecycle authority, GEP admission authority, CHM handoff authority, MOH process-start authority, or V1 orchestration authority.

## Immutable transport-neutral ingress

A V2 package is a directory named by `dger_request_id` containing exactly the execution material below plus the final publication barrier:

```text
<dger_request_id>/
  request.json
  admission.bin
  payload/**
  READY.json
```

`request.json` is canonical transport/routing correlation only:

```json
{
  "schema": "dger-execution-relay-request/v2",
  "dger_request_id": "...",
  "gep_execution_id": "...",
  "ahc_effect_reservation_id": "...",
  "chm_handoff_id": "... or null"
}
```

`admission.bin` is the exact peer-delivered GEP-signed MOH admission. DGER treats it as opaque immutable bytes and preserves it unchanged when staging it to MOH. DGER never mints, repairs, widens, resigns, parses for authorization, or supplies signing trust for the admission.

`READY.json` binds exact request bytes, exact admission bytes, deterministic payload manifest digest, sizes, file count, and total bytes. `tools/build_gen4_ingress.py` deterministically seals this transport package; it grants no execution authority and requires no Dropbox-specific semantics.

Caller/transport material never establishes tenant, principal, deployment, role, fleet epoch, Builder claim, service identity, execution entitlement, or execution profile.

## Private accepted State

DGER first verifies the complete READY closure and copies the exact request, admission, READY, and payload bytes into private DGER State using fsync + atomic rename + same-byte/digest readback. Accepted/recovery behavior is thereafter independent of continued Dropbox package existence.

A DGER request is immutably bound to its transport-intent digest. A distinct private GEP-execution index binds one GEP `execution_id` to one DGER request/transport intent/trusted correlation. Changed-byte reuse conflicts.

## Trusted delegated service identity and correlation

The immediate actor is a protected installed DGER service deployment with role `EXECUTION_RELAY`. Its service identity is installed State, never transport input.

The exact production peer adapter must consume GTG/GTC's delivered delegated-service actor-context contract. It must establish an origin namespace containing at least `{tenant_id, principal_id, deployment_id, fleet_epoch, originating_invocation_id, context_digest}` while separately identifying DGER's immediate protected service deployment.

The normalized trusted correlation retained by DGER also binds distinct AHC execution claim, AHC effect reservation, AHC work revision, GEP execution, GEP request digest, exact admission digest, optional CHM handoff correlation, and payload-closure proof. Cross-tenant/principal/deployment/epoch/service replay must be rejected by authenticated peer truth before execution.

Every successful **semantic** peer call must also carry exact invocation-time GTG provider identity evidence: `tool_id`, the exact normalized operation, GTG `invocation_id`, exact Tool commit, exact Tool tree, exact GTG commit, and exact Registry commit. Correlation establishment requires exactly GEP `correlation_read` and AHC `effect_read`, plus CHM `handoff_read` when CHM correlation is present. Later AHC/MOH/CHM results must match the exact normalized operation DGER actually invoked (`begin_effect`, `effect_status`, `status`, `execute`, `note_moh_in_doubt`, `accept_terminal_effect`, or `publish_terminal_result` as applicable). Same-Tool evidence for a different operation is invalid. DGER never manufactures provider evidence from transport or peer payload fields.

The exact delivered peer adapter is responsible for proving GTG/GTC currentness, authorization, and peer release compatibility before returning a successful normalized result. A provider may advance without forcing a new host execution only when that governed adapter accepts the invocation as current-compatible; DGER records the actual invocation-time provider identity. A compatibility/currentness rejection remains a blocked peer call and cannot reopen MOH execution.

Identifiers remain distinct. DGER never aliases GTG invocation/delegation IDs, AHC claim/effect/review/wake IDs, GEP execution ID, CHM handoff ID, DGER request ID, or MOH record identity.

## Pre-execution ordering

For one accepted execution, DGER's durable order is:

1. freeze and positively verify private ingress;
2. establish exact trusted AHC/GEP/CHM correlation through the authenticated DGER service context;
3. locally materialize and verify exact MOH staging bytes, preserving admission bytes unchanged and performing no semantic peer invocation or process start;
4. durably enter `PRE_AHC_EXECUTE_WAL` (`execute_reconciliation_required=true`);
5. invoke the exact delegated AHC `begin` operation;
6. require exact AHC `IN_DOUBT` for the bound effect;
7. reconcile exact MOH status before first/any possible execute;
8. durably write `moh_execute_call_may_have_happened=true` immediately before the MOH execute call;
9. only then invoke MOH `execute`.

The Generation-4 source contract classifies `stage_moh` specifically as `LOCAL_MATERIALIZATION`. Its receipt must say `LOCAL_MATERIALIZATION`; any other stage kind fails closed. A later delivered architecture that requires a remote/semantic MOH staging operation is changed input: that adapter must return exact invocation-time evidence for the staging operation and receive change-driven review rather than silently treating a semantic call as local preparation.

MOH execute can never precede AHC's durable `IN_DOUBT` observation.

A crash after DGER's local pre-AHC WAL but before AHC begin resumes at AHC begin/reconciliation; it does not assume the effect began. A lost AHC-begin response is reconciled by exact AHC status. If AHC is still `RESERVED`, only the idempotent AHC begin may retry. If it is `IN_DOUBT`, DGER proceeds to MOH status-first reconciliation. An already-terminal conflicting AHC effect fails closed.

## MOH recovery and no blind repeat

DGER preserves Generation 3's write-ahead/status-first recovery and MOH's stronger durable process-start truth.

After the immediate MOH-call WAL, any crash, transport exception, missing response, or process restart resumes through MOH `status`. For an ordinary transport/lost-response ambiguity, a fresh exact `NOT_FOUND` or `ADMITTED` status is the only normalized proof that can permit another same-GEP-execution `execute` attempt. `RUNNING` or other nonterminal process truth remains status-only. Terminal truth is persisted. An exact MOH `IN_DOUBT` observation sets the monotonic no-execute latch and permanently removes DGER execute permission for that execution.

A response that arrives **after the MOH execute call has left DGER** but fails exact correlation, provider-identity, or operation-evidence validation is treated more conservatively than an ordinary missing response. DGER records `moh_execute_response_invalid=true`, sets the same monotonic no-execute latch with source `INVALID_EXECUTE_RESPONSE`, and returns only to status reconciliation. Later valid MOH terminal status may close the execution, but even a later `NOT_FOUND` or `ADMITTED` observation cannot restore execute permission. This prevents an invalid or cross-operation execute response from being converted into a second process-start attempt.

When the no-execute latch came from an exact MOH `IN_DOUBT` observation, that observation is reported idempotently to AHC. If AHC is unavailable, that report remains durably pending; retries cannot invoke MOH execute. DGER does not fabricate an AHC `IN_DOUBT` report from a response-validation failure for which it lacks a valid MOH observation.

Transport retry, READY replay, Dropbox duplication/deletion, CHM state, CHM result absence, lease expiry, task wake, service restart, or peer provider advancement never independently authorizes execution.

## Terminal path

Once exact MOH terminal truth is durable:

1. DGER records the bounded terminal observation/evidence digest and exact MOH invocation-time provider evidence in private State;
2. DGER publishes the exact bounded result record idempotently, including the exact MOH invocation-time provider evidence;
3. DGER reports the exact terminal external-effect result to AHC idempotently and retains the AHC acknowledgement provider evidence;
4. AHC remains lifecycle authority and may produce the causal Builder wake;
5. only after AHC terminal acceptance does DGER publish optional CHM history/result correlation and retain the CHM acknowledgement provider evidence.

AHC unavailability after MOH terminal retries only AHC reporting. CHM unavailability retries only CHM history/result publication. Neither path can return to MOH execution.

Result changed-byte replay is a conflict. Exact replay is idempotent.

## CHM is correlation/history only

Generation 4 removes Gen3's CHM `STARTED` execution-entitlement interpretation from the new V2 path. A CHM handoff ID is merely bounded correlation/history when present. It must match trusted namespace/effect/GEP correlation through the exact delivered CHM contract. Possession of a handoff ID, CHM assignment/STARTED state, or absence of a CHM result never grants or repeats execution.

## Production peer adapter boundary

`Gen4Peers` is an internal normalization port used to make DGER's own ordering/recovery logic independently testable. It is **not** a wire contract and ordinary callers cannot implement it as authority. Its semantic operations require exact operation-bound GTG invocation evidence. The `stage_moh` method is the explicit non-semantic exception in this source release and is restricted to local, non-effectful staging materialization as described above.

`UnavailableGen4Peers` is the only source-published production placeholder until exact peer contracts are delivered. It fails all peer operations closed. A later DGER-only follow-on may bind those exact delivered interfaces without changing peer-owned security semantics; that changed input requires change-driven review only for the new material adapter proposition.

## Legacy/compatibility retirement

Generation 3 production semantics remain available before secure Gen4 activation. `src/dger/relay_v1.py` is unchanged except its runtime construction consults the protected Gen4 activation marker.

When protected installed State contains `gen4/ACTIVATED.json`, every Generation 3 production runtime construction fails closed with `GEN3_SURFACE_RETIRED`. Malformed activation-marker bytes also fail closed.

The older Prototype R0 direct-GEP execution module (`src/dger/relay.py`) is permanently retired in Generation 4 source because it could otherwise provide an equivalent Mac execution effect under weaker authorization. It no longer contains a process-start implementation.

`GOVERNED_EFFECT_SURFACE_INVENTORY.json` plus `tools/validate_gen4_effect_surface_inventory.py` mechanically inventories the material execution/admin/recovery/compatibility surfaces and detects newly reachable Python execution primitives not deliberately classified.

## Activation prerequisites

Creating the Gen4 activation marker is deployment/cutover work, not source publication. It is prohibited until exact current peer release identities are positively resolved and compatibility/callability is proven for:

- GTG/GTC authenticated delegated `EXECUTION_RELAY` context and operation authorization;
- AHC exact reservation/begin/status/in-doubt/terminal-result + causal wake semantics;
- GEP exact namespace-bound execution and signed MOH admission/reconciliation truth;
- CHM tenant-bound external-execution correlation/history;
- MOH exact signed-admission staging/execute/status schema and no-blind-repeat behavior.

Activation also requires protected DGER service credential/identity provisioning, exact Mac runtime/deployment qualification, cross-namespace/service replay falsification, crash/reconciliation matrix qualification, Registry discovery verification, and durable Tool State evidence. Until then, Generation 3 may remain the installed runtime and Gen4 source must not be represented as activated.