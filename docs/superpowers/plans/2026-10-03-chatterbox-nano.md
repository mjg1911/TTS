# Chatterbox Nano Implementation Plan

> For agentic workers: use subagent-driven-development, task-by-task, with tests before changes and a final review.

**Goal:** Add default-voice Chatterbox Nano to the current Windows TTS branch.
**Architecture:** Dedicated worker and local verified assets; existing backend manager, queue and PCM playback.
**Tech Stack:** Python 3.11, Chatterbox Nano, Torch CPU, framed worker protocol, Tk settings, PyInstaller.

## Global constraints

- Work in the current Chatterbox branch, as explicitly requested.
- CPU inference and built-in default voice only.
- Offline speech; assets are staged during setup/build.
- Preserve Piper/Kokoro compatibility, request cancellation, non-blocking errors and transactional engine changes.
- Never report mocked tests as real inference or installer verification.

## Task 1: Nano runtime, assets, worker client and distribution

Files: src/piper/nano_assets.py, src/piper/nano_worker/, src/piper/windows_tray/nano_client.py, requirements/nano-worker.in, script/nano_worker_entry.py, script/nano_worker.spec, script/build_nano_worker.ps1, script/stage_nano_payload.ps1, script/nano_assets.lock.json, tests/windows_tray/test_nano_*.py.

Interface: inspect_nano_installation(root: Path) returns root, worker_executable, model_dir and manifest_sha256. NanoWorkerClient(installation) supplies ensure_ready(cancel_event=None), synthesize(text, cancel_event) returning sample_rate/chunks, shutdown(). Engine identity is ("Chatterbox Nano", "default"). Optional configured source worker Python is documented for development.

- [ ] Add failing tests for manifest integrity, local Nano loading, chunking and PCM conversion, cancellation and worker protocol.
- [ ] Run targeted tests and verify feature-missing failures.
- [ ] Implement the APIs, bounded messages, process lifetime, default voice, and worker build/staging support. Pin compatible upstream and model commits.
- [ ] Run targeted tests and inspect implementation for protocol misuse, stale audio, resource leaks and implicit downloads.

## Task 2: Settings, engine switching and app startup

Files: src/piper/windows_tray/settings.py, controller.py, settings_window.py, app.py; script/piper_tray.spec and build_windows_tray.ps1; tests/windows_tray/test_nano_integration.py; README.md.

Consumes Task 1 client and installation interface. Adds Nano to existing engine set; its voice ID is always default. Keep unrelated voice IDs in saved settings. Prepare and switch through BackendManager; initialize on a background startup path with cancellation and Piper recovery.

- [ ] Add failing tests for settings round trip, transactional switch, rollback and default-voice identity.
- [ ] Run tests to establish missing support.
- [ ] Wire settings UI, startup, cancellation and optional payload packaging into existing patterns.
- [ ] Verify settings/controller/app tests and update installation instructions.

## Task 3: Verification and review

- [ ] Run the full relevant test suite with the existing project environment: .venv/Scripts/python.exe -m pytest tests/windows_tray tests/test_kokoro_assets.py tests/test_core_compatibility.py.
- [ ] Provision compatible Nano dependencies/model assets and attempt real CPU synthesis when feasible; record concrete barriers if unavailable.
- [ ] Review the final diff against approved spec, fix important issues, re-run affected checks, and report verified results and limitations.
