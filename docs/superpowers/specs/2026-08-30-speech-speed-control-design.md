# Independent Speech Speed Control for Piper Tray

## Goal

Add a configurable speech-speed control to Piper’s Windows tray application so users can make generated speech faster or slower without changing the voice’s pitch. Speed should be independent from the existing pitch setting: a user can, for example, use a higher-pitched voice at normal speed or a lower-pitched voice at double speed.

The feature should feel like a natural extension of the existing Pitch settings control, persist across launches, and apply consistently to foreground speech, spoken errors, and the launch welcome message.

## Proposed user behavior

The tray will expose a `Speed settings` action next to `Pitch settings`. The user enters a percentage:

- `-50%` produces half-speed speech.
- `0%` produces normal-speed speech.
- `100%` produces double-speed speech.

The exact accepted range should be shared by settings validation and the UI. Invalid, non-finite, boolean, or non-numeric values should be rejected without replacing the last known-good value. A missing speed field in an existing settings file should use the normal-speed default without changing the settings schema version.

Speed changes apply to the next speech request and are persisted atomically in the existing settings file. Pitch and speed changes must not interrupt speech already being played except through the existing replacement/cancellation behavior.

## Design options considered

### Independent speed and pitch controls — selected

Store `speed_percent` separately from `pitch_percent` and apply both in the same playback pipeline. This is the most flexible and predictable behavior for users and preserves natural voice control.

### Combined voice-style control

Expose one control that bundles pitch and speed. This would reduce menu complexity but prevents users from choosing a high or low voice independently of speaking rate.

### Speed-only processing with natural pitch movement

Change playback rate directly so pitch rises or falls with speed. This is simpler, but it does not meet the goal of making speech faster or slower while retaining the selected pitch and can sound unnatural for larger adjustments.

## Architecture

Keep Piper synthesis, voice loading, phonemization, capture, and the shared `SpeechWorker` API unchanged. Extend the existing tray playback adapter so each speech request continues to use one persistent FFmpeg process, but its filter is built from both pitch and speed settings.

The playback pipeline should:

1. Receive raw signed 16-bit little-endian mono PCM at the Piper voice sample rate.
2. Apply pitch shifting using the existing rate-shift plus tempo-compensation strategy.
3. Apply independent speed adjustment while preserving the resulting pitch.
4. Resample to the exact original sample rate and forward raw PCM to `ffplay`.

The implementation must continue to use an argument list with `shell=False`, drain FFmpeg output continuously, and preserve the existing cancellation-safe lifecycle. A speed of `0%` combined with a pitch of `0%` should retain the direct `ffplay` bypass and should not require FFmpeg.

The design should define the filter ordering and formulas explicitly in the implementation plan. The formulas must ensure that the pitch multiplier and speed multiplier do not accidentally compound each other or alter the selected pitch. If FFmpeg is unavailable for a non-default processed request, the existing concise `Speech playback failed.` behavior remains unchanged.

## Settings and controller behavior

Add a schema-compatible `speed_percent` field to `TraySettings` with a normal-speed default of `0.0`. Keep schema version 1. Reuse the existing validation and atomic-save patterns, with dedicated constants and a validator for the accepted speed range.

The controller should expose a thread-safe current-speed getter and a request method analogous to pitch changes. It must validate before saving, update in-memory state only after a successful save, and retain the last known-good value when validation or persistence fails.

The UI prompt should explain the accepted range and state that speed changes do not change pitch. The tray action should enqueue a command; Tk interactions remain on the UI thread.

## Error handling and compatibility

- Existing settings files without `speed_percent` load normally at `0%`.
- Invalid speed values are treated like other corrupt settings when loaded and do not silently enter runtime state.
- Invalid UI/controller values show a concise range error and preserve the current setting.
- FFmpeg startup, streaming, malformed output, broken pipes, and unexpected exits follow the existing playback failure and cancellation rules.
- A request’s speed and pitch are captured when its playback pipeline is created; later setting changes affect only subsequent requests.
- No FFmpeg or ffplay binaries are bundled into the frozen executable.

## Testing strategy

Add coverage for:

- Defaulting and schema-1 compatibility.
- Inclusive speed boundaries, invalid values, non-finite values, and last-known-good persistence.
- Controller/UI validation, command routing, menu order, and failed-save behavior.
- Exact FFmpeg filter and command construction for speed-only, pitch-only, and combined adjustments.
- Direct bypass when both controls are neutral.
- One FFmpeg process per speech request, chunk streaming, output draining, cancellation, malformed output, and child-process failures.
- Preservation of selected pitch while changing speed, using generated PCM and measurable duration/frequency assertions when FFmpeg is installed.
- Existing tray, CLI, packaging, and frozen-build compatibility contracts.

## Success criteria

The feature is complete when users can independently configure pitch and speed from the tray, both values persist safely, speech duration changes according to speed while pitch remains stable, cancellation cannot leak stale audio, neutral settings retain the direct playback path, and the existing tray/core regression suites remain green.
