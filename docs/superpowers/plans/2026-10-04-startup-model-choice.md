# Startup Model Choice Implementation Plan

**Goal:** Show Piper, Chatterbox Nano, and Chatterbox buttons on every primary app launch before any model loads.

**Architecture:** A modal Tk window returns the selected internal engine identifier or None when dismissed. The app replaces the effective engine before its existing bootstrap. Chatterbox maps to the existing Multilingual V3 backend. Existing Piper fallback remains available after selection.

**Tech Stack:** Python, Tkinter, pytest.

## Constraints

- Work in the current UI-Fix branch and preserve existing edits.
- No model preparation before the choice; cancellation exits successfully and releases the single instance.
- Keep existing Chatterbox background loading, failure handling, and settings behavior.

## Tasks

- [x] Add regression tests for ordering, each selected engine, cancellation, and dialog buttons.
- [x] Run the tests and confirm the missing selection gate causes failures.
- [x] Add TkUi.choose_startup_engine and call it before bootstrap model loading.
- [x] Run startup, UI, and broader Windows tray tests; review the diff.

Validation: Windows tray suite: 915 passed, 2 skipped. Nine new startup tests cover selection ordering, engine mapping, button callbacks, Escape, and window close. The test environment lacks working Tcl/Tk assets, so dialog callbacks use the project's existing fake widgets rather than a live window. Existing settings edits were preserved.
