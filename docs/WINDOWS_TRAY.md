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
  Hotkey settings, Open log, Exit.

## Selection behavior

Piper sends `Ctrl+C` to the foreground application and waits up to one second
for fresh clipboard data. It does not restore the previous clipboard
contents. If the clipboard sequence does not change or fresh non-whitespace
text cannot be read, Piper does not speak the old clipboard contents.

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

The foreground application did not produce fresh clipboard text after
`Ctrl+C`. Piper intentionally refuses to speak stale clipboard contents.

### No audio

Confirm that `ffplay.exe` is on `PATH`, then inspect
`%LOCALAPPDATA%\Piper\piper-tray.log`.

### Voice failed to load

Choose a valid `.onnx` model with its matching `.onnx.json`. A failed
replacement voice does not replace the current known-good voice.

### Open log

The tray's Open log action opens the Piper log location so the rotating
`piper-tray.log` can be inspected.
