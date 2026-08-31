# Dropbox Governed Execution Relay — Project Instructions

Project-local persistent governance binding: `GOVERNANCE_BINDING.md` from the authoritative Tool release commit. Project-specific deployment/quiescence rules are in `PROJECT_GOVERNANCE_PROFILE.md` from that same commit.

Tool authority:
- authoritative Git: `/Users/brettmacpro/ChatGPT/Git/Tools/Dropbox Governed Execution Relay.git`
- release selector: `refs/heads/main`
- authority root: `8a567d45d9fde17f6d7dd779368b48e6b4916d73`
- Tool State: `/Users/brettmacpro/ChatGPT/State/Tools/Dropbox Governed Execution Relay`
- permanent Tool ID: `dropbox-governed-execution-relay`

For every governed act, resolve the exact current Software Governance release through `GOVERNANCE_BINDING.md` and apply it at act time. Resolve DGER current `main` directly from the Tool's authoritative Git; working checkouts, Google Drive, Dropbox, ChatGPT/File Library copies, bundles, and Tool Registry rows are subordinate material only.

DGER Prototype R0 remains a narrow Mac relay. GEP execution truth, CHM routing/ownership truth, the fixed `ai-me` / `platform.self_check` allowlist, `Handoff100`, two-attempt ceiling, and Dropbox protocol remain unchanged unless separately governed.

Development source is disposable and may exist at any filesystem location. Delivered runtime MUST NOT depend on a development checkout. Host resources are explicit adapter bindings: DGER State, DGER authoritative Git, qualified GEP Git, PyRunway, CHM, and the Dropbox transport root are supplied by the installed Mac launcher/entrypoint boundary rather than discovered from neighboring source.

Use scratch-first development, proportionate falsification, and ancestry-preserving expected-predecessor/CAS publication to this Tool's own `main`. Do not modify another Tool's authority or source as a side effect.
