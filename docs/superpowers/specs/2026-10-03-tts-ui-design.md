# Piper TTS interface design

Date: 2026-10-03
Branch: UI-upgrade (keep the current branch)
Status: Approved and implemented

## Goal
Replace the utilitarian settings form with a polished desktop speech workspace. Keep the existing Tkinter toolkit, engine integrations, settings persistence, and tray behavior.

## Recommended direction: dark audio studio
Use a deep charcoal background, slightly lighter panels, warm white text, muted secondary text, and a teal accent for primary actions and focus. Use Segoe UI with a clear type hierarchy and generous spacing. A small static waveform mark beside Piper gives the interface an audio identity without implying active playback.

The window opens to a two-column workspace: voice and speech controls on the left, a larger editable text preview on the right. A header introduces Piper with the subtitle “Your text, given a voice.” A bottom action bar holds Cancel and Save changes. The window is resizable; the text editor absorbs extra space. The minimum size must fit the full settings and action bar on a typical laptop display.

## Controls
- Voice panel: speech engine selector, engine-specific voice controls, readable Piper model filename and wrapped path, and Choose voice action.
- Speech panel: pitch and speed numeric inputs with percent units and concise helper text; sentence pause in milliseconds and the existing Piper sentence streaming toggle.
- Shortcut panel: capture hotkey input with a short example.
- Text panel: editable captured text, scrollbar, and prominent Speak text action. Keep multiline content intact.
- Maintenance: compact Kokoro verification section with status feedback; it remains available for users of either engine.

## Behavior and accessibility
Preserve existing callbacks, validation bounds, engine switching, staged voice selection, Save/Cancel semantics, capture updates, verification progress, and single-window lifecycle. Show errors near their inputs in a readable warning color and wrap long messages. Preserve keyboard navigation, visible focus, and high text contrast. Scope theme styling to Piper widgets.

## Alternatives considered
1. Light Windows-style panels: familiar and readable, but less distinctive for an audio application.
2. Tabbed settings: compact, but makes voice adjustment and text preview harder to use together.

## Validation
Run existing settings-window and settings-apply tests, updating structural fixtures for the new layout while retaining behavioral assertions. Exercise a real Tkinter window with Piper, Kokoro, long model paths, long validation messages, resizing, and editable text. Capture and inspect a preview if available. No audio engine or packaging migration is part of this change.

## Implementation verification

The settings column scrolls independently so all controls remain accessible at the 900 × 680 minimum size. Keyboard focus reveals controls outside the viewport. Validation messages wrap beside the relevant setting. Piper pause settings remain editable when Kokoro is selected because saving validates those values for both engines.

57 focused settings, apply, and real-window tests passed. The broader Windows tray suite recorded 769 passes, two skips for unavailable ffmpeg, and three unrelated failures because `.github/workflows/windows-tray.yml` is absent in this checkout. Formatting checks passed and an independent review found no outstanding issues. The screenshot is saved at `docs/previews/piper-studio.png`. The existing packaged executables have not been rebuilt.
