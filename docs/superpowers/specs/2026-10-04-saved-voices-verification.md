# Saved voices verification

Implemented the approved Voice panel design on UI-Fix. Managed recordings are discovered automatically with readable, unique names. Selection and import enable the saved voice and stage its path until Save; disabling the toggle retains the selection. Full-path clutter is removed, device controls match the dark theme, and Nano/Multilingual share the library.

Verification on 2026-10-04:

- Test-first coverage for library discovery, duplicates, absent/inaccessible folders, existing external and missing selections, and UUID-only filename fallback.
- Test-first coverage for restored dropdown selection, staged Save arguments and refreshed snapshot, import success/failure, pending-operation locking, empty library, folder errors and preservation of the Save reminder after a failed import.
- Final focused suite: 52 passed, including real Tk layout checks at 900x680 for Nano and Multilingual.
- Final Windows tray suite: 937 passed, 2 skipped because ffmpeg is absent. A Tk Variable cleanup warning occurred in the shutdown concurrency test; its assertions passed.
- Visually inspected captures for Nano at 1040x800 and 900x680 and Multilingual at 1040x800, saved under build/saved-voices-preview.
- Luna-high review found no unresolved material issues. The folder-access error includes a recovery hint.
- Updated dist/PiperChatterbox500Test/PiperChatterbox500Test.exe. Verified six embedded modules against current source, including settings_window, settings_theme and chatterbox_voice.
- Verified the launcher hash changed and both speech payload manifest and worker executable hashes stayed identical.
- Launched the updated executable with isolated test settings. It displayed its startup model chooser and exited normally when the test dialog was closed; no model was loaded by this smoke check.

Launcher SHA256: ad2d3ad3d42c8ee6e9dc2827b6ad24c2c6cded253522683d02b7832fb528dfb4.

Packaging logs, prior launcher backup, hash snapshot and verification helpers are under build/saved-voices-package. Existing user settings and unrelated untracked workspace files were preserved.
