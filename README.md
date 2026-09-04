# Dropbox Governed Execution Relay — Generation 3

DGER is the governed transport/reconciliation relay between immutable cloud execution requests and Mac Operation Host (MOH), with durable completion publication through Common Handoff Manager (CHM).

Generation 3 removes Prototype R0's singleton assumptions. Each accepted `execution_id` owns independent immutable request, payload, frozen provider bindings, MOH stage/reconciliation state, result evidence, and CHM publication state. The installed service may serialize work; accepted executions are not globally exhausted after any fixed number of calls.

## Authority and boundary model

- **Tool software authority:** DGER's authoritative GitHub `refs/heads/main`.
- **MOH:** durable host execution truth and the no-blind-repeat invariant.
- **DGER:** immutable transport, exact-binding freeze, relay state, and reconciliation.
- **CHM:** logical handoff/result/history truth.
- **GTG/GTC:** semantic provider discovery, callability/currentness checks, and invocation routing.
- **Dropbox:** transport only; never software authority or execution truth.

DGER never accepts caller-selected shell, argv, cwd, interpreter, environment, network mechanics, or retry policy. It preserves the upstream MOH envelope bytes and payload digest and invokes only the semantic operations already registered for MOH/CHM.

## Current dependency gate

New executions are accepted for host work only when GTG Doctor reports the required current semantic operations as callable and returns exact authoritative/delivered bindings for:

- `mac-operation-host`: `execute`, `status`;
- `common-handoff-manager`: `handoff_get`, `handoff_attach_result`, `handoff_resolve`;
- the consumer Tool/operation named by the immutable MOH envelope.

Before any MOH-visible stage exists, DGER also requires an atomically frozen-binding CHM `handoff_get` to return the supplied logical handoff in `STARTED` state with no prior result. CHM derives project authority from DGER's authenticated GTG transport binding; ingress cannot select a project or credential. Exact provider identities are frozen in DGER State at acceptance.

Doctor alone is not an atomic provider fence. DGER therefore requires the gateway adapter to support `invoke_frozen`, where the expected binding is compared atomically with route selection and dispatch. Current authoritative GTG lacks that capability; the current DGER HTTP adapter fails locally with `GTG_ATOMIC_BINDING_CAS_UNAVAILABLE` rather than issuing a non-atomic effect. This is a production activation dependency, not a claim that Doctor→invoke closes the race. Every MOH `execute` is additionally preceded by durable write-ahead reconciliation State, and once MOH has ever reported `IN_DOUBT`, the monotonic latch permanently bars any later DGER `execute`, including after intervening transport ambiguity or a later `NOT_FOUND`.

Once accepted, reconciliation is State-driven: removal of the external Dropbox ingress package cannot strand a running/ambiguous MOH execution or CHM-only publication. A retained/replayed ingress package is still checked against the frozen intent.

Generation-3 production activation currently has two external gates. First, authoritative CHM Generation 9 (`d3d491acb9cf09ff12a594613da56ecb3f4606d7`) does not expose the required durable logical-result operations. Second, current authoritative GTG does not expose atomic expected/frozen-provider CAS for invocation. DGER fails closed before Mac execution while either gate is absent. No unpublished CHM or GTG candidate is treated as authority.

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
