# Windows Tray TTS Phase 5 V3 — Task 6 Report

## Status

Documentation and the explicit packaged acceptance record were prepared. Final
packaged acceptance remains pending because this environment has no working
Python/Windows packaged executable or Windows CI result.

## Changes

- Added `docs/WINDOWS_TRAY.md` with end-user setup, runtime behavior,
  developer/debug launch, build, and troubleshooting instructions.
- Replaced the empty `README.md` with the requested minimal documentation
  index.
- Added `docs/superpowers/plans/2026-08-28-windows-tray-tts-acceptance.md`
  containing the complete packaged acceptance checklist and evidence rules.
- Left all acceptance checkboxes unchecked and all build/hash/platform fields
  blank; no packaged or CI result is claimed.

## Test/static summary

- Static documentation review: completed against the Task 6 brief; required
  sections, controls, paths, commands, caveats, and acceptance scenarios are
  present.
- Runtime/build/manual/CI checks: not run; required Python, Windows packaged
  executable, and CI result are unavailable in this environment.

## Self-review

- Confirmed the documentation does not claim that `PiperTray.exe` bundles or
  downloads a voice model or `ffplay`.
- Confirmed the acceptance record requires evidence from the actual packaged
  executable for packaged behavior and preserves unchecked placeholders.
- Confirmed only the four Task 6 documentation/report paths are intended for
  this change; unrelated pre-existing files remain untouched and unstaged.

## Concerns

- The acceptance record cannot be treated as a release sign-off until a real
  `PiperTray.exe` is tested on Windows, its SHA-256 is recorded, the manual
  matrix is executed, and the Windows tray CI artifact is verified.

## Review fix evidence

- Corrected `docs/WINDOWS_TRAY.md` so the voice-model picker is documented as
  opening whenever the configured voice cannot be found or loaded, rather than
  only on first launch.
- Verification: `rg -n -C 2 "configured voice cannot be found or loaded|first launch" docs/WINDOWS_TRAY.md`
  confirms the corrected wording and no longer finds the inaccurate phrase.
- Verification: `git diff --check` completed without whitespace errors.
