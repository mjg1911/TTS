# On-demand model release implementation plan

> **For agentic workers:** Use subagent-driven-development to implement and review each task in this session.

**Goal:** Publish Piper 1.10.0 with its default Alba voice and optional GitHub-hosted Nano/Turbo downloads that persist offline.

**Architecture:** A bundled versioned catalog describes multipart ZIP archives for one worker and two model sets. A local installer validates and atomically activates shared payload generations; Tk views use a background download task with queued progress. Existing worker manifest version 2 and model pins remain authoritative.

**Tech Stack:** Python standard library, Tkinter, pytest, PyInstaller, PowerShell, Inno Setup, GitHub CLI.

## Global constraints

- Stay on branch `worker`; preserve unrelated untracked user files.
- Release version `1.10.0`, assets hosted in `mjg1911/TTS` under tag `v1.10.0`.
- Default Piper voice is `en_GB-alba-medium`, bundled with its `.onnx.json`.
- Preserve existing startup chooser; fresh settings select Piper.
- No network access for readiness checks or normal synthesis after installation.
- Download occurs only when clicked; preserve the working engine on failure.
- Download the shared runtime once; preserve the other model when adding an engine.
- Every asset part is at most 1,900,000,000 bytes; verify part bytes and SHA-256 before use.
- Use existing pinned official model inventories and shared manifest version 2.

### Task 1: Local catalog and verified downloader

**Files:** Create `src/piper/windows_tray/model_download.py`, `src/piper/model_catalog.json`, and `tests/windows_tray/test_model_download.py`. Extend installation discovery in `src/piper/windows_tray/app.py` if needed for generation selection.

**Interfaces:** `engine_installed(engine: str) -> bool` performs local inspection, with a cheap cached result for UI polling and explicit invalidation after download. `download_engine(engine: str, progress: Callable[[int,int,str],None], cancel_event: threading.Event) -> Path` installs Nano/Turbo or raises a clear exception. Engine names accept the app's display strings. `catalog` has `version: 1`, `release: v1.10.0`, `components` keyed by `worker`, `nano`, `turbo`, each containing `parts` with `url`, `size`, `sha256`; archive contents use `worker/...` or `models/<engine>/...`. The released catalog must contain real asset metadata; an unprepared source checkout reports that download assets are not configured. `catalog_path` and local installation root may be injected for tests.

- [ ] Write failing tests using tiny ZIP parts and injected response streams: fresh missing engine, downloaded engine usable offline, second engine retains first and reuses worker, wrong hash/size, cancel, unsafe archive paths, serialized installers, rollback. Run `.venv/Scripts/python.exe -m pytest tests/windows_tray/test_model_download.py -q` and record failures before implementation.
- [ ] Implement stream download with timeout and bounded blocks, safe extraction, part integrity, model pin checks and a full shared manifest. Prefer immutable generation directories with an atomic local pointer so an existing worker keeps using its old paths; never modify a running generation. Discovery reads the pointer locally and falls back to existing shared/legacy roots. Do not enumerate many-gigabyte files repeatedly on the Tk thread.
- [ ] Run downloader and existing discovery/assets tests. Commit only task files and record actual red/green evidence in `.superpowers/release/task-1-report.md`.

### Task 2: Download UI in startup and Settings

**Files:** Create `src/piper/windows_tray/model_download_ui.py`, modify `src/piper/windows_tray/ui.py` and `settings_window.py`, add `tests/windows_tray/test_model_download_ui.py`, extend startup/settings behavioral tests.

**Interfaces:** Consume Task 1 functions; reusable UI component owns a queue/background thread/cancel event and polls via Tk `after`. Show button only for a missing selected Chatterbox engine, progress during download, readiness after completion, retry after failure, and cancel on closing. Existing Settings Save starts the engine after installation; startup selection must remain open until download is complete or user chooses Piper/exits.

- [ ] Write/run failing UI tests with fake Tk widgets and controlled download functions. Cover selecting Piper, missing/installed Nano/Turbo, progress, error/retry, close cancellation and absence of implicit network requests.
- [ ] Add the reusable panel to startup chooser and Settings. Disable invalid start/save attempts while selected model is missing or downloading, and leave alternative Piper selection available. Use local readiness checks; never touch Tk widgets from worker threads.
- [ ] Run changed UI tests plus relevant settings/startup regressions; commit task files and write `.superpowers/release/task-2-report.md`.

### Task 3: Release assets, default voice and packaging

**Files:** Create `script/prepare_model_release.py`, update `script/piper_tray.spec`, `script/build_windows_tray.ps1`, `script/build_windows_installer.ps1`, `script/piper_tray_installer.iss` as necessary, `setup.py`, `README.md`, `CHANGELOG.md`, add `tests/windows_tray/test_model_release.py` and packaged voice discovery tests.

**Interfaces:** `prepare_model_release.py --payload-dir PATH --output PATH --catalog PATH --release v1.10.0` validates a staged shared payload, produces worker/nano/turbo ZIP parts below the global limit and real catalog metadata with GitHub release download URLs. JSON catalog is bundled via setup package data/PyInstaller. Base app includes default voice data and catalog; ensure Chatterbox and Torch dependencies are excluded from the base app. `app._voice_data_dirs()` includes bundled voice directory. Require default model and configuration for release packaging without overwriting user's chosen voice.

- [ ] Write/run failing tests with tiny staged payload: independent archive inventories, deterministic integrity metadata, part splitting/reassembly, correct URLs, packaged default voice resolution and absent optional payloads in base release mode.
- [ ] Implement release asset generator and Piper-only packaging; use explicit release mode to prevent stale environment variables accidentally bundling Chatterbox. Keep optional developer bundled-payload mode working. Use a release version override where necessary rather than confusing upstream package version.
- [ ] Run release tests and existing packaging/discovery regressions, update usage and release notes, commit only task files, record `.superpowers/release/task-3-report.md`.

Packaged verification uses a hidden `--offline-smoke-test PATH` diagnostic: resolve the bundled default voice, generate nonempty speech, validate configured release asset metadata, construct/destroy the real Tk download panel, and write JSON results without changing settings or starting tray/hotkeys. Test the diagnostic behavior before implementation. Support a compiler-path override for the workspace-local Inno Setup compiler and an optional bootstrap skip for an already verified build environment.

### Task 4: Real build, integration review and publish

- [ ] Run Windows tray regression suite. Review cumulative diff against approved spec and resolve substantive findings before publication.
- [ ] Build fresh shared worker from pinned dependencies, stage existing locally verified model files, generate archives/catalog, then build base app and installer. Do not use stale legacy worker executables renamed as a shared worker.
- [ ] Verify artifacts: default voice synthesis offline; local install/download workflow using generated release parts; Nano and Turbo worker handshake/synthesis where hardware permits; missing-model button state and installed-model reuse; catalog/archive integrity; installer and portable app inventories. Record limitations if a hardware-specific test cannot run.
- [ ] Commit the real catalog and final code, push this branch, create tag/release `v1.10.0`, upload all assets and checksums, and verify published asset URLs/metadata. Publish only the verified artifacts. If hosting is blocked by automatic approval review, preserve prepared artifacts and report exact blocking reason.
