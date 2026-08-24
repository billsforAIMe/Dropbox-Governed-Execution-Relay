# Dropbox Governed Execution Relay — Prototype R0

Prototype R0 proves a zero-Owner-courier loop from Chat-authored Dropbox request to a resident Mac relay, CHM ownership, one fixed GEP `platform.self_check` operation, and Dropbox result.

Hard qualification: GEP bare `main` must remain `fe088a93eee537dbe7f8857aec85303f151cbb63`; otherwise requests fail closed as `CLASSIFICATION_VOID` until requalified.

The only request project/operation pair is `ai-me` / `platform.self_check`. The GEP operation accepts no arguments.

Prototype R0 reconstructs the exact qualified GEP commit for every attempt, provisions its locked offline `.venv`, and invokes the fixed self-check through project-canonical strict PyRunway. Standalone PyRunway is used for the installed DGER launcher itself, not for GEP's governed CLI.

Prototype R0 uses one dedicated CHM lane, `Handoff100`, because the relay is single-worker. It uses target-local CHM `assign/status` only and never depends on global `handoff-manager active`; a busy or unsafe dedicated lane produces visible degraded state and no GEP invocation.
