# Chatterbox device implementation plan

**Goal:** Add persistent CPU/GPU selection to Chatterbox Nano.

**Architecture:** Keep Torch in the isolated worker. Preserve backend voice
identity and explicitly replace the worker when the saved device changes.

**Tech stack:** Python, Tkinter, Torch, existing framed worker protocol.

**Constraints:** Stay in the current branch; CPU default; CUDA fallback message;
preserve saved GPU preference even when the current runtime uses CPU.

- [x] Write and run failing settings and controller device-switch tests. Add
   `chatterbox_device` validation/persistence and snapshot fields. Pass requested
   device through the existing thread-local preparation context; force preparation
   when preference changes and retain rollback on save failure.
- [x] Worker task (Luna High): write failing CPU/CUDA tests, extend worker startup
   and client device metadata, resolve CUDA availability, and load all inference
   components using the resolved device. Support CUDA worker packaging.
- [x] Add CPU/GPU radio buttons to the Nano frame, pass the device to Apply,
   restore from snapshots, and retain fallback messages after Apply. Wire app
   startup and replacement workers to the saved/requested device.
- [x] Run focused settings/Nano/UI tests followed by the tray test suite; review
   diffs, document setup, and report hardware verification limitations.

Verification: 840 tray tests passed, 2 skipped. Focused device, Nano, packaging,
and layout checks: 59 passed. Independent Luna High reviews found no blockers.
The test app is built in `dist/PiperChatterboxDeviceTest`. Its packaged worker
generated nonempty 24 kHz speech on both CPU and the NVIDIA RTX 4070 using
Torch 2.6.0+cu124. The packaged app archive contains the new device selector.
The build now pins the CUDA wheel suffix explicitly so an existing CPU-only
Torch installation cannot satisfy the build dependency unchanged.

User-account test follow-up: the Nano payload had owner-only Windows permissions from the sandbox build, so the normal Windows user could not read manifest.json. Granted Mjg\mhoem read/execute access to the test payload. Verified fresh 24 kHz speech on CPU and CUDA under that account, including the frozen tray backend and its normal worker launcher (132480 GPU PCM bytes). Corrected TEST-INSTRUCTIONS.txt to use the actual Save changes button label.

Pre-commit review preserved manifest-only CPU initialization for compatibility with existing Nano workers. A regression test verifies the outgoing CPU request with the legacy strict initialization validator; GPU requests continue to include the selected device.
