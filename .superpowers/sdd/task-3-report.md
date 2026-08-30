# Task 3 Report

## Changed files

- `src/piper/windows_tray/pitch_playback.py`
- `tests/windows_tray/test_pitch_playback.py`

## Commit

`454b596 feat: add ffmpeg pitch playback pipeline`

## Test command/output

```text
& 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/windows_tray/test_pitch_playback.py tests/windows_tray/test_audio_playback_cancel.py -q
..................                                                       [100%]
18 passed in 0.18s
```

## Concerns

- Unit tests use deterministic fake FFmpeg/player processes; real FFmpeg integration remains covered by the later integration-test task.
- Existing unrelated working-tree changes were preserved and are not part of the commit.

## Fix report

The stdout reader now terminates FFmpeg immediately when `player.play()` fails outside cancellation, while retaining the playback exception for `__exit__` to surface.

## Fix test command/output

```text
& 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/windows_tray/test_pitch_playback.py tests/windows_tray/test_audio_playback_cancel.py -q
...................                                                      [100%]
19 passed in 0.18s
```
