# Shared Chatterbox Worker Implementation Plan

**Goal:** Build and install one worker runtime usable by Nano and Turbo.
**Architecture:** Shared executable and version-2 payload; engine-specific inference stays in existing modules. Existing clients and backend switching retain their lifecycle.
**Constraints:** Stay in this branch. Preserve Nano CPU/CUDA and custom voice support, Turbo CUDA requirement and delivery modes, errors, switching, and Piper fallback. Preserve pinned models and offline integrity verification.

- [x] Assets: add shared installation inspection and adapter support. Test valid one/two-engine payloads, identical executable paths, corruption, missing selected model, traversal and inventory rejection before implementation.
- [x] Runtime: add shared startup entry point with explicit engine and verified model directory; update clients to launch it for shared payloads. Test startup routing and command construction before implementation.
- [x] Packaging: one requirements file, worker spec/build, combined staging and tray/installer collection. Test collection paths and staging inventory before implementation.
- [x] Integration: prefer shared payload in app discovery, retain legacy compatibility. Test both engines, lifecycle switching and fallback.
- [x] Review: inspect complete diff, address findings, run Windows tray regression suite and report any unavailable hardware/build verification.
