# Governance Binding — Dropbox Governed Execution Relay

The instantiated binding is effective only when resolved from this Tool's authoritative immutable activation commit under current Software Governance. No self-declared status field creates adoption or authority.

Persistent Software Governance authority/channel binding:
- authority_id: `software-governance`
- authority type: `local_bare_git`
- authority locator: `/Users/brettmacpro/AI/Git/software-governance.git`
- authority_root_commit: `fe043da0131eef34b46c3ed6dc34821af2e7b784`
- authority verification: `local_authority`
- release selector: `refs/heads/main`
- governed release manifest path: `GOVERNED_RELEASE.json`
- accepted manifest schema major: `1`
- resolution policy: `act_time_current_release`
- release identity policy: `immutable_for_the_exact_governed_act_once_resolved`
- authoritative State/evidence locus for preserved act-time identities where later assurance needs them: `/Users/brettmacpro/ChatGPT/State/Tools/Dropbox Governed Execution Relay`

For each governed act, resolve the current Software Governance release identity from this persistent authority/channel binding and verify the exact governed-release manifest and withdrawal status. If that exact release identity is unchanged from the actor's previously resolved release, no governance-content reread is required. If it changed, inspect the exact changed authoritative governance material needed to understand the new release, preferably through a mechanically verified release delta plus required dependency closure when available. Once resolved for that exact act, use the immutable release identity for that act. Prior act/review evidence retains the SG identity under which it was produced, but ordinary continuation creates no per-task governance epoch and does not authorize continued use of an older release for a later governed act.

Do not persist the current Software Governance release commit, tree, normative content hashes, or release generation in this persistent Tool binding.

## Common Tool authority
- Immutable common-Tool binding-set locator: `NONE`

`NONE` grants no Tool capability and waives no Tool-specific rule. DGER's runtime use of GEP and CHM is governed by DGER's own fixed R0 contract and the exact external bindings supplied by its installed Mac adapter; this binding does not declare either Tool as a common-governance capability.

## Tool-local governance paths in this same activation commit
- Project instructions path: `PROJECT_INSTRUCTIONS.md`
- Project governance profile path: `PROJECT_GOVERNANCE_PROFILE.md`

Mutable working trees, cloud copies, chats, transport copies, and Tool Registry discovery MUST NOT substitute for required authoritative or immutable identities.
