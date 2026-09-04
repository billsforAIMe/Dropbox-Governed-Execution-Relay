# Dropbox Governed Execution Relay — Generation 3

DGER is the governed transport/reconciliation relay between immutable cloud execution requests and Mac Operation Host (MOH), with durable completion publication through Common Handoff Manager (CHM).

Generation 3 removes Prototype R0's singleton assumptions. Each accepted `execution_id` owns independent immutable request, payload, acceptance-time provider observations, MOH stage/reconciliation state, invocation identity evidence, result evidence, and CHM publication state. The installed service may serialize work; accepted executions are not globally exhausted after any fixed number of calls.

## Authority and boundary model

- **Tool software authority:** DGER's authoritative GitHub `refs/heads/main`.
- **MOH:** durable host execution truth and the no-blind-repeat invariant.
- **DGER:** immutable transport, relay state, reconciliation, and bounded identity/evidence recording.
- **CHM:** logical handoff/result/history truth.
- **GTG/GTC:** semantic provider discovery, callability/currentness checks, invocation-time route selection, exact Tool dispatch, and identity attestation.
- **Dropbox:** transport only; never software authority or execution truth.

DGER never accepts caller-selected shell, argv, cwd, interpreter, environment, network mechanics, or retry policy. It preserves the upstream MOH envelope bytes and payload digest and invokes only the semantic operations already registered for MOH/CHM.

## Provider identity and current callability

New executions are accepted for host work only when GTG Doctor reports the required current semantic operations as callable and returns exact authoritative/delivered bindings for:

- `mac-operation-host`: `execute`, `status`;
- `common-handoff-manager`: `handoff_get`, `handoff_attach_result`, `handoff_resolve`;
- the consumer Tool/operation named by the immutable MOH envelope.

The consumer Tool is special: the immutable MOH envelope already names its exact commit/tree/repository/selector, so its Doctor binding must match that envelope at acceptance.

MOH and CHM Doctor bindings are acceptance-time observations, not permanent dispatch locks. GTG may legitimately select a later current-compatible MOH or CHM release for a later semantic invocation. For each successful `invoke_tool`, DGER requires GTG's exact identity attestation and invocation evidence, and records the Tool identity actually selected for that call. Current GTG dispatch materializes and executes the exact `delivered_tool_identity` selected by that invocation; DGER therefore does not represent a stale earlier Doctor observation as the actual executor.

Before any MOH-visible stage exists, DGER calls CHM `handoff_get` and requires the supplied logical handoff to be `STARTED` with no prior result. That successful read must carry exact GTG identity attestation. CHM derives project authority from DGER's authenticated GTG transport binding; ingress cannot select a project or credential.

Every MOH `execute` is preceded by durable write-ahead reconciliation State. If the GTG transport/result is ambiguous, or a purported successful result lacks exact identity attestation, DGER does not treat the semantic observation as trusted completion; it remains in reconciliation. Once MOH has ever reported `IN_DOUBT`, the monotonic latch permanently bars any later DGER `execute`, including after intervening transport ambiguity or a later `NOT_FOUND`.

This model deliberately does not claim that an earlier Doctor observation is atomically pinned to a later invocation. The authoritative identity for an invocation is GTG's invocation-time selected and attested exact Tool release. A future GTG expected-binding compare-and-invoke guard can provide stricter caller-side preselection, but it is not required for Generation-3 correctness under this narrower contract.

Once accepted, reconciliation is State-driven: removal of the external Dropbox ingress package cannot strand a running/ambiguous MOH execution or CHM-only publication. A retained/replayed ingress package is still checked against the immutable accepted intent.

As of the Generation-3 delivery work, authoritative CHM Generation 10 exposes the required stable logical lifecycle, and authoritative GTG Generation 18 preserves the exact identity-attestation semantics introduced in Generation 16. Production activation must still verify those capabilities are actually deployed and callable in the target environment; DGER fails closed if required operations or successful-call identity attestation are unavailable.

## Protocol

See `docs/PROTOCOL_V1.md`. Prototype R0 remains in `src/dger/relay.py` for historical regression coverage; the installed entry point uses `src/dger/relay_v1.py`.

## Runtime binding

The portable relay core contains no Owner checkout paths. The installed Mac launcher supplies:

- DGER State root;
- Dropbox transport root;
- MOH home;
- GTG endpoint and private bearer-token file;
- governed PyRunway.

The GTG endpoint/token/MOH binding is deployment state, not caller input and not software identity. The service remains Mac-bound in operation while the relay core and crash/concurrency protocol are portable for cloud falsification.