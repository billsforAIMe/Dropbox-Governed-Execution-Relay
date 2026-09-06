# Project Governance Profile — Dropbox Governed Execution Relay

## Tool authority

- Tool ID: `dropbox-governed-execution-relay`
- Software authority: private GitHub repository `billsforAIMe/Dropbox-Governed-Execution-Relay`, repository ID `1351496555`, selector `refs/heads/main`.
- Tool Registry is descriptive discovery only.
- Authoritative persistent Tool State and deployment/recovery evidence locus: `/Users/brettmacpro/AI/State/Tools/Dropbox Governed Execution Relay`.

## Applicable stronger classes for Generation 4

Generation 4 materially changes future automated external-execution composition, trust/authorization boundaries, persistent reconciliation State, peer identity evidence, legacy execution-surface retirement, and the machinery used for later secure activation. The applicable LG-00 classes therefore include `TRUST_SECURITY_CREDENTIAL_PERMISSION_OR_PRIVILEGE`, `CONSEQUENTIAL_EXECUTION_EXTERNAL_EFFECT_OR_EXECUTION_CAPABILITY`, `PERSISTENT_DESTRUCTIVE_SCHEMA_OR_DATA`, and, when installation/cutover is performed, `DEPLOYMENT_MIGRATION_OR_RECOVERY`.

Generation-4 source publication is separate from runtime activation. Source publication requires independent non-Builder semantic review of the changed trust/execution/recovery proposition. It does not itself create the protected DGER service credential, Gen4 activation marker, peer tuple, or Mac cutover. Activation remains separately blocked until exact delivered peers and deployment preconditions are satisfied.

## Runtime safety model

- MOH remains the sole Mac process-start and terminal host-truth authority.
- AHC is consequential-effect lifecycle/entitlement authority. DGER may begin/reconcile/report only the exact AHC effect bound by authenticated peer truth; DGER never creates Builder entitlement or wake authorization.
- GEP remains execution-admission authority. DGER preserves the exact GEP-signed MOH admission bytes and payload closure unchanged; it does not mint, repair, widen, resign, parse for authorization, or rotate admission trust.
- CHM is optional correlation/result/history only and never authorizes host execution or lifecycle progress.
- GTG/GTC is the semantic provider/currentness/authorization route. Every successful Gen4 semantic peer operation must carry exact invocation-time GTG provider identity evidence: invocation ID, Tool commit/tree, GTG identity, and Registry identity. The exact delivered peer adapter must reject a provider that is not current-compatible before returning success.
- The immediate authenticated service actor is `EXECUTION_RELAY`; origin tenant/principal/deployment/fleet epoch remains separately trusted and non-caller-selectable.
- Caller/Dropbox input cannot establish tenant, principal, deployment, role, fleet epoch, execution entitlement, service identity, execution profile, shell, executable, interpreter, argv, cwd, environment, PATH, handler, trust key, result channel, or retry policy.
- Dropbox is immutable transport only and never establishes software authority, execution authority, lifecycle authority, or trusted identity.
- Private accepted DGER State is independent of continued Dropbox package presence and binds exact request/admission/payload/READY bytes plus trusted correlation.
- Before any MOH execute call, DGER durably records its local reconciliation boundary, requires exact AHC `IN_DOUBT`, obtains exact MOH status truth, then durably records that the MOH execute call may have happened.
- After an ambiguous/lost MOH call, DGER reconciles status before any possible same-ID retry. Only exact fresh `NOT_FOUND`/`ADMITTED` truth can permit a retry; transport retry, provider advancement, CHM state, wake state, service restart, or lease expiry cannot.
- MOH `IN_DOUBT` is monotonic for DGER execution permission: once observed, DGER never executes that GEP execution again and retries only AHC in-doubt reporting.
- Durable MOH terminal truth is published to AHC before optional CHM history/result publication. AHC/CHM outages after MOH terminal can retry only their own idempotent reporting phases, never host execution.
- Exact result replay is idempotent; changed-byte replay/correlation is a conflict.

## Generation-3 compatibility and anti-circumvention

Generation-4 source publication deliberately permits the exact delivered Generation-3 runtime to remain installed before secure cutover. The authoritative release manifest declares that predecessor runtime compatibility explicitly.

The protected activation predicate is DGER State `gen4/ACTIVATED.json`. Once that marker exists, or if marker bytes are malformed/unsafe, Generation-3 runtime construction fails closed. A later Gen4 activation act must create the marker only after exact peer tuple/currentness, service identity, deployment and rollback requirements are satisfied.

The older Prototype R0 direct-GEP process-start module is permanently retired in Generation-4 source; it is not a pre-activation compatibility path. `GOVERNED_EFFECT_SURFACE_INVENTORY.json` plus its validator inventory the materially callable execution/admin/recovery/compatibility surfaces and mechanically detect an unclassified DGER Python execution primitive.

## Peer dependency and activation boundary

Generation 4 source is allowed to be durable while exact peer contracts are still developing, but production Gen4 semantics remain fail-closed through `UnavailableGen4Peers`. DGER MUST NOT invent substitutes for unavailable peer trust contracts.

Activation requires an exact current-compatible tuple providing at least:

- GTG/GTC authenticated delegated `EXECUTION_RELAY` context, operation authorization, and invocation-time identity attestation;
- AHC exact effect reservation/begin/status/in-doubt/terminal-result and causal wake semantics;
- GEP exact namespace-bound execution, signed MOH admission, immutable execution/admission correlation, and reconciliation truth;
- CHM tenant-bound external-execution correlation/history without lifecycle authority;
- MOH exact signed-admission staging/execute/status contract and no-blind-repeat behavior.

The later DGER adapter that binds those delivered peer interfaces is a changed material input and receives change-driven review for that adapter proposition only; unchanged Gen4 core recovery/order semantics reuse prior valid coverage.

## Portability and Mac boundary

Relay protocol, namespace/replay isolation, crash-window ordering, state integrity, peer normalization, provider-evidence handling, terminal retry behavior, and effect-surface inventory tests are portable cloud work. Actual MOH invocation through installed peers, DGER service-credential provisioning, LaunchAgent deployment, protected activation-marker creation, cross-service integrated qualification, and cutover are Mac-specific.

Source development/publication is not Mac-specific merely because the eventual execution effect is hosted on macOS.

## Governed Python

Governed Python assurance uses authoritative PyRunway. Ambient/system Python may be used only as non-authoritative scratch diagnostics and is never publication or deployment evidence. Fresh cloud environments without an installed PyRunway may materialize exact authoritative PyRunway source bytes, bind its declared Linux-cloud dependencies through its governed installer, verify the resulting runtime, and then use that exact governed runtime. If exact materialization/runtime verification cannot be established, fail `PYRUNWAY_ENVIRONMENT_UNAVAILABLE`.

## Deployment

Material Mac activation is governed deployment/recovery work. Use the current bound Governed Offline Deployer/GTG path when available; do not replace it with ad-hoc shell installation. Quiesce the existing LaunchAgent, prove exact predecessor/runtime identity, deploy atomically, verify, then reactivate. Preserve rollback to the exact predecessor runtime until post-activation verification passes.

The existing Generation-3 deployment lifecycle adapter and profile remain unchanged source mechanics for the pre-activation installed runtime. They are not authority to create the Gen4 activation marker. A later Gen4 activation must update/render the exact deployment profile as needed for the delivered peer/service tuple and must preserve write-ahead rollback necessity before any candidate configuration or activation-State mutation.

## SG11 semantic-access classification

DGER remains `SUBSTRATE`, exception class `transport`: an immutable transport/recovery relay beneath normal semantic Tool business logic when the direct governed path is unavailable or asynchronous Mac execution is required. Generation 4 does not turn DGER into the business-semantic front door for AHC, GEP, MOH, CHM, or consumer Tools. The Dropbox transport never establishes software authority, semantic truth, permission, or execution truth.
