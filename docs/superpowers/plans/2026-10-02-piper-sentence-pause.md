# Configurable Piper Sentence Pause Implementation Plan

> **For agentic workers:** Implement this plan inline in the current Piper-SBS checkout. Keep each step focused and preserve the unrelated untracked user files.

**Goal:** Let users set the silence between Piper sentences in milliseconds from Settings.

**Architecture:** Persist `sentence_pause_ms` on `TraySettings`, include it in the Settings snapshot/apply flow, and let `SpeechWorker` read the current value through a controller provider. Keep the default at 180 ms and use the existing silence insertion and playback-speed compensation.

**Tech Stack:** Python dataclasses, JSON settings, Tkinter/ttk settings UI, Piper speech worker.

## Global Constraints

- Accept whole numbers from 0 through 2000 ms.
- Default missing and new values to 180 ms; 0 disables inserted silence.
- Apply only between Piper sentence chunks; leave Kokoro timing unchanged.
- Preserve the current playback-speed compensation.
- Do not change sentence splitting behavior.
- No automated tests were requested; do not add or run tests.

---

### Task 1: Persist the delay in settings

**Files:**
- Modify: `src/piper/windows_tray/settings.py`

**Interfaces:**
- Produces `DEFAULT_SENTENCE_PAUSE_MS`, `validate_sentence_pause_ms(value: object) -> int`, and `TraySettings.sentence_pause_ms`.

- [x] Add the default and bounds (`0` and `2000`) beside the existing pitch and speed settings constants.
- [x] Add integer validation that rejects booleans, non-integers, and values outside the bounds.
- [x] Add `sentence_pause_ms` to `TraySettings` and its explicit initializer.
- [x] Read the optional JSON field with the 180 ms default and include the validated value in `_validated`'s `TraySettings` result. Keep schema version 2 because old documents can omit this additive field.
- [x] Inspect `asdict`-based saving and loading to confirm the value is emitted and missing fields retain the default.

### Task 2: Show, validate, and apply the setting

**Files:**
- Modify: `src/piper/windows_tray/controller.py`
- Modify: `src/piper/windows_tray/settings_window.py`
- Modify: `tests/windows_tray/test_settings_window.py` (existing callback argument expectation only)
- Modify: `src/piper/windows_tray/ui.py` only if its callback wiring requires an update.

**Interfaces:**
- `SettingsWindowSnapshot.sentence_pause_ms: int` carries the saved value to the window.
- `Controller.apply_settings(..., sentence_pause_text: str)` validates and saves the entered value.
- `Controller.current_sentence_pause_ms() -> int` returns the current setting or its default.

- [x] Add the value to the settings snapshot and populate it from `TraySettings`.
- [x] Add a `sentence_pause` field variable and error label in `SettingsWindow`; show it with an `ms` suffix and pass its text to the controller on Save/Apply.
- [x] Validate whole-number input and display a field error stating the accepted 0–2000 ms range; leave the window open on invalid input using the existing error flow.
- [x] Include the validated value in the `replace(current, ...)` save/apply path. Preserve the current value for any legacy caller that omits the new optional argument.
- [x] Refresh the field from a successful settings snapshot.
- [x] Update the existing callback argument expectation to include the new default value; do not add or run tests.

### Task 3: Use the saved delay between Piper chunks

**Files:**
- Modify: `src/piper/windows_tray/app.py`
- Modify: `src/piper/windows_tray/speech.py`

**Interfaces:**
- `SpeechWorker.set_sentence_pause_provider(provider: Callable[[], int])` receives the current value provider; the application supplies `controller.current_sentence_pause_ms`.

- [x] Replace the fixed pause constant in `speech.py` with the provided current value while retaining the existing sample-rate and speed calculations.
- [x] Keep silence insertion after the first Piper sentence only, and keep Kokoro chunks untouched.
- [x] Inspect the call path from Settings Save/Apply through the controller and worker provider to confirm new values take effect without restarting Piper.
