# Deployment

This is the canonical repository location for durable deployment assets for this software.

When this application or Tool uses Governed Offline Deployer (GOD) for Mac deployment, keep the consumer-owned assets here:

- `god_profile.json`
- `god_adapter` only when lifecycle behavior is required
- `god-deploy.command` as the reusable deployment launcher

Reuse these assets across software updates. Expected predecessor, candidate commit/tree, run IDs, and other per-act identities are invocation inputs and must not be baked into a new wrapper per release.

This directory does not imply that this software requires Mac deployment or every listed file. Exact deployment semantics and file contracts are owned by the current GOD consumer contract.
