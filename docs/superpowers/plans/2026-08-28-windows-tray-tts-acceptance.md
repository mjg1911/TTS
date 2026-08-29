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
- [ ] A no-copy application shows the native `No text selected` tray notification, never opens a modal for this case, and never speaks stale clipboard contents.
- [ ] Logs rotate and contain diagnostics without captured text.

## Error sounds disabled pass

- [ ] Start from settings with Error sounds disabled and confirm the tray item is unchecked.
- [ ] Successful launch speaks `Piper is ready.` with no welcome modal or tray notification.
- [ ] A no-copy/no-selection application shows only the native `No text selected` tray notification and does not open a modal.
- [ ] Runtime hotkey conflict, invalid hotkey, no-selection, and clipboard-access failures remain visual only; none of the four error messages is spoken.
- [ ] Replay and Show last text still refer only to the last successfully captured selected text.
- [ ] F8 / Stop speaking can stop the audible `Piper is ready.` welcome without changing Replay availability.

## Error sounds enabled pass

- [ ] Enable Error sounds from the tray, confirm the native checkmark appears, relaunch, and confirm the checkmark remains enabled.
- [ ] Successful launch does not speak `Piper is ready.`.
- [ ] Runtime hotkey conflict speaks `That hotkey is already in use. Choose another combination.` while preserving the existing visual feedback.
- [ ] Runtime invalid hotkey speaks `That hotkey is not valid. Choose another combination.` while preserving the existing visual feedback.
- [ ] No-selection shows the native `No text selected` notification and speaks `No text selected or the application did not provide it`.
- [ ] Clipboard-access failure speaks `The selected text could not be read from the clipboard.` while preserving the existing visual feedback.
- [ ] While selected text is speaking, trigger a **runtime invalid-hotkey or runtime hotkey-conflict** error and confirm selected text is not interrupted; the error feedback follows only after foreground speech finishes. Do not use a new capture/no-selection attempt for this check because a new capture request intentionally replaces foreground playback.
- [ ] Trigger new selected-text playback while feedback is audible and confirm the selected text takes priority.
- [ ] F8 / Stop speaking stops currently audible feedback without replacing the last selected text or changing Replay availability.
- [ ] `Piper is already running.`, voice-selection errors, settings-save failures, and other unrelated status messages remain visual only.

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
