# Piper Sentence Streaming Toggle

## Goal

Let users choose whether Piper begins playback as each sentence is synthesized or waits until the full request is synthesized and then plays it continuously.

## Design

Add a persisted boolean setting named `piper_sentence_streaming_enabled` and a checkbox in the Settings window beside the existing Piper sentence-pause control. The checkbox is on by default, preserving current behavior for new installations and settings files that omit the new field.

When enabled, keep the existing conservative sentence splitter and Piper chunk playback. Insert the configured sentence pause between sentence chunks as today. When disabled, pass the full request text to Piper, collect its audio chunks into one PCM buffer, and play that buffer after synthesis completes. Do not add the configured sentence pause in this mode. This mode may delay the beginning of playback and use more memory for long requests.

The setting applies to subsequent speech requests that use Piper, regardless of request source. It does not change Kokoro synthesis or playback. Persist the setting in the existing settings JSON under schema version 2; validate it as a boolean and default a missing value to `true`.

## Settings flow

Include the value in `TraySettings`, the settings snapshot, Settings window checkbox, and controller Save/Apply validation and persistence flow. Applying settings changes the behavior of subsequent requests without restarting Piper. A failed validation or save keeps the existing settings active, using the current Settings error handling.

## Speech flow

The speech worker reads the setting when a Piper request starts. In sentence streaming mode, retain lazy synthesis and current pause insertion. In buffered mode, synthesize the complete text, concatenate each returned PCM chunk in order, and submit the resulting buffer as a single playback operation. Honor cancellation while synthesizing; discard buffered audio if the request is cancelled before playback. Leave the non-Piper streamed backend path unchanged.

## Alternatives considered

- Toggle only the added sentence pause: rejected because the existing pause setting already accepts `0` ms.
- Persist a sentence-streaming mode and make disabled mode synthesize and buffer the full request: chosen because it controls the actual sentence-by-sentence playback behavior while preserving current defaults.

## Scope and success criteria

- Existing and new settings default to sentence streaming enabled.
- The Settings checkbox round-trips through save and load.
- Disabled mode plays all Piper audio continuously after full-request synthesis, without inserted sentence gaps.
- Enabled mode preserves current sentence splitting, incremental playback, and configured pauses.
- Kokoro behavior remains unchanged.

## Verification approach

Review the settings serialization and validation path, Settings snapshot and apply flow, and both Piper speech modes for consistent behavior. No automated tests were requested, so do not add or run tests.
