# Phase-1 Governed Runtime Execution Handoff

Phase 1 is a narrow addition beside R0. It relays only CHM Execution Handoffs for `ai-me / platform.self_check` with no parameters.

## Relay rule

DGER always asks GEP to reconcile the immutable execution descriptor before any start request. It calls `execution-start` only when GEP reports `ABSENT` or `NOT_STARTED`. `UNCERTAIN` blocks capacity and never causes an automatic relaunch.

DGER does not accept shell, command, executable, argv, environment, or operation-catalog input. The Mac host adapter binds the exact installed GEP Phase-1 launcher at:

`~/ChatGPT/Installed/Tools/Governed Execution Platform/phase1/gep-phase1`

## Durable completion obligation

For a GEP terminal result DGER first durably writes `OUTBOX_PENDING`. Only then may it publish the exact correlated terminal proof to CHM. After exact CHM readback the outbox advances to `DELIVERY_REQUIRED`. Advisory wake delivery may repeat until an exact acknowledgment terminalizes the outbox.

A crash while `OUTBOX_PENDING` may republish/reconcile only the same exact terminal proof; that recovery path contains no GEP start operation.

## Wake

Wake is advisory only. It carries exact V1 action, execution, and CHM handoff correlation. It is not execution truth, entitlement, or V1 State authority. Duplicate wake is permitted; V1 must reread authoritative state.
