# Phase 3 Task 1 Handoff Report

## Result

Implemented cancellable, windowless `AudioPlayer` behavior while preserving the existing CLI context-manager API and `is_available()` method.

## Files changed

- `src/piper/audio_playback.py`
  - Added a lock and idempotent stopped state.
  - Added `stop()` to terminate an active ffplay process safely.
  - Added Windows `subprocess.CREATE_NO_WINDOW` creation flags.
  - Made `play()` safely ignore missing/dead processes and broken pipes.
  - Made `__exit__` close stdin only for a live process, wait up to the existing five-second timeout, and fall back to `kill()` on timeout.
- `tests/windows_tray/test_audio_playback_cancel.py`
  - Added the two required cancellation and idempotent-exit tests from the task brief.

## Test commands and results

- `pytest tests/windows_tray/test_audio_playback_cancel.py -v`
  - Could not start: `pytest` is not available on PATH.
- `py -m pytest tests/windows_tray/test_audio_playback_cancel.py -v`
  - Could not start: `py` is not available on PATH.
- Fallback interpreter with `PYTHONPATH=src`: collection reached the package but failed because the available environment lacks `numpy`.
- `pytest tests/windows_tray/test_audio_playback_cancel.py tests/test_piper.py -q` via the fallback interpreter:
  - Could not run because `tests/test_piper.py` is absent from this checkout.
- `py_compile` on `src/piper/audio_playback.py`: PASS.
- Direct stdlib mock checks for both required cancellation behaviors: PASS.

## Self-review

- Scope is limited to the two requested implementation/test files plus this handoff report.
- Existing CLI construction and context-manager call sites remain unchanged.
- Stop and cleanup access `_proc` under the same lock, and repeated stop/exit calls do not re-terminate the process.
- No selected text or new playback data is logged.
- The implementation follows the exact creation-flag, timeout, and kill-fallback requirements.

## Concerns

- Full pytest verification could not be completed in this checkout because the normal Python/pytest commands are unavailable, the fallback environment lacks `numpy`, and the required `tests/test_piper.py` file is absent. A dependency-complete checkout should rerun the two required pytest commands before merging.

## Fix: cancellation while playback I/O is blocked

Review finding: `play()` previously held `_lock` across `stdin.write()` and `flush()`, preventing `stop()` from acquiring the lock while either operation was blocked.

The fix snapshots process state under `_lock`, performs stdin I/O outside the lock, and keeps `__exit__`'s stdin close/wait/kill operations outside the lock. A focused threaded regression test now proves that `stop()` terminates an active process while `play()` is blocked in `stdin.write()`.

### TDD red check

Command:

```text
& 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util, threading; from unittest.mock import Mock; s=importlib.util.spec_from_file_location('audio_playback','src/piper/audio_playback.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); started=threading.Event(); release=threading.Event(); stream=Mock(); stream.write.side_effect=lambda data:(started.set(), release.wait(2)); proc=Mock(); proc.poll.return_value=None; proc.stdin=stream; player=m.AudioPlayer(22050); player._proc=proc; play=threading.Thread(target=player.play,args=(b'audio',)); done=threading.Event(); stop=threading.Thread(target=lambda:(player.stop(),done.set())); play.start(); assert started.wait(1); stop.start(); failed=not done.wait(0.2); release.set(); play.join(2); stop.join(2); assert not failed, 'stop remained blocked by play I/O'; print('unexpected PASS')"
```

Output:

```text
AssertionError: stop remained blocked by play I/O
```

Exit code: `1`.

### Covering checks

Command:

```text
& 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util, threading; from unittest.mock import Mock; s=importlib.util.spec_from_file_location('audio_playback','src/piper/audio_playback.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); started=threading.Event(); release=threading.Event(); stream=Mock(); stream.write.side_effect=lambda data:(started.set(), release.wait(2)); proc=Mock(); proc.poll.return_value=None; proc.stdin=stream; player=m.AudioPlayer(22050); player._proc=proc; play=threading.Thread(target=player.play,args=(b'audio',)); done=threading.Event(); stop=threading.Thread(target=lambda:(player.stop(),done.set())); play.start(); assert started.wait(1); stop.start(); assert done.wait(1), 'stop remained blocked by play I/O'; proc.terminate.assert_called_once(); release.set(); play.join(2); stop.join(2); print('concurrency cancellation check: PASS')"
```

Output:

```text
concurrency cancellation check: PASS
```

Exit code: `0`.

Command:

```text
& 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m py_compile src\piper\audio_playback.py; git diff --check
```

Output:

```text
py_compile + git diff --check: PASS
```

Exit code: `0`.

Command:

```text
pytest tests/windows_tray/test_audio_playback_cancel.py -v
```

Output:

```text
ModuleNotFoundError: No module named 'numpy'
```

Exit code: `1` during collection in the available fallback environment.

Command:

```text
pytest tests/windows_tray/test_audio_playback_cancel.py tests/test_piper.py -q
```

Output:

```text
ERROR: file or directory not found: tests/test_piper.py
no tests ran in 0.00s
```

Exit code: `1`.

### Fix self-review

- Lock scope no longer includes `stdin.write()`, `stdin.flush()`, `stdin.close()`, or `proc.wait()`.
- `stop()` can acquire the lock and call `terminate()` while playback I/O is blocked.
- `_stopped` preserves idempotent termination; `_closing` prevents new playback during exit.
- Existing CLI context-manager behavior, Windows `CREATE_NO_WINDOW`, and `is_available()` remain unchanged.
- No unrelated files or phase-plan files were modified.
