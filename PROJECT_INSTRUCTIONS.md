# Dropbox Governed Execution Relay — Project Instructions

Project-local persistent governance binding: `GOVERNANCE_BINDING.md` from the authoritative Tool release commit. Project-specific deployment/quiescence rules are in `PROJECT_GOVERNANCE_PROFILE.md` from that same commit.

Tool authority resolution:
- current Git authority is established only by the current registered external authority binding resolved through its non-circular binding channel; this source file does not name a mutable authority location;
- authority root: `8a567d45d9fde17f6d7dd779368b48e6b4916d73`;
- permanent Tool ID: `dropbox-governed-execution-relay`;
- the current release selector/locator are resolved from that external binding and then verified against the named Git authority before any authoritative act; generation-1 local Tool-State binding is historical/current only until a governed successor binding is activated.

Tool State and other host paths are environment bindings, not source-location contracts. A cloud Builder may use exact captured binding evidence for non-consequential development/falsification, but any consequential authority/publication act must resolve the current binding through its declared non-circular binding authority at act time.

For every governed act, resolve the exact current Software Governance release through `GOVERNANCE_BINDING.md` and apply it at act time. Working checkouts, Google Drive, Dropbox, ChatGPT/File Library copies, bundles, mirrors, and Tool Registry rows are subordinate unless the current external DGER authority binding names the corresponding Git authority.

DGER Prototype R0 remains a narrow Mac relay. GEP execution truth, CHM routing/ownership truth, the fixed `ai-me` / `platform.self_check` allowlist, `Handoff100`, two-attempt ceiling, and Dropbox protocol remain unchanged unless separately governed.

Development source is disposable and may exist at any filesystem location. Delivered runtime MUST NOT depend on a development checkout or on the retired location of DGER's own Git authority. Host resources actually consumed at runtime are explicit adapter bindings: DGER State, qualified GEP Git/material, PyRunway, CHM, and the Dropbox transport root are supplied by the installed Mac launcher/entrypoint boundary rather than discovered from neighboring source.

Use scratch-first development, proportionate falsification, and ancestry-preserving expected-predecessor/CAS publication to this Tool's currently bound authority. Do not modify another Tool's authority or source as a side effect.
