# Dropbox Governed Execution Relay — Governance Profile

## Deployment/quiescence
- Exact quiescence/restart-inhibition truth source: the macOS `launchd` GUI-domain job `com.brettmacpro.chatgpt.dropbox-governed-execution-relay` together with absence of a live process executing the installed DGER launcher/runtime. A deployment is quiescent only after the job is booted out or already absent, `launchctl print` confirms it is absent, and no live exact DGER launcher/runtime process remains. Restart is controlled by bootstrapping the exact delivered LaunchAgent plist and verifying the resulting loaded job before unquiescence.

## Operating environment / risk model
- Intended principals/actors: single-user local Mac service consuming authenticated Dropbox transport material and invoking only the fixed R0 CHM/GEP contract.
- In-scope failure model: stale or mismatched Tool/GEP identity, malformed or noncanonical request material, unsafe filesystem objects, interrupted relay/deployment state, and bounded local service failure.
- Recovery baseline: exact predecessor runtime/launcher/LaunchAgent bytes plus Tool-local durable State and the governed offline-deployment recovery path.
