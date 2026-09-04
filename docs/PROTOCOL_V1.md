# DGER immutable execution protocol v1

## 1. Ingress

Each execution is a directory under:

```text
Ingress/<execution_id>/
  request.json
  envelope.json
  payload/...
  READY.json
```

`READY.json` is the publication marker. DGER ignores a package until `READY.json` exists. A valid package is bounded to MOH Generation-1 material limits: 64 regular files, 256 KiB per file, 2 MiB total payload, 240 UTF-8 bytes per relative path, and a 32 KiB envelope.

`request.json` is closed-schema:

```json
{
  "schema": "dger-execution-request/v1",
  "execution_id": "...",
  "logical_handoff_id": "hnd_<sha256>",
  "dger_request_id": "..."
}
```

`envelope.json` is the exact immutable `moh-execution-envelope/v1`. DGER verifies the envelope request digest, payload closure digest, execution ID, authority selector, and exact consumer release identity but does not rewrite the envelope.

`READY.json` binds the exact request/envelope bytes and the deterministic payload manifest by SHA-256, sizes, file count, and total bytes.

## 2. Acceptance and frozen identity

For new work DGER uses GTG Doctor to resolve current callable bindings for MOH, CHM, and the consumer Tool/operation named by the MOH envelope. The consumer Doctor binding must equal the exact commit/tree/repository/selector in the envelope.

Before any MOH-visible stage exists, DGER must invoke CHM `handoff_get` for the supplied logical ID through an atomic frozen-binding gateway operation and require a `STARTED` handoff with no existing result. Ingress never supplies a project or selects a GTG credential. Doctor establishes the candidate binding; it does **not** by itself make later invocation atomic with respect to provider advancement.

DGER then persists an immutable per-execution `intent_digest` over:

- exact request bytes;
- exact envelope bytes;
- payload-manifest digest;
- frozen MOH binding;
- frozen CHM binding;
- frozen consumer binding.

An accepted execution retains its frozen provider identities in State. A replay with the same `execution_id` but a changed intent fails `EXECUTION_ID_INTENT_CONFLICT`.

DGER's semantic execution paths require an internal `invoke_frozen(tool_id, operation, arguments, frozen_binding)` gateway operation whose binding comparison is atomic with route selection and dispatch. Current authoritative GTG does not provide such an expected-binding/CAS field on `invoke_tool`. The production `GTGHttpGateway` therefore refuses `invoke_frozen` locally with `GTG_ATOMIC_BINDING_CAS_UNAVAILABLE` and sends no invocation. Doctor checks remain useful for discovery and diagnostics but are not claimed to close the Doctor→invoke TOCTOU race. Production activation is blocked until authoritative GTG exposes an atomic exact-binding invocation mechanism and the DGER adapter is bound to that published contract.

After acceptance, recovery is driven by DGER State rather than continued presence of the external Dropbox package. The accepted request/envelope/payload are already frozen in private State, so later MOH reconciliation and CHM-only publication continue even if `Ingress/<execution_id>` is removed. If an ingress package remains or reappears, DGER still validates it against the frozen intent before treating it as an idempotent replay.

## 3. MOH stage and execution

DGER first copies the immutable package to private DGER State, verifies read-back, then materializes only:

```text
<MOH_HOME>/inbox/<execution_id>/envelope.json
<MOH_HOME>/inbox/<execution_id>/payload/...
```

The MOH final stage is published only after a complete verified temporary stage exists. DGER-owned unpublished temporary stages may be cleaned after crash. An existing final stage is never deleted or overwritten; it must verify byte/digest-exactly or DGER fails closed.

After `MOH_STAGE_COMPLETE`, DGER uses only the MOH semantic operations:

```text
execute(execution_id)
status(execution_id)
```

Before **every** `execute` attempt, DGER durably records `moh_execute_may_have_happened=true`, increments the execute-attempt counter, and moves phase to `MOH_RECONCILE`. Only after that write-ahead State is fsync-published may the gateway dispatch `execute`. A process or power loss after MOH receives the effect but before DGER receives or records its response therefore restarts in reconciliation and asks `status` rather than blindly executing again.

If status later says `NOT_FOUND` and DGER has never observed `IN_DOUBT`, DGER may issue another write-ahead-protected `execute` for the same immutable execution ID; MOH still owns admission/start uniqueness. Once DGER has ever observed `IN_DOUBT`, it sets the monotonic `moh_in_doubt_ever=true` safety latch. Transport ambiguity or later phase changes cannot erase that latch. A later `NOT_FOUND` can only remain unresolved and can never permit another DGER `execute`.

## 4. State ordering

Per execution:

```text
ACCEPTED
  -> MOH_STAGE_COMPLETE
  -> MOH_RECONCILE                     (durable before every execute dispatch)
       -> MOH_IN_DOUBT                 (unresolved; monotonic no-execute latch)
       -> MOH_TERMINAL                 (durable terminal truth)
  -> CHM_PENDING
  -> CHM_ATTACHED
  -> DONE
```

Once `MOH_TERMINAL` is durable, DGER never returns to `execute`. `MOH_TERMINAL` is itself a resumable phase: restart regenerates/publishes the exact bounded result idempotently and advances to `CHM_PENDING`. CHM availability cannot cause host re-execution.

`IN_DOUBT` is preserved and reconciled with MOH. It is not converted into success, does not resolve CHM, and permanently bars any later DGER `execute` for that execution ID.

## 5. Result and CHM publication

For publishable MOH terminal states, DGER first writes bounded `Runs/<execution_id>/result.json`. Large stdout/stderr bytes remain in MOH evidence; the DGER record carries only digests, byte counts, truncation flags, and evidence references.

The compact CHM result contains:

- logical handoff ID;
- execution ID;
- terminal disposition;
- exact consumer Tool/operation binding;
- MOH request/receipt/result identities;
- DGER result/evidence digest;
- bounded result reference;
- DGER terminal-observation time;
- DGER request identity.

The time is explicitly an observation time (`DGER_OBSERVED_MOH_TERMINAL`), not a fabricated host process completion timestamp; MOH Generation 1 does not expose a separate terminal timestamp in its public status response.

DGER calls `handoff_attach_result` with the exact compact result, then `handoff_resolve`. Exact replay after a lost response must converge idempotently. A conflicting existing terminal result fails closed as `HANDOFF_RESULT_CONFLICT`/`CHM_RESULT_CONFLICT`.

## 6. Concurrency and isolation

DGER uses one durable state document and one lock per `execution_id`. A single service may serialize scans, while overlapping independent executions remain independently durable. There is no global one-request lifetime, fixed `Handoff100`, fixed two-launch allowance, or fixed historical GEP generation.

If the envelope's consumer Tool is GEP, GEP remains the governed consumer/execution substrate identified by that exact envelope and GTG binding; DGER does not recreate or bypass GEP.

## 7. Failure ordering

- **Crash before complete MOH stage:** no `execute`; only DGER-owned unpublished temporary material may be cleaned.
- **Crash after complete stage / after execute dispatch but before receipt:** the durable execute-intent write-ahead phase is already `MOH_RECONCILE`; restart asks MOH `status` before any possible later execute.
- **Crash after durable `MOH_TERMINAL` before result/CHM transition:** idempotently rebuild/publish the bounded result from stored terminal response, move to `CHM_PENDING`, and retry only CHM publication.
- **Crash after attach before local acknowledgement:** replay exact `handoff_attach_result`, then resolve.
- **CHM unavailable after MOH terminal:** preserve terminal truth; never rerun MOH.
- **Same ID/altered bytes:** explicit identity-intent conflict.
- **Same logical handoff/conflicting result:** fail closed; never overwrite history.
