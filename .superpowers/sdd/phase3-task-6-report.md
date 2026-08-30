# Phase 3 Task 6 Final Regression Gate Report

Date: 2026-08-29 22:24:17 +02:00
Branch: `Error-sound-Phase-3`
HEAD: `f69def7dba170c05727f46ed9b5a317210ee0445`

## Scope and constraints

Verification followed `.superpowers/sdd/phase3-task-6-brief.md`. No production
code or tests were modified. The acceptance checklist was not edited because
the packaged manual evidence could not be completed truthfully on this host.

The normal `python`, `py -3`, and repository `.venv` interpreter preflights were
unavailable. The bundled workspace Python was used only as the documented
fallback. It is Python 3.12.13. The `.venv` site-packages directory was added
to `PYTHONPATH` only to supply already-installed test/CLI dependencies; no
dependencies were installed.

## Automated gates

| Gate | Result | Evidence |
|---|---|---|
| `pytest tests/windows_tray tests/test_core_compatibility.py -q` | PASS with fallback interpreter | Bundled Python plus workspace temp directory: `275 passed in 3.57s`, exit `0`. The initial fallback attempt reached `235 passed` but had `40` setup errors because pytest could not access its default `C:\Users\mhoem\AppData\Local\Temp\pytest-of-mhoem`; the rerun used a workspace temp directory. |
| `python -m piper --help` | PASS with fallback interpreter | Normal `python` was not found. Bundled Python initially lacked `pathvalidate`; with the existing `.venv\Lib\site-packages` on `PYTHONPATH`, help output was produced and exit was `0`. |
| `python -m compileall -q src/piper/windows_tray` | PASS with fallback interpreter | Bundled Python command completed with exit `0`. |
| `git diff --check` | PASS | No whitespace errors; exit `0`. Git emitted only its existing LF-to-CRLF warning for `.superpowers/sdd/phase3-task-1-report.md`. |
| Core compatibility import | PASS | `from piper import PiperVoice, SynthesisConfig` printed `core import ok`, exit `0`. |

The normal-interpreter preflight itself did not pass: `python` and `py -3`
were not recognized, and `.venv\Scripts\python.exe` points to a missing
`C:\Users\mhoem\AppData\Local\Programs\Python\Python312\python.exe`.

## Packaging and frozen smoke

### Build

The existing build artifact was inspected but not treated as a build result:

- `dist\\PiperTray.exe` exists, size `79,002,556` bytes.
- Last write time: `2026-08-28 14:43:29 +02:00`.
- SHA-256: `067093051919C561BB8D943251A3F015C2E895AAC96C0BD81E0544298BF54852`.
- Windows prerequisite checks found `setup.py`, the icon script, the spec, and
  one `src\\piper\\espeakbridge*.pyd`.
- The bundled Python has no `PyInstaller` module, and the repository venv has
  no `PyInstaller` package. The normal `python` launcher is also unavailable.

`script/build_windows_tray.ps1` was therefore not run: its required Python /
PyInstaller build environment was unavailable. No new executable or acceptance
evidence was produced.

### Frozen smoke

`script/smoke_windows_tray.ps1` was run against the existing executable. It
started the packaged process, but the smoke command exited `1` during its
cleanup loop at line 115:

```text
Remove-Item: The process cannot access the file
'...\\LocalAppData\\Piper\\piper-tray.log' because it is being used by another process.
```

The required `Piper tray runtime ready` marker was not captured as standalone
evidence, so this is recorded as `BLOCKED/INCONCLUSIVE`, not PASS. The spawned
test processes and temporary smoke directory were subsequently cleaned up.

The smoke fixture was inspected and contains no `error_sounds` field, as
required for the schema-v1 backward-compatibility check.

## Workflow, scripts, documentation, and acceptance inspection

- `.github/workflows/windows-tray.yml` runs the required tray/core pytest
  command, CLI help, compileall, build script, frozen smoke, non-empty artifact
  check, and uploads `PiperTray-windows`.
- `script/build_windows_tray.ps1` enforces Windows, installs the two Windows
  extras, builds the native bridge, invokes the icon/spec packaging steps, and
  checks size plus SHA-256.
- `script/smoke_windows_tray.ps1` uses isolated APPDATA/LOCALAPPDATA,
  removes `PYTHONPATH`, uses the existing schema-v1 fixture without
  `error_sounds`, waits for the readiness marker, and attempts process/temp
  cleanup.
- `docs/WINDOWS_TRAY.md` documents voice placement, `%LOCALAPPDATA%` logs,
  external `ffplay`, debug launch, no-copy behavior, and disabled/enabled error
  sounds consistently with the acceptance checklist.
- `docs/superpowers/plans/2026-08-28-windows-tray-tts-acceptance.md` remains
  unchanged with all packaged and manual acceptance items unchecked.

## Manual packaged acceptance

The disabled and enabled packaged acceptance passes are `BLOCKED`. They require
interactive execution of the actual executable with Notepad/foreground-window
selection, tray menu state, hotkeys, sleep/resume, second-instance behavior,
voice changes, `ffplay` removal/restoration, audio observations, and clean
directory launch. This host provided no trustworthy completed manual evidence,
so no checklist item was marked PASS.

## Final regression assessment

Automated source-level regression evidence is green under the documented
bundled-Python fallback: `275 passed`, CLI help, compileall, and diff check all
exit successfully. The final Phase 3 packaged regression gate is **not
complete** because the normal build environment is unavailable, frozen smoke
cleanup failed with a locked log, and both manual packaged acceptance passes
remain blocked. The acceptance plan was not updated or committed.
