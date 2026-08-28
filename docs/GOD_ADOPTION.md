# DGER R0 governed GOD adoption

This document is load-bearing adoption guidance for `DGER_R0_FIRST_DELIVERY_001`.

## Operative governance binding

The operative binding is **binding epoch 2**, content hash `29efe52c22a882d433d33c6710d63111f56ceb73a6592a2779310e5d34df9e4c`. Its authoritative State record is:

`/Users/brettmacpro/ChatGPT/State/Tools/Intelligent Automated Governance (IAG)/GOVERNANCE/EFFECTIVE_BINDINGS/DGER_R0_FIRST_DELIVERY_001__binding_epoch_2__sha256_29efe52c22a882d433d33c6710d63111f56ceb73a6592a2779310e5d34df9e4c.json`

The immutable effective deployment Tool binding is `governed-offline-deployer`, content hash `e53851c9e0976436518271329705730f5199e9bc819ac88cc8f0f829e2b4eeff`, at:

`/Users/brettmacpro/ChatGPT/State/Tools/Intelligent Automated Governance (IAG)/GOVERNANCE/EFFECTIVE_TOOL_BINDINGS/DGER_R0_FIRST_DELIVERY_001__binding_epoch_2__tool_governed-offline-deployer__sha256_e53851c9e0976436518271329705730f5199e9bc819ac88cc8f0f829e2b4eeff.json`

That Tool binding freezes GOD commit `9958a9e26a2946d8924a0814f82ddf2fc630e0f3`, tree `5ee313abe8001ba52ea11a36506e70751369d5db`, consumer-contract SHA-256 `49c065a4a2243f8c1786b7694b4749ad9217b32c9ae50eba816f6309b53d0807`, and required operation `deploy`. Tool Registry is discovery metadata only and has no authority effect.

Local Git Reader closure is required and is bound by exact re-verification at commit `cf305ce10143fb2a4f7cbcbf24b1500d441b0a0e`, tree `4db0e850ff0a4bb7bb89dbb8bac58d0c2743e190`. The selected GOD contract did not require a separate Effective Tool Binding record for LGR in this lineage.

## Historical epoch 1

Binding epoch 1, content hash `ff47ad4fd1502c94208d88e7adc1c76dc46695fec537898e07625c238f844ef1`, and its candidate-specific common-Tool-binding waiver are preserved **only as immutable history**. They are **non-operative** for epoch 2, C7W, current adoption, deployment, or future Tool use. The old waiver does not remain in force and grants no authority to this candidate.

## Crash-safe GEP launch reservation and guarded adoption

Before any GEP `Popen`, DGER durably increments the automatic-attempt count and records `GEP_STARTING` with the exact attempt directory and physical GEP target. A relay restart in that phase first accepts any already-terminal normalized GEP result. Otherwise, process adoption is permitted only after a **guarded native ownership proof** for one process incarnation: a first native `proc_bsdinfo` identity is captured; native argv is then read inside that guard; the argv must exactly identify the expected per-attempt `governed_exec.py` target and fixed `self-check ai-me` operation; same-user UID, exact cwd, interpreter/TXT ownership, target path and symlink boundaries must all match; and a second native `proc_bsdinfo` identity must equal the first exactly. Preliminary argv/classification is filter-only and is re-established inside this guarded proof.

Rendered `ps command=` text, shell reconstruction, a command-string substring, or mere target containment is **never sufficient ownership proof** and must not authorize adoption, lifecycle classification, or termination. Ambiguous/duplicate, wrong-target, wrong-UID, wrong-cwd, wrong-executable/TXT, symlink-boundary, or PID-reuse observations fail closed. `process_identity()`, lifecycle discovery/smoke, and the GOD stop path rely only on guarded ownership records. The guarded writer argv must identify the exact per-attempt `governed_exec.py self-check ai-me` role: the target occurs exactly once and the target plus operation/project form the exact argv suffix; missing, alternate, or extra operation arguments fail closed. The GOD stop path never sends a PID-only signal to a discovered GEP writer. After the launchd-managed DGER runtime is booted out, any still-live guarded writer blocks quiescence and therefore blocks deployment until it exits; correctness and process-incarnation safety outrank availability.

Native `KERN_PROCARGS2` decoding preserves legitimate empty argv elements. An empty argument string is not itself malformed and an unrelated process containing one must not globally block lifecycle discovery. This parser tolerance does **not** weaken ownership: DGER runtime identification still requires the exact runtime target, and GEP writer ownership still requires the exact target plus `self-check ai-me` role suffix; an empty, missing, alternate, or extra element within or after that role suffix fails closed.

If no terminal result or exactly owned live child exists after the bounded adoption scan, that launch reservation remains consumed; DGER may reserve the next attempt only when the count is still below two. A second `GEP_STARTING` reservation with no live/terminal child therefore terminates as `RERUN_LIMIT_EXCEEDED` and can never create a third GEP launch.

## Required gates

Before any affected Tool use or final delivery, re-verify the exact bound Tool release, withdrawal/compatibility state, Local Git Reader closure, recovery prerequisites, and applicable Software Governance gates. An immutable binding never silently rebinds to a newer Tool release.

No DGER `main` movement, runtime deployment/activation, or LaunchAgent mutation is authorized by this document. Those actions require the applicable fresh independent `REVIEW_PASS`, current-authority/CAS checks, recovery readiness, runtime verification, and the required Owner notice before `main` moves.

Dropbox transport discovery is bound to the canonical macOS File Provider root `$HOME/Library/CloudStorage/Dropbox`. A different CloudStorage provider is never treated as Dropbox merely because it also contains `Software/NSP - Temporary Files`. The canonical Dropbox provider, its `Software` directory, and the `NSP - Temporary Files` marker must each be real non-symlink directories; a missing or symlinked canonical Dropbox path fails closed.

