# Saved Voices Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the independent library helper and code review. Execute UI integration in this session. Track steps below.

**Goal:** Make imported recordings reusable from a polished Voice panel and deliver an updated local test build.

**Architecture:** Enumerate managed recordings into a display-name/path mapping in chatterbox_voice.py. SettingsWindow consumes this mapping and stages selected paths using the existing settings fields and apply transaction. Styling remains scoped to the Piper ttk theme.

**Tech Stack:** Python 3.11, pathlib, Tk/ttk, pytest, PyInstaller.

## Global Constraints

- Stay on UI-Fix; preserve unrelated user files.
- Keep the Use saved voice toggle and existing settings schema.
- Importing or selecting a recording enables the saved voice; Save applies it.
- Keep imported recordings on Cancel; discard only staged settings.
- No new dependencies, model changes, or speech payload rebuilds.
- Update dist/PiperChatterbox500Test and commit after verification.

### Task 1: Reference library

**Files:** src/piper/windows_tray/chatterbox_voice.py; tests/windows_tray/test_chatterbox_voice_library.py.

**Interface:** `list_reference_voices(current: str = "", directory: Optional[Path] = None) -> dict[str, str]`, mapping unique readable labels to absolute paths.

- [x] Write tests for discovery of .wav/.WAV files only, absent folder, UUID removal, duplicate stems, external/missing current selection, and folder read errors. Call `list_reference_voices(directory=tmp_path)` and assert every returned path and label; create files with `Path.write_bytes` because scanning must not decode audio.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/windows_tray/test_chatterbox_voice_library.py -q` and observe missing-helper failures.
- [x] Implement deterministic path sorting and label collision numbering; preserve the current selection and suffix missing selections with `(unavailable)`. Return an empty mapping for an absent managed folder. Convert folder access errors into ReferenceClipError.
- [x] Run the new tests and existing reference/import tests; review implementation.

### Task 2: Settings panel integration

**Files:** src/piper/windows_tray/settings_window.py; src/piper/windows_tray/settings_theme.py; tests/windows_tray/test_saved_voice_selection.py; tests/windows_tray/test_chatterbox_custom_layout.py.

**Interfaces:** Library mapping above; existing `pending_reference_clip`, `displayed_reference_clip`, and `chatterbox_custom_voice_var` feed `_apply` unchanged.

- [x] Add failing UI tests using the existing fake Tk harness: restored selection, choice stages the mapped path and enables custom voice, successful import refreshes the library and selects the imported clip, errors preserve selection, refresh after Save, empty library and busy states. Use real Tk for minimum-size bounds and verify no full-path label is rendered.
- [x] Run new tests to observe failures before implementation.
- [x] Add `reference_voice_var`, `reference_voice_combo`, and `_reference_voice_choices`. `_refresh_reference_voices(reference)` calls the helper and restores the matching dropdown label; `_select_reference_voice(event=None)` stages the selected path, enables saved voice, and clears reference errors. Refresh choices on construction, successful import and snapshot refresh. Disable selection during import and restore it afterwards.
- [x] Replace verbose filename/path labels with the dropdown and concise helper/status text. Keep their variables for compatibility. Style device radiobuttons with scoped dark backgrounds, accent selected state, padding and visible focus. Keep all controls within the sidebar width.
- [x] Run focused selection/layout and settings tests, then the Windows tray suite. Inspect screenshots for Nano and Multilingual at minimum and default sizes.

### Task 3: Review, distribution and commit

**Files:** Build output under build/saved-voices-package; existing dist/PiperChatterbox500Test; design and plan documents.

- [x] Obtain a Luna-high review of the final diff and resolve material findings.
- [x] Package current tray code using the existing test-build spec into a new staging directory. Verify embedded settings_window, settings_theme and chatterbox_voice code against source.
- [x] Copy staged application files into dist/PiperChatterbox500Test, preserving existing nano_payload and multilingual_payload. Compare speech manifest hashes before/after and executable hashes to confirm an updated launcher.
- [x] Run `git diff --check`, review the final diff, and commit only the intended source/tests/docs. Report the executable path and commit.
