# Configurable TTS Stop and Pause Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users configure global shortcuts for stopping speech and toggling pause/resume, defaulting to F8 and F9, and persist those settings without changing the existing capture shortcut.

**Architecture:** Extend settings schema and validation with two playback bindings. Generalize the global hotkey manager to register and transactionally replace capture, stop, and pause bindings. Add settings recorders and controller dispatch for these actions. Pause by gating PCM output in the existing playback pipeline so an active request continues from its current stream position.

**Tech Stack:** Python, Tkinter settings UI, Windows `RegisterHotKey`, existing threading-based speech worker and PCM playback pipeline.

## Global Constraints

- Stop TTS defaults to `F8`; pause/resume TTS defaults to `F9`.
- The existing capture shortcut remains `Alt+backtick` by default.
- The capture, stop, and pause/resume shortcuts must be distinct.
- `F12` remains unavailable because Windows reserves it.
- Existing settings migrate to schema version 3 and receive the `F8` and `F9` defaults.
- Pause/resume is one toggle for any active speech request; pressing it while idle has no effect.
- Stop cancels active speech and clears its paused state.
- No tray-menu controls, separate pause and resume keys, or speech queue policy changes.
- Make one commit at the end containing this plan and the feature implementation.

---

## File map

- `src/piper/windows_tray/__init__.py`: app defaults and settings schema version.
- `src/piper/windows_tray/settings.py`: persisted `TraySettings`, migration, and validation.
- `src/piper/windows_tray/hotkey.py`: canonical shortcut parsing and role-specific F8 allowance.
- `src/piper/windows_tray/hotkey_service.py`: global registration, dispatch, suspension, re-registration, and rollback.
- `src/piper/windows_tray/commands.py`: pause-toggle command.
- `src/piper/windows_tray/controller.py`: settings snapshot/application, validation, stop and pause dispatch.
- `src/piper/windows_tray/settings_window.py`: two playback shortcut recorders and apply/refresh flow.
- `src/piper/audio_playback.py`: pause-aware PCM writes to `ffplay`.
- `src/piper/windows_tray/pitch_playback.py`: pause/resume delegation through the pitch pipeline.
- `src/piper/windows_tray/speech.py`: active request pause state and pipeline coordination.
- `src/piper/windows_tray/app.py`: persisted playback bindings and three-action global hotkey startup wiring.

## Tasks

### Task 1: Add playback shortcut defaults and schema migration

**Files:**
- Modify: `src/piper/windows_tray/__init__.py`
- Modify: `src/piper/windows_tray/settings.py`

**Interfaces:**
- Produce `DEFAULT_STOP_TTS_HOTKEY = "f8"` and `DEFAULT_PAUSE_RESUME_HOTKEY = "f9"`.
- Add `stop_tts_hotkey` and `pause_resume_hotkey` fields to `TraySettings` and its constructor.
- Advance `SETTINGS_SCHEMA_VERSION` from 2 to 3. Extend `_migrate` to accept schema versions 1, 2, and 3; for version 2, set both new defaults and version 3. Ensure version 1's existing voice/engine migration also receives the new defaults before validation.
- In `_validated`, use the two defaults when reading schema-v2-compatible payloads that omit the fields, and persist both fields in returned settings.

- [x] Add the defaults and constructor fields without changing `DEFAULT_HOTKEY`.
- [x] Update migration and schema validation so a v2 settings file retains its other values and acquires `f8` and `f9`.
- [x] Confirm serialization through the existing `asdict` path includes both settings.

### Task 2: Allow F8 only for a playback binding

**Files:**
- Modify: `src/piper/windows_tray/hotkey.py`
- Modify: `src/piper/windows_tray/shortcut_recorder.py`

**Interfaces:**
- Extend `parse_hotkey(value, *, allow_f8=False)`; by default it keeps rejecting F8, while stop-binding validation and its recorder pass `allow_f8=True`. Keep the F12 rejection for every role.
- Add an optional parser callback to `ShortcutRecorder`, defaulting to the existing `parse_hotkey`, so the stop recorder can accept F8 while capture and pause/resume retain the normal parser.

- [x] Update the F8 rejection text to say the key is reserved for the stop action when `allow_f8` is false.
- [x] Route only the stop recorder through the F8-enabled parser.
- [x] Preserve canonicalization and modifier ordering for all shortcuts.

### Task 3: Extend global hotkey registration to three actions

**Files:**
- Modify: `src/piper/windows_tray/hotkey_service.py`

**Interfaces:**
- Define separate registration IDs for capture, stop, and pause/resume while retaining the existing two-ID capture rebind strategy.
- Store the active `capture_spec`, `stop_spec`, and `pause_resume_spec` on `HotkeyManager`.
- Change `HotkeyManager.start` to accept all three specs and callbacks `on_capture`, `on_stop`, and `on_pause_resume`.
- Update `dispatch_message` to route each active ID to the matching callback and suppress all three actions while shortcut recording is active.
- Generalize `suspend_capture` and `resume_capture` to suspend and restore all three registrations; keep method names as compatibility aliases if existing callers need them.
- Make startup, `reregister`, cleanup, and registration errors role-aware for capture, stop, and pause/resume.

- [x] Register all three distinct bindings on the hotkey message thread and unwind already-registered IDs if a later role fails.
- [x] Add a set-level prepare/commit/rollback rebind path that restores the prior three specs if registration or settings persistence fails.
- [x] Ensure suspend/resume and system re-registration retain the latest committed set of specs.

### Task 4: Persist and apply all three shortcut settings

**Files:**
- Modify: `src/piper/windows_tray/controller.py`
- Modify: `src/piper/windows_tray/settings_window.py`

**Interfaces:**
- Add `stop_tts_hotkey` and `pause_resume_hotkey` to `SettingsWindowSnapshot`, defaulting to the constants from Task 1.
- Add optional keyword parameters with those names to `Controller.apply_settings` and `_apply_settings`, preserving existing positional arguments.
- Extend `_validate_settings_scalars` to parse capture, stop, and pause/resume values with the correct F8 rule and return field-specific errors. Reject any duplicate canonical shortcuts before hotkey registration.
- Add `stop_tts_hotkey_var`, `pause_resume_hotkey_var`, and one `ShortcutRecorder` for each to `SettingsWindow`; keep the existing capture recorder.
- Include both new values in the controller apply call and refresh them from the returned snapshot after a successful save.

- [x] Add two recorder fields under the existing shortcut settings panel, labeled “Stop TTS” and “Pause/Resume TTS”.
- [x] Ensure every recorder uses the existing start/finish callbacks, which suspend and restore the complete global shortcut set.
- [x] Apply the three specs and the `TraySettings` update transactionally; on any save or registration failure, restore the previous settings and registrations.
- [x] Keep the existing seven positional settings arguments stable for callbacks that do not accept the new controller keyword options.

### Task 5: Add pause-aware PCM output

**Files:**
- Modify: `src/piper/audio_playback.py`
- Modify: `src/piper/windows_tray/pitch_playback.py`

**Interfaces:**
- Add `pause()` and `resume()` to `PlaybackPipeline`.
- In `AudioPlayer`, add a condition-backed pause gate. Split large PCM writes into bounded chunks, wait at the gate before each chunk, and notify waiting writers from `resume()` and `stop()`.
- In `FfmpegPitchPipeline`, delegate `pause()` and `resume()` to its active `AudioPlayer`; keep `stop()` waking a paused output writer through the player's stop notification.

- [x] Ensure `AudioPlayer.stop()` wakes any paused `play()` call so cancellation cannot hang.
- [x] Ensure `__exit__` still closes and waits for subprocesses when output is paused.
- [x] Keep existing behavior unchanged whenever playback is not paused.

### Task 6: Coordinate pause/resume with the speech worker

**Files:**
- Modify: `src/piper/windows_tray/speech.py`
- Modify: `src/piper/windows_tray/commands.py`
- Modify: `src/piper/windows_tray/controller.py`

**Interfaces:**
- Add `CommandKind.TOGGLE_PAUSE_REQUEST`.
- Add `SpeechWorker.toggle_pause()`; it toggles only while an active request exists and calls `pause()` or `resume()` on the active pipeline when present.
- Track a pause toggle received during synthesis and apply it when the pipeline becomes active. Reset pause state after the request ends or is cancelled.
- Handle `TOGGLE_PAUSE_REQUEST` in `Controller.handle` by invoking the worker. The existing stop path continues to cancel the speech worker and thereby clear pause state.

- [x] Synchronize active request, pause state, and active pipeline updates with the worker condition so a pause issued during synthesis is not lost.
- [x] Avoid requiring pause methods from injected legacy player doubles by treating missing methods as a no-op outside the production pipeline.
- [x] Confirm new requests begin unpaused after a paused request is stopped or completed.

### Task 7: Wire startup validation and global callbacks

**Files:**
- Modify: `src/piper/windows_tray/app.py`

**Interfaces:**
- Parse saved capture, stop, and pause/resume settings before starting the hotkey manager. Recover invalid individual values to their defaults and report a concise startup status.
- Start `HotkeyManager` with the three specs. Map stop to the existing `CANCEL_REQUEST` command and pause/resume to `TOGGLE_PAUSE_REQUEST`.
- Preserve role-specific startup error reporting when Windows cannot register one of the three shortcuts.

- [x] Keep the existing capture startup fallback behavior.
- [x] Ensure old schema files receive defaults before startup parsing.
- [x] Ensure all three callbacks enqueue commands rather than touching controller or playback state from the hotkey thread.

### Task 8: Review the final change and create the requested commit

**Files:**
- Review: all files listed above plus `docs/superpowers/plans/2026-10-05-configurable-tts-controls.md`

- [x] Compare the implementation to every acceptance criterion in `docs/superpowers/specs/2026-10-05-configurable-tts-controls-design.md`.
- [x] Review the final diff for accidental edits to pre-existing untracked files and for whitespace errors.
- [x] Create one commit containing the implementation and this plan, leaving the prior design-spec commit intact.

\n