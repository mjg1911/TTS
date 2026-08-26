# Windows Tray TTS Application Design

## Goal

Provide a Windows tray application for Piper that can run without an open terminal. The application stays in the Windows notification area, captures selected text from the foreground application when a global hotkey is pressed, and immediately speaks that text through Piper's local neural TTS engine.

## User-facing behavior

- The default voice is `en_GB-alba-medium`.
- The default global hotkey is Alt plus the backtick/tilde key (`Alt` + `backtick`).
- `F8` is a global cancel shortcut for stopping the current speech.
- The voice and hotkey are changeable from the tray UI.
- The user launches the app manually; it does not install or enable Windows logon startup.
- Pressing the global hotkey attempts to send `Ctrl+C` to the foreground application, reads the clipboard, and starts speaking immediately in the background without opening any playback window. This is a best-effort capture path and the initial and only selection-capture method.
- Clipboard contents are not restored after capture.
- Piper always remains a background tray application while capturing and speaking; there is no playback window. A Tkinter modal/window may open only when the user chooses voice or hotkey settings, or when first-run setup is required.
- The tray menu provides Show last text, Stop speaking, Replay, voice configuration, hotkey configuration, open log, and Exit.

## Architecture

The Windows tray application is isolated from Piper's core synthesis library in a Windows-specific desktop module and entry point. It uses:

- Tkinter for first-run setup and user-invoked configuration modals/windows only; playback has no user-facing window.
- `pystray` for the notification-area icon and menu.
- The Windows `RegisterHotKey` API for a system-wide shortcut.
- Piper's existing Python API (`PiperVoice`) for in-process synthesis.
- A background worker for synthesis and playback so UI and tray events remain responsive.
- A Windows named mutex plus an inter-process activation signal to enforce one running instance.

All behavior is coordinated by one application state/controller. Tray callbacks, Windows hotkey callbacks, worker completion/cancellation events, inter-process activation, and window actions do not mutate shared state directly; they enqueue commands for the controller. The controller serializes capture, replacement, Stop, Replay, and shutdown transitions, and marshals all Tkinter widget updates through the Tkinter main thread. This single ownership boundary prevents races such as a late worker completion restarting audio after `F8`, Replay starting during shutdown, or a second hotkey replacing the wrong request.

The existing engine remains usable independently through its current CLI, HTTP server, and Python API.

## Interaction flow

1. The user launches the Windows executable.
2. The application acquires its named mutex. If another instance already owns it, the new process signals the existing instance to show/activate its UI and exits without loading a voice, creating a tray icon, or registering hotkeys.
3. The first instance loads persisted settings and the configured voice.
4. If no voice is configured, a setup window requests a model path; otherwise the app starts directly in the tray.
5. The global hotkeys are registered with Windows.
6. On capture-hotkey activation, the application copies the foreground selection, reads the clipboard, logs the capture event without logging the text itself, and starts background speech without opening a playback window.
7. Synthesis and playback begin immediately on a worker thread.
8. Playback state is maintained internally and surfaced through tray notifications or tray actions when needed; no playback window is shown. Configuration remains available through the tray and may open a settings modal.
9. Stop cancels the current synthesis/playback. Replay speaks the last captured text again. The tray process remains active throughout.
10. Exit stops playback, unregisters the hotkeys, releases the mutex, closes the tray icon, and shuts down cleanly.

After Windows sleep/resume, the controller returns to a consistent idle-or-stopped state, verifies that the tray icon is still available, and re-registers the global hotkeys if Windows released them. Any in-flight synthesis is cancelled rather than resumed with stale state.

Pressing global `F8` cancels the active synthesis/playback immediately, updates the internal playback state to `Stopped`, and invalidates the active request generation so no remaining worker output can be played. If Piper is idle, `F8` has no effect. `F8` is reserved for cancellation and is not part of the configurable text-capture hotkey.

If the global hotkey is pressed while speech is active, the application immediately cancels the current utterance and begins a fresh capture. A successful new capture replaces the previous text and playback; a failed capture leaves the app stopped rather than resuming or replaying the previous utterance. Each capture/playback request receives a generation identifier, and worker updates are ignored when they belong to an older generation, preventing stale synthesis from changing playback state or sending audio after a replacement request.

## Clipboard capture correctness

The application must not assume that the clipboard changed just because `Ctrl+C` was sent. Before sending the key sequence, it records the Windows clipboard sequence number with `GetClipboardSequenceNumber`. It then sends `Ctrl+C` to the foreground application and polls for a changed sequence number every 50 milliseconds for up to 1 second. Once the sequence number changes, it reads plain text from the clipboard; if the clipboard is temporarily unavailable or the text is not yet rendered, it retries within the same timeout.

The capture succeeds only when both conditions are true: the sequence number changed after the hotkey action and non-whitespace text was read. Existing clipboard contents are never accepted as a successful capture when the sequence number remains unchanged, and therefore can never be sent to Piper merely because the target application ignored the copy request. Capture is explicitly best-effort for elevated/admin applications, protected fields, games, remote desktop sessions, terminals, and unusual UI frameworks where simulated `Ctrl+C` may be ignored, blocked, or handled differently. If the timeout expires, no speech is started; the user sees `No text selected or the application did not provide it` as a tray notification, while the log records whether the timeout, an unchanged clipboard, an empty result, an access/permission failure, or another clipboard error caused the failure. The selected text itself is not logged.

## Configuration and packaging

Settings are stored in `%APPDATA%\\Piper\\settings.json` using an explicit integer `schema_version` field. The initial schema is version `1` and includes:

- voice model path or voice identifier, defaulting to `en_GB-alba-medium`;
- hotkey, defaulting to Alt plus the backtick/tilde key;
- logging level and other supported speech settings.

Settings loading is defensive. A missing file uses defaults and may open first-run setup. Valid older schema versions are migrated in memory and rewritten in the current schema after successful startup. Malformed JSON, invalid field values, unreadable files, or unsupported older versions are logged, ignored, and replaced in memory with safe defaults so the tray application still starts. The original invalid file is retained for diagnosis (renamed with a `.corrupt` suffix when safe), and the user can configure settings again from the tray. Settings writes are performed through a temporary file followed by an atomic replacement to reduce corruption during shutdown or power loss.

The tray application is packaged as a Windows executable without a console window. A developer/debug launch mode keeps the console visible and enables verbose logging. The packaged application must include or clearly document the Piper runtime, required native dependencies, and voice-model setup.

## Diagnostics and failure handling

Logs are written to `%LOCALAPPDATA%\\Piper\\piper-tray.log` with rotation. Entries include timestamps, severity, application version, hotkey registration, foreground-window and clipboard steps, selected-text length, voice loading, synthesis timing, playback state, and shutdown events.

Selected text is not written to logs by default. User-facing playback and capture errors are concise tray notifications; detailed exceptions and tracebacks go to the log. A hotkey conflict leaves the app running and explains how to choose another combination. Missing voices, failed synthesis, and playback errors also leave the tray app alive so the user can correct settings and retry. The tray includes an action to open the log file or its containing folder.

## Testing and acceptance criteria

Automated tests cover:

- hotkey parsing and configuration persistence;
- settings schema validation, older-version fallback/migration, malformed-file recovery, and atomic writes;
- single-instance enforcement, second-launch activation, and duplicate-hotkey prevention;
- registration failure handling;
- clipboard capture and empty-selection behavior;
- clipboard freshness checks, delayed clipboard rendering, timeout/retry behavior, and stale-clipboard rejection;
- best-effort behavior for applications where simulated `Ctrl+C` is unavailable or inappropriate, including proof that previous clipboard contents are not spoken;
- log creation and rotation;
- missing/invalid voice configuration;
- synthesis cancellation and replay;
- hotkey re-entry while speaking, including immediate cancellation, replacement by a fresh capture, and suppression of stale worker output;
- global `F8` cancellation while speaking and its no-op behavior while idle;
- serialized controller behavior across tray callbacks, hotkey callbacks, worker events, Stop, Replay, and shutdown;
- tray lifecycle and background playback state transitions.

Acceptance scenarios additionally cover:

- stale clipboard prevention: pre-populate the clipboard, make the target app ignore `Ctrl+C`, and verify that the old contents are not spoken;
- repeated hotkey presses: verify that each new request cancels and supersedes the prior request without duplicate audio;
- pressing the capture hotkey during playback: verify immediate cancellation followed by playback of only the newly captured selection;
- second-instance launch: verify that the second executable activates the first instance and creates no second tray icon or hotkey registration;
- Windows sleep/resume: verify that the app remains in the tray, returns to idle/stopped state, and restores its hotkeys;
- failed voice switch: verify that an invalid or unloadable voice is rejected, the current known-good voice remains active, and the error is logged;
- large text: verify that a large selection is handled without freezing the UI, crashing, or speaking stale text, with any configured safety limit reported clearly;
- clean exit during synthesis: verify that worker threads and playback terminate, hotkeys are unregistered, settings remain valid, and the process exits without a traceback;
- no-copy application: verify that an application producing no new clipboard data results in the clear no-text message and no speech.

Manual Windows smoke testing verifies that:

- selecting text in another Windows application and pressing Alt plus backtick starts speech immediately without opening any playback window;
- the tray remains active throughout capture, playback, cancellation, and replay;
- the voice and hotkey can be changed and persist after relaunch;
- a packaged launch shows no terminal window;
- failures are visible to the user and diagnosable from the log.

## Scope boundaries

This design does not add automatic startup, clipboard restoration, UI Automation selection capture, cloud services, or a browser-based UI. UI Automation may be considered later as an optional way to avoid changing the clipboard in applications that support it. The design does not change Piper's existing engine behavior except where a reusable playback/cancellation boundary is needed by the tray application.
