# Chatterbox Multilingual Implementation Plan

> **For agentic workers:** Use subagent-driven-development for settings/UI work and review; execute worker integration in this session.

**Goal:** Add GPU-only Chatterbox Multilingual V3 with language, expressiveness, and voice/style guidance settings.

**Architecture:** Separate Multilingual payload and worker; reuse bounded framing and loaded-model cancellation lifecycle. Follow existing transactional backend preparation for save/startup.

**Tech Stack:** Python, Tkinter, PyTorch CUDA, Chatterbox, PyInstaller, pytest.

## Global Constraints

- Stay on the current branch.
- NVIDIA CUDA GPU only; no CPU fallback for Multilingual.
- Explicit V3 weights; local inference with pinned assets.
- Language defaults to en; exaggeration defaults to 0.5 in 0.25â€“2; cfg_weight defaults to 0.5 in 0â€“1.
- Preserve Nano/Piper behavior and existing untracked user files.

### Task 1: Settings and controls

Files: settings.py, controller.py, settings_window.py, errors.py and tests/windows_tray/test_multilingual_options.py.

- [x] Add failing tests for persistence, invalid settings, engine switching, rollback, and visible controls.
- [x] Add settings named multilingual_language, multilingual_exaggeration, multilingual_cfg_weight and validators.
- [x] Carry settings through snapshots, apply requests, and background startup options. Multilingual uses cuda regardless of Nano device selection.
- [x] Show dropdown and two numeric sliders only for Multilingual; share reference clip controls.
- [x] Verify with `python -m pytest tests/windows_tray`.

### Task 2: Offline GPU worker and installation

Files: multilingual_options.py, multilingual_assets.py, multilingual_worker/, windows_tray/multilingual_client.py, script/*multilingual*, requirements/multilingual-worker.in and tests/multilingual/.

- [x] Test missing CUDA rejection and model loading with `from_local(directory, device='cuda', t3_model='v3')` before implementation.
- [x] Pin model revision and hashes from official Hugging Face metadata; verify full payload inventory.
- [x] Validate initialize options, generate Unicode chunks with `generate(piece, language_id=language, exaggeration=exaggeration, cfg_weight=cfg_weight)` and return bounded PCM.
- [x] Keep worker stdout reserved for protocol; propagate clear GPU initialization errors.
- [x] Add explicit CUDA build and offline staging scripts and documentation.
- [x] Verify with `python -m pytest tests/multilingual`.

### Task 3: App integration and final review

Files: windows_tray/app.py, speech.py where needed, README.md, relevant packaging entry points, and tests/windows_tray/test_multilingual_backend.py.

- [x] Test configured startup and preparation failure before adding Multilingual backend routing.
- [x] Route engine startup and background changes through the separate worker and payload, forwarding all persisted options.
- [x] Verify speech interfaces, cancellation, replay, automatic reading, and lifecycle cleanup reuse the existing client contract.
- [x] Run worker and tray regression suites and inspect branch diff. Independent review checks GPU-only behavior, payload security, and control data flow.
- [x] Address review findings and report verification and real-GPU limits.
