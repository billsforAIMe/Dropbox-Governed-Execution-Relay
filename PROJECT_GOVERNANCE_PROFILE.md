# Project Governance Profile — Dropbox Governed Execution Relay

## Tool authority

- Tool ID: `dropbox-governed-execution-relay`
- Software authority: private GitHub repository `billsforAIMe/Dropbox-Governed-Execution-Relay`, repository ID `1351496555`, selector `refs/heads/main`.
- Tool Registry is descriptive discovery only.
- Tool State: `/Users/brettmacpro/ChatGPT/State/Tools/Dropbox Governed Execution Relay`.

## Applicable stronger classes for Generation 3

Generation 3 materially changes future automated execution/recovery behavior, trust boundaries, persistent state, external-effect routing, and deployment/runtime bindings. The applicable LG-00 classes therefore include consequential external execution capability, trust/security boundary change, persistent recovery/state change, and material deployment/activation when installation is performed. Independent non-Builder semantic review is required before durable publication.

## Runtime safety model

- MOH is the only host-execution truth source.
- DGER transports immutable MOH stages and reconciles execute/status; it never chooses arbitrary host commands.
- CHM is handoff/result/history truth and never decides whether the Mac process ran.
- GTG/GTC is the semantic provider/currentness route; exact provider identities are frozen per accepted execution.
- Dropbox is transport only.
- New work fails closed unless required MOH/CHM/consumer semantic capabilities are current and callable.
- Accepted work never re-resolves a newer provider during recovery.
- A CHM outage after MOH terminal truth can cause only CHM-publication retry, never host re-execution.
- MOH `IN_DOUBT` remains unresolved and does not close CHM as success.

## Portability and Mac boundary

Relay protocol, concurrency, crash-window, identity, stage-integrity, and CHM-adapter tests are portable cloud work. Actual MOH invocation/LaunchAgent activation is Mac-specific. Source development and publication are not Mac-specific.

## Governed Python

Governed Python assurance uses authoritative PyRunway. Ambient/system Python may be used only as non-authoritative scratch diagnostics and is never publication or deployment evidence. Fresh cloud environments without `/usr/local/bin/pyrunway` must materialize exact governed PyRunway bytes or fail `PYRUNWAY_ENVIRONMENT_UNAVAILABLE`.

## Deployment

Material Mac activation is governed deployment work. Use the current bound Governed Offline Deployer/GTG path when available; do not replace it with ad-hoc shell installation. Quiesce the existing LaunchAgent, prove exact predecessor/runtime identity, deploy atomically, verify, then reactivate. Preserve rollback to the exact predecessor runtime until post-activation verification passes.

## SG11 semantic-access classification

DGER is explicitly classified by current Tool Registry semantic-access metadata as `SUBSTRATE`, exception class `transport`: an immutable transport/recovery relay beneath normal semantic Tool business logic when the direct governed path is unavailable. Generation 3 preserves that narrow exception. DGER does not become the business-semantic front door for MOH, CHM, or consumer Tools; those Tool-owned capabilities remain resolved and invoked through GTG/GTC. The Dropbox transport never establishes software authority, semantic truth, permission, or execution truth.
