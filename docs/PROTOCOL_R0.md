# Prototype R0 transport contract

Transport root: `/Software/Dropbox Governed Execution Relay/V1` under the safely resolved local Dropbox File Provider root.

For request id `r0-` plus 32 lowercase hex digits, Chat authors an immutable CHM record named `DGER_R0_<request_id>.json` in the current common CHM Registry Records area, then publishes:

`Ingress/<request_id>/request.json`

```json
{"operation_id":"platform.self_check","project_id":"ai-me","request_id":"r0-...","schema_version":"DGER_R0_REQUEST_V1"}
```

The bytes are canonical UTF-8 JSON: sorted keys, compact separators, one trailing LF. There are no operation arguments.

`READY.json` is also canonical JSON and contains exactly `schema_version=DGER_R0_READY_V1`, `request_id`, `request_sha256` over the exact `request.json` bytes, and `request_size` in bytes. READY is permission to examine only; it may materialize before request.json.

The CHM record is authored outside CHM, as CHM requires, and minimally contains a nonempty `project`, `task`, `next_role`, and a 40-hex `principal_git_identity`. For R0, `principal_git_identity` may bind the qualified GEP commit because the routed work is exactly that fixed GEP classification. The record should also include the deterministic result path `/Software/Dropbox Governed Execution Relay/V1/Runs/<request_id>/result.json` so a later Chat can recover without Owner relay.

DGER uses only public `handoff-manager assign/status` calls. Prototype R0 is single-worker and binds every request to the dedicated CHM lane `Handoff100`; it deliberately does not call global `active`, so an unrelated malformed Registry route cannot become DGER's discovery mechanism. Assignment remains fail-closed if `Handoff100` is busy/unsafe. CHM same-record OPEN assignment is the pre-STARTED recovery primitive, and an `INVALID_HANDOFF_TRANSITION` that reports the exact requested current state (`STARTED` or `CLOSED`) is treated as committed target-local recovery. CHM is routing/ownership truth; GEP normalized stdout is execution truth. DGER's local O_EXCL claim and request state are recovery facts only.

## Governed GEP execution environment

DGER reconstructs the exact qualified GEP Git commit into per-attempt durable State, provisions that reconstruction with `uv sync --locked` in offline mode, and then invokes the fixed `platform.self_check` CLI through project-canonical strict PyRunway: `PYRUNWAY_STRICT=1 /usr/local/bin/pyrunway <physical>/scripts/governed_exec.py self-check ai-me`. The GEP governed CLI is deliberately **not** launched with PyRunway `--standalone`, because GEP's own runtime contract requires the interpreter prefix to equal that reconstruction's canonical `.venv`. DGER does not weaken or bypass that check.
## Crash-safe GEP launch reservation

Before any GEP `Popen`, DGER durably increments the automatic-attempt count and records `GEP_STARTING` with the exact attempt directory and physical GEP target. A relay restart in that phase first accepts any already-terminal normalized GEP result, otherwise adopts only a live process whose command contains that exact per-attempt target. If neither exists after the bounded adoption scan, that launch reservation remains consumed; DGER may reserve the next attempt only when the count is still below two. A second `GEP_STARTING` reservation with no live/terminal child therefore terminates as `RERUN_LIMIT_EXCEEDED` and can never create a third GEP launch.

The configured DGER State root is rejected if it is a symlink **before** `Path.resolve()` is applied; transport and State safety checks therefore cannot be bypassed by supplying a symlink as the root itself.
