# Windows Tray TTS

## Requirements

- Windows 10 or Windows 11.
- A Piper `.onnx` voice model and its matching `.onnx.json` file.
- `ffplay.exe` available on `PATH` for audio playback.
- `ffmpeg.exe` available on `PATH` when either Pitch settings or Speed
  settings is non-neutral.

Neither `ffplay` nor `ffmpeg` is bundled into `PiperTray.exe`. Only when both
Pitch settings and Speed settings are `0%` does Piper use the direct `ffplay`
PCM path without requiring `ffmpeg`. With either control non-neutral, a
missing `ffmpeg` is reported through the normal recoverable speech-playback
error and the tray application stays running.

## Voice setup

The default voice setting is `en_GB-alba-medium`; the voice model itself is
not bundled or downloaded automatically by `PiperTray.exe`.

For identifier-based lookup, place both files together in either:

- the directory you launch Piper from, or
- `%LOCALAPPDATA%\Piper`

For the default voice, the pair is:

- `en_GB-alba-medium.onnx`
- `en_GB-alba-medium.onnx.json`

If the configured voice cannot be found or loaded, Piper opens the existing
voice-model picker. You may select another `.onnx` file, but its matching
`.onnx.json` must be beside it.

## Packaged launch

Run `PiperTray.exe`.

The packaged application stays in the Windows notification area and does not
enable Windows logon startup. It must not open a terminal or playback window.

## Default controls

- Speak selected text: `Alt` + `backtick`.
- Stop current speech: `F8`.
- Tray actions: Settings, Stop speaking, Replay, Enable Codex, Error sounds,
  Open log, Exit.

## Settings window

Choose `Settings` from the tray to open Piper's single settings window. Choosing
`Settings` again while it is already open focuses the same window.

The window contains:

- Voice model: shows the current model and provides `Choose voice...`.
- Last captured text: read-only and refreshed after each successful capture.
- Hotkey settings: edits the capture hotkey.
- Pitch settings: accepts `-50%` through `100%`.
- Speed settings: accepts `-50%` through `100%`.

`Save/Apply` validates the editable settings together. A changed voice is loaded
before Piper commits it. The candidate hotkey is registered and the complete
settings object is saved before the new runtime settings are committed. If
validation, voice loading, hotkey registration, or saving fails, the window
stays open and the previous known-good settings remain active.

`Cancel` closes the window without applying edits. Last captured text is
informational only and is never stored in `settings.json`.

Changes apply to subsequent speech requests. Applying settings does not alter
speech that is already playing.

## Pitch settings

Pitch defaults to `+26%`. The accepted range is `-50%` through `100%`.
Positive values raise the synthetic voice pitch, negative values lower it,
and `0%` disables FFmpeg pitch processing. The FFmpeg filter compensates tempo
so the overall speech duration remains approximately unchanged.

The setting applies to foreground speech, spoken errors, and the launch welcome
because all three use the shared speech worker. A changed value applies to the
next speech request and persists in `%APPDATA%\Piper\settings.json`.

## Speed settings

Speed defaults to `0%`. The accepted range is `-50%` through `100%`: `-50%`
means half speed, `0%` means normal speed, and `100%` means double speed.
Speed changes duration without changing pitch. The setting applies to the
next speech request and persists in `%APPDATA%\Piper\settings.json`.

## Error sounds

`Error sounds` is disabled by default. Its enabled state is shown by the
native checkmark in the tray menu and persists across launches.

When Error sounds is disabled, a successful launch speaks `Piper is ready.`
and the approved runtime errors remain visual only.

When Error sounds is enabled, the launch welcome is suppressed and Piper
speaks these runtime errors with the currently selected voice:

- `That hotkey is already in use. Choose another combination.`
- `That hotkey is not valid. Choose another combination.`
- `No text selected or the application did not provide it`
- `The selected text could not be read from the clipboard.`

These four listed messages are the only approved runtime errors that Error
sounds may speak.

Other status messages are not spoken merely because Error sounds is enabled.
Feedback speech does not replace the last captured text and does not become
available through Replay or Show last text.

F8 and the tray's Stop speaking action can stop currently audible Piper
speech, including error or launch feedback.

## Selection behavior

Piper sends `Ctrl+C` to the foreground application and waits up to one second
for fresh clipboard data. It does not restore the previous clipboard
contents. If no fresh selected text is available, Piper shows no native tray
notification. It does not open a message box for this case and does not speak
stale clipboard contents. When Error sounds is enabled, Piper speaks `No text
selected or the application did not provide it`; when disabled, there is no
user-facing no-text feedback.

## Enable Codex

`Enable Codex` is off by default. When enabled, Piper locally watches the current
Windows user's supported Codex session history and reads the newest newly completed
final Codex answer with the configured Piper voice.

Piper establishes a baseline when monitoring starts, after restart, and after
resume/recovery. Existing or missed responses are not read aloud later. Codex
responses are latest-only: they are never queued as a backlog.

Speech priority is:

1. selected text;
2. error feedback;
3. Codex response;
4. launch welcome.

Starting selected-text speech stops current Codex speech. A Codex answer that arrives
while higher-priority speech is active is skipped. `Stop speaking`/F8 stops current
Codex speech but keeps monitoring enabled. Turning `Enable Codex` off stops monitoring
and cancels Codex speech.

Codex response text stays local and is not stored in Piper settings or logs. Piper
may log non-content diagnostics such as response identity, character count, monitor
state, and failure category. Unsupported Codex history formats fail closed instead of
being guessed. Automatic Codex read-aloud omits closed fenced code blocks and caps
prepared text at 6,000 characters.

## Files

- Settings: `%APPDATA%\Piper\settings.json`
- Log: `%LOCALAPPDATA%\Piper\piper-tray.log`

The log rotates and must not contain captured text.

## Developer/debug launch

Install the tray development dependencies:

`python -m pip install -e ".[windows-tray]"`

Run:

`python -m piper.windows_tray --debug`

or

`piper-tray --debug`

Debug mode keeps the normal developer console visible, forces DEBUG logging,
and mirrors the same privacy-safe tray diagnostics to the console and rotating
log. It does not change capture, synthesis, playback, hotkey, or lifecycle
behavior.

## Build from source

On Windows PowerShell:

`./script/build_windows_tray.ps1`

The expected artifact is:

`dist\PiperTray.exe`

To run the clean-environment bootstrap smoke:

`./script/smoke_windows_tray.ps1`

## Troubleshooting

### Hotkey already in use

Choose another capture hotkey. `F8` is reserved for cancellation.

### No text selected or the application did not provide it

If no fresh selected text is available after `Ctrl+C`, Piper shows no native
notification, does not open a message box, and does not speak stale clipboard
contents. When Error sounds is enabled, Piper speaks `No text selected or the
application did not provide it`; when disabled, there is no user-facing
no-text feedback.

### No audio

Confirm that `ffplay.exe` is on `PATH`; if either Pitch settings or Speed
settings is non-neutral, also confirm that `ffmpeg.exe` is on `PATH`. Only
when both settings are `0%` is direct `ffplay` playback used. Then inspect
`%LOCALAPPDATA%\Piper\piper-tray.log`.

### Voice failed to load

Choose a valid `.onnx` model with its matching `.onnx.json`. A failed
replacement voice does not replace the current known-good voice.

### Open log

The tray's Open log action opens the Piper log location so the rotating
`piper-tray.log` can be inspected.
