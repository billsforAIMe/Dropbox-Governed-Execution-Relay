# Phase-1 Governed Runtime Execution Handoff

Phase 1 is a narrow addition beside R0. It relays only CHM Execution Handoffs for `ai-me / platform.self_check` with no parameters.

## Relay rule

DGER obtains capacity through CHM's Phase-1 `execution acquire-once` operation. The exact logical execution/principal/claim identity therefore recovers or creates one allocation atomically under CHM's pool lock, including crash recovery between allocation and logical handoff binding.

After binding the allocation, DGER establishes the CHM slot as `RUNNING` before entering the consequential GEP start interval. DGER always asks GEP to reconcile the immutable execution descriptor before any start request. It calls `execution-start` only when GEP reports `ABSENT` or `NOT_STARTED`. A `BLOCKED` capacity allocation can never start.

If GEP returns `UNCERTAIN`, DGER transitions exact capacity `RUNNING -> BLOCKED`, persists its correlated local uncertainty record, and publishes only GEP's exact durable start-intent reference/digest to CHM. It never automatically relaunches.

DGER does not accept shell, command, executable, argv, environment, or operation-catalog input. The Mac host adapter binds the exact installed GEP Phase-1 launcher at:

`~/ChatGPT/Installed/Tools/Governed Execution Platform/phase1/gep-phase1`

## Durable completion obligation

For a GEP terminal result DGER first durably writes `OUTBOX_PENDING`. Only then may it publish the exact correlated terminal proof to CHM. After exact CHM readback the outbox advances to `DELIVERY_REQUIRED`. Advisory wake delivery may repeat until an exact acknowledgment terminalizes the outbox.

A crash while `OUTBOX_PENDING` may republish/reconcile only the same exact terminal proof; that recovery path contains no GEP start operation. Once CHM is terminal and capacity has been released, a repeated ingress scan resumes solely from the correlated CHM terminal result plus existing outbox and does not reacquire capacity or enter GEP again. CHM terminal truth without the mandatory pre-existing outbox fails closed rather than being repaired by re-execution.

## Wake

Wake is advisory only. It carries exact V1 action, execution, and CHM handoff correlation. It is not execution truth, entitlement, or V1 State authority. Duplicate wake is permitted; V1 must reread authoritative state.
