# Settings usability implementation plan

**Goal:** Implement the five requested settings improvements on the existing UI-Fix branch.

**Design:** Keep the current Tk workspace and staged settings. Speed uses the existing -50% to 100% range with a percentage readout. Shortcut recording captures a supported key combination and retains parser validation. Small keyboard-accessible question-mark buttons reveal short explanations. Saving prepares every engine asynchronously, displays an animated indicator and status, and disables conflicting controls. Cancel discards unsaved edits or cancels preparation; Save stays open; Save & Close closes only after success.

**Files and work:**
- `settings_window.py`: slider, help buttons, recorder integration, footer, background save and result handling.
- `shortcut_recorder.py`: local keyboard recording and canonical hotkey validation.
- `settings_theme.py`: scoped progress and help styling.
- Settings and shortcut tests: cover capture, validation, save modes, cancellation, responsiveness and small-window layout.

**Verification:** Run focused tests after implementation, then the Windows tray suite. Inspect a rendered settings window with all new controls and a pending model preparation. Preserve existing user files and remain on UI-Fix.
