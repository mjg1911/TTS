# Saved voices and Voice panel

Approved by the user on 2026-10-04: add a Saved voices dropdown with readable names and automatic discovery of existing imports, an Import voice… button that selects the new voice, cleaner spacing, compact status text, and CPU/GPU styling matching the dark workspace.

Keep the custom-voice toggle, labelled Use saved voice, to return to the bundled voice without losing the chosen recording. Importing or selecting a recording enables the saved voice; Save applies the staged selection through the existing transactional backend preparation. Cancel discards the staged selection but keeps imported recordings in the library. The dropdown remembers all imports across restarts by scanning the existing managed References folder. No settings migration or new dependency is needed.

Use source stems as names, removing only the managed UUID suffix and disambiguating duplicate names deterministically. Preserve the currently saved path even when it is external or missing; unavailable selections stay visible and existing apply validation reports missing recordings. Directory read failures receive a compact actionable message. Scan file names without decoding every WAV; existing import and apply validation remain authoritative.

Arrange controls in a clear sequence: speech engine, styled processing-device buttons, saved-voice toggle and dropdown, import action, brief WAV guidance and status. Remove the long full-path readout from the panel. Share the library with Nano and Multilingual while retaining their engine-specific settings.

Verify library discovery and duplicate names, import/selection/save/reopen, failed-import preservation, pending-apply locking, missing selections, minimum-size Tk layout and theme. Run the Windows tray suite. Rebuild the executable in dist/PiperChatterbox500Test with current code while preserving its existing speech payloads. Stay on UI-Fix and commit the fix after verification.
