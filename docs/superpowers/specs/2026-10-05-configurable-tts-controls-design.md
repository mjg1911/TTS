# Configurable TTS Stop and Pause Controls

**Status:** Approved design  
**Date:** 2026-10-05

## Context

The Windows tray app currently registers F8 as a fixed global speech-cancel shortcut. Its settings window can record and persist one separate global shortcut for starting text capture. Speech flows through a worker and a playback pipeline, but playback has no pause/resume operation.

## Design

Keep the existing capture shortcut and add two independently configurable playback shortcuts to Settings:

- **Stop TTS** defaults to `F8` and retains the current stop behavior.
- **Pause/Resume TTS** defaults to `F9` and toggles the current speech output between paused and playing.

Both controls use the settings window's shortcut recorder and accept the same supported keys and modifier combinations as the existing shortcut. The three shortcuts must be distinct. `F12` remains unavailable because Windows reserves it. A registration conflict or a save failure leaves the prior settings and registrations active and reports an error on the affected setting.

Add the two shortcuts to persisted tray settings and advance the settings schema to version 3. Migration from existing settings fills in `F8` and `F9`, preserving the capture shortcut and other saved preferences.

At playback, pause gates outgoing PCM data at the playback boundary. The existing request and generated audio remain alive while paused, so resuming continues the same stream instead of synthesizing it again. Audio already buffered by the playback process may finish before the pause becomes silent. The toggle affects any active speech request, including foreground and auxiliary speech; pressing it while idle has no effect. Stopping speech cancels the request and clears its paused state, so later speech starts normally.

While a shortcut is being recorded, temporarily unregister all three global shortcuts and restore their active registrations when recording ends. This prevents the currently configured actions from firing as the user records a key.

## Components and flow

1. Settings persistence supplies backward-compatible stop and pause/resume defaults.
2. The settings window exposes a recorder for each playback action alongside the existing capture recorder.
3. The controller validates all three shortcuts, rejects duplicates, and applies their registrations and saved settings as one transaction. Failed registration or persistence rolls back to the previous set.
4. The hotkey manager dispatches stop and pause/resume actions to the controller. Stop uses the current cancellation path; pause/resume toggles the active speech worker's playback gate.
5. The speech worker applies pause state to the active playback pipeline, including pipelines that begin playback after a pause keypress during synthesis.

## Failure handling

- Invalid shortcut syntax or duplicate bindings are shown in the relevant settings field.
- If Windows cannot register a shortcut because another application owns it, the update is rolled back and the previous binding remains in effect.
- If settings cannot be saved after candidate registrations are prepared, those registrations are rolled back.
- Stopping paused speech clears pause state; later requests start unpaused.

## Acceptance criteria

- Fresh settings use capture `Alt+backtick`, stop `F8`, and pause/resume `F9`.
- Existing settings load with their capture shortcut and other preferences intact, and receive the new defaults.
- Users can record and save different stop and pause/resume shortcuts from Settings.
- Duplicate shortcuts are rejected before applying settings; system registration conflicts do not partially change active bindings or persisted settings.
- The configured stop shortcut cancels speech as F8 currently does.
- The configured pause/resume shortcut pauses active audio and resumes the same speech stream. It has no effect while idle.
- Stopping a paused request cancels it, and the next speech request plays normally.
- While any shortcut recorder is active, none of the app's global shortcuts fire.

## Scope boundaries

This change does not add tray-menu pause controls, separate pause and resume keys, or a new speech queue policy. The pause/resume binding is one toggle. Existing speech priority and cancellation rules remain in effect.
