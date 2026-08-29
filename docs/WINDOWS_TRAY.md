# Windows Tray TTS

## Requirements

- Windows 10 or Windows 11.
- A Piper `.onnx` voice model and its matching `.onnx.json` file.
- `ffplay.exe` available on `PATH` for audio playback.

`ffplay` is not bundled into `PiperTray.exe`. If it is missing, Piper remains
running in the tray, but speaking fails with the normal audio-playback error
and details are written to the Piper log.

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
- Tray actions: Voice settings, Show last text, Stop speaking, Replay,
  Hotkey settings, Error sounds, Open log, Exit.

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
contents. If no fresh selected text is available, Piper shows a native tray
notification with `No text selected`. It does not open a message box for this
case and does not speak stale clipboard contents. The longer full no-text
message is spoken only when Error sounds is enabled.

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

If no fresh selected text is available after `Ctrl+C`, Piper shows the native
tray notification `No text selected`, does not open a message box, and does
not speak stale clipboard contents. The longer no-text message is spoken only
when Error sounds is enabled.

### No audio

Confirm that `ffplay.exe` is on `PATH`, then inspect
`%LOCALAPPDATA%\Piper\piper-tray.log`.

### Voice failed to load

Choose a valid `.onnx` model with its matching `.onnx.json`. A failed
replacement voice does not replace the current known-good voice.

### Open log

The tray's Open log action opens the Piper log location so the rotating
`piper-tray.log` can be inspected.
