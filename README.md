# Dropbox Governed Execution Relay — Prototype R0

Prototype R0 proves a zero-Owner-courier loop from Chat-authored Dropbox request to a resident Mac relay, CHM ownership, one fixed GEP `platform.self_check` operation, and Dropbox result.

Hard qualification: GEP bare `main` must remain `fe088a93eee537dbe7f8857aec85303f151cbb63`; otherwise requests fail closed as `CLASSIFICATION_VOID` until requalified.

The only request project/operation pair is `ai-me` / `platform.self_check`. The GEP operation accepts no arguments.

Prototype R0 reconstructs the exact qualified GEP commit for every attempt, provisions its locked offline `.venv`, and invokes the fixed self-check through project-canonical strict PyRunway. Standalone PyRunway is used for the installed DGER launcher itself, not for GEP's governed CLI.

Prototype R0 uses one dedicated CHM lane, `Handoff100`, because the relay is single-worker. It uses target-local CHM `assign/status` only and never depends on global `handoff-manager active`; a busy or unsafe dedicated lane produces visible degraded state and no GEP invocation.

## Location-independent runtime binding

DGER source does not encode a development checkout. The installed Mac launcher supplies the host-specific DGER State root, qualified GEP Git/material binding, PyRunway, CHM, and Dropbox transport root explicitly to `scripts/dger.py`. The relay core accepts those bindings as paths and preserves the R0 protocol/allowlist semantics. Moving or deleting a development checkout therefore does not change runtime resolution.

The service is Mac-bound in operation; cloud/Linux is a development and falsification surface for the portable relay core, not a simulated Mac service.

DGER's own Git authority is a development/governance concern, not a runtime dependency. The installed launcher verifies the GOD-delivered `delivered-identity.json` and runtime root, but does not require the retired Mac DGER bare repository to exist. This allows DGER source authority to move to an eligible GitStorage-backed hosted location while the Mac service continues to use its delivered runtime and explicit host bindings.
