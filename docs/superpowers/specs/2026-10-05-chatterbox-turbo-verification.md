# Chatterbox Turbo replacement verification

Implemented on branch `350M`: Piper, Chatterbox Nano, and Chatterbox Turbo (350M). Startup selection, Settings, isolated worker, revision-pinned model payload, source distribution, Windows packaging, and installer checks now use Turbo. Saved Multilingual selections migrate to Turbo; retired language/style settings are removed. Piper/Nano behavior and the shared managed reference voice library are preserved.

## Automated checks

- Focused Turbo worker, assets, protocol, settings, rollback, custom voice, startup, UI and packaging checks: **79 passed, 2 skipped**.
- Full `tests/turbo` and `tests/windows_tray` regression run: **950 passed, 16 failed, 2 skipped**. All 16 failures also reproduce against unchanged HEAD extracted into `build/turbo-baseline`; they concern older F8 hotkey behavior and tests expecting settings schema 2 while the branch uses schema 3. No replacement-specific test failures remain.
- Two real Tk layout tests skipped because this Python environment could not load `init.tcl`.
- All four changed/new PowerShell build and staging scripts parse successfully. Python compilation and `git diff --check` pass.
- Final independent review found no actionable defects; specification compliance and code quality passed.
- Fresh pre-commit rerun after packaging: **81 passed**, including both real Tk layout tests that previously skipped.

## Real GPU synthesis

Using the pinned Chatterbox source in the existing CUDA Python environment and an NVIDIA RTX 4070, all nine downloaded Turbo model files matched their pinned SHA-256 hashes. The new Turbo runtime loaded `nano=False`, then produced non-silent 24 kHz PCM for both the default voice and a custom reference. Each output contains 96,960 samples. The custom reference was generated speech, avoiding any private recording. Results and WAVs are under `build/turbo-gpu-smoke-results.json` and `build/turbo-smoke-*.wav`.

## Packaged test build

At the user's follow-up request, rebuilt `dist/PiperChatterbox500Test/PiperChatterbox500Test.exe` with Piper, Nano, and Turbo. Built the frozen Turbo worker with the pinned CUDA environment, staged the pinned model files, and bundled the verified Nano and Turbo payloads. The packaged worker generated speech twice for both default and custom reference voices on the GPU, and its manifest inventory remained unchanged. The new app archive contains Turbo modules and no Multilingual modules; Tcl/Tk runtime files are present.

The previous complete test build is preserved at `build/PiperChatterbox500Test-before-turbo-20261005`. Detailed evidence is in `build/turbo-packaged-smoke-results.json` and `build/turbo-test-build-report.json`. The Windows installer was not rebuilt.
