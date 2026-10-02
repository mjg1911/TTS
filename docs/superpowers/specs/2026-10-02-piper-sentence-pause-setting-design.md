# Piper Sentence Pause Setting

## Goal

Let users choose the silence between consecutive Piper sentences from the
Settings window, in milliseconds.

## Design

Add a numeric `Piper sentence pause (ms)` setting to the existing Settings
window. The setting applies to Piper sentence chunks only; Kokoro playback is
unchanged. It accepts whole numbers from 0 through 2000. The default is 180 ms,
which preserves the current behavior, and 0 disables the inserted pause.

Store the value as `sentence_pause_ms` in `TraySettings` and the existing
settings JSON. Older settings files that omit the field load with the 180 ms
default. The setting is optional within schema version 2, so this additive
change does not require a schema migration.

The Settings window displays the saved value and submits it with the existing
settings. The controller validates and saves it with the other settings. The
speech worker reads the current value when it inserts silence between Piper
sentence chunks. It does not add silence before the first sentence. Preserve
the current speed compensation so the configured value remains the approximate
audible gap at different playback speeds.

## Alternatives considered

- A numeric field in Settings: chosen because it permits precise millisecond
  values and fits the existing numeric settings fields.
- A slider or preset list: not chosen because it limits the values users can
  enter.
- A settings-file-only value: not chosen because the requested control belongs
  in the Settings window.

## Scope and behavior

- Persist and reload a validated whole-number delay from 0 to 2000 ms.
- Keep 180 ms as the fallback for missing values and new installations.
- Apply the current setting to the silence between Piper sentence chunks.
- Leave Kokoro sentence timing and other playback behavior unchanged.

## Verification

Review the settings load/save path, Settings window apply flow, controller
validation, and Piper sentence-gap calculation for consistent use of the new
value. Do not change the existing sentence splitting behavior.
