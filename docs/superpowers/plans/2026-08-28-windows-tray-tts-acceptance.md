# Windows Tray TTS Acceptance — 2026-08-28

Build under test:
- Commit:
- `PiperTray.exe` SHA256:
- Windows version:
- Python used for build:
- `ffplay` version used for successful-playback checks:

## Packaged launch and runtime isolation

- [ ] `PiperTray.exe` launches from a clean directory outside the repository with no terminal window.
- [ ] Clean-directory launch does not require the repository `.venv` or `PYTHONPATH`.
- [ ] The packaged process creates `%LOCALAPPDATA%\Piper\piper-tray.log`.
- [ ] Default voice identifier lookup succeeds when the `.onnx` and `.onnx.json` pair is placed in `%LOCALAPPDATA%\Piper`.
- [ ] With `ffplay` removed from `PATH`, a speech attempt reports playback failure, writes diagnostics, and leaves the tray process alive.
- [ ] After restoring `ffplay` to `PATH`, the same packaged executable can speak successfully with no playback window.

## Core tray behavior

- [ ] Fresh selection in Notepad + Alt+backtick starts speech with no playback window.
- [ ] Tray remains present during capture, playback, Stop, F8, Replay, and settings.
- [ ] Voice and hotkey changes persist after relaunch.
- [ ] Prefilled clipboard + ignored Ctrl+C never speaks stale clipboard text.
- [ ] Repeated capture-hotkey presses cancel/supersede without duplicate audio.
- [ ] Capture hotkey during playback cancels old audio and plays only the fresh selection.
- [ ] Failed replacement capture leaves the app stopped and does not resume old text.
- [ ] F8 stops active speech and is a no-op while idle.
- [ ] A second packaged `PiperTray.exe` invocation activates the first instance and creates no second tray icon/hotkey registration.
- [ ] Sleep/resume preserves the tray, cancels stale synthesis, and restores hotkeys.
- [ ] Invalid replacement voice keeps the current known-good voice active.
- [ ] Large selection does not freeze the UI, crash, or produce stale speech.
- [ ] Exit during synthesis terminates playback/worker, unregisters hotkeys, preserves valid settings, and exits without traceback.
- [ ] A no-copy application produces the clear no-text message and no speech.
- [ ] Logs rotate and contain diagnostics without captured text.

## Developer and compatibility checks

- [ ] `python -m piper.windows_tray --debug` retains a console and mirrors DEBUG diagnostics there without logging captured text.
- [ ] `python -m piper --help` succeeds after the Phase 5 dependency changes.
- [ ] `from piper import PiperVoice, SynthesisConfig` succeeds independently of tray UI use.
- [ ] Windows tray CI passes tests, build, frozen-runtime smoke, and artifact upload.

## Evidence rule

Mark an item `[x]` only after testing the actual packaged executable where the
item refers to packaged behavior.

For every failed item, record evidence immediately below it using:

  - Evidence: FAIL — <observed behavior>; log timestamp <YYYY-MM-DD HH:MM:SS>.

For completed items that benefit from concrete proof, use:

  - Evidence: PASS — <short observation, command, artifact hash, or log timestamp>.
