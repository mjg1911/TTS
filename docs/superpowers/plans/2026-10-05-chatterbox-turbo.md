# Chatterbox Turbo Implementation Plan

**Goal:** Replace Multilingual V3 with Turbo (350M) in this branch.

**Architecture:** Keep the isolated offline CUDA worker and readiness/rollback interface. Replace model assets and loading, remove unsupported options, and migrate saved settings.

**Global constraints:** Piper, Chatterbox Nano, Chatterbox Turbo (350M) only. Preserve Nano/Piper behavior and custom voices. No runtime downloads. All delegated work uses gpt-6-luna with xhigh.

- [x] Worker and packaging: rename Multilingual modules/scripts/tests to Turbo, load from_local(nano=False), remove language/exaggeration/cfg initialization fields, verify pinned Turbo payload hashes, remove Chinese segmentation staging and dependencies. Test runtime, protocol, assets and staging.
- [x] Tray integration: rename imports/backend preparation/client, remove multilingual settings and UI controls, migrate old engine names to Turbo, update explicit startup label and README. Test selection, settings migration, readiness rollback and voice management.
- [x] Review and verify: run Turbo and tray suites, inspect full change, resolve findings, perform real GPU smoke where possible.
